"""
rotas_gestor.py - Painel do gestor (síndico) - Bloco 3.
=======================================================

O que o gestor responde com este painel, e que antes não tinha como saber:
  - Quanto da potência do prédio a recarga está usando AGORA, e quanto sobra.
  - Se o alocador está segurando alguém (demanda maior que o limite).
  - Quanto a garagem consumiu hoje e no mês, e quanto disso caiu na ponta.
  - Quanto foi faturado, quanto foi estornado e quantas recargas foram
    recusadas por falta de saldo.
  - A curva de carga por hora do dia (onde estão os picos).
  - Quem consome quanto (para rateio ou cobrança no condomínio).
  - (ADR-016) Energia, receita, custo e margem POR FONTE - rede fora da
    ponta, rede na ponta e solar - cada número com a sua origem; quanto o
    sol economizou para morador e condomínio; pico evitado pela gestão e
    pico coberto pelo sol.
  - (ADR-016) Os parâmetros do mapa Modbus de cada carregador HCA G2.

O gestor só vê e só configura o condomínio dele (`usuarios.condominio_id`).
"""

from datetime import datetime, timedelta, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import cartoes
import demanda
from config import FUSO, SOLAR_FATOR_PICO, para_datetime, supabase, um
from fisica import detalhar_custo, economia_vs_so_rede, minimo_kw, potencia_disjuntor_kw
from identidade import gestor_logado

router = APIRouter(prefix="/gestor", tags=["gestor"])


class CartaoCondominio(BaseModel):
    uid: str = Field(..., min_length=4, max_length=40)
    apelido: Optional[str] = Field(None, max_length=40)


# HH:MM de verdade (00:00 a 23:59). O padrão antigo \d{2}:\d{2} aceitava
# "25:99", que quebrava o horário de ponta - e com ele a prévia, a cobrança e
# o laço do simulador de TODOS os condomínios.
HORA_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"

# Premissas de custo da energia para o condomínio (o que ELE paga à
# distribuidora). Padrões ilustrativos: o síndico ajusta com a conta real.
CUSTO_ENERGIA_PADRAO = 0.95
CUSTO_ENERGIA_PONTA_PADRAO = 1.45


class ConfigDemanda(BaseModel):
    limite_potencia_kw: Optional[float] = Field(None, gt=0, le=2000)
    ponta_inicio: Optional[str] = Field(None, pattern=HORA_HHMM)
    ponta_fim: Optional[str] = Field(None, pattern=HORA_HHMM)
    ponta_fator_limite: Optional[float] = Field(None, gt=0, le=1)
    ponta_multiplicador_tarifa: Optional[float] = Field(None, ge=1, le=5)
    custo_energia_kwh: Optional[float] = Field(None, gt=0, le=20)
    custo_energia_ponta_kwh: Optional[float] = Field(None, gt=0, le=20)
    # ADR-016: FV (simulada) e premissas solares. FV = 0 desliga a camada solar.
    fv_potencia_kwp: Optional[float] = Field(None, ge=0, le=1000)
    custo_solar_kwh: Optional[float] = Field(None, gt=0, le=20)
    preco_solar_kwh: Optional[float] = Field(None, gt=0, le=20)
    # Preço do kWh da rede ao morador: vale para TODOS os pontos do condomínio
    # (fica em carregadores.tarifa_kwh, congelado em cada recarga ao começar).
    tarifa_rede_kwh: Optional[float] = Field(None, gt=0, le=20)


class CenarioDemanda(BaseModel):
    carros: int = Field(6, ge=1, le=200)
    potencia_carro_kw: float = Field(7.0, gt=0, le=350)
    limite_kw: Optional[float] = Field(None, gt=0, le=2000)
    em_ponta: bool = False
    # "E se o condomínio tivesse X kWp?" - sol de céu limpo ao meio-dia.
    fv_potencia_kwp: Optional[float] = Field(None, ge=0, le=1000)


class ConfigModbus(BaseModel):
    """Parâmetros do mapa Modbus HCA G2. Campo ausente = não muda."""
    garantir_minimo: Optional[bool] = None            # 10024
    controle_dinamico: Optional[bool] = None          # 10025
    limite_disjuntor_a: Optional[float] = Field(None, ge=0, le=2000)   # 10026 (null limpa)
    potencia_maxima_kw: Optional[float] = Field(None, gt=0, le=22)     # 10029
    modo_carga: Optional[int] = Field(None, ge=0, le=2)                # 10032


