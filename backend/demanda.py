"""
demanda.py - Gestão de demanda de potência do condomínio, em duas fontes.
=========================================================================

O PROBLEMA
----------
O quadro geral do prédio aguenta uma potência máxima (`limite_potencia_kw`).
Seis carros de 7 kW puxando ao mesmo tempo somam 42 kW; se o limite for 30,
o disjuntor geral desarma e o prédio inteiro fica sem luz - não só a garagem.

A SOLUÇÃO: UM ALOCADOR SÓ (ADR-016)
-----------------------------------
Toda decisão de "quanto cada ponto pode puxar agora, e de qual fonte" passa
por `distribuir_fontes()`. Ela roda a cada ciclo do simulador (10 s) e no
instante em que uma recarga começa ou termina.

Duas fontes, nunca misturadas:
  rede   limitada pelo quadro (menor na ponta), paga pela tarifa da distribuidora
  sol    excedente FV lido de `geracao_solar` (opcional: FV = 0 desliga tudo)

Os parâmetros de cada ponto são os do mapa Modbus do HCA G2:
  10025 controle dinâmico   ligado = o alocador modula; desligado = carga fixa
  10026 disjuntor (A)       teto do ponto, só com o 10025 ligado
  10029 potência máxima     teto do ponto
  10032 modo de carga       0 rápido (rede + sol) · 1 prioridade FV (só sol)
  10024 garantir mínimo     no modo FV, completa da rede até 1,4/4,2 kW

Ordem da divisão:
  1. Cargas fixas (ESP32, 10025 desligado) levam o que pedem - sol primeiro.
  2. Sol restante: primeiro para quem está em modo FV, depois para o rápido.
  3. Rede restante: o que falta ao modo rápido; o modo FV com 10024 recebe
     só o que falta para o mínimo.
  4. Ninguém fica abaixo do mínimo do modelo (6 A por fase): quem não
     alcança é PAUSADO, como o HCA G2 faz. Na falta, pausa quem chegou por último.

ADMISSÃO
--------
Conta só a REDE. O sol não é despachável: admitir um carro contando com o
meio-dia é prometer o que não se cumpre às 17h.

VAGA SOLAR DO TOTEM (ADR-018 D6)
--------------------------------
Na bancada o painel é ligado SÓ à porta solar (comutação painel/bateria,
nunca em paralelo). As portas vizinhas da mesma placa entram com
`so_rede = True`: não recebem sol atribuído. A política da bateria da porta
solar (Modbus 10030 + 10024) é `decidir_vaga_solar()`, função pura.

HONESTIDADE
-----------
Os parâmetros são armazenados e simulados; o sistema não fala Modbus RS485
com um HCA G2. Num equipamento real, `alocado_kw` seria escrito no 10029 e a
parcela da rede corresponde ao 10039 (limite de compra da rede).
"""

from datetime import timedelta

from fastapi import HTTPException

import dispositivos
from config import SOLAR_VALIDADE_MIN, agora, supabase, um
from fisica import MINIMO_MONOFASICO_KW, em_horario_de_ponta, minimo_kw, potencia_no_soc, teto_kw

MINIMO_CONTROLAVEL_KW = MINIMO_MONOFASICO_KW      # referência (ponto de 7 kW)
LIMIAR_CARGA_FIXA_KW = 0.1
TOLERANCIA_GRAVACAO_KW = 0.01
EPS = 1e-9

PAUSA_LIMITE = "limite_da_rede"
PAUSA_SEM_SOL = "sem_excedente_fv"      # status 10 do registrador 10017


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def condominio(condominio_id: str) -> dict | None:
    return um(supabase.table("condominios").select("*").eq("id", condominio_id).execute())


def limite_efetivo(cond: dict, momento=None) -> tuple[float, bool]:
    """(limite da REDE disponível agora em kW, está em horário de ponta?)"""
    nominal = float(cond.get("limite_potencia_kw") or 0)
    if em_horario_de_ponta(cond, momento):
        return round(nominal * float(cond.get("ponta_fator_limite") or 1), 3), True
    return nominal, False


