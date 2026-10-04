"""
placa_v2.py - Uma placa de mentira que fala o protocolo v2 (ADR-015).
=====================================================================

É a REFERÊNCIA do que o firmware v2 precisa fazer (Chat 3): mesma ordem dos
campos, mesma conta de HMAC, mesma numeração. Se aqui passa e na placa não,
o problema está no firmware, no relógio ou na chave - não no backend.

Usada de dois jeitos:

1. Pelos testes (test_protocolo_v2.py), sobre o TestClient do FastAPI.
2. Como SMOKE TEST contra o backend de verdade + Supabase de verdade, o que
   exercita as RPCs reais (consumir_seq, registrar_lote_telemetria):

    python testes/placa_v2.py --dispositivo <uuid> --chave <hex>
    # id e chave saem de: python provisionar.py placa-v2 ...  (ou chave-v2)

   Faz handshake, busca comandos, manda um lote de telemetria com o relé
   aberto nas portas SEM recarga ativa e confere que o backend recusa um
   replay, um timestamp velho e uma assinatura errada. Não mexe em saldo.
   ATENÇÃO: o handshake v2 aposenta o token v1 dessa placa.

COMO ASSINAR (o firmware faz exatamente isto)
---------------------------------------------
    boot  = aleatório de 32 bits sorteado ao ligar
    seq   = 1, 2, 3... (+1 a CADA requisição, inclusive as que falharam)
    ts    = hora unix em segundos (acertada por GET /hardware/v2/hora)
    corpo = os bytes exatos do JSON enviado (b"" no GET)
    msg   = MÉTODO + "\\n" + caminho + "\\n" + boot + "\\n" + seq + "\\n" + ts
            + "\\n" + sha256_hex(corpo)
    X-Sig = hex(HMAC-SHA256(chave, msg))
"""

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import time

PREFIXO = "/hardware/v2"


class PlacaV2:
    def __init__(self, http, dispositivo_id: str, chave_hex: str, boot: int | None = None,
                 base: str = ""):
        """`http` pode ser um httpx.Client ou o TestClient do FastAPI."""
        self.http, self.base = http, base.rstrip("/")
        self.dispositivo_id = dispositivo_id
        self.chave = bytes.fromhex(chave_hex)
        self.boot = boot if boot is not None else secrets.randbits(32)
        self.seq = 0
        self.offset_s = 0                      # relógio do servidor - relógio local
        self.t0 = time.monotonic()

    # -- relógio e millis() --------------------------------------------------
    def agora_ts(self) -> int:
        return int(time.time()) + self.offset_s

    def millis(self) -> int:
        return int((time.monotonic() - self.t0) * 1000)

    def acertar_relogio(self) -> dict:
        r = self.http.get(f"{self.base}{PREFIXO}/hora").json()
        self.offset_s = int(r["ts"]) - int(time.time())
        return r

    # -- assinatura ----------------------------------------------------------
    def assinar(self, metodo: str, caminho: str, boot: int, seq: int, ts: int, corpo: bytes,
                chave: bytes | None = None) -> str:
        msg = "\n".join([metodo.upper(), caminho, str(boot), str(seq), str(ts),
                         hashlib.sha256(corpo).hexdigest()]).encode()
        return hmac.new(chave or self.chave, msg, hashlib.sha256).hexdigest()

    def montar(self, metodo: str, rota: str, corpo=None, *, boot=None, seq=None, ts=None,
               chave=None, corpo_enviado: bytes | None = None, dispositivo_id=None) -> dict:
        """Prepara uma requisição assinada. Os parâmetros extras existem para os testes de ataque."""
        caminho = f"{PREFIXO}{rota}"
        dados = b"" if corpo is None else json.dumps(corpo, separators=(",", ":")).encode()
        if seq is None:
            self.seq += 1
            seq = self.seq
        boot = self.boot if boot is None else boot
        ts = self.agora_ts() if ts is None else ts
        cab = {"X-Device-Id": dispositivo_id or self.dispositivo_id, "X-Boot": str(boot),
               "X-Seq": str(seq), "X-Ts": str(ts),
               "X-Sig": self.assinar(metodo, caminho, boot, seq, ts, dados, chave)}
        if corpo is not None:
            cab["Content-Type"] = "application/json"
        return {"metodo": metodo, "url": f"{self.base}{caminho}", "headers": cab,
                "content": dados if corpo_enviado is None else corpo_enviado}

    def enviar(self, req: dict):
        """Manda EXATAMENTE os bytes e cabeçalhos montados (é o que permite testar replay)."""
        return self.http.request(req["metodo"], req["url"], headers=req["headers"],
                                 content=req["content"])

    def chamar(self, metodo: str, rota: str, corpo=None, **extra):
        return self.enviar(self.montar(metodo, rota, corpo, **extra))

    # -- protocolo -----------------------------------------------------------
    def reiniciar(self):
        """Simula a placa religando: boot novo, sequência do zero."""
        self.boot, self.seq = secrets.randbits(32), 0

    def handshake(self, firmware: str = "sim-v2"):
        # A sequência NÃO zera aqui: re-handshake no mesmo boot continua contando.
        return self.chamar("POST", "/handshake", {"mac": "SIM:V2", "ip": "127.0.0.1",
                                                  "firmware": firmware})

    def comandos(self):
        return self.chamar("GET", "/comandos")

    def confirmar(self, comando_id: str, sucesso: bool = True):
        return self.chamar("POST", f"/comandos/{comando_id}/confirmar", {"sucesso": sucesso})

    def rfid(self, porta: int, uid: str):
        return self.chamar("POST", "/rfid", {"porta": porta, "uid": uid})

    def telemetria(self, leituras: list[dict], t_envio_ms: int | None = None, **extra):
        return self.chamar("POST", "/telemetria",
                           {"t_envio_ms": self.millis() if t_envio_ms is None else t_envio_ms,
                            "leituras": leituras}, **extra)