# Faixa do registrador 10029 por modelo (mapa Modbus HCA G2).
FAIXA_10029 = {7: (1.4, 7.0), 11: (4.2, 11.0), 22: (4.2, 22.0)}
ROTULO_MODO = {0: "Rápido", 1: "Prioridade de energia FV", 2: "FV + bateria"}
AVISO_MODBUS = ("Parâmetros equivalentes ao mapa Modbus do HCA G2, armazenados e simulados: "
                "o sistema não escreve em RS485.")


def _inicio_local(dias_atras: int = 0, mes: bool = False) -> str:
    agora_local = datetime.now(FUSO)
    base = agora_local.replace(day=1) if mes else agora_local - timedelta(days=dias_atras)
    return datetime.combine(base.date(), time(0, 0), tzinfo=FUSO).isoformat()


def _resumo(sessoes: list[dict]) -> dict:
    finalizadas = [s for s in sessoes if s["status"] == "finalizada"]
    return {
        "recargas": len(finalizadas),
        "energia_faturada_kwh": round(sum(float(s.get("energia_entregue_kwh") or 0) for s in finalizadas), 4),
        "energia_faturada_ponta_kwh": round(sum(float(s.get("energia_ponta_kwh") or 0) for s in finalizadas), 4),
        "energia_faturada_solar_kwh": round(sum(float(s.get("energia_solar_kwh") or 0) for s in finalizadas), 4),
        "energia_kwh": round(sum(float(s.get("energia_entregue_kwh") or 0) for s in sessoes), 4),
        "energia_ponta_kwh": round(sum(float(s.get("energia_ponta_kwh") or 0) for s in sessoes), 4),
        "energia_solar_kwh": round(sum(float(s.get("energia_solar_kwh") or 0) for s in sessoes), 4),
        "faturamento": round(sum(float(s.get("custo_final") or 0) for s in finalizadas), 2),
        "estornado": round(sum(float(s.get("valor_estornado") or 0) for s in finalizadas), 2),
        "recusas_saldo": sum(1 for s in sessoes if s["status"] == "recusada"),
    }


def _premissas(cond: dict) -> dict:
    """Custos que o condomínio paga por kWh, por fonte. Todos configuráveis."""
    return {
        "custo_energia_kwh": float(cond.get("custo_energia_kwh") or CUSTO_ENERGIA_PADRAO),
        "custo_energia_ponta_kwh": float(cond.get("custo_energia_ponta_kwh") or CUSTO_ENERGIA_PONTA_PADRAO),
        "custo_solar_kwh": float(cond["custo_solar_kwh"]) if cond.get("custo_solar_kwh") is not None else None,
        "preco_solar_kwh": float(cond["preco_solar_kwh"]) if cond.get("preco_solar_kwh") is not None else None,
    }


def _hora_local(linha: dict) -> datetime:
    return datetime.fromisoformat(str(linha["hora"]).replace("Z", "+00:00")).astimezone(FUSO)


def _pico_rede(linha: dict) -> float:
    """Linha antiga (antes do 16) não tem pico da rede: tudo veio da rede."""
    pico = float(linha.get("pico_kw") or 0)
    rede = float(linha.get("pico_rede_kw") or 0)
    return rede if (rede > 0 or float(linha.get("energia_solar_kwh") or 0) > 0) else pico


def _geracao(cond_id: str, desde: str) -> dict:
    """Soma da geração solar no período, por origem (a soma é feita no banco)."""
    try:
        linhas = supabase.rpc("somar_geracao_solar", {"p_cond": cond_id, "p_desde": desde}).execute().data or []
    except Exception:
        return {"gerado_kwh": 0.0, "pico_kw": 0.0, "origens": []}
    return {"gerado_kwh": round(sum(float(l.get("energia_kwh") or 0) for l in linhas), 4),
            "pico_kw": round(max((float(l.get("pico_kw") or 0) for l in linhas), default=0.0), 3),
            "origens": sorted({f"solar_{l['origem']}" for l in linhas if l.get("origem")})}