def fv_ativo(cond: dict | None) -> bool:
    return float((cond or {}).get("fv_potencia_kwp") or 0) > 0


def excedente_solar(cond: dict | None) -> tuple[float, str | None]:
    """
    (kW de sol disponível agora, origem do número). Lê SÓ `geracao_solar`:
    hoje o simulador grava 'simulado'; com inversor, alguém grava 'medido'
    e nada aqui muda. Sem leitura recente = 0 (sem sol, nada se promete).
    """
    if not fv_ativo(cond):
        return 0.0, None
    desde = (agora() - timedelta(minutes=SOLAR_VALIDADE_MIN)).isoformat()
    try:
        linha = um(supabase.table("geracao_solar").select("potencia_kw, origem, momento")
                   .eq("condominio_id", cond["id"]).gte("momento", desde)
                   .order("momento", desc=True).limit(1).execute())
    except Exception as e:
        print(f"[DEMANDA] geração solar indisponível: {e}")
        return 0.0, None
    if not linha:
        return 0.0, None
    return max(0.0, float(linha.get("potencia_kw") or 0)), linha.get("origem") or "simulado"


def modo_efetivo(charger: dict, cond: dict | None) -> int:
    """
    10032: 0 rápido, 1 FV, 2 FV + bateria. Sem bateria modelada, 2 vale 1
    (a API nem deixa gravar 2). Sem FV no condomínio, todo modo vira rápido.
    """
    modo = int(charger.get("modo_carga") or 0)
    if modo == 0 or not fv_ativo(cond):
        return 0
    return 1


def item_de(charger: dict, veiculo: dict, soc: float, cond: dict | None, item_id: str,
            ordem: int, medida_kw: float = 0.0, so_rede: bool = False) -> dict:
    """Um ponto em uso visto pelo alocador."""
    teto = teto_kw(charger, veiculo)
    hardware = charger.get("origem") == "hardware"
    minusculo = teto < LIMIAR_CARGA_FIXA_KW
    fixa = hardware or minusculo or charger.get("controle_dinamico") is False
    # Relé do ESP32 e cargas minúsculas entram pelo que estão MEDINDO; carro
    # (modulado ou não), pelo que a bateria aceitaria.
    usar_medida = (hardware or minusculo) and medida_kw > 0
    demanda = medida_kw if usar_medida else potencia_no_soc(teto, soc)
    return {
        "id": item_id,
        "carregador_id": charger.get("id"),
        "carregador_numero": charger.get("numero"),
        "controlavel": not fixa,
        "demanda_kw": round(demanda, 4),
        "minimo_kw": 0.0 if fixa else minimo_kw(charger, veiculo),
        "modo": modo_efetivo(charger, cond),
        "garantir_minimo": bool(charger.get("garantir_minimo")),
        "ordem": ordem,
        "so_rede": bool(so_rede),
    }


def _sessoes_ativas(condominio_id: str, cond: dict | None = None) -> list[dict]:
    cond = cond or condominio(condominio_id)
    chargers = supabase.table("carregadores").select("*").eq("condominio_id", condominio_id) \
        .execute().data or []
    if not chargers:
        return []
    por_id = {c["id"]: c for c in chargers}

    sessoes = supabase.table("sessoes_recarga").select(
        "*, veiculos(capacidade_bateria_kwh, potencia_carro_kw, tipo)"
    ).eq("status", "carregando").in_("carregador_id", list(por_id)).execute().data or []
    # Ordem de chegada decide quem pausa primeiro na falta.
    sessoes.sort(key=lambda s: str(s.get("iniciado_em") or s.get("criado_em") or ""))

    so_rede = dispositivos.carregadores_so_rede(list({s["carregador_id"] for s in sessoes})) \
        if sessoes else set()
    itens = []
    for ordem, s in enumerate(sessoes):
        it = item_de(por_id[s["carregador_id"]], s.get("veiculos") or {},
                     float(s.get("percentual_bateria_atual") or 0), cond, s["id"], ordem,
                     float(s.get("potencia_atual_kw") or 0), so_rede=s["carregador_id"] in so_rede)
        it["alocado_atual"] = s.get("potencia_alocada_kw")
        it["alocado_solar_atual"] = s.get("potencia_alocada_solar_kw")
        itens.append(it)
    return itens


