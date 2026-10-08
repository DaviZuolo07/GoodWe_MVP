"""
GoodWe ChargeOps - API ADMINISTRATIVA (painel do gestor) - ADR-023
==================================================================

É OUTRO processo, em OUTRO endereço. O app do morador não sabe que ele existe.

  API pública         main.py         app do morador + totem     porta 8000
  API administrativa  main_admin.py   painel do gestor           porta 8001

O que separa as duas, em camadas (cada uma segura sozinha):

  1. Rotas       /gestor/* e /admin/* só existem AQUI. Na API pública dão 404.
  2. Token       audiência própria: o token do morador é recusado aqui, e o
                 do gestor é recusado lá.
  3. Login       /admin/login: senha + conta de gestor + código do autenticador.
  4. CORS        só a origem do painel (ADMIN_ORIGINS). A origem do app do
                 morador não entra na lista.
  5. Papel       `tipo_usuario = 'gestor'` relido do banco a cada chamada.
  6. Auditoria   login, recusa e toda alteração gravados em `auditoria_admin`.

Esta API NÃO roda o laço do simulador (isso é da pública): pode ser ligada,
desligada e publicada sem tocar nas recargas em andamento.

Rodar (de dentro de backend/):
    uvicorn main_admin:app --reload --host 127.0.0.1 --port 8001
"""

import jwt
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

import endurecimento
from config import ADMIN_MFA_OBRIGATORIO, ADMIN_ORIGIN_REGEX, ADMIN_ORIGINS, PRODUCAO
from hardware_api import router_admin as hardware_admin_router
from rotas_admin import auditar, router as admin_router
from rotas_geral import router as geral_router
from rotas_gestor import router as gestor_router
from seguranca import ip_do_cliente, mfa_configurado, validar_token_admin

if PRODUCAO and ADMIN_MFA_OBRIGATORIO and not mfa_configurado():
    raise RuntimeError(
        "API administrativa em produção sem ADMIN_MFA_KEY. Gere com "
        "`python provisionar.py chave-mfa` e cadastre o gestor com "
        "`python provisionar.py gestor-mfa --nome \"...\"`.")

app = FastAPI(title="GoodWe ChargeOps - API administrativa", **endurecimento.opcoes_fastapi())

endurecimento.aplicar(app)


@app.middleware("http")
async def registrar_alteracoes(request: Request, call_next):
    """Toda escrita bem-sucedida do painel vira uma linha de auditoria."""
    resposta = await call_next(request)
    caminho = request.url.path
    if (request.method in ("POST", "PATCH", "PUT", "DELETE") and resposta.status_code < 400
            and not caminho.startswith("/admin/")          # login e MFA já se registram
            and not caminho.endswith("/simular-demanda")):  # não grava nada no banco
        try:
            claims = validar_token_admin((request.headers.get("authorization") or "")[7:].strip())
            from starlette.concurrency import run_in_threadpool
            await run_in_threadpool(lambda: auditar(
                "alteracao", usuario={"id": claims["sub"], "condominio_id": _condominio(claims["sub"])},
                ip=ip_do_cliente(request), detalhe=f"{request.method} {caminho}"))
        except jwt.InvalidTokenError:
            pass
    return resposta


def _condominio(usuario_id: str):
    from config import supabase, um
    u = um(supabase.table("usuarios").select("condominio_id").eq("id", usuario_id).execute())
    return u.get("condominio_id") if u else None


# CORS por último = camada mais externa: responde ao preflight antes de tudo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ADMIN_ORIGINS,
    allow_origin_regex=ADMIN_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

app.include_router(admin_router)
app.include_router(gestor_router)
app.include_router(geral_router)
app.include_router(hardware_admin_router)


@app.get("/", tags=["saúde"])
def raiz():
    return {"status": "ok"}