def _energia_por_fonte(cond: dict, sessoes: list[dict], horas: list[dict], desde: str) -> dict:
    """
    A conta do condomínio por fonte, sem misturar: rede fora da ponta, rede na
    ponta e solar, cada linha com energia, receita, custo e margem. Receita sai
    do recibo de cada recarga (preço congelado); custo, das premissas.
    """
    p = _premissas(cond)
    linhas: dict[tuple, dict] = {}
    ajuste_reserva = economia_morador = 0.0

    for s in sessoes:
        if s["status"] != "finalizada":
            continue
        d = detalhar_custo(s)
        for it in d["itens"]:
            chave = (it["origem"], it["faixa"])
            l = linhas.setdefault(chave, {"origem": it["origem"], "faixa": it["faixa"],
                                          "energia_kwh": 0.0, "receita": 0.0})
            l["energia_kwh"] += it["energia_kwh"]
            l["receita"] += it["subtotal"]
        # Recarga que bateu no teto da reserva cobrou menos que a soma das linhas.
        ajuste_reserva += float(s.get("custo_final") or 0) - d["total"]
        economia_morador += economia_vs_so_rede(s)

    custo_por = {"fora_ponta": p["custo_energia_kwh"], "ponta": p["custo_energia_ponta_kwh"]}
    saida = []
    for (origem, faixa), l in sorted(linhas.items(), key=lambda kv: (kv[0][0] != "rede", kv[0][1] or "")):
        custo_kwh = custo_por[faixa] if origem == "rede" else (p["custo_solar_kwh"] or 0.0)
        energia = round(l["energia_kwh"], 4)
        receita = round(l["receita"], 2)
        custo = round(energia * custo_kwh, 2)
        saida.append({
            "origem": origem, "faixa": faixa, "energia_kwh": energia,
            "receita": receita, "preco_medio_kwh": round(receita / energia, 4) if energia > 0 else None,
            "custo_kwh": custo_kwh, "custo": custo, "margem": round(receita - custo, 2),
            "custo_origem": "premissa",
        })

    energia_solar = sum(l["energia_kwh"] for l in saida if l["origem"].startswith("solar_"))
    receita = round(sum(l["receita"] for l in saida) + ajuste_reserva, 2)
    custo = round(sum(l["custo"] for l in saida), 2)
    gerado = _geracao(cond["id"], desde)
    absorvido = round(sum(float(h.get("energia_solar_kwh") or 0) for h in horas), 4)

    sem = max((max(float(h.get("pico_kw") or 0), float(h.get("demanda_kw") or 0)) for h in horas), default=0.0)
    com = max((float(h.get("pico_kw") or 0) for h in horas), default=0.0)
    rede = max((_pico_rede(h) for h in horas), default=0.0)
    return {
        "linhas": saida,
        "ajuste_teto_reserva": round(ajuste_reserva, 2),
        "total": {"energia_kwh": round(sum(l["energia_kwh"] for l in saida), 4), "receita": receita,
                  "custo": custo, "margem": round(receita - custo, 2)},
        "economia_vs_so_rede": {
            "morador": round(economia_morador, 2),
            # kWh solar que o condomínio deixou de comprar da distribuidora.
            "condominio": round(max(0.0, energia_solar * (p["custo_energia_kwh"] - (p["custo_solar_kwh"] or 0))), 2),
            "origem": "estimado",
        },
        "solar": {"gerado_kwh": gerado["gerado_kwh"], "absorvido_kwh": absorvido,
                  "nao_aproveitado_kwh": round(max(0.0, gerado["gerado_kwh"] - absorvido), 4),
                  "pico_geracao_kw": gerado["pico_kw"], "origens": gerado["origens"],
                  "observacao": "Excedente não absorvido iria para a rede; créditos fora de escopo."},
        "pico": {"sem_gestao_kw": round(sem, 3), "com_gestao_kw": round(com, 3), "da_rede_kw": round(rede, 3),
                 "evitado_pela_gestao_kw": round(max(0.0, sem - com), 3),
                 "coberto_pelo_sol_kw": round(max(0.0, com - rede), 3)},
    }


def _incentivo(cond: dict, chargers: list[dict]) -> dict:
    """
    Margem do kWh solar x margem do kWh da rede fora da ponta. Se a da rede for
    maior, o condomínio ganha MENOS quando o sol brilha - o painel avisa.
    """
    p = _premissas(cond)
    tarifas = [float(c.get("tarifa_kwh") or 0) for c in chargers if c.get("perfil") != "bancada"]
    margem_rede = round(max(tarifas, default=0.0) - p["custo_energia_kwh"], 4)
    if p["preco_solar_kwh"] is None or p["custo_solar_kwh"] is None:
        return {"alinhado": None, "margem_rede_fora_kwh": margem_rede, "margem_solar_kwh": None}
    margem_solar = round(p["preco_solar_kwh"] - p["custo_solar_kwh"], 4)
    return {"alinhado": margem_solar >= margem_rede, "margem_rede_fora_kwh": margem_rede,
            "margem_solar_kwh": margem_solar,
            "alerta": None if margem_solar >= margem_rede else
            "A margem da rede é maior que a do sol: o condomínio ganha menos quando há sol."}


