"""
identidade.py - Quem está chamando, resolvido a partir do token (Bloco 2).
=========================================================================

Regra do projeto: o que vem do cliente é PEDIDO, não permissão.

Antes, o corpo da requisição dizia `usuario_id: "..."` e o backend
acreditava. Bastava trocar o id para recarregar o saldo de outra pessoa,
vincular o próprio cartão na conta de outra pessoa (e carregar com o saldo
dela), encerrar a recarga do vizinho ou cancelar a espera dele.

Agora nenhum modelo Pydantic tem `usuario_id`. A identidade sai do JWT
assinado pelo backend (seguranca.usuario_atual), e todo recurso tocado -
veículo, sessão, fila - é conferido contra ela.
"""

from fastapi import Depends, HTTPException

from config import supabase, um
from seguranca import usuario_atual

CAMPOS_PUBLICOS = ("id, nome, papel, tipo_usuario, condominio_id, bloco_apto, "
                   "saldo, criado_em")


def usuario_logado(usuario_id: str = Depends(usuario_atual)) -> dict:
    """A linha do usuário do token. Token de conta apagada vira 401."""
    u = um(supabase.table("usuarios").select(CAMPOS_PUBLICOS).eq("id", usuario_id).execute())
    if not u:
        raise HTTPException(status_code=401, detail="Sessão inválida. Entre novamente.",
                            headers={"WWW-Authenticate": "Bearer"})
    u["saldo"] = round(float(u.get("saldo") or 0), 2)
    return u


def gestor_logado(usuario: dict = Depends(usuario_logado)) -> dict:
    if usuario.get("tipo_usuario") != "gestor":
        raise HTTPException(status_code=403, detail="Área restrita ao gestor do condomínio.")
    return usuario


def veiculo_do_usuario(veiculo_id: str, usuario_id: str) -> dict:
    """
    404 e não 403 quando o veículo é de outra pessoa: responder "proibido"
    confirmaria que aquele id existe.
    """
    v = um(supabase.table("veiculos").select("*").eq("id", veiculo_id)
           .eq("usuario_id", usuario_id).execute())
    if not v:
        raise HTTPException(status_code=404, detail="Veículo não encontrado.")
    return v


def sessao_do_usuario(sessao_id: str, usuario_id: str) -> dict:
    s = um(supabase.table("sessoes_recarga").select("*").eq("id", sessao_id)
           .eq("usuario_id", usuario_id).execute())
    if not s:
        raise HTTPException(status_code=404, detail="Recarga não encontrada.")
    return s
