"""
demanda.py - Gestão de demanda de potência do condomínio (Bloco 3).
====================================================================

O PROBLEMA
----------
O quadro geral do prédio aguenta uma potência máxima (`limite_potencia_kw`).
Seis carros de 7,4 kW puxando ao mesmo tempo somam 44 kW; se o limite for 30,
o disjuntor geral desarma e o prédio inteiro fica sem luz - não só a garagem.

A SOLUÇÃO: UM ALOCADOR SÓ
-------------------------
Toda decisão de "quanto cada ponto pode puxar agora" passa por `alocar()`.
Ela roda a cada ciclo do simulador (10 s) e também no instante em que uma
recarga começa ou termina, para reagir sem esperar o próximo ciclo.

Como divide (water-filling, o mesmo princípio de balanceamento dinâmico dos
wallboxes comerciais):
  1. Cargas que NÃO dá para modular entram primeiro, pelo que estão puxando:
     o ponto do ESP32 (relé liga/desliga, não regula corrente) e qualquer
     carga minúscula como um celular.
  2. O que sobra é dividido igualmente entre os carros. Quem precisa de menos
     que a sua parte (carro quase cheio, na fase lenta da curva) recebe só o
     que precisa, e a sobra volta para os outros.

HORÁRIO DE PONTA
----------------
Dias úteis na janela do condomínio (padrão 18h-21h) o limite disponível para
recarga cai para `ponta_fator_limite` (padrão 60%): é quando o prédio inteiro
consome mais e a energia é mais cara. A tarifa sobe junto (ver fisica.py).

ADMISSÃO
--------
Antes de liberar uma recarga nova, `verificar_admissao()` simula a divisão
COM ela. Se algum carro ficaria abaixo de 1,4 kW (6 A em 230 V, o mínimo que
a norma IEC 61851 permite sinalizar), a recarga não começa e o morador é
orientado a entrar na fila. Melhor recusar com clareza do que liberar uma
recarga que não anda.
"""

from fastapi import HTTPException

from config import supabase, um
from fisica import em_horario_de_ponta, potencia_no_soc, teto_kw

MINIMO_CONTROLAVEL_KW = 1.4
LIMIAR_CARGA_FIXA_KW = 0.1
TOLERANCIA_GRAVACAO_KW = 0.01


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def condominio(condominio_id: str) -> dict | None:
    return um(supabase.table("condominios").select("*").eq("id", condominio_id).execute())


def limite_efetivo(cond: dict, momento=None) -> tuple[float, bool]:
    """(limite disponível agora em kW, está em horário de ponta?)"""
    nominal = float(cond.get("limite_potencia_kw") or 0)
    if em_horario_de_ponta(cond, momento):
        return round(nominal * float(cond.get("ponta_fator_limite") or 1), 3), True
    return nominal, False


def _sessoes_ativas(condominio_id: str) -> list[dict]:
    chargers = supabase.table("carregadores").select(
        "id, numero, potencia_maxima_kw, temperatura_c, origem, perfil"
    ).eq("condominio_id", condominio_id).execute().data or []
    if not chargers:
        return []
    por_id = {c["id"]: c for c in chargers}

    sessoes = supabase.table("sessoes_recarga").select(
        "id, carregador_id, percentual_bateria_atual, potencia_atual_kw, potencia_alocada_kw, "
        "veiculos(capacidade_bateria_kwh, potencia_carro_kw, tipo)"
    ).eq("status", "carregando").in_("carregador_id", list(por_id)).execute().data or []

    itens = []
    for s in sessoes:
        c = por_id[s["carregador_id"]]
        v = s.get("veiculos") or {}
        teto = teto_kw(c, v)
        soc = float(s.get("percentual_bateria_atual") or 0)
        fixa = c.get("origem") == "hardware" or teto < LIMIAR_CARGA_FIXA_KW
        medida = float(s.get("potencia_atual_kw") or 0)
        itens.append({
            "id": s["id"],
            "carregador_numero": c["numero"],
            "controlavel": not fixa,
            # Carga fixa entra pelo que está MEDINDO; carro, pelo que aceitaria.
            "demanda_kw": round(medida if (fixa and medida > 0) else potencia_no_soc(teto, soc), 4),
            "alocado_atual": s.get("potencia_alocada_kw"),
        })
    return itens


