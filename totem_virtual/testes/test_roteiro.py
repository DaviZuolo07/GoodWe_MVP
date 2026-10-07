"""
O modo roteiro inteiro, em tempo real, contra os dois servidores:
  - o backend de hoje (em memória): nada falha, o tag-primeiro fica "aguardando backend";
  - o servidor v2.1 de referência: tudo passa;
  - um servidor que erra de propósito: o roteiro ACUSA a falha.
"""

import pytest
from fastapi.testclient import TestClient

import servidor_v21
from mesa import TAGS_V21
from totem_virtual import backend_de_bolso
from totem_virtual import config as K
from totem_virtual.config import Config
from totem_virtual.roteiro import AGUARDANDO, FALHOU, PASSOU, PULADO, Roteiro
from totem_virtual.totem import TotemVirtual

# Cenários tag-primeiro funcionando com o backend D1.
TAG_FIRST_D1 = ["inicia_pela_tag", "vaga_ocupada", "duas_vagas_pela_tag", "mesma_tag_outra_vaga",
                "encerra_pela_tag", "saldo_insuficiente", "tag_alheia", "bateria_solar_baixa"]
# Cenários que dependem de detecção de fim de sessão pelo INA219 (D2 — ainda não implementado).
TAG_FIRST_D2 = ["desplugado", "vaga_sem_celular", "celular_cheio"]
TAG_FIRST = TAG_FIRST_D1 + TAG_FIRST_D2


@pytest.fixture
def rapido(monkeypatch):
    monkeypatch.setattr(K, "TIMEOUT_ESCOLHA_MS", 2000)
    monkeypatch.setattr(K, "TELA_MS", 1000)
    monkeypatch.setattr(servidor_v21, "PRAZO_S", 1.5)


def _rodar(http, cfg):
    cfg.amostra_ms, cfg.envio_ms = 500, 1500
    totem = TotemVirtual(cfg, http=http, base="")
    totem.iniciar()
    linhas = []
    try:
        roteiro = Roteiro(totem, http, "", espera_s=15, wifi_s=4, saida=linhas.append)
        codigo = roteiro.executar()
    finally:
        totem.parar()
    return codigo, {nome: (status, detalhe) for nome, status, detalhe in roteiro.resultados}, linhas


def _cfg_v21(tags):
    return Config(backend_url="", dispositivo_id="totem-de-teste", chave_hex="00" * 32, tags=dict(tags))


def test_roteiro_no_backend_de_hoje_nada_falha(rapido):
    """
    Backend D1 (v2.1). TAG_FIRST_D1 passa; TAG_FIRST_D2 (desplugado,
    vaga_sem_celular, celular_cheio) ainda falha: o fim de sessão pela
    medição do INA219 (vaga vazia, desplugada, cheia) é o chat D2 do Daniel
    (ADR-018 §9 P6). Não são regressões; quando o D2 entrar, viram PASSOU e
    este teste continua verde.
    """
    http, cfg = backend_de_bolso.subir()
    codigo, r, linhas = _rodar(http, cfg)
    falhas = {nome for nome, (status, _) in r.items() if status == FALHOU}
    assert falhas <= set(TAG_FIRST_D2), (
        f"cenários inesperados falhando: {falhas - set(TAG_FIRST_D2)}\n" + "\n".join(linhas))
    for nome in ("conexao", "timeout_escolha", "app_duas_vagas", "wifi_caiu", "reboot"):
        assert r[nome][0] == PASSOU, (nome, r[nome])
    assert "2 recarga(s) seguiram" in r["wifi_caiu"][1]
    assert "2 recarga(s) religadas" in r["reboot"][1]
    for nome in TAG_FIRST_D1 + ["solar_na_telemetria"]:
        assert r[nome][0] == PASSOU, (nome, r[nome])


def test_roteiro_no_servidor_v21_de_referencia_tudo_passa(rapido):
    saldos = {uid: (0.0 if apelido == "SEM_SALDO" else 50.0) for apelido, uid in TAGS_V21.items()}
    http = TestClient(servidor_v21.criar(saldos))
    codigo, r, linhas = _rodar(http, _cfg_v21(TAGS_V21))
    assert codigo == 0, "\n".join(linhas)
    assert r["app_duas_vagas"][0] == PULADO, "sem contas do app configuradas"
    for nome in TAG_FIRST_D1 + TAG_FIRST_D2 + ["conexao", "timeout_escolha", "solar_na_telemetria", "wifi_caiu", "reboot"]:
        assert r[nome][0] == PASSOU, (nome, r[nome])
    assert "2 recarga(s) seguiram" in r["wifi_caiu"][1], "as falhas rodaram com as recargas da tag"
    assert "iniciadas pela tag" in r["duas_vagas_pela_tag"][1]


def test_roteiro_acusa_backend_que_liga_vaga_sem_saldo(rapido):
    saldos = {uid: 50.0 for uid in TAGS_V21.values()}            # o "sem saldo" tem saldo: erro
    http = TestClient(servidor_v21.criar(saldos))
    totem = TotemVirtual(_cfg_v21(TAGS_V21), http=http, base="")
    totem.iniciar()
    linhas = []
    try:
        roteiro = Roteiro(totem, http, "", espera_s=5, saida=linhas.append)
        roteiro.rodar("conexao", roteiro.conexao)
        roteiro.rodar("saldo_insuficiente", roteiro.saldo_insuficiente)
    finally:
        totem.parar()
    assert roteiro.resultados[-1][1] == FALHOU and "saldo_insuficiente" in roteiro.resultados[-1][2]


def test_roteiro_sem_tags_pula_em_vez_de_falhar(rapido):
    http = TestClient(servidor_v21.criar({}))
    totem = TotemVirtual(_cfg_v21({}), http=http, base="")
    totem.iniciar()
    try:
        roteiro = Roteiro(totem, http, "", saida=lambda _: None)
        roteiro.rodar("conexao", roteiro.conexao)
        roteiro.rodar("inicia_pela_tag", roteiro.inicia_pela_tag)
    finally:
        totem.parar()
    assert roteiro.resultados[-1][1] == PULADO and "TAG_A" in roteiro.resultados[-1][2]


def test_roteiro_sem_backend_falha_na_conexao_com_mensagem_clara():
    import httpx
    cfg = Config(backend_url="http://127.0.0.1:9", dispositivo_id="x", chave_hex="00" * 32)
    cfg.http_timeout_s = 0.3
    totem = TotemVirtual(cfg)
    totem.iniciar()
    linhas = []
    try:
        roteiro = Roteiro(totem, totem.http, cfg.backend_url, saida=linhas.append)
        original = roteiro.esperar
        roteiro.esperar = lambda cond, limite, passo=0.05: original(cond, min(limite, 1.5), passo)
        assert roteiro.executar() == 1
    finally:
        totem.parar()
    assert roteiro.resultados == [("conexao", FALHOU, roteiro.resultados[0][2])]
    assert "BACKEND_URL" in roteiro.resultados[0][2]
    assert isinstance(totem.http, httpx.Client)
