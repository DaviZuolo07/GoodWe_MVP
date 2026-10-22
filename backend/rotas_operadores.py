"""
rotas_operadores.py - Operador de condomínio entrando com a conta Google.
=========================================================================

Só a API ADMINISTRATIVA (main_admin.py) monta este arquivo.

QUEM É QUEM
  admin da plataforma  conta criada pelo `provisionar.py admin-global`, com
                       linha em `admins_globais`. Vê todos os locais.
  operador             pessoa de UM condomínio. Não é criada por ninguém
                       "por id": ela mesma pede o acesso entrando com o Google,
                       escolhe o condomínio, e o admin da plataforma aprova.

O FLUXO (db/23, tabela operadores_google)
  1. "Entrar com Google" no painel -> o Google devolve um ID token assinado.
  2. POST /admin/google {credencial, condominio_id}: o backend confere a
     assinatura do Google, a audiência (GOOGLE_CLIENT_ID) e o e-mail
     verificado. Conta nova vira PEDIDO pendente. Nada é liberado.
  3. O admin da plataforma aprova em "Operadores". Só então nasce a conta de
     gestor, PRESA ao condomínio do pedido e SEM senha (não há como entrar
     por nome + senha: não existe credencial).
  4. Entrada seguinte pelo Google: primeiro fator ok -> o mesmo segundo
     fator obrigatório de qualquer gestor (rotas_admin.concluir_entrada):
     cadastra o app autenticador no primeiro acesso e, daí em diante, código
     a cada entrada. Antes do código, nenhuma rota de dados responde.

O que o operador alcança é o que `gestor_logado` + o condomínio da conta
deixam: as rotas de gestor filtram SEMPRE pelo condomínio de quem chama.
Ele nunca entra em `admins_globais` (nada aqui escreve lá).
"""

import re
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import GOOGLE_CLIENT_ID, agora_iso, supabase, um
from identidade import CAMPOS_PUBLICOS
from rotas_admin import auditar, concluir_entrada
from rotas_geral import admin_global
from seguranca import LimitadorTentativas, ip_do_cliente

router = APIRouter(prefix="/admin", tags=["operadores"])

UUID = re.compile(r"[0-9a-fA-F-]{36}")
EMISSORES_GOOGLE = ("accounts.google.com", "https://accounts.google.com")
CHAVES_GOOGLE = "https://www.googleapis.com/oauth2/v3/certs"

# Cada entrada pelo Google custa uma verificação de assinatura; 20 por IP a
# cada 15 min segura quem tenta adivinhar códigos com um ID token roubado.
limitador_google = LimitadorTentativas(maximo=20, janela_s=900)

SEM_TABELA = HTTPException(status_code=503, detail="Entrada pelo Google indisponível: rode o db/23.")


class EntradaGoogle(BaseModel):
    credencial: str = Field(..., min_length=20, max_length=4096)
    condominio_id: Optional[str] = Field(None, max_length=40)
    codigo: Optional[str] = Field(None, max_length=12)


# ---------------------------------------------------------------------------
# Conferência do ID token do Google
# ---------------------------------------------------------------------------

_jwks = None


def verificar_google(credencial: str) -> dict:
    """
    Confere o ID token como o Google manda: assinatura RS256 com as chaves
    públicas do Google, emissor, audiência = o NOSSO client id, validade e
    e-mail verificado. Devolve {sub, email, nome}. Qualquer falha -> 401.
    Nenhuma biblioteca nova: o PyJWT já tem o cliente de JWKS.
    """
    global _jwks
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Entrada pelo Google não configurada "
                                                    "(GOOGLE_CLIENT_ID no backend/.env).")
    try:
        if _jwks is None:
            _jwks = jwt.PyJWKClient(CHAVES_GOOGLE, cache_keys=True, timeout=8)
        chave = _jwks.get_signing_key_from_jwt(credencial)
        dados = jwt.decode(credencial, chave.key, algorithms=["RS256"], audience=GOOGLE_CLIENT_ID,
                           options={"require": ["sub", "iss", "aud", "exp", "iat"]}, leeway=30)
    except (jwt.InvalidTokenError, jwt.PyJWKClientError) as e:
        raise HTTPException(status_code=401, detail="Entrada com o Google não confirmada.") from e
    if dados.get("iss") not in EMISSORES_GOOGLE or not dados.get("email_verified"):
        raise HTTPException(status_code=401, detail="Entrada com o Google não confirmada.")
    return {"sub": str(dados["sub"])[:64], "email": str(dados.get("email") or "")[:254],
            "nome": str(dados.get("name") or dados.get("email") or "Operador")[:120]}


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

