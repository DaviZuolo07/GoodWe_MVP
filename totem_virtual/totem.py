"""
totem.py - Junta bancada + firmware + enlace num totem que roda sozinho.
========================================================================

É o que a página, o modo roteiro e os testes usam. Um único cadeado protege
tudo: o laço roda numa thread e os botões chegam de outra.
"""

import random
import threading
import time

from .bancada import Bancada, Relogio
from .config import Config
from .firmware import Firmware
from .rede import Enlace

PASSO_S = 0.05          # 20 voltas por segundo, como um loop() folgado


class TotemVirtual:
    def __init__(self, cfg: Config, http=None, base: str | None = None,
                 relogio: Relogio | None = None, rng: random.Random | None = None, avisar=None):
        """`avisar(texto)`: chamado uma vez a cada diagnóstico novo (o terminal, no painel)."""
        self.cfg = cfg
        self.avisar = avisar
        self._avisado = None
        self._http_proprio = http is None
        if http is None:
            import httpx
            http = httpx.Client(timeout=cfg.http_timeout_s)
            base = cfg.backend_url if base is None else base
        self.http, self.base = http, base or ""
        self.relogio = relogio or Relogio()
        self.bancada = Bancada(self.relogio, rng)
        self.enlace = Enlace(http, cfg, self.bancada, base=self.base)
        self.firmware = Firmware(self.bancada, self.enlace, cfg)
        self.reinicios = 0
        self._trava = threading.RLock()
        self._ultimo = self.relogio.agora_s()
        self._thread, self._parar = None, threading.Event()

    # -- laço --------------------------------------------------------------
    def passo(self) -> None:
        """Avança a física pelo tempo que passou e dá uma volta no loop() do firmware."""
        with self._trava:
            agora = self.relogio.agora_s()
            self.bancada.avancar(max(0.0, min(1.0, agora - self._ultimo)))
            self._ultimo = agora
            self.firmware.loop()
            diagnostico = self.firmware.diagnostico
            if diagnostico != self._avisado:
                self._avisado = diagnostico
                if diagnostico and self.avisar:
                    self.avisar(diagnostico)

    def iniciar(self) -> None:
        if self._thread:
            return
        self._parar.clear()

        def rodar():
            while not self._parar.is_set():
                try:
                    self.passo()
                except Exception as e:      # um erro aqui não pode matar a bancada inteira
                    self.firmware.eventos.append({"t_ms": self.bancada.millis(),
                                                  "texto": f"ERRO no laco: {type(e).__name__}: {e}"})
                time.sleep(PASSO_S)

        self._thread = threading.Thread(target=rodar, name="totem-virtual", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        if self._http_proprio:
            self.http.close()

    # -- o que a pessoa faz na bancada --------------------------------------
    def aproximar_tag(self, uid: str) -> None:
        with self._trava:
            self.bancada.aproximar_tag(uid)

    def apertar_botao(self, porta: int) -> None:
        with self._trava:
            self.bancada.apertar_botao(int(porta))

    def plugar(self, porta: int, capacidade_wh: float = 15.0, soc: float = 20.0) -> None:
        with self._trava:
            self.bancada.plugar(int(porta), capacidade_wh, soc)

    def desplugar(self, porta: int) -> None:
        with self._trava:
            self.bancada.desplugar(int(porta))

    def luz(self, percentual: float) -> None:
        with self._trava:
            self.bancada.painel.luz = max(0.0, min(100.0, float(percentual))) / 100.0

    def bateria(self, soc: float) -> None:
        with self._trava:
            self.bancada.bateria.soc = max(0.0, min(100.0, float(soc)))

    def wifi(self, ligado: bool) -> None:
        with self._trava:
            self.bancada.wifi = bool(ligado)

    def reiniciar(self) -> None:
        """Tira e põe a placa na tomada: relés caem, RAM some, boot novo."""
        with self._trava:
            self.bancada.reiniciar()
            self.enlace.reiniciar()
            self.firmware = Firmware(self.bancada, self.enlace, self.cfg)
            self._avisado = None
            self.reinicios += 1
            self._ultimo = self.relogio.agora_s()

    # -- retrato para a página e para o roteiro ------------------------------
    def estado(self) -> dict:
        with self._trava:
            fw, b = self.firmware, self.bancada
            vagas = []
            for p, v in fw.vagas.items():
                cel = b.celulares[p]
                vagas.append({
                    "porta": p, "existe": v.existe, "rele": v.rele, "motivo_rele": v.motivo_rele,
                    "estado": v.estado, "estado_do_backend": v.estado_do_backend,
                    "sessao_id": v.sessao_id, "energia_wh": round(v.energia_wh, 4),
                    **v.medida,
                    "pedido": v.pedido_de if v.pedido_ate_ms is not None else None,
                    "aguarda_tag": v.pedido_ate_ms is not None,
                    "backend": {k: v.ultima_resposta.get(k) for k in
                                ("percentual", "custo_ate_agora", "tempo_restante_min", "alocado_kw",
                                 "deve_liberar", "motivo") if k in v.ultima_resposta},
                    "celular": None if not cel else {"soc": round(cel.soc, 2),
                                                     "capacidade_wh": cel.capacidade_wh},
                })
            return {
                "lcd": list(b.lcd.linhas),
                "ui": fw.ui, "link": fw.link, "online": fw.online(), "wifi": b.wifi,
                "chave_recusada": fw.chave_recusada,
                "recusa": fw.recusa, "recusas_seguidas": fw.recusas_seguidas,
                "diagnostico": fw.diagnostico,
                "boot": self.enlace.boot, "seq": self.enlace.seq, "millis": b.millis(),
                "reinicios": self.reinicios,
                "fila_leituras": len(fw.fila_leituras), "fila_fontes": len(fw.fila_fontes),
                "descartadas": fw.descartadas, "lotes_enviados": fw.lotes_enviados,
                "lotes_descartados": fw.lotes_descartados,
                "vagas": vagas,
                "solar": {"luz": round(b.painel.luz * 100, 1), "fonte": b.fonte_selecionada(),
                          "fonte_backend": fw.fonte_backend,
                          "painel": b.painel_visto(), "bateria": b.ler_bateria(),
                          "bateria_soc": round(b.bateria.soc, 2), "bateria_ok": fw.bateria_ok},
                "eventos": list(fw.eventos)[-40:],
                "trocas": [{k: x.get(k) for k in ("n", "t_ms", "seq", "metodo", "rota", "status",
                                                  "resumo", "leituras", "fontes")}
                           for x in list(self.enlace.registro)[-40:]],
            }

    def trocas(self, rota: str | None = None, desde: int = 0) -> list[dict]:
        """Registro completo (com a resposta do backend). `desde` = último `n` já visto."""
        with self._trava:
            return [x for x in self.enlace.registro
                    if x["n"] > desde and (rota is None or x["rota"] == rota)]

    def marca(self) -> int:
        with self._trava:
            return self.enlace.registro[-1]["n"] if self.enlace.registro else 0
