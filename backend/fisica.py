"""
fisica.py - Modelo físico da recarga e regra de tarifa.
=======================================================

Funções PURAS: recebem dicionários, devolvem números. Nenhuma toca no banco.
É isso que permite testar a conta inteira sem Supabase (ver testes/) e
garante que simulador, ESP32, prévia e chatbot usem a MESMA conta.

Três coisas mudam o tempo e o custo de uma recarga:
  1. Curva de carga  - até 80% a bateria aceita potência cheia (corrente
                       constante); acima disso a corrente cai (tensão constante).
  2. Derating        - carregador acima de 35 °C reduz a potência.
  3. Eficiência      - parte da energia da tomada vira calor. Cobra-se pela
                       energia que SAI DA TOMADA, como na conta de luz.

E uma coisa muda só o custo:
  4. Horário de ponta - dias úteis, na janela do condomínio, a energia custa
                        `ponta_multiplicador_tarifa` vezes a tarifa base.
"""

from datetime import datetime, time

from config import FUSO

EFICIENCIA_CARGA = 0.92
SOC_JOELHO = 80.0
FATOR_FINAL = 0.20
TARIFA_PADRAO_KWH = 2.10


# ---------------------------------------------------------------------------
# Curva de carga e temperatura
# ---------------------------------------------------------------------------

def fator_termico(temperatura_c) -> float:
    if temperatura_c is None or float(temperatura_c) <= 35:
        return 1.0
    return max(0.7, 1 - (float(temperatura_c) - 35) * 0.02)


def potencia_no_soc(potencia_max_kw: float, soc: float) -> float:
    """Potência que a bateria aceita num estado de carga."""
    if soc <= SOC_JOELHO:
        return potencia_max_kw
    if soc >= 100:
        return potencia_max_kw * FATOR_FINAL
    proporcao = (soc - SOC_JOELHO) / (100 - SOC_JOELHO)
    return potencia_max_kw * (1 - proporcao * (1 - FATOR_FINAL))


def tempo_de_carga_min(capacidade_kwh: float, soc_ini: float, soc_fim: float,
                       potencia_max_kw: float) -> int:
    """Integra dt = dE / P(SoC) em passos de 1% de SoC."""
    if potencia_max_kw <= 0 or soc_fim <= soc_ini or capacidade_kwh <= 0:
        return 0
    energia_por_ponto = capacidade_kwh / 100.0
    horas, soc = 0.0, float(soc_ini)
    while soc < soc_fim:
        passo = min(1.0, soc_fim - soc)
        p = potencia_no_soc(potencia_max_kw, soc + passo / 2)
        horas += (energia_por_ponto * passo) / (p * EFICIENCIA_CARGA)
        soc += passo
    return int(round(horas * 60))


def teto_kw(charger: dict, veiculo: dict) -> float:
    """O menor entre o carregador e o que o veículo aceita, já com derating."""
    nominal = min(float(charger.get("potencia_maxima_kw") or 0),
                  float(veiculo.get("potencia_carro_kw") or charger.get("potencia_maxima_kw") or 0))
    return nominal * fator_termico(charger.get("temperatura_c"))


# ---------------------------------------------------------------------------
# Horário de ponta e tarifa
# ---------------------------------------------------------------------------

def _hora(valor, padrao: str) -> time:
    if isinstance(valor, time):
        return valor
    texto = str(valor or padrao)
    partes = texto.split(":")
    return time(int(partes[0]), int(partes[1]) if len(partes) > 1 else 0)


def em_horario_de_ponta(condominio: dict | None, momento: datetime | None = None) -> bool:
    """Dias úteis dentro da janela [ponta_inicio, ponta_fim), no fuso local."""
    if not condominio:
        return False
    momento = (momento or datetime.now(FUSO)).astimezone(FUSO)
    if momento.weekday() >= 5:          # sábado e domingo não têm ponta
        return False
    inicio = _hora(condominio.get("ponta_inicio"), "18:00")
    fim = _hora(condominio.get("ponta_fim"), "21:00")
    agora_t = momento.time()
    if inicio <= fim:
        return inicio <= agora_t < fim
    return agora_t >= inicio or agora_t < fim   # janela que vira a meia-noite


def multiplicador_ponta(condominio: dict | None) -> float:
    return float((condominio or {}).get("ponta_multiplicador_tarifa") or 1.0)


def tarifa_base(charger: dict) -> float:
    valor = charger.get("tarifa_kwh")
    return float(valor) if valor is not None else TARIFA_PADRAO_KWH


def tarifa_do_momento(charger: dict, condominio: dict | None,
                      momento: datetime | None = None) -> float:
    base = tarifa_base(charger)
    if em_horario_de_ponta(condominio, momento):
        return round(base * multiplicador_ponta(condominio), 4)
    return base


# ---------------------------------------------------------------------------
# Estimativa (prévia) e custo
# ---------------------------------------------------------------------------