def _faixa_10029(c: dict) -> tuple[float, float] | None:
    nominal = c.get("potencia_nominal_kw")
    return FAIXA_10029.get(int(float(nominal))) if nominal is not None else None


def _modbus(c: dict, cond: dict) -> dict:
    """Os cinco registradores do carregador, com rótulo e o efeito no alocador."""
    modo = int(c.get("modo_carga") or 0)
    faixa = _faixa_10029(c)
    dinamico = c.get("controle_dinamico") is not False
    return {
        "carregador_id": c["id"], "numero": c["numero"], "modelo": c.get("modelo"),
        "potencia_nominal_kw": c.get("potencia_nominal_kw"),
        "registradores": [
            {"registrador": 10024, "campo": "garantir_minimo", "valor": bool(c.get("garantir_minimo")),
             "rotulo": "Garantir potência mínima (nos modos FV)"},
            {"registrador": 10025, "campo": "controle_dinamico", "valor": dinamico,
             "rotulo": "Controle dinâmico de carga"},
            {"registrador": 10026, "campo": "limite_disjuntor_a", "valor": c.get("limite_disjuntor_a"),
             "rotulo": "Corrente do disjuntor (A)", "equivale_kw": potencia_disjuntor_kw(c)},
            {"registrador": 10029, "campo": "potencia_maxima_kw", "valor": c.get("potencia_maxima_kw"),
             "rotulo": "Potência máxima de carga (kW)", "faixa": list(faixa) if faixa else None},
            {"registrador": 10032, "campo": "modo_carga", "valor": modo,
             "rotulo": f"Modo de carga: {ROTULO_MODO.get(modo, modo)}"},
        ],
        "efeito": {
            "modulado_pelo_alocador": dinamico,
            "modo_efetivo": ROTULO_MODO[demanda.modo_efetivo(c, cond)],
            "minimo_kw": minimo_kw(c),
            "observacao": None if demanda.modo_efetivo(c, cond) == modo or modo == 0 else
            ("Sem FV no condomínio: tratado como rápido." if not demanda.fv_ativo(cond)
             else "Sem bateria modelada: FV + bateria tratado como FV."),
        },
        "aviso": AVISO_MODBUS,
    }


