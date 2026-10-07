"""
endurecimento.py - O que as DUAS APIs (pública e administrativa) têm em comum
na borda: cabeçalhos de segurança e documentação desligada em produção.
=============================================================================

Fica num arquivo só para as duas não divergirem: main.py e main_admin.py
chamam `aplicar(app)` e `opcoes_fastapi()`.
"""

from fastapi import FastAPI, Request

from config import PRODUCAO


def opcoes_fastapi() -> dict:
    """
    /docs, /redoc e /openapi.json publicam o mapa completo da API: toda rota,
    todo campo. Na bancada isso ajuda; na internet, é o roteiro de quem ataca.
    """
    if PRODUCAO:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {}


def aplicar(app: FastAPI) -> None:
    @app.middleware("http")
    async def cabecalhos(request: Request, call_next):
        resposta = await call_next(request)
        h = resposta.headers
        # A API só devolve JSON: nada dela deve ser interpretado como página,
        # embutido em iframe, nem guardado em cache de navegador ou de proxy.
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Cache-Control", "no-store")
        h.setdefault("Cross-Origin-Resource-Policy", "cross-origin")
        if not request.url.path.startswith(("/docs", "/redoc", "/openapi")):
            h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if PRODUCAO:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resposta
