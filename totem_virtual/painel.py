"""
painel.py - A página do totem virtual, servida SÓ em 127.0.0.1.
===============================================================

Biblioteca padrão apenas, nenhum arquivo externo: funciona sem internet.

Segurança (ADR-020 D7):
  - escuta em 127.0.0.1, nunca em 0.0.0.0;
  - recusa requisição com Host diferente de 127.0.0.1/localhost (DNS rebinding);
  - /api/* exige um token sorteado a cada execução, que só esta página
    conhece: um site aberto em outra aba não consegue apertar botão;
  - a chave da placa nunca sai do processo. O retrato (/api/estado) não a
    contém, e um teste garante isso.
"""

import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import PASTA
from .totem import TotemVirtual

ENDERECO = "127.0.0.1"
CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'"


def _num(dados: dict, chave: str, minimo: float, maximo: float) -> float:
    valor = float(dados[chave])
    if not minimo <= valor <= maximo:
        raise ValueError(f"{chave} fora de {minimo}..{maximo}")
    return valor


def executar_acao(totem: TotemVirtual, d: dict) -> None:
    """Uma ação da página = um gesto na bancada. Levanta ValueError/KeyError se vier torta."""
    acao = d.get("acao")
    if acao == "tag":
        uid = str(d["uid"]).strip()
        if not 1 <= len(uid) <= 40:
            raise ValueError("uid vazio ou longo demais")
        totem.aproximar_tag(uid)
    elif acao == "botao":
        totem.apertar_botao(int(_num(d, "porta", 1, 4)))
    elif acao == "plugar":
        totem.plugar(int(_num(d, "porta", 1, 4)), _num(d, "capacidade_wh", 0.05, 200),
                     _num(d, "soc", 0, 100))
    elif acao == "desplugar":
        totem.desplugar(int(_num(d, "porta", 1, 4)))
    elif acao == "luz":
        totem.luz(_num(d, "valor", 0, 100))
    elif acao == "bateria":
        totem.bateria(_num(d, "valor", 0, 100))
    elif acao == "wifi":
        totem.wifi(bool(d["ligado"]))
    elif acao == "reiniciar":
        totem.reiniciar()
    else:
        raise ValueError("acao desconhecida")


def criar_servidor(totem: TotemVirtual, porta: int, tags: dict | None = None) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(24)
    pagina = (PASTA / "painel.html").read_text(encoding="utf-8") \
        .replace("__TOKEN__", token) \
        .replace("__TAGS__", json.dumps(tags or {}).replace("<", "\\u003c"))

    class Tratador(BaseHTTPRequestHandler):
        server_version = "TotemVirtual"

        def log_message(self, *_):            # silêncio no terminal
            pass

        def _responder(self, status: int, corpo: bytes, tipo: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(corpo)

        def _json(self, status: int, dados: dict) -> None:
            self._responder(status, json.dumps(dados).encode(), "application/json")

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return host in ("127.0.0.1", "localhost")

        def _token_ok(self) -> bool:
            return secrets.compare_digest(self.headers.get("X-Totem-Token") or "", token)

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"erro": "host"})
            if self.path == "/":
                return self._responder(200, pagina.encode(), "text/html; charset=utf-8")
            if self.path == "/api/estado":
                if not self._token_ok():
                    return self._json(403, {"erro": "token"})
                return self._json(200, totem.estado())
            self._json(404, {"erro": "nao encontrado"})

        def do_POST(self):
            if not self._host_ok():
                return self._json(403, {"erro": "host"})
            if self.path != "/api/acao":
                return self._json(404, {"erro": "nao encontrado"})
            if not self._token_ok():
                return self._json(403, {"erro": "token"})
            try:
                tamanho = int(self.headers.get("Content-Length") or 0)
                if not 0 < tamanho <= 2048:
                    raise ValueError("corpo vazio ou grande demais")
                dados = json.loads(self.rfile.read(tamanho))
                if not isinstance(dados, dict):
                    raise ValueError("esperava um objeto")
                executar_acao(totem, dados)
            except (ValueError, KeyError, TypeError) as e:
                return self._json(400, {"erro": str(e)})
            self._json(200, {"ok": True})

    servidor = ThreadingHTTPServer((ENDERECO, porta), Tratador)
    servidor.daemon_threads = True
    servidor.token = token
    return servidor


def servir(cfg, http=None, base: str | None = None, porta: int = 8765) -> int:
    totem = TotemVirtual(cfg, http=http, base=base)
    totem.iniciar()
    servidor = criar_servidor(totem, porta, cfg.tags)
    print(f"\nTotem virtual no ar:  http://{ENDERECO}:{porta}")
    print("Só esta máquina enxerga a página. Ctrl+C para sair.\n")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
        totem.parar()
    return 0