@router.get("/painel")
def painel(gestor: dict = Depends(gestor_logado)):
    cond_id = gestor.get("condominio_id")
    cond = um(supabase.table("condominios").select("*").eq("id", cond_id).execute())
    if not cond:
        raise HTTPException(status_code=404, detail="Condomínio do gestor não encontrado.")

    agora_estado = demanda.alocar(cond_id, gravar=False)
    por_sessao = {x["carregador_id"]: x for x in agora_estado.get("sessoes", []) if x.get("carregador_id")}
    chargers = supabase.table("carregadores").select("*").eq("condominio_id", cond_id) \
        .order("numero").execute().data or []
    ids = [c["id"] for c in chargers]

    ativas = {}
    ao_vivo = []
    sessoes_mes, sessoes_hoje = [], []
    if ids:
        numero_por_id = {c["id"]: c["numero"] for c in chargers}
        for s in supabase.table("sessoes_recarga").select(
            "*, usuarios(nome, bloco_apto), veiculos(modelo, tipo)"
        ).eq("status", "carregando").in_("carregador_id", ids).execute().data or []:
            ativas[s["carregador_id"]] = s
            # A conta ao vivo é a MESMA do recibo (detalhar_custo): o painel do
            # gestor nunca recalcula por conta própria. Mid-recarga, o total é
            # o consumido até agora.
            try:
                custo_parcial = round(detalhar_custo(s)["total"], 2)
            except Exception:
                custo_parcial = round(float(s.get("custo_estimado") or 0), 2)
            u = s.get("usuarios") or {}
            v = s.get("veiculos") or {}
            ao_vivo.append({
                "sessao_id": s["id"], "carregador_id": s["carregador_id"],
                "numero": numero_por_id.get(s["carregador_id"]),
                "morador": u.get("nome"), "bloco_apto": u.get("bloco_apto"),
                "veiculo": v.get("modelo"), "veiculo_tipo": v.get("tipo"),
                "percentual": round(float(s.get("percentual_bateria_atual") or 0), 1),
                "alvo": round(float(s.get("alvo_percentual") or 100), 0),
                "energia_kwh": round(float(s.get("energia_entregue_kwh") or 0), 4),
                "potencia_kw": round(float(s.get("potencia_atual_kw") or 0), 3),
                "potencia_alocada_kw": s.get("potencia_alocada_kw"),
                "tempo_min": s.get("tempo_estimado_min"),
                "custo_parcial": custo_parcial,
                "iniciado_em": s.get("iniciado_em"),
            })
        ao_vivo.sort(key=lambda x: x["numero"] or 0)

        sessoes_mes = supabase.table("sessoes_recarga").select(
            "*, usuarios(nome, bloco_apto)"
        ).in_("carregador_id", ids).gte("criado_em", _inicio_local(mes=True)).execute().data or []
        inicio_hoje = datetime.fromisoformat(_inicio_local())
        sessoes_hoje = [s for s in sessoes_mes
                        if (para_datetime(s["criado_em"]) or inicio_hoje) >= inicio_hoje]

    # Curva de carga: 24 barras do dia local, vindas de consumo_horario.
    # `pico_kw` é o que a garagem puxou (COM gestão); `demanda_kw` é o que teria
    # puxado se ninguém fosse limitado (SEM gestão); `pico_rede_kw`, o que veio
    # da distribuidora (a diferença para `pico_kw` foi coberta pelo sol).
    horas_mes = supabase.table("consumo_horario").select("*").eq("condominio_id", cond_id) \
        .gte("hora", _inicio_local(mes=True)).order("hora").execute().data or []
    inicio_dia = datetime.fromisoformat(_inicio_local())
    horas_hoje = [h for h in horas_mes if _hora_local(h) >= inicio_dia]
    por_hora = [{"hora": h, "energia_kwh": 0.0, "energia_ponta_kwh": 0.0, "energia_solar_kwh": 0.0,
                 "pico_kw": 0.0, "pico_rede_kw": 0.0, "demanda_kw": 0.0} for h in range(24)]
    for linha in horas_hoje:
        pico = float(linha.get("pico_kw") or 0)
        por_hora[_hora_local(linha).hour].update({
            "energia_kwh": round(float(linha.get("energia_kwh") or 0), 4),
            "energia_ponta_kwh": round(float(linha.get("energia_ponta_kwh") or 0), 4),
            "energia_solar_kwh": round(float(linha.get("energia_solar_kwh") or 0), 4),
            "pico_kw": round(pico, 3),
            "pico_rede_kw": round(_pico_rede(linha), 3),
            "demanda_kw": round(max(pico, float(linha.get("demanda_kw") or pico)), 3),
        })

    moradores = {}
    for s in sessoes_mes:
        if s["status"] != "finalizada":
            continue
        u = s.get("usuarios") or {}
        m = moradores.setdefault(s["usuario_id"], {"nome": u.get("nome", "—"), "bloco_apto": u.get("bloco_apto"),
                                                   "recargas": 0, "energia_kwh": 0.0,
                                                   "energia_solar_kwh": 0.0, "valor": 0.0})
        m["recargas"] += 1
        m["energia_kwh"] = round(m["energia_kwh"] + float(s.get("energia_entregue_kwh") or 0), 4)
        m["energia_solar_kwh"] = round(m["energia_solar_kwh"] + float(s.get("energia_solar_kwh") or 0), 4)
        m["valor"] = round(m["valor"] + float(s.get("custo_final") or 0), 2)

    resumo_mes = _resumo(sessoes_mes)
    energia_mes = _energia_por_fonte(cond, sessoes_mes, horas_mes, _inicio_local(mes=True))
    energia_hoje = _energia_por_fonte(cond, sessoes_hoje, horas_hoje, _inicio_local())
    return {
        "condominio": {k: cond.get(k) for k in ("id", "nome", "endereco", "limite_potencia_kw", "ponta_inicio",
                                                "ponta_fim", "ponta_fator_limite", "ponta_multiplicador_tarifa",
                                                "custo_energia_kwh", "custo_energia_ponta_kwh",
                                                "fv_potencia_kwp", "custo_solar_kwh", "preco_solar_kwh")},
        "agora": agora_estado,
        "recargas_ao_vivo": ao_vivo,
        "carregadores": [{
            "id": c["id"], "numero": c["numero"], "status": c["status"], "origem": c.get("origem"),
            "perfil": c.get("perfil"), "modelo": c.get("modelo"), "potencia_maxima_kw": c["potencia_maxima_kw"],
            "potencia_nominal_kw": c.get("potencia_nominal_kw"),
            "tarifa_kwh": c.get("tarifa_kwh"), "temperatura_c": c.get("temperatura_c"),
            "potencia_atual_kw": (ativas.get(c["id"]) or {}).get("potencia_atual_kw"),
            "potencia_alocada_kw": (ativas.get(c["id"]) or {}).get("potencia_alocada_kw"),
            "alocado_solar_kw": (por_sessao.get(c["id"]) or {}).get("alocado_solar_kw"),
            "alocado_rede_kw": (por_sessao.get(c["id"]) or {}).get("alocado_rede_kw"),
            "pausado_motivo": (por_sessao.get(c["id"]) or {}).get("pausado_motivo"),
            "modbus": None if c.get("perfil") == "bancada" else {
                "garantir_minimo": bool(c.get("garantir_minimo")),
                "controle_dinamico": c.get("controle_dinamico") is not False,
                "limite_disjuntor_a": c.get("limite_disjuntor_a"),
                "potencia_maxima_kw": c.get("potencia_maxima_kw"),
                "modo_carga": int(c.get("modo_carga") or 0)},
        } for c in chargers],
        "hoje": _resumo(sessoes_hoje),
        "mes": resumo_mes,
        "por_hora": por_hora,
        "demanda": _indicadores_demanda(cond, horas_mes, inicio_dia),
        "energia": {"hoje": energia_hoje, "mes": energia_mes,
                    "incentivo_solar": _incentivo(cond, chargers),
                    "fv_ativo": demanda.fv_ativo(cond)},
        "valor": _valor_para_o_condominio(cond, resumo_mes, energia_mes),
        "por_morador": sorted(moradores.values(), key=lambda m: -m["energia_kwh"])[:20],
    }


