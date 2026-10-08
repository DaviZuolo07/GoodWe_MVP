"""
rotas_suporte.py - Chamados do morador (Suporte do app).
========================================================

O morador abre um chamado com assunto e mensagem; o painel do gestor
(rotas_geral.py) responde, e a resposta chega no sino e nesta lista.

A tabela `chamados` (db/20) é fechada ao navegador: tudo passa por aqui, com
a identidade do token. O morador só vê os próprios chamados.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import supabase
from identidade import usuario_logado

router = APIRouter(prefix="/me/chamados", tags=["suporte"])

# Chamados em aberto por pessoa. Segura spam sem atrapalhar quem tem dúvida
# de verdade: depois de respondido, o chamado deixa de contar.
MAX_ABERTOS = 5
SEM_TABELA = "Os chamados ainda não estão disponíveis. Use o chat enquanto isso."


class NovoChamado(BaseModel):
    assunto: str = Field(..., min_length=3, max_length=120)
    mensagem: str = Field(..., min_length=5, max_length=2000)


@router.get("")
def meus_chamados(usuario: dict = Depends(usuario_logado)):
    try:
        return supabase.table("chamados").select(
            "id, assunto, mensagem, status, resposta, respondido_em, criado_em, atualizado_em"
        ).eq("usuario_id", usuario["id"]).order("criado_em", desc=True).limit(50).execute().data or []
    except Exception:                                        # noqa: BLE001
        raise HTTPException(status_code=503, detail=SEM_TABELA)


@router.post("")
def abrir_chamado(payload: NovoChamado, usuario: dict = Depends(usuario_logado)):
    try:
        abertos = supabase.table("chamados").select("id").eq("usuario_id", usuario["id"]) \
            .neq("status", "resolvido").execute().data or []
    except Exception:                                        # noqa: BLE001
        raise HTTPException(status_code=503, detail=SEM_TABELA)
    if len(abertos) >= MAX_ABERTOS:
        raise HTTPException(status_code=429, detail=(
            f"Você já tem {MAX_ABERTOS} chamados em aberto. Aguarde a resposta de algum deles."))
    novo = supabase.table("chamados").insert({
        "usuario_id": usuario["id"], "condominio_id": usuario.get("condominio_id"),
        "assunto": payload.assunto.strip(), "mensagem": payload.mensagem.strip(), "status": "aberto",
    }).execute().data
    return {"success": True, "chamado": novo[0] if novo else None}
