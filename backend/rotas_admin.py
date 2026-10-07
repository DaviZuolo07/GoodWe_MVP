"""
rotas_admin.py - Entrada do painel do gestor (ADR-023).
=======================================================

Só a API ADMINISTRATIVA (main_admin.py) monta este arquivo. O app do morador
não conhece estas rotas, e a API pública não as tem.

O login daqui é mais exigente que o do morador:

  1. nome + senha            (o mesmo Argon2id da conta)
  2. a conta É de gestor      (conferido no banco, não no navegador)
  3. código do autenticador   (TOTP de 6 dígitos; cada código vale uma vez)

Respostas de erro NÃO dizem qual das três falhou antes da senha estar certa:
"credenciais inválidas" vale para nome inexistente, senha errada e conta que
não é de gestor. Só depois da senha correta o servidor pede o código - senão
a tela revelaria quais nomes são de gestor.

Toda tentativa (boa ou ruim) e toda alteração feita pelo painel vão para
`auditoria_admin` (db/18): quem, quando, de onde, o quê.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import ADMIN_MFA_OBRIGATORIO, agora_iso, supabase, um
from identidade import CAMPOS_PUBLICOS, gestor_logado
from rotas_conta import NOME_VALIDO
from seguranca import (SENHA_MAX, cifrar_segredo_mfa, conferir_senha, conferir_totp,
                       decifrar_segredo_mfa, emitir_token_admin, gerar_segredo_totp,
                       hash_ficticio, ip_do_cliente, limitador_admin_ip, limitador_admin_nome,
                       mfa_configurado, uri_totp)

router = APIRouter(prefix="/admin", tags=["admin"])


class LoginAdmin(BaseModel):
    nome: str = Field(..., min_length=1, max_length=60)
    senha: str = Field(..., min_length=1, max_length=SENHA_MAX)
    codigo: Optional[str] = Field(None, max_length=12)


class CodigoMfa(BaseModel):
    codigo: str = Field(..., min_length=6, max_length=12)


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------

def auditar(acao: str, *, usuario: dict | None = None, ip: str | None = None,
            detalhe: str | None = None) -> None:
    """NUNCA levanta: log que falha não pode derrubar a operação do gestor."""
    try:
        supabase.table("auditoria_admin").insert({
            "acao": acao[:60],
            "usuario_id": usuario.get("id") if usuario else None,
            "condominio_id": usuario.get("condominio_id") if usuario else None,
            "ip": (ip or "")[:64] or None,
            "detalhe": (detalhe or "")[:200] or None,
        }).execute()
    except Exception as e:                                   # noqa: BLE001
        print(f"[ADMIN] auditoria não gravou ({acao}): {type(e).__name__}: {str(e)[:120]}")


# ---------------------------------------------------------------------------
# Segundo fator
# ---------------------------------------------------------------------------

def _mfa_do(usuario_id: str) -> dict | None:
    try:
        return um(supabase.table("gestor_mfa").select("*").eq("usuario_id", usuario_id).execute())
    except Exception as e:                                   # noqa: BLE001
        # Tabela ausente (db/18 não rodou). Tratar como "sem MFA" abriria a
        # porta em produção: o chamador decide pelo ADMIN_MFA_OBRIGATORIO.
        print(f"[ADMIN] não consegui ler gestor_mfa: {type(e).__name__}: {str(e)[:120]}")
        return None


def _conferir_codigo(mfa: dict, codigo: str | None) -> bool:
    """Confere e QUEIMA o código (grava o passo, para não valer de novo)."""
    try:
        segredo = decifrar_segredo_mfa(mfa["segredo_cifrado"])
    except Exception:                                        # noqa: BLE001
        print("[ADMIN] segredo de MFA ilegível: ADMIN_MFA_KEY mudou? Recadastre o gestor.")
        return False
    passo = conferir_totp(segredo, codigo or "", mfa.get("ultimo_passo"))
    if passo is None:
        return False
    supabase.table("gestor_mfa").update({"ultimo_passo": passo, "ultimo_uso": agora_iso()}) \
        .eq("usuario_id", mfa["usuario_id"]).execute()
    return True


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

@router.post("/login")
def login(payload: LoginAdmin, request: Request):
    nome, ip = payload.nome.strip(), ip_do_cliente(request)
    chave_nome, chave_ip = f"nome:{nome.lower()}", f"ip:{ip}"
    limitador_admin_nome.verificar(chave_nome)
    limitador_admin_ip.verificar(chave_ip)

    def recusar(motivo: str, usuario: dict | None = None, status: int = 401,
                detalhe: str = "Credenciais inválidas."):
        limitador_admin_nome.registrar_falha(chave_nome)
        limitador_admin_ip.registrar_falha(chave_ip)
        auditar("login_recusado", usuario=usuario, ip=ip, detalhe=f"{motivo}: {nome}")
        raise HTTPException(status_code=status, detail=detalhe)

    usuario = None
    if NOME_VALIDO.fullmatch(nome):
        usuario = um(supabase.table("usuarios").select(CAMPOS_PUBLICOS).ilike("nome", nome).execute())
    credencial = None
    if usuario:
        credencial = um(supabase.table("credenciais_usuario").select("senha_hash")
                        .eq("usuario_id", usuario["id"]).execute())

    # O Argon2 roda SEMPRE (contra um hash fictício se preciso): o tempo de
    # resposta não distingue nome inexistente, senha errada e conta de morador.
    senha_ok = conferir_senha(credencial["senha_hash"] if credencial else hash_ficticio(),
                              payload.senha)
    if not (usuario and credencial and senha_ok):
        recusar("senha")
    if usuario.get("tipo_usuario") != "gestor":
        # Senha certa, mas é conta de morador: a MESMA resposta de senha errada.
        recusar("nao_gestor", usuario)

    mfa = _mfa_do(usuario["id"])
    ativo = bool(mfa and mfa.get("ativado_em"))
    if ativo:
        if not payload.codigo:
            # Senha correta e ainda falta o código: não conta como falha.
            return {"success": False, "mfa_necessario": True}
        if not _conferir_codigo(mfa, payload.codigo):
            recusar("codigo", usuario, detalhe="Código inválido ou já usado. Espere o próximo.")
    elif ADMIN_MFA_OBRIGATORIO:
        auditar("login_recusado", usuario=usuario, ip=ip, detalhe="mfa_nao_cadastrado")
        raise HTTPException(status_code=403, detail=(
            "Esta conta ainda não tem o segundo fator cadastrado. Peça a quem administra o "
            "servidor para rodar: python provisionar.py gestor-mfa --nome \"<seu nome>\""))

    limitador_admin_nome.limpar(chave_nome)
    auditar("login", usuario=usuario, ip=ip, detalhe="mfa" if ativo else "sem_mfa")
    return {"success": True, "gestor": _publico(usuario), "mfa": ativo,
            **emitir_token_admin(usuario["id"], mfa=ativo)}


def _publico(u: dict) -> dict:
    return {k: u.get(k) for k in ("id", "nome", "condominio_id", "tipo_usuario")}


@router.get("/me")
def eu(gestor: dict = Depends(gestor_logado)):
    c = um(supabase.table("condominios").select("id, nome, endereco")
           .eq("id", gestor.get("condominio_id")).execute()) if gestor.get("condominio_id") else None
    return {"gestor": _publico(gestor), "condominio": c, "mfa": gestor["_mfa"]}


@router.post("/mfa/iniciar")
def mfa_iniciar(request: Request, gestor: dict = Depends(gestor_logado)):
    """
    Gera o segredo e devolve o endereço otpauth:// UMA vez. Fica pendente até
    o gestor provar, em /mfa/confirmar, que o app está gerando o código certo.
    Quem já tem MFA ativo não troca por aqui (precisa do provisionar.py): um
    token roubado não deve conseguir trocar o segundo fator.
    """
    if not mfa_configurado():
        raise HTTPException(status_code=503, detail="ADMIN_MFA_KEY não configurada no servidor.")
    atual = _mfa_do(gestor["id"])
    if atual and atual.get("ativado_em"):
        raise HTTPException(status_code=409, detail="O segundo fator já está ativo nesta conta.")
    segredo = gerar_segredo_totp()
    linha = {"usuario_id": gestor["id"], "segredo_cifrado": cifrar_segredo_mfa(segredo),
             "ativado_em": None, "ultimo_passo": None}
    if atual:
        supabase.table("gestor_mfa").update(linha).eq("usuario_id", gestor["id"]).execute()
    else:
        supabase.table("gestor_mfa").insert(linha).execute()
    auditar("mfa_iniciado", usuario=gestor, ip=ip_do_cliente(request))
    return {"segredo": segredo, "uri": uri_totp(segredo, gestor["nome"])}


@router.post("/mfa/confirmar")
def mfa_confirmar(payload: CodigoMfa, request: Request, gestor: dict = Depends(gestor_logado)):
    mfa = _mfa_do(gestor["id"])
    if not mfa:
        raise HTTPException(status_code=404, detail="Comece pelo cadastro do segundo fator.")
    if mfa.get("ativado_em"):
        raise HTTPException(status_code=409, detail="O segundo fator já está ativo nesta conta.")
    limitador_admin_nome.verificar(f"mfa:{gestor['id']}")
    if not _conferir_codigo(mfa, payload.codigo):
        limitador_admin_nome.registrar_falha(f"mfa:{gestor['id']}")
        raise HTTPException(status_code=400, detail="Código inválido. Confira o relógio do celular.")
    supabase.table("gestor_mfa").update({"ativado_em": agora_iso()}) \
        .eq("usuario_id", gestor["id"]).execute()
    auditar("mfa_ativado", usuario=gestor, ip=ip_do_cliente(request))
    # Token novo, já com amr = otp. O antigo vence sozinho em minutos.
    return {"success": True, "mfa": True, **emitir_token_admin(gestor["id"], mfa=True)}


@router.get("/auditoria")
def auditoria(limite: int = 50, gestor: dict = Depends(gestor_logado)):
    """Os últimos acessos e alterações do painel NESTE condomínio."""
    limite = max(1, min(int(limite), 200))
    linhas = supabase.table("auditoria_admin").select("criado_em, acao, ip, detalhe, usuario_id") \
        .eq("condominio_id", gestor.get("condominio_id")) \
        .order("criado_em", desc=True).limit(limite).execute().data or []
    return {"eventos": linhas}