def _pico(linhas: list[dict]) -> tuple[float, float, int]:
    com = max((float(l.get("pico_kw") or 0) for l in linhas), default=0.0)
    sem = max((max(float(l.get("pico_kw") or 0), float(l.get("demanda_kw") or 0)) for l in linhas), default=0.0)
    horas_limitadas = sum(1 for l in linhas if float(l.get("demanda_kw") or 0) > float(l.get("pico_kw") or 0) + 0.01)
    return round(com, 3), round(sem, 3), horas_limitadas


def _recusas(cond_id: str, desde: str) -> int | None:
    try:
        r = supabase.table("eventos_demanda").select("id").eq("condominio_id", cond_id) \
            .eq("tipo", "recusa_limite").gte("criado_em", desde).execute()
        return len(r.data or [])
    except Exception:
        return None          # migration 14 não rodou


def _indicadores_demanda(cond: dict, horas_mes: list[dict], inicio_dia: datetime) -> dict:
    """
    A prova da gestão de demanda em quatro números: o limite do quadro, o pico
    que o prédio TERIA puxado sem gestão, o pico que puxou de fato, e quantas
    recargas foram seguradas para não estourar.
    """
    hoje = [l for l in horas_mes if _hora_local(l) >= inicio_dia]
    com_hoje, sem_hoje, lim_hoje = _pico(hoje)
    com_mes, sem_mes, lim_mes = _pico(horas_mes)
    limite = float(cond.get("limite_potencia_kw") or 0)
    return {
        "limite_kw": limite,
        "limite_ponta_kw": round(limite * float(cond.get("ponta_fator_limite") or 1), 3),
        "hoje": {"pico_com_gestao_kw": com_hoje, "pico_sem_gestao_kw": sem_hoje,
                 "pico_evitado_kw": round(max(0.0, sem_hoje - com_hoje), 3),
                 "horas_com_limitacao": lim_hoje, "recusas_por_limite": _recusas(cond["id"], _inicio_local())},
        "mes": {"pico_com_gestao_kw": com_mes, "pico_sem_gestao_kw": sem_mes,
                "pico_evitado_kw": round(max(0.0, sem_mes - com_mes), 3),
                "horas_com_limitacao": lim_mes, "recusas_por_limite": _recusas(cond["id"], _inicio_local(mes=True)),
                "estouraria_limite": sem_mes > limite + 1e-9},
    }


