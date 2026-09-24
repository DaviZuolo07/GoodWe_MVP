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

from datetime import datetime, time, timedelta

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


def potencia_efetiva(potencia_max_kw: float, soc: float, limite_kw: float | None = None) -> float:
    """
    O que o carro puxa de verdade: o MENOR entre a curva da bateria e o que o
    alocador de demanda liberou. Aplicar a curva em cima do valor alocado
    (o que o código fazia antes) contava a queda acima de 80% duas vezes.
    """
    p = potencia_no_soc(potencia_max_kw, soc)
    if limite_kw is not None:
        p = min(p, max(0.0, float(limite_kw)))     # alocado 0 = carro parado
    return p


def _integrar(capacidade_kwh: float, soc_ini: float, soc_fim: float, potencia_max_kw: float,
              limite_kw: float | None = None, inicio: datetime | None = None,
              condominio: dict | None = None, tarifa: float | None = None) -> dict:
    """
    Integra a recarga em passos de 1% de SoC: dt = dE / P(SoC).

    Com `inicio` e `tarifa`, cada passo é cobrado pela tarifa do INSTANTE em
    que ele acontece. Uma recarga que começa às 17h40 e vai até 18h30 tem
    parte da energia na ponta - a estimativa passa a saber disso, e a
    reserva no saldo cobre o custo real em vez de estourar o teto no meio.
    """
    res = {"horas": 0.0, "custo": 0.0, "energia_ponta_kwh": 0.0}
    if potencia_max_kw <= 0 or soc_fim <= soc_ini or capacidade_kwh <= 0:
        return res
    # Alocação zero (ou desconhecida) não entra no tempo: dividiria por zero.
    if limite_kw is not None and limite_kw <= 0:
        limite_kw = None
    energia_por_ponto = capacidade_kwh / 100.0
    soc = float(soc_ini)
    while soc < soc_fim - 1e-9:
        passo = min(1.0, soc_fim - soc)
        p = potencia_efetiva(potencia_max_kw, soc + passo / 2, limite_kw)
        energia_rede = energia_por_ponto * passo / EFICIENCIA_CARGA
        dt_h = energia_rede / p
        if tarifa is not None:
            momento = (inicio + timedelta(hours=res["horas"] + dt_h / 2)) if inicio else None
            ponta = em_horario_de_ponta(condominio, momento)
            fator = multiplicador_ponta(condominio) if ponta else 1.0
            res["custo"] += energia_rede * tarifa * fator
            if ponta:
                res["energia_ponta_kwh"] += energia_rede
        res["horas"] += dt_h
        soc += passo
    return res


def tempo_de_carga_min(capacidade_kwh: float, soc_ini: float, soc_fim: float,
                       potencia_max_kw: float, limite_kw: float | None = None) -> int:
    """Minutos para ir de soc_ini a soc_fim, respeitando a curva E a alocação."""
    return int(round(_integrar(capacidade_kwh, soc_ini, soc_fim, potencia_max_kw, limite_kw)["horas"] * 60))


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