def _pedido_do(sub: str) -> dict | None:
    try:
        return um(supabase.table("operadores_google").select("*").eq("google_sub", sub).execute())
    except Exception as e:                                   # noqa: BLE001
        print(f"[OPERADOR] operadores_google ilegível: {type(e).__name__}: {str(e)[:120]}")
        raise SEM_TABELA


def _locais_para_pedido() -> list[dict]:
    """Os mesmos locais que o /condominios do app já mostra a qualquer um."""
    return supabase.table("condominios").select("id, nome").order("nome").execute().data or []


@router.post("/google")
def entrar_com_google(payload: EntradaGoogle, request: Request):
    ip = ip_do_cliente(request)
    limitador_google.consumir(f"ip:{ip}")
    g = verificar_google(payload.credencial)
    pedido = _pedido_do(g["sub"])

    if not pedido:
        if not payload.condominio_id:
            # Primeira vez: a tela pergunta de qual condomínio a pessoa é.
            return {"success": False, "precisa_condominio": True, "email": g["email"],
                    "condominios": _locais_para_pedido()}
        if not UUID.fullmatch(payload.condominio_id) or not um(
                supabase.table("condominios").select("id").eq("id", payload.condominio_id).execute()):
            raise HTTPException(status_code=422, detail="Condomínio inválido.")
        supabase.table("operadores_google").insert({
            "google_sub": g["sub"], "email": g["email"], "nome_google": g["nome"],
            "condominio_id": payload.condominio_id, "status": "pendente"}).execute()
        auditar("operador_pedido", usuario={"id": None, "condominio_id": payload.condominio_id}, ip=ip,
                detalhe=f"pedido de {g['email']}")
        return {"success": False, "pedido": "pendente", "email": g["email"]}

    if pedido["status"] == "pendente":
        return {"success": False, "pedido": "pendente", "email": g["email"]}
    if pedido["status"] != "aprovado":
        auditar("login_recusado", usuario={"id": pedido.get("usuario_id"),
                                           "condominio_id": pedido["condominio_id"]},
                ip=ip, detalhe=f"google {pedido['status']}: {g['email']}")
        raise HTTPException(status_code=403, detail="Acesso não liberado para esta conta Google.")

    usuario = um(supabase.table("usuarios").select(CAMPOS_PUBLICOS).eq("id", pedido.get("usuario_id"))
                 .execute()) if pedido.get("usuario_id") else None
    # Conta apagada (reset do banco) ou mexida à mão: volta para a fila do admin.
    if (not usuario or usuario.get("tipo_usuario") != "gestor"
            or usuario.get("condominio_id") != pedido["condominio_id"]):
        supabase.table("operadores_google").update({"status": "pendente", "usuario_id": None}) \
            .eq("id", pedido["id"]).execute()
        return {"success": False, "pedido": "pendente", "email": g["email"]}

    def recusar(motivo: str, u: dict | None = None, status: int = 401,
                detalhe: str = "Entrada com o Google não confirmada."):
        limitador_google.registrar_falha(f"ip:{ip}")
        auditar("login_recusado", usuario=u, ip=ip, detalhe=f"google {motivo}: {g['email']}")
        raise HTTPException(status_code=status, detail=detalhe)

    return concluir_entrada(usuario, payload.codigo, ip, "google", recusar)


# ---------------------------------------------------------------------------
# Aprovação (só o admin da plataforma)
# ---------------------------------------------------------------------------

def _pedido(pedido_id: str) -> dict:
    if not UUID.fullmatch(pedido_id):
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")
    try:
        p = um(supabase.table("operadores_google").select("*").eq("id", pedido_id).execute())
    except Exception:                                        # noqa: BLE001
        raise SEM_TABELA
    if not p:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")
    return p


