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
from seguranca import admin_atual, usuario_atual

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


def gestor_identificado(claims: dict = Depends(admin_atual)) -> dict:
    """
    O gestor do token, SEM exigir o segundo fator. Só três rotas usam isto:
    /admin/me, /admin/mfa/iniciar e /admin/mfa/confirmar - o caminho para
    cadastrar o autenticador no primeiro acesso. Todo o resto usa
    `gestor_logado`, que exige o código.

    Conferido no servidor a cada chamada:
      1. o token é o administrativo (audiência própria - o do morador não serve);
      2. a conta ainda existe;
      3. a conta ainda é de gestor AGORA, no banco - quem foi rebaixado perde
         o acesso na chamada seguinte, sem esperar o token vencer.
    """
    u = um(supabase.table("usuarios").select(CAMPOS_PUBLICOS).eq("id", claims["sub"]).execute())
    if not u:
        raise HTTPException(status_code=401, detail="Sessão inválida. Entre novamente.",
                            headers={"WWW-Authenticate": "Bearer"})
    if u.get("tipo_usuario") != "gestor":
        raise HTTPException(status_code=403, detail="Área restrita ao gestor do condomínio.")
    u["saldo"] = round(float(u.get("saldo") or 0), 2)
    amr = claims.get("amr") or []
    u["_mfa"] = "otp" in amr
    u["_metodo"] = "google" if "google" in amr else "pwd"
    return u


def gestor_logado(u: dict = Depends(gestor_identificado)) -> dict:
    """
    Só existe na API ADMINISTRATIVA (main_admin.py). Além das três checagens
    de `gestor_identificado`, exige o SEGUNDO FATOR no token, sempre - não há
    modo "opcional". Senha (ou Google) sem o código do autenticador não lê
    nem altera nada: só cadastra o autenticador.
    """
    if not u["_mfa"]:
        raise HTTPException(status_code=403, detail="mfa_pendente: cadastre o app autenticador "
                                                    "e entre com o código para continuar.")
    return u


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
