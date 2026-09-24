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

O gestor só vê e só configura o condomínio dele (`usuarios.condominio_id`).
"""

from datetime import datetime, timedelta, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import cartoes
import demanda
from config import FUSO, para_datetime, supabase, um
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


class CenarioDemanda(BaseModel):
    carros: int = Field(6, ge=1, le=200)
    potencia_carro_kw: float = Field(7.4, gt=0, le=350)
    limite_kw: Optional[float] = Field(None, gt=0, le=2000)
    em_ponta: bool = False


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
        "energia_kwh": round(sum(float(s.get("energia_entregue_kwh") or 0) for s in sessoes), 4),
        "energia_ponta_kwh": round(sum(float(s.get("energia_ponta_kwh") or 0) for s in sessoes), 4),
        "faturamento": round(sum(float(s.get("custo_final") or 0) for s in finalizadas), 2),
        "estornado": round(sum(float(s.get("valor_estornado") or 0) for s in finalizadas), 2),
        "recusas_saldo": sum(1 for s in sessoes if s["status"] == "recusada"),
    }


@router.get("/painel")
def painel(gestor: dict = Depends(gestor_logado)):
    cond_id = gestor.get("condominio_id")
    cond = um(supabase.table("condominios").select("*").eq("id", cond_id).execute())
    if not cond:
        raise HTTPException(status_code=404, detail="Condomínio do gestor não encontrado.")

    agora_estado = demanda.alocar(cond_id, gravar=False)
    chargers = supabase.table("carregadores").select("*").eq("condominio_id", cond_id) \
        .order("numero").execute().data or []
    ids = [c["id"] for c in chargers]

    ativas = {}
    sessoes_mes, sessoes_hoje = [], []
    if ids:
        for s in supabase.table("sessoes_recarga").select(
            "carregador_id, potencia_atual_kw, potencia_alocada_kw, percentual_bateria_atual"
        ).eq("status", "carregando").in_("carregador_id", ids).execute().data or []:
            ativas[s["carregador_id"]] = s

        sessoes_mes = supabase.table("sessoes_recarga").select(
            "status, energia_entregue_kwh, energia_ponta_kwh, custo_final, valor_estornado, "
            "usuario_id, criado_em, usuarios(nome, bloco_apto)"
        ).in_("carregador_id", ids).gte("criado_em", _inicio_local(mes=True)).execute().data or []
        inicio_hoje = datetime.fromisoformat(_inicio_local())
        sessoes_hoje = [s for s in sessoes_mes
                        if (para_datetime(s["criado_em"]) or inicio_hoje) >= inicio_hoje]

    # Curva de carga: 24 barras do dia local, vindas de consumo_horario.
    # `pico_kw` é o que o prédio puxou (COM gestão); `demanda_kw` é o que teria
    # puxado se ninguém fosse limitado (SEM gestão). Sem a migration 14 a
    # segunda coluna não existe e vale igual à primeira.
    horas_mes = supabase.table("consumo_horario").select("*").eq("condominio_id", cond_id) \
        .gte("hora", _inicio_local(mes=True)).order("hora").execute().data or []
    inicio_dia = datetime.fromisoformat(_inicio_local())
    por_hora = [{"hora": h, "energia_kwh": 0.0, "energia_ponta_kwh": 0.0, "pico_kw": 0.0,
                 "demanda_kw": 0.0} for h in range(24)]
    for linha in horas_mes:
        instante = datetime.fromisoformat(linha["hora"].replace("Z", "+00:00")).astimezone(FUSO)
        if instante < inicio_dia:
            continue
        pico = float(linha.get("pico_kw") or 0)
        por_hora[instante.hour].update({
            "energia_kwh": round(float(linha["energia_kwh"]), 4),
            "energia_ponta_kwh": round(float(linha["energia_ponta_kwh"]), 4),
            "pico_kw": round(pico, 3),
            "demanda_kw": round(max(pico, float(linha.get("demanda_kw") or pico)), 3),
        })

    moradores = {}
    for s in sessoes_mes:
        if s["status"] != "finalizada":
            continue
        u = s.get("usuarios") or {}
        m = moradores.setdefault(s["usuario_id"], {"nome": u.get("nome", "—"), "bloco_apto": u.get("bloco_apto"),
                                                   "recargas": 0, "energia_kwh": 0.0, "valor": 0.0})
        m["recargas"] += 1
        m["energia_kwh"] = round(m["energia_kwh"] + float(s.get("energia_entregue_kwh") or 0), 4)
        m["valor"] = round(m["valor"] + float(s.get("custo_final") or 0), 2)

    resumo_mes = _resumo(sessoes_mes)
    return {
        "condominio": {k: cond.get(k) for k in ("id", "nome", "endereco", "limite_potencia_kw", "ponta_inicio",
                                                "ponta_fim", "ponta_fator_limite", "ponta_multiplicador_tarifa",
                                                "custo_energia_kwh", "custo_energia_ponta_kwh")},
        "agora": agora_estado,
        "carregadores": [{
            "id": c["id"], "numero": c["numero"], "status": c["status"], "origem": c.get("origem"),
            "perfil": c.get("perfil"), "potencia_maxima_kw": c["potencia_maxima_kw"],
            "tarifa_kwh": c.get("tarifa_kwh"), "temperatura_c": c.get("temperatura_c"),
            "potencia_atual_kw": (ativas.get(c["id"]) or {}).get("potencia_atual_kw"),
            "potencia_alocada_kw": (ativas.get(c["id"]) or {}).get("potencia_alocada_kw"),
        } for c in chargers],
        "hoje": _resumo(sessoes_hoje),
        "mes": resumo_mes,
        "por_hora": por_hora,
        "demanda": _indicadores_demanda(cond, horas_mes, inicio_dia),
        "valor": _valor_para_o_condominio(cond, resumo_mes),
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
    hoje = [l for l in horas_mes
            if datetime.fromisoformat(l["hora"].replace("Z", "+00:00")) >= inicio_dia]
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


def _valor_para_o_condominio(cond: dict, mes: dict) -> dict:
    """
    Receita x custo da energia no mês, e quanto da conta cai na ponta. As
    tarifas da distribuidora são PREMISSAS configuráveis - o painel mostra os
    valores usados para ninguém confundir estimativa com fatura.
    """
    c = float(cond.get("custo_energia_kwh") or CUSTO_ENERGIA_PADRAO)
    cp = float(cond.get("custo_energia_ponta_kwh") or CUSTO_ENERGIA_PONTA_PADRAO)
    energia = float(mes.get("energia_faturada_kwh") or 0)
    ponta = min(energia, float(mes.get("energia_faturada_ponta_kwh") or 0))
    custo = round((energia - ponta) * c + ponta * cp, 2)
    receita = float(mes.get("faturamento") or 0)
    margem = round(receita - custo, 2)
    return {
        "receita_mes": round(receita, 2),
        "custo_energia_mes": custo,
        "margem_mes": margem,
        "margem_percentual": round(margem / receita * 100, 1) if receita > 0 else None,
        "energia_mes_kwh": round(energia, 4),
        "energia_ponta_mes_kwh": round(ponta, 4),
        "participacao_ponta_percentual": round(ponta / energia * 100, 1) if energia > 0 else None,
        # Se a energia da ponta viesse de armazenamento carregado fora dela
        # (bateria + inversor híbrido), o condomínio pagaria a tarifa normal.
        "economia_potencial_armazenamento_mes": round(ponta * max(0.0, cp - c), 2),
        "premissas": {"custo_energia_kwh": c, "custo_energia_ponta_kwh": cp,
                      "configuravel_em": "PATCH /gestor/condominio",
                      "observacao": "Tarifas da distribuidora são premissas do síndico, não leitura da fatura."},
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
    r = demanda.simular_cenario(limite, payload.carros, payload.potencia_carro_kw)
    r["em_ponta"] = payload.em_ponta
    return r


@router.patch("/condominio")
def configurar(payload: ConfigDemanda, gestor: dict = Depends(gestor_logado)):
    dados = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not dados:
        raise HTTPException(status_code=400, detail="Nada para alterar.")
    supabase.table("condominios").update(dados).eq("id", gestor["condominio_id"]).execute()
    # Mudou o limite: a divisão vale na hora, não no próximo ciclo.
    return {"success": True, "agora": demanda.alocar(gestor["condominio_id"])}


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
