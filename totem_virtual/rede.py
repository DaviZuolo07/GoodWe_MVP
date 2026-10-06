"""
rede.py - O enlace do totem com o backend (protocolo v2, ADR-015).
==================================================================

A assinatura, o boot e a sequência são da PlacaV2 (backend/testes/placa_v2.py),
IMPORTADA sem alteração: é a referência que o firmware também copia.

O que este arquivo acrescenta é o que o firmware precisa em volta dela:
  - nunca levantar exceção: toda chamada devolve uma Resposta;
  - não tentar nada com o Wi-Fi caído;
  - guardar um registro das trocas (a página e o modo roteiro leem daqui).

A chave da placa fica só dentro da PlacaV2. O registro NUNCA guarda chave
nem assinatura.
"""

import sys
from collections import Counter, deque
from dataclasses import dataclass, field

from .config import RAIZ

sys.path.insert(0, str(RAIZ / "backend" / "testes"))
from placa_v2 import PlacaV2  # noqa: E402  (referência do protocolo; não alterar)


@dataclass
class Resposta:
    chegou: bool                       # o servidor respondeu (com qualquer status)
    status: int = 0
    dados: dict = field(default_factory=dict)
    codigo: str = ""                   # o `detail` dos erros v2 (replay, fora_da_janela...)

    @property
    def ok(self) -> bool:
        return self.chegou and self.status == 200


def _resumo(dados: dict, codigo: str) -> str:
    if codigo:
        return codigo
    partes = []
    for chave in ("motivo", "acao", "gravadas", "autorizado"):
        if chave in dados:
            partes.append(f"{chave}={dados[chave]}")
    if "comandos" in dados:
        partes.append("comandos=" + (",".join(f"{c.get('acao')}@{c.get('porta')}"
                                              for c in dados["comandos"]) or "nenhum"))
    if "portas" in dados and "gravadas" not in dados:
        partes.append(f"portas={len(dados['portas'])}")
    return " ".join(partes) or "ok"


class Enlace:
    def __init__(self, http, cfg, hal, base: str = ""):
        self.hal = hal
        self.placa = PlacaV2(http, cfg.dispositivo_id, cfg.chave_hex, base=base)
        self.registro: deque = deque(maxlen=400)
        self.contagem: Counter = Counter()
        self._n = 0

    # -- numeração -------------------------------------------------------
    def reiniciar(self) -> None:
        """A placa religou: boot novo, seq do zero, relógio por acertar."""
        self.placa.reiniciar()
        self.placa.offset_s = 0

    def novo_boot(self) -> None:
        self.placa.reiniciar()

    @property
    def boot(self) -> int:
        return self.placa.boot

    @property
    def seq(self) -> int:
        return self.placa.seq

    # -- chamadas --------------------------------------------------------
    def _anotar(self, metodo, rota, resposta: Resposta, extra: dict | None = None) -> Resposta:
        self._n += 1
        self.contagem["confirmar" if rota.endswith("/confirmar") else rota.strip("/").split("/")[0]] += 1
        self.registro.append({
            "n": self._n, "t_ms": self.hal.millis(), "boot": self.placa.boot, "seq": self.placa.seq,
            "metodo": metodo, "rota": rota, "status": resposta.status if resposta.chegou else None,
            "resumo": _resumo(resposta.dados, resposta.codigo) if resposta.chegou else "sem resposta",
            "dados": resposta.dados, **(extra or {})})
        return resposta

    def _chamar(self, metodo: str, rota: str, corpo=None, extra: dict | None = None) -> Resposta:
        if not self.hal.wifi_ok():
            return Resposta(False)                   # sem Wi-Fi nem assina: não gasta seq
        try:
            r = self.placa.chamar(metodo, rota, corpo)
        except Exception:                            # conexão recusada, timeout, DNS...
            return self._anotar(metodo, rota, Resposta(False), extra)
        try:
            dados = r.json()
        except Exception:
            dados = {}
        if not isinstance(dados, dict):
            dados = {}
        detalhe = dados.get("detail")
        codigo = "" if r.status_code == 200 else (detalhe if isinstance(detalhe, str) else "invalido")
        return self._anotar(metodo, rota, Resposta(True, r.status_code, dados, codigo), extra)

    def acertar_relogio(self) -> Resposta:
        if not self.hal.wifi_ok():
            return Resposta(False)
        try:
            dados = self.placa.acertar_relogio()
        except Exception:
            return self._anotar("GET", "/hora", Resposta(False))
        return self._anotar("GET", "/hora", Resposta(True, 200, dados))

    def handshake(self, firmware: str) -> Resposta:
        return self._chamar("POST", "/handshake",
                            {"mac": "VIRTUAL", "ip": "127.0.0.1", "firmware": firmware})

    def comandos(self) -> Resposta:
        return self._chamar("GET", "/comandos")

    def confirmar(self, comando_id: str, sucesso: bool, erro: str | None = None) -> Resposta:
        corpo = {"sucesso": sucesso}
        if erro:
            corpo["erro"] = erro[:200]
        return self._chamar("POST", f"/comandos/{comando_id}/confirmar", corpo)

    def rfid(self, porta: int, uid: str) -> Resposta:
        return self._chamar("POST", "/rfid", {"porta": porta, "uid": uid}, {"porta": porta})

    def telemetria(self, corpo: dict) -> Resposta:
        return self._chamar("POST", "/telemetria", corpo,
                            {"leituras": len(corpo.get("leituras") or []),
                             "fontes": len(corpo.get("fontes") or [])})