def _valor_para_o_condominio(cond: dict, mes: dict, energia_mes: dict) -> dict:
    """
    Receita x custo da energia no mês, por fonte (o detalhe está em
    painel.energia). As tarifas são PREMISSAS configuráveis - o painel mostra
    os valores usados para ninguém confundir estimativa com fatura.
    """
    p = _premissas(cond)
    energia = float(mes.get("energia_faturada_kwh") or 0)
    solar = min(energia, float(mes.get("energia_faturada_solar_kwh") or 0))
    ponta = min(energia - solar, float(mes.get("energia_faturada_ponta_kwh") or 0))
    receita = float(mes.get("faturamento") or 0)
    custo = energia_mes["total"]["custo"]
    margem = round(receita - custo, 2)
    return {
        "receita_mes": round(receita, 2),
        "custo_energia_mes": custo,
        "margem_mes": margem,
        "margem_percentual": round(margem / receita * 100, 1) if receita > 0 else None,
        "energia_mes_kwh": round(energia, 4),
        "energia_ponta_mes_kwh": round(ponta, 4),
        "energia_solar_mes_kwh": round(solar, 4),
        "participacao_ponta_percentual": round(ponta / energia * 100, 1) if energia > 0 else None,
        "participacao_solar_percentual": round(solar / energia * 100, 1) if energia > 0 else None,
        # Se a energia da ponta viesse de armazenamento carregado fora dela
        # (bateria + inversor híbrido), o condomínio pagaria a tarifa normal.
        "economia_potencial_armazenamento_mes": round(
            ponta * max(0.0, p["custo_energia_ponta_kwh"] - p["custo_energia_kwh"]), 2),
        "premissas": {**p, "configuravel_em": "PATCH /gestor/condominio",
                      "observacao": "Tarifas e custos são premissas do síndico (simuladas), não leitura da fatura."},
    }


@router.post("/simular-demanda")
def simular_demanda(payload: CenarioDemanda, gestor: dict = Depends(gestor_logado)):
    """
    "E se N carros ligarem juntos?" com o MESMO algoritmo da operação.
    Não grava nada. Serve para o síndico dimensionar e para a banca ver o
    alocador funcionando sem precisar de N carros de verdade.
    """
    cond = um(supabase.table("condominios").select("*").eq("id", gestor["condominio_id"]).execute()) or {}
    limite = payload.limite_kw or float(cond.get("limite_potencia_kw") or 0)
    if payload.em_ponta:
        limite = limite * float(cond.get("ponta_fator_limite") or 1)
    kwp = payload.fv_potencia_kwp if payload.fv_potencia_kwp is not None else 0.0
    solar = 0.0 if payload.em_ponta else kwp * SOLAR_FATOR_PICO
    r = demanda.simular_cenario(limite, payload.carros, payload.potencia_carro_kw, solar_kw=solar)
    r["em_ponta"] = payload.em_ponta
    r["fv_potencia_kwp"] = kwp
    r["solar_origem"] = "simulado" if solar > 0 else None
    return r


@router.patch("/condominio")
def configurar(payload: ConfigDemanda, gestor: dict = Depends(gestor_logado)):
    dados = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not dados:
        raise HTTPException(status_code=400, detail="Nada para alterar.")
    tarifa = dados.pop("tarifa_rede_kwh", None)
    if dados:
        supabase.table("condominios").update(dados).eq("id", gestor["condominio_id"]).execute()
    if tarifa is not None:
        # Vale para recargas NOVAS: a tarifa é congelada em cada sessão ao começar.
        supabase.table("carregadores").update({"tarifa_kwh": tarifa}) \
            .eq("condominio_id", gestor["condominio_id"]).execute()
    # Mudou limite, FV ou preço: a divisão vale na hora, não no próximo ciclo.
    return {"success": True, "agora": demanda.alocar(gestor["condominio_id"])}


# ---------------------------------------------------------------------------
# Parâmetros Modbus por carregador (ADR-016 D10)
# ---------------------------------------------------------------------------