# ---------------------------------------------------------------------------
# Divisão (funções puras - testadas em testes/)
# ---------------------------------------------------------------------------

def distribuir(limite_kw: float, itens: list[dict]) -> dict:
    """
    Water-filling de UMA fonte. `itens`: [{id, demanda_kw, controlavel}].
    Devolve {id: kW}. É o tijolo de `distribuir_fontes`.
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


def _normalizar(it: dict, ordem_padrao: int) -> dict:
    """Aceita itens antigos ({id, demanda_kw, controlavel}) sem os campos novos."""
    controlavel = bool(it.get("controlavel", True))
    return {**it,
            "controlavel": controlavel,
            "demanda_kw": max(0.0, float(it.get("demanda_kw") or 0)),
            "minimo_kw": float(it.get("minimo_kw", MINIMO_CONTROLAVEL_KW if controlavel else 0.0)),
            "modo": int(it.get("modo") or 0),
            "garantir_minimo": bool(it.get("garantir_minimo")),
            "ordem": it.get("ordem", ordem_padrao)}


def _piso(it: dict) -> float:
    """Mínimo que o ponto precisa receber para carregar - ou o que o carro pede, se pede menos."""
    return min(it["minimo_kw"], it["demanda_kw"])


def _tentar(ativos: list[dict], sol: float, rede: float) -> dict:
    """Uma rodada de divisão para um conjunto de moduláveis: {id: (kW sol, kW rede)}."""
    fv = [i for i in ativos if i["modo"] == 1]
    rapidos = [i for i in ativos if i["modo"] == 0]

    a_fv = distribuir(sol, [{"id": i["id"], "demanda_kw": i["demanda_kw"], "controlavel": True} for i in fv])
    sol_resto = max(0.0, sol - sum(a_fv.values()))
    a_rs = distribuir(sol_resto, [{"id": i["id"], "demanda_kw": i["demanda_kw"], "controlavel": True}
                                  for i in rapidos])

    pedidos = [{"id": i["id"], "demanda_kw": max(0.0, i["demanda_kw"] - a_rs.get(i["id"], 0.0)),
                "controlavel": True} for i in rapidos]
    pedidos += [{"id": i["id"], "demanda_kw": max(0.0, _piso(i) - a_fv.get(i["id"], 0.0)),
                 "controlavel": True} for i in fv if i["garantir_minimo"]]
    a_rede = distribuir(rede, pedidos)

    return {i["id"]: (a_fv.get(i["id"], a_rs.get(i["id"], 0.0)), a_rede.get(i["id"], 0.0)) for i in ativos}


def distribuir_fontes(limite_rede_kw: float, solar_kw: float, itens: list[dict]) -> dict:
    """
    Divide rede e sol entre os pontos em uso (ver o docstring do módulo).

    Item: {id, demanda_kw, controlavel, minimo_kw, modo (0|1), garantir_minimo, ordem}.
    Devolve {"itens": {id: {alocado_kw, alocado_solar_kw, alocado_rede_kw, pausado_motivo}},
             rede_kw, solar_kw, solar_absorvido_kw, solar_nao_aproveitado_kw, estouro_kw}.
    Com sol = 0, todos moduláveis em modo 0 e ninguém abaixo do mínimo, dá
    exatamente o mesmo que `distribuir(limite, itens)`.
    """
    norm = [_normalizar(it, k) for k, it in enumerate(itens)]
    sol_total = max(0.0, float(solar_kw))
    sol, rede = sol_total, max(0.0, float(limite_rede_kw))
    out = {it["id"]: {"alocado_kw": 0.0, "alocado_solar_kw": 0.0, "alocado_rede_kw": 0.0,
                      "pausado_motivo": None} for it in norm}

    # 1. Fixas: levam o que pedem. Sol primeiro, depois rede - mesmo que estoure.
    #    `so_rede` (porta vizinha da vaga solar na bancada) não recebe sol.
    for it in (i for i in norm if not i["controlavel"]):
        do_sol = 0.0 if it.get("so_rede") else min(it["demanda_kw"], sol)
        sol -= do_sol
        da_rede = it["demanda_kw"] - do_sol
        rede -= da_rede
        out[it["id"]].update(alocado_solar_kw=do_sol, alocado_rede_kw=da_rede)
    estouro = max(0.0, -rede)
    rede = max(0.0, rede)

    # 2-4. Moduláveis, pausando quem não alcança o mínimo.
    ativos = sorted((i for i in norm if i["controlavel"]), key=lambda i: i["ordem"])
    while True:
        tentativa = _tentar(ativos, sol, rede)
        abaixo = [i for i in ativos if sum(tentativa[i["id"]]) + EPS < _piso(i)]
        if not abaixo:
            break
        so_sol = [i for i in abaixo if i["modo"] == 1 and not i["garantir_minimo"]]
        if so_sol:
            vez, motivo = max(so_sol, key=lambda i: i["ordem"]), PAUSA_SEM_SOL
        else:
            dependentes = [i for i in ativos if i["modo"] == 0 or i["garantir_minimo"]]
            vez, motivo = max(dependentes, key=lambda i: i["ordem"]), PAUSA_LIMITE
        ativos.remove(vez)
        out[vez["id"]]["pausado_motivo"] = motivo

    for it in ativos:
        do_sol, da_rede = tentativa[it["id"]]
        out[it["id"]].update(alocado_solar_kw=do_sol, alocado_rede_kw=da_rede)

    for x in out.values():
        x["alocado_solar_kw"] = round(x["alocado_solar_kw"], 4)
        x["alocado_rede_kw"] = round(x["alocado_rede_kw"], 4)
        x["alocado_kw"] = round(x["alocado_solar_kw"] + x["alocado_rede_kw"], 4)

    # Totais em 3 casas: a soma de partes arredondadas em 4 casas pode passar
    # do disponível por 0,0001 kW (5/3 x 3 = 5,0001), e o sol absorvido nunca
    # é maior que o gerado.
    absorvido = min(sol_total, sum(x["alocado_solar_kw"] for x in out.values()))
    return {
        "itens": out,
        "rede_kw": round(sum(x["alocado_rede_kw"] for x in out.values()), 3),
        "solar_kw": round(sol_total, 3),
        "solar_absorvido_kw": round(absorvido, 3),
        "solar_nao_aproveitado_kw": round(max(0.0, sol_total - absorvido), 3),
        "estouro_kw": round(estouro, 3),
    }


def avaliar_admissao(limite_rede_kw: float, itens: list[dict], nova: dict) -> tuple[float | None, str | None]:
    """
    Pura. (kW que a recarga nova receberia, motivo da recusa ou None).
    Simula SÓ com a rede: o sol nunca é capacidade garantida (ADR-016 P3).
    """
    todos = list(itens) + [nova]
    r = distribuir_fontes(limite_rede_kw, 0.0, todos)
    recebe = r["itens"][nova["id"]]["alocado_kw"]
    norm = _normalizar(nova, len(todos))

    if not norm["controlavel"]:
        fixa = sum(_normalizar(i, 0)["demanda_kw"] for i in todos if not _normalizar(i, 0)["controlavel"])
        return (None, "limite") if fixa > limite_rede_kw + EPS else (recebe, None)
    if norm["modo"] == 1 and not norm["garantir_minimo"]:
        return None, None            # só sol: não usa rede, espera o sol pausada
    if any(x["pausado_motivo"] == PAUSA_LIMITE for x in r["itens"].values()):
        return None, "minimo"
    return recebe, None


# ---------------------------------------------------------------------------
# Vaga solar: bateria x Modbus 10030 / 10024 (função pura)
# ---------------------------------------------------------------------------

HISTERESE_SOC = 5.0            # volta ao sol só com 10030 + 5 pontos (sem liga-desliga)
LIMIAR_DESCARGA_W = 0.05       # W BRUTOS: a bateria está entregando à vaga
MODOS_VAGA_SOLAR = ("solar", "rede", "pausada")


def decidir_vaga_solar(modo_atual: str | None, soc: float | None, bateria_w: float | None,
                       soc_minimo: float, garantir_minimo: bool) -> str:
    """
    Modbus 10030: abaixo deste SOC a bateria NÃO descarrega mais para o ponto.
    Com o painel dando conta (bateria parada), a vaga segue no sol mesmo com
    a bateria baixa. Com a bateria descarregando abaixo do mínimo:
      10024 ligado    -> "rede"     (manual 3.5: garantir potência mínima)
      10024 desligado -> "pausada"  (status 10 do 10017: PV/bateria insuficiente)
    Volta ao "solar" quando o SOC passa de 10030 + HISTERESE_SOC.
    Sem leitura de bateria, não muda nada (não se decide no escuro).
    """
    modo = modo_atual if modo_atual in MODOS_VAGA_SOLAR else "solar"
    if soc is None:
        return modo
    minimo = max(0.0, min(100.0, float(soc_minimo)))
    if modo in ("pausada", "rede"):
        if soc >= minimo + HISTERESE_SOC:
            return "solar"
        return "rede" if garantir_minimo else "pausada"
    if soc < minimo and float(bateria_w or 0) > LIMIAR_DESCARGA_W:
        return "rede" if garantir_minimo else "pausada"
    return "solar"


# ---------------------------------------------------------------------------
# O alocador
# ---------------------------------------------------------------------------

def alocar(condominio_id: str, gravar: bool = True) -> dict:
    cond = condominio(condominio_id)
    if not cond:
        return {}
    limite, ponta = limite_efetivo(cond)
    solar, origem = excedente_solar(cond)
    itens = _sessoes_ativas(condominio_id, cond)
    r = distribuir_fontes(limite, solar, itens)
    ativo = fv_ativo(cond)

    if gravar:
        for it in itens:
            x = r["itens"][it["id"]]
            upd = {}
            antigo = it.get("alocado_atual")
            if antigo is None or abs(float(antigo) - x["alocado_kw"]) > TOLERANCIA_GRAVACAO_KW:
                upd["potencia_alocada_kw"] = x["alocado_kw"]
            # Parcela solar só é escrita com FV ligado (ou para zerar uma antiga):
            # com FV = 0 o sistema escreve exatamente o que escrevia antes do 16.
            sol_antigo = it.get("alocado_solar_atual")
            if ativo or (sol_antigo is not None and float(sol_antigo) != 0):
                if sol_antigo is None or abs(float(sol_antigo) - x["alocado_solar_kw"]) > TOLERANCIA_GRAVACAO_KW:
                    upd["potencia_alocada_solar_kw"] = x["alocado_solar_kw"]
            if upd:
                supabase.table("sessoes_recarga").update(upd).eq("id", it["id"]).execute()

    demanda = sum(i["demanda_kw"] for i in itens)
    alocado = sum(x["alocado_kw"] for x in r["itens"].values())
    return {
        "condominio_id": condominio_id,
        "limite_nominal_kw": float(cond.get("limite_potencia_kw") or 0),
        "limite_kw": limite,
        "em_ponta": ponta,
        "demanda_kw": round(demanda, 3),
        "alocado_kw": round(alocado, 3),
        "rede_kw": round(r["rede_kw"], 3),
        "folga_kw": round(max(0.0, limite - r["rede_kw"]), 3),
        "limitando": demanda - alocado > TOLERANCIA_GRAVACAO_KW,
        "estouro_kw": r["estouro_kw"],
        "fv_ativo": ativo,
        "solar_kw": r["solar_kw"],
        "origem_solar": f"solar_{origem}" if origem else None,
        "solar_absorvido_kw": r["solar_absorvido_kw"],
        "solar_nao_aproveitado_kw": r["solar_nao_aproveitado_kw"],
        "sessoes": [
            {**{k: v for k, v in i.items() if k not in ("alocado_atual", "alocado_solar_atual")},
             **r["itens"][i["id"]]}
            for i in itens
        ],
    }


def verificar_admissao(condominio_id: str, charger: dict, veiculo: dict, soc: float) -> float | None:
    """
    Simula a divisão COM a recarga nova, só com a rede. Devolve os kW que ela
    receberia (None para modo FV puro, que espera o sol), ou levanta 409.
    """
    cond = condominio(condominio_id)
    if not cond:
        raise HTTPException(status_code=404, detail="Condomínio não encontrado.")
    limite, ponta = limite_efetivo(cond)
    itens = _sessoes_ativas(condominio_id)
    nova = item_de(charger, veiculo, soc, cond, "__nova__", len(itens) + 10**6)
    recebe, motivo = avaliar_admissao(limite, itens, nova)

    motivo_ponta = " (horário de ponta: o limite está reduzido)" if ponta else ""
    if motivo == "limite":
        raise HTTPException(status_code=409, detail=(
            f"O condomínio está no limite de potência{motivo_ponta}. Entre na fila."))
    if motivo == "minimo":
        raise HTTPException(status_code=409, detail=(
            f"O condomínio está no limite de potência{motivo_ponta}: liberar mais um carro "
            f"deixaria algum abaixo da potência mínima do carregador ({nova['minimo_kw']:.1f} kW). "
            "Entre na fila e você será avisado quando houver potência."))
    return recebe


# ---------------------------------------------------------------------------
# Registro (curva do gestor e recusas) - nunca derruba a recarga se falhar
# ---------------------------------------------------------------------------

def registrar_consumo(condominio_id: str, kwh: float, ponta: bool, carga_kw: float,
                      demanda_kw: float = 0.0, solar_kwh: float = 0.0,
                      rede_kw: float | None = None) -> None:
    """
    Soma energia na hora cheia (total e a parte solar) e guarda três picos:
    o que a garagem PUXOU (com gestão), o que teria puxado sem gestão e o que
    veio da REDE. Sem gestão - com gestão = pico evitado; garagem - rede =
    pico coberto pelo sol. Cai para as assinaturas antigas se o 16 não rodou.
    """
    base = {"p_cond": condominio_id, "p_kwh": round(max(0.0, kwh), 6), "p_ponta": bool(ponta),
            "p_carga_kw": round(max(0.0, carga_kw), 4)}
    com_demanda = {**base, "p_demanda_kw": round(max(0.0, demanda_kw), 4)}
    completo = {**com_demanda, "p_solar_kwh": round(max(0.0, solar_kwh), 6),
                "p_rede_kw": round(max(0.0, carga_kw if rede_kw is None else rede_kw), 4)}
    for params in (completo, com_demanda, base):
        try:
            supabase.rpc("registrar_consumo", params).execute()
            return
        except Exception as e:
            erro = e
    print(f"[CONSUMO] falhou: {erro}")


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
                    carga_fixa_kw: float = 0.0, solar_kw: float = 0.0) -> dict:
    """
    "E se N carros ligarem ao mesmo tempo?" - roda o MESMO `distribuir()` da
    operação real, sem tocar no banco. Mostra o pico sem gestão, quantos
    entram com pelo menos 1,4 kW e quantos iriam para a fila.

    `solar_kw` (opcional): "e se houvesse FV gerando isto agora?" - a
    admissão continua só pela rede (o sol não é garantido); o resultado
    mostra quanto do pico o sol tiraria da rede.
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
        "solar_kw": round(max(0.0, solar_kw), 3),
        "pico_da_rede_com_sol_kw": round(max(0.0, min(limite, sum(alocacao.values()) + max(0.0, carga_fixa_kw))
                                             - max(0.0, solar_kw)), 2),
    }
