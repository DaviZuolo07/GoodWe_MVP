"""
Servidor que responde mas recusa a placa (ADR-021).

O laço de 06/10: relógio do PC 249 s atrasado -> o /hora devolve a hora errada
-> todo handshake volta 401 fora_da_janela -> o totem acertava a hora e tentava
de novo, ~10 vezes por segundo, para sempre.
"""

import time

from mesa import Mesa, mesa_bolso
from totem_virtual import config as K
from totem_virtual.config import Config
from totem_virtual.roteiro import FALHOU, Roteiro
from totem_virtual.totem import TotemVirtual

A = "A1A1A1A1"


class _Resp:
    def __init__(self, status: int, dados: dict):
        self.status_code, self._dados = status, dados

    def json(self):
        return self._dados


class ServidorQueRecusa:
    """Responde o /hora e recusa toda chamada assinada com o mesmo 401."""
    def __init__(self, codigo: str):
        self.codigo = codigo
        self.chamadas: list[str] = []

    def get(self, url, **_):
        self.chamadas.append("hora")
        return _Resp(200, {"ts": int(time.time()), "iso": "", "janela_s": 120})

    def request(self, metodo, url, headers=None, content=None):
        self.chamadas.append(url.rsplit("/", 1)[-1])
        return _Resp(401, {"detail": self.codigo})

    def close(self):
        pass


def _mesa_recusada(codigo: str, avisos: list) -> tuple[Mesa, ServidorQueRecusa]:
    servidor = ServidorQueRecusa(codigo)
    m = Mesa(servidor, Config(dispositivo_id="totem-x", chave_hex="00" * 32))   # anda 1 s
    m.t.avisar = avisos.append                   # o 3º 401 só vem depois de ~3 s
    return m, servidor


def test_fora_da_janela_repetido_para_de_insistir_e_culpa_o_relogio_do_servidor():
    avisos = []
    m, servidor = _mesa_recusada("fora_da_janela", avisos)
    m.andar(10)
    assert servidor.chamadas.count("handshake") == K.RECUSAS_PARA_BLOQUEAR
    assert servidor.chamadas.count("hora") == K.RECUSAS_PARA_BLOQUEAR, "acerta a hora antes de cada tentativa"
    e = m.e()
    assert e["recusa"] == "fora_da_janela" and e["link"] != "PRONTO" and e["ui"] == "INICIANDO"
    assert "relogio do computador do backend" in e["diagnostico"] and "w32tm" in e["diagnostico"]
    assert m.lcd() == ["ChargeOps GoodWe", "Relogio servidor"]
    assert len(avisos) == 1 and avisos[0] == e["diagnostico"], "o terminal recebe o diagnóstico uma vez"

    antes = len(servidor.chamadas)
    m.andar(K.BLOQUEIO_MS / 1000 - 10)
    assert len(servidor.chamadas) == antes, "bloqueado: silêncio total por um minuto"
    m.andar(12)
    assert servidor.chamadas[antes:] == ["hora", "handshake"], "uma tentativa por minuto, não um laço"
    assert len(avisos) == 1, "a mesma recusa não repete o aviso"


def test_chave_errada_bloqueia_e_manda_rodar_o_preparar_totem():
    avisos = []
    m = mesa_bolso(chave_hex="11" * 32)
    m.t.avisar = avisos.append
    m.andar(10)
    e = m.e()
    assert len(m.t.trocas("/handshake")) == K.RECUSAS_PARA_BLOQUEAR
    assert e["recusa"] == "assinatura_invalida" and e["chave_recusada"]
    assert "preparar_totem.py" in e["diagnostico"] and "DEVICE_MASTER_KEY" in e["diagnostico"]
    assert m.lcd() == ["ChargeOps GoodWe", "Chave invalida"]
    assert "11" * 32 not in str(e)


def test_recusa_no_meio_da_recarga_abre_os_reles_pela_trava_offline():
    m = mesa_bolso()
    m.t.plugar(1, 3.0, 30)
    assert m.tag_na_vaga(A, 1)["dados"]["acao"] == "ligar"
    m.andar(1)
    assert m.vaga(1)["rele"]

    m.t.enlace.placa.chave = bytes(32)           # o servidor passa a recusar a placa
    m.andar(m.cfg.offline_corte_ms / 1000 - 10)
    e = m.e()
    assert e["recusa"] == "assinatura_invalida" and e["diagnostico"]
    assert m.vaga(1)["rele"], "uma recusa não derruba a recarga na hora"
    m.andar(15)
    assert not m.vaga(1)["rele"] and m.vaga(1)["motivo_rele"] == "trava offline", \
        "servidor que não aceita a placa = ninguém acompanhando a recarga"


def test_recusa_some_quando_o_servidor_volta_a_aceitar():
    m = mesa_bolso(chave_hex="11" * 32)
    m.andar(5)
    assert m.e()["diagnostico"]
    from totem_virtual import backend_de_bolso
    _, cfg_certa = backend_de_bolso.subir()      # mesma placa, chave certa
    m.t.enlace.placa.chave = bytes.fromhex(cfg_certa.chave_hex)
    m.andar(K.BLOQUEIO_MS / 1000 + 2)
    e = m.e()
    assert e["link"] == "PRONTO" and e["online"]
    assert e["diagnostico"] is None and e["recusa"] is None
    assert m.convite()[1] == "Aproxime cartao"


def test_roteiro_diz_que_o_backend_recusou_e_nao_que_ficou_mudo():
    servidor = ServidorQueRecusa("fora_da_janela")
    totem = TotemVirtual(Config(dispositivo_id="totem-x", chave_hex="00" * 32), http=servidor, base="")
    totem.iniciar()
    linhas = []
    inicio = time.monotonic()
    try:
        roteiro = Roteiro(totem, servidor, "", saida=linhas.append)
        assert roteiro.executar() == 1
    finally:
        totem.parar()
    nome, status, detalhe = roteiro.resultados[0]
    assert (nome, status) == ("conexao", FALHOU)
    assert "RESPONDEU e recusou" in detalhe and "fora_da_janela" in detalhe
    assert "não respondeu" not in detalhe
    assert time.monotonic() - inicio < 12, "não espera os 15 s quando já sabe o motivo"