def _carregador_do_gestor(carregador_id: str, gestor: dict) -> dict:
    c = um(supabase.table("carregadores").select("*").eq("id", carregador_id)
           .eq("condominio_id", gestor["condominio_id"]).execute())
    if not c:
        raise HTTPException(status_code=404, detail="Carregador não encontrado neste condomínio.")
    if c.get("perfil") == "bancada":
        raise HTTPException(status_code=409, detail="A bancada USB não tem parâmetros do HCA G2.")
    return c


def _cond_do_gestor(gestor: dict) -> dict:
    return um(supabase.table("condominios").select("*").eq("id", gestor["condominio_id"]).execute()) or {}


@router.get("/carregadores")
def listar_modbus(gestor: dict = Depends(gestor_logado)):
    cond = _cond_do_gestor(gestor)
    chargers = supabase.table("carregadores").select("*").eq("condominio_id", gestor["condominio_id"]) \
        .order("numero").execute().data or []
    return [_modbus(c, cond) for c in chargers if c.get("perfil") != "bancada"]


@router.get("/carregadores/{carregador_id}/modbus")
def ler_modbus(carregador_id: str, gestor: dict = Depends(gestor_logado)):
    return _modbus(_carregador_do_gestor(carregador_id, gestor), _cond_do_gestor(gestor))


@router.patch("/carregadores/{carregador_id}/modbus")
def ajustar_modbus(carregador_id: str, payload: ConfigModbus, gestor: dict = Depends(gestor_logado)):
    """
    Grava os parâmetros validando as faixas do mapa Modbus. Campo ausente não
    muda; `limite_disjuntor_a: null` limpa o 10026.
    """
    c = _carregador_do_gestor(carregador_id, gestor)
    cond = _cond_do_gestor(gestor)
    dados = payload.model_dump(exclude_unset=True)
    for campo in ("garantir_minimo", "controle_dinamico", "potencia_maxima_kw", "modo_carga"):
        if campo in dados and dados[campo] is None:
            raise HTTPException(status_code=422, detail=f"{campo} não aceita vazio.")
    if not dados:
        raise HTTPException(status_code=400, detail="Nada para alterar.")

    if "potencia_maxima_kw" in dados:
        faixa = _faixa_10029(c)
        if faixa is None:
            raise HTTPException(status_code=409, detail="Carregador sem potência nominal cadastrada (7, 11 ou 22 kW).")
        minimo, maximo = faixa
        if not minimo <= dados["potencia_maxima_kw"] <= maximo:
            raise HTTPException(status_code=422, detail=(
                f"10029: no modelo de {int(maximo)} kW a potência máxima vai de "
                f"{str(minimo).replace('.', ',')} a {int(maximo)} kW."))
    if dados.get("modo_carga") == 2:
        raise HTTPException(status_code=422, detail=(
            "10032: o modo FV + bateria fica indisponível enquanto não houver bateria modelada."))
    if dados.get("modo_carga") == 1 and not demanda.fv_ativo(cond):
        raise HTTPException(status_code=422, detail=(
            "10032: o modo FV precisa de geração FV no condomínio (fv_potencia_kwp > 0)."))

    supabase.table("carregadores").update(dados).eq("id", c["id"]).execute()
    novo = {**c, **dados}
    return {"success": True, "carregador": _modbus(novo, cond), "agora": demanda.alocar(gestor["condominio_id"])}


# ---------------------------------------------------------------------------
# Cartões compartilhados do condomínio
# ---------------------------------------------------------------------------

@router.get("/cartoes")
def listar_cartoes(gestor: dict = Depends(gestor_logado)):
    return cartoes.do_condominio(gestor["condominio_id"])


@router.post("/cartoes")
def cadastrar_cartao(payload: CartaoCondominio, gestor: dict = Depends(gestor_logado)):
    """
    Cartão compartilhado: prova PRESENÇA no ponto, não identidade. Autoriza a
    recarga preparada ali, e a cobrança sai de quem a preparou no app. É o que
    permite um único cartão físico atender todos os moradores.
    """
    return {"success": True,
            "cartao": cartoes.registrar_compartilhado(gestor["condominio_id"], payload.uid,
                                                      payload.apelido)}


@router.delete("/cartoes/{uid}")
def remover_cartao(uid: str, gestor: dict = Depends(gestor_logado)):
    if not cartoes.remover(uid, condominio_id=gestor["condominio_id"]):
        raise HTTPException(status_code=404, detail="Cartão não encontrado neste condomínio.")
    return {"success": True}