# ---------------------------------------------------------------------------
# Smoke test contra o backend real
# ---------------------------------------------------------------------------

def _smoke(base: str, dispositivo: str, chave: str) -> int:
    import httpx

    falhas = 0

    def checar(cond, texto, extra=""):
        nonlocal falhas
        falhas += not cond
        print(f"  {'PASSOU' if cond else 'FALHOU'}  {texto}{'' if cond else f'  <- {extra}'}")

    with httpx.Client(timeout=15) as http:
        placa = PlacaV2(http, dispositivo, chave, base=base)
        hora = placa.acertar_relogio()
        print(f"\nRelógio acertado (offset {placa.offset_s} s, janela ±{hora['janela_s']} s)\n")

        r = placa.handshake()
        checar(r.status_code == 200, "handshake v2 assinado", r.text[:200])
        if r.status_code != 200:
            return 1
        portas = r.json()["portas"]
        print(f"         {len(portas)} porta(s): " +
              ", ".join(f"{p['porta']}->ponto {p['carregador']['numero']}" for p in portas))

        r = placa.comandos()
        checar(r.status_code == 200, "busca de comandos", r.text[:200])

        livres = [p["porta"] for p in portas if not p["sessao_ativa"]]
        if not livres:
            print("  (todas as portas com recarga ativa: pulando a telemetria para não interferir)")
        else:
            t = placa.millis()
            lote = [{"porta": p, "t_ms": t, "potencia_w": 0, "energia_wh": 0, "rele_ligado": False}
                    for p in livres]
            req = placa.montar("POST", "/telemetria", {"t_envio_ms": t, "leituras": lote})
            r = placa.enviar(req)
            checar(r.status_code == 200 and r.json()["gravadas"] == len(lote),
                   f"lote de telemetria ({len(lote)} leitura(s)) gravado", r.text[:200])
            r = placa.enviar(req)
            checar(r.status_code == 409 and r.json()["detail"] == "replay",
                   "o MESMO lote reenviado é recusado (replay)", r.text[:200])

        r = placa.chamar("GET", "/comandos", ts=placa.agora_ts() - 600)
        checar(r.status_code == 401 and r.json()["detail"] == "fora_da_janela",
               "requisição com 10 min de atraso é recusada", r.text[:200])
        r = placa.chamar("GET", "/comandos", chave=b"\x00" * 32)
        checar(r.status_code == 401 and r.json()["detail"] == "assinatura_invalida",
               "assinatura com chave errada é recusada", r.text[:200])

    print(f"\n{'Tudo certo.' if not falhas else f'{falhas} falha(s).'}\n")
    return 1 if falhas else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Smoke test do protocolo v2 contra o backend real")
    p.add_argument("--base", default=os.getenv("BACKEND_URL", "http://localhost:8000"))
    p.add_argument("--dispositivo", default=os.getenv("DEVICE_ID"), help="uuid da placa")
    p.add_argument("--chave", default=os.getenv("DEVICE_KEY_HEX"), help="chave v2 em hex")
    a = p.parse_args()
    if not a.dispositivo or not a.chave:
        sys.exit("Informe --dispositivo e --chave (saem de provisionar.py placa-v2 / chave-v2).")
    raise SystemExit(_smoke(a.base, a.dispositivo, a.chave))