# ---------------------------------------------------------------------------
# Divisão (função pura - testada em testes/test_demanda.py)
# ---------------------------------------------------------------------------

def distribuir(limite_kw: float, itens: list[dict]) -> dict:
    """
    Water-filling. `itens`: [{id, demanda_kw, controlavel}]. Devolve {id: kW}.
    """
    alocacao = {}
    restante = max(0.0, float(limite_kw))

    for it in (i for i in itens if not i["controlavel"]):
        alocacao[it["id"]] = it["demanda_kw"]
        restante -= it["demanda_kw"]
    restante = max(0.0, restante)

    controlaveis = sorted((i for i in itens if i["controlavel"]), key=lambda i: i["demanda_kw"])
    faltam = len(controlaveis)
    for it in controlaveis:
        parte = restante / faltam if faltam else 0
        dado = min(it["demanda_kw"], parte)
        alocacao[it["id"]] = round(dado, 4)
        restante -= dado
        faltam -= 1
    return alocacao


# ---------------------------------------------------------------------------
# O alocador
# ---------------------------------------------------------------------------

def alocar(condominio_id: str, gravar: bool = True) -> dict:
    cond = condominio(condominio_id)
    if not cond:
        return {}
    limite, ponta = limite_efetivo(cond)
    itens = _sessoes_ativas(condominio_id)
    alocacao = distribuir(limite, itens)

    if gravar:
        for it in itens:
            novo = alocacao.get(it["id"], 0)
            antigo = it.get("alocado_atual")
            if antigo is None or abs(float(antigo) - novo) > TOLERANCIA_GRAVACAO_KW:
                supabase.table("sessoes_recarga").update(
                    {"potencia_alocada_kw": round(novo, 4)}
                ).eq("id", it["id"]).execute()

    demanda = sum(i["demanda_kw"] for i in itens)
    alocado = sum(alocacao.values())
    return {
        "condominio_id": condominio_id,
        "limite_nominal_kw": float(cond.get("limite_potencia_kw") or 0),
        "limite_kw": limite,
        "em_ponta": ponta,
        "demanda_kw": round(demanda, 3),
        "alocado_kw": round(alocado, 3),
        "folga_kw": round(max(0.0, limite - alocado), 3),
        "limitando": demanda - alocado > TOLERANCIA_GRAVACAO_KW,
        "sessoes": [
            {**{k: v for k, v in i.items() if k != "alocado_atual"},
             "alocado_kw": alocacao.get(i["id"], 0)}
            for i in itens
        ],
    }


def verificar_admissao(condominio_id: str, charger: dict, veiculo: dict, soc: float) -> float:
    """
    Simula a divisão COM a recarga nova. Devolve os kW que ela receberia, ou
    levanta 409 se ela (ou alguém) ficaria abaixo do mínimo.
    """
    cond = condominio(condominio_id)
    if not cond:
        raise HTTPException(status_code=404, detail="Condomínio não encontrado.")
    limite, ponta = limite_efetivo(cond)

    teto = teto_kw(charger, veiculo)
    fixa = charger.get("origem") == "hardware" or teto < LIMIAR_CARGA_FIXA_KW
    nova = {"id": "__nova__", "demanda_kw": potencia_no_soc(teto, soc), "controlavel": not fixa}

    itens = _sessoes_ativas(condominio_id) + [nova]
    alocacao = distribuir(limite, itens)
    recebe = alocacao["__nova__"]

    motivo_ponta = " (horário de ponta: o limite está reduzido)" if ponta else ""
    if fixa:
        carga_fixa = sum(i["demanda_kw"] for i in itens if not i["controlavel"])
        if carga_fixa > limite + 1e-9:
            raise HTTPException(status_code=409, detail=(
                f"O condomínio está no limite de potência{motivo_ponta}. Entre na fila."))
        return recebe

    # Cada carro controlável precisa receber o mínimo de 1,4 kW - OU o que ele
    # pede, se pede menos (carro quase cheio na fase lenta da curva). Antes a
    # regra comparava o MENOR valor alocado com 1,4 kW: um carro a 99% pedindo
    # 0,9 kW fazia o prédio recusar recarga nova mesmo com 30 kW sobrando.
    abaixo = [i for i in itens if i["controlavel"]
              and alocacao[i["id"]] + 1e-9 < min(MINIMO_CONTROLAVEL_KW, i["demanda_kw"])]
    if abaixo:
        raise HTTPException(status_code=409, detail=(
            f"O condomínio está no limite de potência{motivo_ponta}: liberar mais um carro "
            f"deixaria algum abaixo de {MINIMO_CONTROLAVEL_KW:.1f} kW. Entre na fila e você "
            "será avisado quando houver potência."))
    return recebe


