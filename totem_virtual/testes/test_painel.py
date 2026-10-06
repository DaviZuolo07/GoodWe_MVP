"""A página local: só em 127.0.0.1, com token, sem vazar a chave."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from mesa import mesa_bolso
from totem_virtual import painel


@pytest.fixture
def servido():
    m = mesa_bolso()
    servidor = painel.criar_servidor(m.t, 0, m.cfg.tags)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield m, servidor, f"http://127.0.0.1:{servidor.server_address[1]}"
    servidor.shutdown()
    servidor.server_close()


def _pedir(url, corpo=None, cabecalhos=None):
    dados = None if corpo is None else json.dumps(corpo).encode()
    req = urllib.request.Request(url, data=dados, headers=cabecalhos or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers


def test_escuta_so_em_127_0_0_1(servido):
    _, servidor, _ = servido
    assert servidor.server_address[0] == "127.0.0.1" and painel.ENDERECO == "127.0.0.1"


def test_pagina_sai_sem_a_chave_e_sem_arquivo_externo(servido):
    m, servidor, url = servido
    status, html, cab = _pedir(url + "/")
    assert status == 200 and "SIMULADO" in html and servidor.token in html
    assert m.cfg.chave_hex not in html
    assert "http://" not in html and "https://" not in html, "funciona sem internet"
    assert "default-src 'none'" in cab["Content-Security-Policy"]


def test_api_exige_token_e_host_local(servido):
    m, servidor, url = servido
    token = {"X-Totem-Token": servidor.token}
    assert _pedir(url + "/api/estado")[0] == 403
    assert _pedir(url + "/api/estado", cabecalhos={"X-Totem-Token": "errado"})[0] == 403
    assert _pedir(url + "/api/acao", {"acao": "reiniciar"})[0] == 403
    assert m.t.reinicios == 0, "sem token ninguém reinicia a placa"
    assert _pedir(url + "/api/estado", cabecalhos={**token, "Host": "site-malicioso.com"})[0] == 403
    assert _pedir(url + "/", cabecalhos={"Host": "site-malicioso.com"})[0] == 403

    status, corpo, _ = _pedir(url + "/api/estado", cabecalhos=token)
    assert status == 200 and len(json.loads(corpo)["vagas"]) == 4
    assert m.cfg.chave_hex not in corpo, "a chave da placa nunca vai para o navegador"


def test_todas_as_acoes_da_bancada(servido):
    m, servidor, url = servido
    cab = {"X-Totem-Token": servidor.token, "Content-Type": "application/json"}
    ok = lambda corpo: _pedir(url + "/api/acao", corpo, cab)[0]  # noqa: E731

    assert ok({"acao": "plugar", "porta": 2, "capacidade_wh": 10, "soc": 55}) == 200
    assert m.vaga(2)["celular"] == {"soc": 55.0, "capacidade_wh": 10.0}
    assert ok({"acao": "desplugar", "porta": 2}) == 200 and m.vaga(2)["celular"] is None
    assert ok({"acao": "luz", "valor": 35}) == 200 and m.e()["solar"]["luz"] == 35.0
    assert ok({"acao": "bateria", "valor": 80}) == 200 and m.e()["solar"]["bateria_soc"] == 80.0
    assert ok({"acao": "wifi", "ligado": False}) == 200 and m.e()["wifi"] is False
    assert ok({"acao": "wifi", "ligado": True}) == 200 and m.e()["wifi"] is True
    assert ok({"acao": "tag", "uid": "A1A1A1A1"}) == 200
    m.andar(0.1)
    assert m.e()["ui"] == "ESCOLHA_VAGA"
    assert ok({"acao": "botao", "porta": 4}) == 200
    m.andar(0.1)
    assert m.t.trocas("/rfid")[-1]["porta"] == 4
    assert ok({"acao": "reiniciar"}) == 200 and m.t.reinicios == 1

    for torta in ({"acao": "botao", "porta": 9}, {"acao": "luz", "valor": 500}, {"acao": "explodir"},
                  {"acao": "plugar", "porta": 1}, {"acao": "tag", "uid": ""}, ["lista"]):
        assert ok(torta) == 400, torta
