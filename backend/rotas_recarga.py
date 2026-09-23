"""
rotas_recarga.py - Prévia, preparar, cancelar, encerrar e fila.
==============================================================

Casca HTTP fina: toda regra mora em recarga.py. Aqui só se resolve QUEM está
pedindo (token) e se valida o formato do que chegou.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

import recarga
from config import supabase
from identidade import usuario_logado

router = APIRouter(tags=["recarga"])


class RecargaRequest(BaseModel):
    charger_id: str
    veiculo_id: str
    percentual_bateria_atual: float = Field(..., ge=0, le=99)
    alvo_percentual: float = Field(100, ge=1, le=100)


@router.post("/recargas/previa")
def previa(payload: RecargaRequest, usuario: dict = Depends(usuario_logado)):
    """A MESMA conta que a cobrança usa, sem gravar nada."""
    return recarga.previa(usuario, payload.charger_id, payload.veiculo_id,
                          payload.percentual_bateria_atual, payload.alvo_percentual)


@router.post("/recargas/preparar")
def preparar(payload: RecargaRequest, usuario: dict = Depends(usuario_logado)):
    return {"success": True, **recarga.preparar(
        usuario, payload.charger_id, payload.veiculo_id,
        payload.percentual_bateria_atual, payload.alvo_percentual)}


@router.post("/recargas/{sessao_id}/cancelar")
def cancelar(sessao_id: str, usuario: dict = Depends(usuario_logado)):
    return recarga.cancelar_espera(usuario, sessao_id)


@router.post("/recargas/{sessao_id}/encerrar")
def encerrar(sessao_id: str, usuario: dict = Depends(usuario_logado)):
    return recarga.encerrar_pelo_usuario(usuario, sessao_id)


@router.get("/recargas/{sessao_id}/leituras")
def leituras(sessao_id: str, usuario: dict = Depends(usuario_logado)):
    """Série medida pelo ESP32 da MINHA recarga (base do gráfico ao vivo)."""
    from identidade import sessao_do_usuario
    sessao_do_usuario(sessao_id, usuario["id"])
    return supabase.table("leituras_hardware").select(
        "potencia_w, energia_wh, tensao_v, corrente_a, temperatura_c, rele_ligado, criado_em"
    ).eq("sessao_id", sessao_id).order("criado_em", desc=True).limit(300).execute().data


@router.post("/fila/{charger_id}/entrar")
def entrar_fila(charger_id: str, usuario: dict = Depends(usuario_logado)):
    return recarga.entrar_fila(usuario, charger_id)


@router.post("/fila/{charger_id}/sair")
def sair_fila(charger_id: str, usuario: dict = Depends(usuario_logado)):
    return recarga.sair_fila(usuario, charger_id)
