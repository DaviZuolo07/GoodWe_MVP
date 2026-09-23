"""
rotas_debug.py - Atalhos para testar o fluxo sem a placa (só com MODO_DEMO=1).
=============================================================================

Antes, POST /debug/simular-rfid aceitava QUALQUER uid e qualquer carregador,
sem login: bastava saber o uid de alguém para iniciar uma recarga em nome
dele. Agora as rotas só existem com MODO_DEMO=1, exigem login e simulam
apenas o cartão DE QUEM ESTÁ LOGADO.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import recarga
from config import agora_iso, supabase
from identidade import usuario_logado

router = APIRouter(prefix="/debug", tags=["debug (MODO_DEMO)"])


class MeuCartaoRequest(BaseModel):
    charger_id: str


@router.post("/meu-cartao")
def aproximar_meu_cartao(payload: MeuCartaoRequest, usuario: dict = Depends(usuario_logado)):
    """Faz o que o ESP32 faria ao ler o SEU cartão neste carregador."""
    if not usuario.get("rfid_uid"):
        raise HTTPException(status_code=400, detail="Vincule um cartão em Configurações primeiro.")
    resposta = recarga.processar_cartao(payload.charger_id, usuario["rfid_uid"])
    resposta.pop("sessao", None)
    return resposta


@router.post("/esp32-online/{charger_id}")
def simular_esp32_online(charger_id: str, _usuario: dict = Depends(usuario_logado)):
    """O que o handshake faria: ponto físico volta a disponível."""
    c = recarga.carregador(charger_id)
    ativa = recarga.sessao_ativa_do_carregador(charger_id)
    supabase.table("carregadores").update({"status": "em_uso" if ativa else "disponivel"}) \
        .eq("id", charger_id).execute()
    supabase.table("dispositivos").update({"online": True, "ultimo_contato": agora_iso()}) \
        .eq("carregador_id", charger_id).execute()
    return {"ok": True, "carregador": c["numero"], "status": "em_uso" if ativa else "disponivel"}