# ---------------------------------------------------------------------------
# Registro (curva do gestor e recusas) - nunca derruba a recarga se falhar
# ---------------------------------------------------------------------------

def registrar_consumo(condominio_id: str, kwh: float, ponta: bool, carga_kw: float,
                      demanda_kw: float = 0.0) -> None:
    """
    Soma energia na hora cheia e guarda dois picos: o que o prédio PUXOU
    (com gestão) e o que teria puxado se todo mundo carregasse no máximo
    (sem gestão). A diferença entre os dois é o gráfico que prova o valor
    da gestão de demanda. Se a migration 14 não rodou, grava só o antigo.
    """
    base = {"p_cond": condominio_id, "p_kwh": round(max(0.0, kwh), 6), "p_ponta": bool(ponta),
            "p_carga_kw": round(max(0.0, carga_kw), 4)}
    try:
        supabase.rpc("registrar_consumo", {**base, "p_demanda_kw": round(max(0.0, demanda_kw), 4)}).execute()
    except Exception:
        try:
            supabase.rpc("registrar_consumo", base).execute()
        except Exception as e:
            print(f"[CONSUMO] falhou: {e}")


def registrar_recusa(condominio_id: str, usuario_id: str | None, carregador_id: str | None,
                     etapa: str) -> None:
    """Recarga barrada pelo limite: vira número no painel do síndico."""
    try:
        cond = condominio(condominio_id) or {}
        limite, ponta = limite_efetivo(cond) if cond else (0.0, False)
        supabase.table("eventos_demanda").insert({
            "condominio_id": condominio_id, "usuario_id": usuario_id,
            "carregador_id": carregador_id, "tipo": "recusa_limite", "etapa": etapa,
            "limite_kw": limite, "em_ponta": ponta,
        }).execute()
    except Exception as e:
        print(f"[DEMANDA] recusa não registrada: {e}")


# ---------------------------------------------------------------------------
# Simulação de cenário (painel do síndico e explicação na banca)
# ---------------------------------------------------------------------------

def simular_cenario(limite_kw: float, carros: int, potencia_carro_kw: float,
                    carga_fixa_kw: float = 0.0) -> dict:
    """
    "E se N carros ligarem ao mesmo tempo?" - roda o MESMO `distribuir()` da
    operação real, sem tocar no banco. Mostra o pico sem gestão, quantos
    entram com pelo menos 1,4 kW e quantos iriam para a fila.
    """
    carros = max(0, int(carros))
    p = max(0.0, float(potencia_carro_kw))
    limite = max(0.0, float(limite_kw))
    livre = max(0.0, limite - max(0.0, carga_fixa_kw))

    # Quantos cabem sem ninguém ficar abaixo do mínimo.
    minimo = min(MINIMO_CONTROLAVEL_KW, p) if p > 0 else MINIMO_CONTROLAVEL_KW
    cabem = carros if p == 0 else min(carros, int(livre // minimo)) if minimo > 0 else carros

    itens = [{"id": f"carro_{i + 1}", "demanda_kw": p, "controlavel": True} for i in range(cabem)]
    alocacao = distribuir(livre, itens)
    por_carro = round(alocacao["carro_1"], 3) if cabem else 0.0
    sem_gestao = round(carros * p + max(0.0, carga_fixa_kw), 3)
    return {
        "limite_kw": round(limite, 3),
        "carros": carros,
        "potencia_carro_kw": round(p, 3),
        "pico_sem_gestao_kw": sem_gestao,
        "estouraria_limite": sem_gestao > limite + 1e-9,
        "excesso_evitado_kw": round(max(0.0, sem_gestao - limite), 3),
        "admitidos": cabem,
        "na_fila": carros - cabem,
        "kw_por_carro": por_carro,
        "pico_com_gestao_kw": round(min(limite, sum(alocacao.values()) + max(0.0, carga_fixa_kw)), 2),
        "fracao_da_potencia_nominal": round(por_carro / p, 3) if p > 0 else None,
        "minimo_por_carro_kw": MINIMO_CONTROLAVEL_KW,
    }
