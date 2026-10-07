"""Ferramentas dos testes: um totem com relógio manual sobre cada um dos dois servidores."""

import random

from fastapi.testclient import TestClient

import servidor_v21
from totem_virtual import backend_de_bolso
from totem_virtual import config as K
from totem_virtual.bancada import RelogioManual
from totem_virtual.config import Config
from totem_virtual.totem import TotemVirtual

TAGS_V21 = {"A": "A1A1A1A1", "B": "B2B2B2B2", "SEM_SALDO": "C3C3C3C3"}


class Mesa:
    """Totem + relógio que só anda quando o teste manda."""
    def __init__(self, http, cfg, app=None):
        self.http, self.cfg, self.app = http, cfg, app
        self.relogio = RelogioManual()
        self.t = TotemVirtual(cfg, http=http, base="", relogio=self.relogio, rng=random.Random(11))
        self.andar(1.0)                       # hora + handshake

    def andar(self, segundos: float, passo: float = 0.05) -> None:
        for _ in range(round(segundos / passo)):
            self.relogio.avancar(passo)
            self.t.passo()

    def e(self) -> dict:
        return self.t.estado()

    def vaga(self, porta: int) -> dict:
        return self.e()["vagas"][porta - 1]

    def lcd(self) -> list[str]:
        return [x.rstrip() for x in self.e()["lcd"]]

    def _espera(self, pagina: int) -> list[str]:
        """Tela de espera do LCD 16x2: anda até a página pedida (alterna a cada ALTERNA_MS)."""
        for _ in range(2 * K.ALTERNA_MS // 50 + 2):
            e = self.e()
            if e["ui"] == "AGUARDANDO_TAG" and (e["millis"] // K.ALTERNA_MS) % 2 == pagina:
                return self.lcd()
            self.andar(0.05)
        raise AssertionError(f"a tela de espera não chegou à página {pagina}: {self.lcd()}")

    def convite(self) -> list[str]:
        """"ChargeOps GoodWe" / aviso da vez."""
        return self._espera(0)

    def quadro(self) -> list[str]:
        """As 4 vagas em 2 linhas: "1:LIVRE 2:7.4W" / "3:FILA  4:7.4WS"."""
        return self._espera(1)

    def tag_na_vaga(self, uid: str, porta: int) -> dict:
        marca = self.t.marca()
        self.t.aproximar_tag(uid)
        self.andar(0.2)
        self.t.apertar_botao(porta)
        self.andar(0.2)
        trocas = self.t.trocas("/rfid", marca)
        return trocas[0] if trocas else {}

    def preparar_no_app(self, conta: int, porta: int, soc: float = 30) -> tuple[str, dict]:
        """Fluxo de hoje: o morador prepara a recarga no app (só no backend de bolso)."""
        nome, senha = self.cfg.app_contas[conta]
        r = self.http.post("/login", json={"nome": nome, "senha": senha})
        cab = {"Authorization": f"Bearer {r.json()['token']}"}
        veiculo = self.http.get("/me/veiculos", headers=cab).json()[0]
        r = self.http.post("/recargas/preparar", headers=cab, json={
            "charger_id": backend_de_bolso.VAGAS[porta], "veiculo_id": veiculo["id"],
            "percentual_bateria_atual": soc, "alvo_percentual": 100})
        assert r.status_code == 200, r.text
        return r.json()["sessao"]["id"], cab

    def carregar_pelo_app(self, conta: int, porta: int, apelido: str) -> tuple[str, dict]:
        sessao, cab = self.preparar_no_app(conta, porta)
        self.andar(1.5)                       # o comando solicitar_cartao chega
        self.t.plugar(porta, 3.0, 30)
        assert self.tag_na_vaga(self.cfg.tags[apelido], porta)["dados"]["autorizado"]
        self.andar(1.5)                       # o comando liberar chega
        assert self.vaga(porta)["rele"]
        return sessao, cab


def mesa_bolso(**ajustes) -> Mesa:
    """Sobre o backend DE VERDADE (FastAPI de backend/ + supabase falso)."""
    http, cfg = backend_de_bolso.subir()
    cfg.amostra_ms, cfg.envio_ms = 1000, 2000
    for chave, valor in ajustes.items():
        setattr(cfg, chave, valor)
    return Mesa(http, cfg)


def mesa_v21(tags: dict | None = None, **ajustes) -> Mesa:
    """Sobre o servidor v2.1 de referência (leitura do contrato, só para teste)."""
    tags = dict(TAGS_V21 if tags is None else tags)
    saldos = {uid: (0.0 if apelido == "SEM_SALDO" else 50.0) for apelido, uid in tags.items()}
    app = servidor_v21.criar(saldos)
    cfg = Config(backend_url="", dispositivo_id="totem-de-teste", chave_hex="00" * 32,
                 amostra_ms=1000, envio_ms=2000, tags=tags)
    for chave, valor in ajustes.items():
        setattr(cfg, chave, valor)
    return Mesa(TestClient(app), cfg, app)
