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

import demanda
from config import FUSO, para_datetime, supabase, um
from identidade import gestor_logado

router = APIRouter(prefix="/gestor", tags=["gestor"])


class ConfigDemanda(BaseModel):
    limite_potencia_kw: Optional[float] = Field(None, gt=0, le=2000)
    ponta_inicio: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    ponta_fim: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    ponta_fator_limite: Optional[float] = Field(None, gt=0, le=1)
    ponta_multiplicador_tarifa: Optional[float] = Field(None, ge=1, le=5)


def _inicio_local(dias_atras: int = 0, mes: bool = False) -> str:
    agora_local = datetime.now(FUSO)
    base = agora_local.replace(day=1) if mes else agora_local - timedelta(days=dias_atras)
    return datetime.combine(base.date(), time(0, 0), tzinfo=FUSO).isoformat()


def _resumo(sessoes: list[dict]) -> dict:
    finalizadas = [s for s in sessoes if s["status"] == "finalizada"]
    return {
        "recargas": len(finalizadas),
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
    horas = supabase.table("consumo_horario").select("*").eq("condominio_id", cond_id) \
        .gte("hora", _inicio_local()).order("hora").execute().data or []
    por_hora = [{"hora": h, "energia_kwh": 0.0, "energia_ponta_kwh": 0.0, "pico_kw": 0.0} for h in range(24)]
    for linha in horas:
        h = datetime.fromisoformat(linha["hora"].replace("Z", "+00:00")).astimezone(FUSO).hour
        por_hora[h].update({
            "energia_kwh": round(float(linha["energia_kwh"]), 4),
            "energia_ponta_kwh": round(float(linha["energia_ponta_kwh"]), 4),
            "pico_kw": round(float(linha["pico_kw"]), 3),
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

    return {
        "condominio": {k: cond.get(k) for k in ("id", "nome", "endereco", "limite_potencia_kw", "ponta_inicio",
                                                "ponta_fim", "ponta_fator_limite", "ponta_multiplicador_tarifa")},
        "agora": agora_estado,
        "carregadores": [{
            "id": c["id"], "numero": c["numero"], "status": c["status"], "origem": c.get("origem"),
            "perfil": c.get("perfil"), "potencia_maxima_kw": c["potencia_maxima_kw"],
            "tarifa_kwh": c.get("tarifa_kwh"), "temperatura_c": c.get("temperatura_c"),
            "potencia_atual_kw": (ativas.get(c["id"]) or {}).get("potencia_atual_kw"),
            "potencia_alocada_kw": (ativas.get(c["id"]) or {}).get("potencia_alocada_kw"),
        } for c in chargers],
        "hoje": _resumo(sessoes_hoje),
        "mes": _resumo(sessoes_mes),
        "por_hora": por_hora,
        "por_morador": sorted(moradores.values(), key=lambda m: -m["energia_kwh"])[:20],
    }


@router.patch("/condominio")
def configurar(payload: ConfigDemanda, gestor: dict = Depends(gestor_logado)):
    dados = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not dados:
        raise HTTPException(status_code=400, detail="Nada para alterar.")
    supabase.table("condominios").update(dados).eq("id", gestor["condominio_id"]).execute()
    # Mudou o limite: a divisão vale na hora, não no próximo ciclo.
    return {"success": True, "agora": demanda.alocar(gestor["condominio_id"])}