def calcular_estimativa(charger: dict, veiculo: dict, percentual_atual: float,
                        alvo: float = 100.0, condominio: dict | None = None,
                        potencia_alocada_kw: float | None = None,
                        momento: datetime | None = None) -> dict:
    """
    Prévia de energia, tempo e custo para levar o veículo de `percentual_atual`
    até `alvo`. Usada na tela de confirmação, na pré-autorização do saldo e
    pelo chatbot - um único dono para a conta.

    `potencia_alocada_kw` entra quando o condomínio está perto do limite: o
    alocador de demanda pode liberar menos que o teto do carregador, e aí o
    tempo sobe. Mostrar o tempo sem isso seria prometer o que não vai
    acontecer.

    O custo usa a tarifa DO MOMENTO (com ponta, se for o caso). É uma
    estimativa conservadora: a cobrança real separa, leitura a leitura, o que
    caiu dentro e fora da ponta (ver custo_da_sessao).
    """
    teto = teto_kw(charger, veiculo)
    if potencia_alocada_kw is not None and potencia_alocada_kw > 0:
        teto = min(teto, float(potencia_alocada_kw))
    teto = round(teto, 4)

    capacidade = float(veiculo.get("capacidade_bateria_kwh") or 0)
    soc = max(0.0, min(100.0, float(percentual_atual)))
    alvo = max(soc, min(100.0, float(alvo)))

    energia_bateria = capacidade * (alvo - soc) / 100.0
    energia_rede = energia_bateria / EFICIENCIA_CARGA

    ponta = em_horario_de_ponta(condominio, momento)
    tarifa = tarifa_do_momento(charger, condominio, momento)

    return {
        "potencia_efetiva_kw": teto,
        "potencia_agora_kw": round(potencia_no_soc(teto, soc), 4),
        "energia_necessaria_kwh": round(energia_rede, 5),
        "energia_bateria_kwh": round(energia_bateria, 5),
        "tempo_estimado_min": tempo_de_carga_min(capacidade, soc, alvo, teto),
        # Nunca zero: mesmo uma recarga de centavos reserva R$ 0,01.
        "custo_estimado": max(0.01, round(energia_rede * tarifa, 2)) if energia_rede > 0 else 0.0,
        "tarifa_kwh": tarifa,
        "tarifa_base_kwh": tarifa_base(charger),
        "em_ponta": ponta,
        "multiplicador_ponta": multiplicador_ponta(condominio),
        "fator_termico": round(fator_termico(charger.get("temperatura_c")), 3),
        "temperatura_c": charger.get("temperatura_c"),
        "eficiencia": EFICIENCIA_CARGA,
        "limitado_pela_demanda": potencia_alocada_kw is not None
                                  and 0 < float(potencia_alocada_kw) < teto_kw(charger, veiculo),
    }


def custo_da_sessao(sessao: dict) -> float:
    """
    Custo real: energia fora da ponta pela tarifa base, energia na ponta pela
    tarifa base vezes o multiplicador. A tarifa e o multiplicador foram
    CONGELADOS na sessão quando ela começou - mudar a tabela depois não muda
    a conta de quem já estava carregando.
    """
    energia = float(sessao.get("energia_entregue_kwh") or 0)
    ponta = min(energia, float(sessao.get("energia_ponta_kwh") or 0))
    fora = energia - ponta
    tarifa = float(sessao.get("tarifa_kwh") or TARIFA_PADRAO_KWH)
    mult = float(sessao.get("multiplicador_ponta") or 1.0)
    return round(fora * tarifa + ponta * tarifa * mult, 2)


def soc_pela_energia(sessao: dict, veiculo: dict, energia_rede_kwh: float) -> float | None:
    """SoC derivado da energia entregue - a inversa da conta da estimativa."""
    capacidade = float(veiculo.get("capacidade_bateria_kwh") or 0)
    if capacidade <= 0:
        return None
    inicial = float(sessao.get("percentual_bateria_inicial") or 0)
    ganho = (energia_rede_kwh * EFICIENCIA_CARGA / capacidade) * 100.0
    return min(100.0, inicial + ganho)


def minutos_pela_potencia_medida(sessao: dict, veiculo: dict, soc: float,
                                 potencia_media_kw: float | None) -> int | None:
    """
    Previsão de término pela potência MEDIDA (bloco 5).

    O modelo teórico supõe o teto do carregador. Um celular num carregador de
    25 W puxa 7 a 10 W e cai perto do fim - quem sabe quanto ele está puxando
    é o sensor. Energia que falta dividida pela média recente do que o sensor
    mediu: a previsão se corrige sozinha a cada leitura.
    """
    if not potencia_media_kw or potencia_media_kw <= 0:
        return None
    capacidade = float(veiculo.get("capacidade_bateria_kwh") or 0)
    alvo = float(sessao.get("alvo_percentual") or 100)
    if capacidade <= 0 or soc >= alvo:
        return 0
    energia_rede_restante = capacidade * (alvo - soc) / 100.0 / EFICIENCIA_CARGA
    return max(0, int(round(energia_rede_restante / potencia_media_kw * 60)))