def fim_da_ponta(condominio: dict | None, momento: datetime | None = None) -> datetime | None:
    """Se agora é ponta, quando ela acaba (no fuso local). Senão, None."""
    if not em_horario_de_ponta(condominio, momento):
        return None
    momento = (momento or datetime.now(FUSO)).astimezone(FUSO)
    fim = _hora(condominio.get("ponta_fim"), "21:00")
    alvo = momento.replace(hour=fim.hour, minute=fim.minute, second=0, microsecond=0)
    if alvo <= momento:                  # janela que vira a meia-noite
        alvo += timedelta(days=1)
    return alvo


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

    O custo é integrado NO TEMPO: cada kWh previsto é cobrado pela tarifa do
    horário em que vai ser entregue (base ou ponta). É a mesma regra da
    cobrança real (custo_da_sessao), aplicada à previsão.
    """
    teto_fisico = teto_kw(charger, veiculo)
    limite = float(potencia_alocada_kw) if potencia_alocada_kw is not None and potencia_alocada_kw > 0 else None
    teto = round(min(teto_fisico, limite) if limite else teto_fisico, 4)

    capacidade = float(veiculo.get("capacidade_bateria_kwh") or 0)
    soc = max(0.0, min(100.0, float(percentual_atual)))
    alvo = max(soc, min(100.0, float(alvo)))

    energia_bateria = capacidade * (alvo - soc) / 100.0
    energia_rede = energia_bateria / EFICIENCIA_CARGA

    inicio = (momento or datetime.now(FUSO)).astimezone(FUSO)
    base = tarifa_base(charger)
    conta = _integrar(capacidade, soc, alvo, teto_fisico, limite, inicio, condominio, base)
    custo = round(conta["custo"], 2)

    # Dica de economia: está na ponta? Quanto custaria começando quando ela acabar?
    economia, ponta_termina = None, fim_da_ponta(condominio, inicio)
    if ponta_termina:
        depois = _integrar(capacidade, soc, alvo, teto_fisico, limite, ponta_termina, condominio, base)
        economia = round(max(0.0, custo - round(depois["custo"], 2)), 2)

    return {
        "potencia_efetiva_kw": teto,
        "potencia_agora_kw": round(potencia_efetiva(teto_fisico, soc, limite), 4),
        "energia_necessaria_kwh": round(energia_rede, 5),
        "energia_bateria_kwh": round(energia_bateria, 5),
        "energia_ponta_estimada_kwh": round(conta["energia_ponta_kwh"], 5),
        "tempo_estimado_min": int(round(conta["horas"] * 60)),
        # Nunca zero: mesmo uma recarga de centavos reserva R$ 0,01.
        "custo_estimado": max(0.01, custo) if energia_rede > 0 else 0.0,
        "tarifa_kwh": tarifa_do_momento(charger, condominio, inicio),
        "tarifa_base_kwh": base,
        "em_ponta": em_horario_de_ponta(condominio, inicio),
        "multiplicador_ponta": multiplicador_ponta(condominio),
        "ponta_termina_em": ponta_termina.isoformat() if ponta_termina else None,
        "economia_se_esperar": economia,
        "fator_termico": round(fator_termico(charger.get("temperatura_c")), 3),
        "temperatura_c": charger.get("temperatura_c"),
        "eficiencia": EFICIENCIA_CARGA,
        "limitado_pela_demanda": limite is not None and limite < teto_fisico,
    }


def detalhar_custo(sessao: dict) -> dict:
    """
    As linhas do recibo. Cada linha é arredondada no centavo e o total é a
    SOMA das linhas - o morador confere com calculadora e bate.
    A tarifa e o multiplicador foram CONGELADOS na sessão quando ela começou:
    mudar a tabela depois não muda a conta de quem já estava carregando.
    """
    energia = float(sessao.get("energia_entregue_kwh") or 0)
    ponta = min(energia, float(sessao.get("energia_ponta_kwh") or 0))
    fora = energia - ponta
    tarifa = float(sessao.get("tarifa_kwh") or TARIFA_PADRAO_KWH)
    mult = float(sessao.get("multiplicador_ponta") or 1.0)
    sub_fora = round(fora * tarifa, 2)
    sub_ponta = round(ponta * tarifa * mult, 2)
    return {
        "energia_kwh": round(energia, 6),
        "energia_fora_ponta_kwh": round(fora, 6),
        "energia_ponta_kwh": round(ponta, 6),
        "tarifa_kwh": tarifa,
        "tarifa_ponta_kwh": round(tarifa * mult, 4),
        "multiplicador_ponta": mult,
        "subtotal_fora_ponta": sub_fora,
        "subtotal_ponta": sub_ponta,
        "total": round(sub_fora + sub_ponta, 2),
    }


def custo_da_sessao(sessao: dict) -> float:
    """Custo real: fora da ponta pela tarifa base, ponta pela base x multiplicador."""
    return detalhar_custo(sessao)["total"]


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