def _nome_livre(base: str, email: str) -> str:
    """`usuarios.nome` é o login do app: não pode repetir. Acrescenta o e-mail se precisar."""
    base = re.sub(r"[^\wÀ-ÿ .'-]", "", base).strip()[:40] or "Operador"
    for nome in (base, f"{base} ({email.split('@')[0][:15]})"):
        if not supabase.table("usuarios").select("id").ilike("nome", nome).execute().data:
            return nome
    return f"{base} {agora_iso()[11:19].replace(':', '')}"


@router.get("/operadores")
def listar_operadores(_: dict = Depends(admin_global)):
    try:
        lista = supabase.table("operadores_google").select("*").order("criado_em", desc=True) \
            .limit(200).execute().data or []
    except Exception:                                        # noqa: BLE001
        raise SEM_TABELA
    conds = {c["id"]: c["nome"] for c in supabase.table("condominios").select("id, nome").execute().data or []}
    return [{"id": p["id"], "email": p["email"], "nome_google": p.get("nome_google"),
             "condominio_id": p["condominio_id"], "local": conds.get(p["condominio_id"]),
             "status": p["status"], "usuario_id": p.get("usuario_id"),
             "criado_em": p["criado_em"], "decidido_em": p.get("decidido_em")} for p in lista]


@router.post("/operadores/{pedido_id}/aprovar")
def aprovar(pedido_id: str, request: Request, admin: dict = Depends(admin_global)):
    p = _pedido(pedido_id)
    if p["status"] == "aprovado" and p.get("usuario_id"):
        raise HTTPException(status_code=409, detail="Este operador já está aprovado.")
    u = supabase.table("usuarios").insert({
        "nome": _nome_livre(p.get("nome_google") or p["email"], p["email"]),
        "papel": "Operador", "tipo_usuario": "gestor", "condominio_id": p["condominio_id"],
        "bloco_apto": "Operação", "saldo": 0,
    }).execute().data[0]
    # Sem linha em credenciais_usuario: esta conta NÃO entra por nome + senha.
    supabase.table("operadores_google").update({
        "status": "aprovado", "usuario_id": u["id"], "decidido_por": admin["id"],
        "decidido_em": agora_iso()}).eq("id", p["id"]).execute()
    auditar("operador_aprovado", usuario=admin, ip=ip_do_cliente(request),
            detalhe=f"{p['email']} -> {u['nome']}")
    return {"success": True, "usuario": {"id": u["id"], "nome": u["nome"]}}


@router.post("/operadores/{pedido_id}/recusar")
def recusar_pedido(pedido_id: str, request: Request, admin: dict = Depends(admin_global)):
    p = _pedido(pedido_id)
    if p["status"] != "pendente":
        raise HTTPException(status_code=409, detail="Só pedido pendente pode ser recusado.")
    supabase.table("operadores_google").update({
        "status": "recusado", "decidido_por": admin["id"], "decidido_em": agora_iso()}) \
        .eq("id", p["id"]).execute()
    auditar("operador_recusado", usuario=admin, ip=ip_do_cliente(request), detalhe=p["email"])
    return {"success": True}


@router.post("/operadores/{pedido_id}/revogar")
def revogar(pedido_id: str, request: Request, admin: dict = Depends(admin_global)):
    """Tira o acesso NA HORA: a conta deixa de ser gestor e o token aberto morre na chamada seguinte."""
    p = _pedido(pedido_id)
    if p["status"] != "aprovado":
        raise HTTPException(status_code=409, detail="Só operador aprovado pode ser revogado.")
    if p.get("usuario_id"):
        supabase.table("usuarios").update({"tipo_usuario": "morador", "papel": "Operador revogado"}) \
            .eq("id", p["usuario_id"]).execute()
        supabase.table("gestor_mfa").delete().eq("usuario_id", p["usuario_id"]).execute()
    supabase.table("operadores_google").update({
        "status": "revogado", "decidido_por": admin["id"], "decidido_em": agora_iso()}) \
        .eq("id", p["id"]).execute()
    auditar("operador_revogado", usuario=admin, ip=ip_do_cliente(request), detalhe=p["email"])
    return {"success": True}
