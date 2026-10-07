"""
test_preparar_totem.py - O script que prepara o banco real para o Totem Central.
================================================================================

Roda o `preparar_totem.py` contra o Supabase falso (o mesmo cliente que o
script usa no banco real), DUAS vezes, e confere que:
  - nada duplica (idempotente);
  - a placa sai com fator 1000, porta solar 4 e virtual;
  - o totem_virtual/.env gerado autentica no backend (handshake v2);
  - a tag de teste inicia recarga pelo totem (Totem v2.1) e cobra em escala.
"""

import ambiente                                    # precisa vir primeiro

fake = ambiente.usar_supabase_falso()

import sys                                         # noqa: E402

from fastapi.testclient import TestClient          # noqa: E402

import main                                        # noqa: E402
import preparar_totem                              # noqa: E402
import provisionar                                 # noqa: E402
from placa_v2 import PlacaV2                       # noqa: E402

CLIENTE = TestClient(main.app)


def _rodar(monkeypatch, tmp_path, *args):
    monkeypatch.setattr(provisionar, "_supabase", lambda: fake)
    monkeypatch.setattr(preparar_totem, "ENV_TOTEM", tmp_path / ".env")
    monkeypatch.setattr(sys, "argv", ["preparar_totem.py", *args])
    preparar_totem.main()
    linhas = (tmp_path / ".env").read_text(encoding="utf-8").splitlines()
    return dict(x.split("=", 1) for x in linhas if "=" in x and not x.startswith("#"))


def test_prepara_uma_vez_so_e_o_env_gerado_funciona(monkeypatch, tmp_path):
    fake.limpar()
    env1 = _rodar(monkeypatch, tmp_path)
    env2 = _rodar(monkeypatch, tmp_path)               # de novo: não duplica nada
    assert env1 == env2
    assert (tmp_path / ".env.bak").exists(), "o .env anterior vira backup"

    assert len(fake.t("condominios")) == 1 and len(fake.t("carregadores")) == 4
    assert len(fake.t("dispositivos")) == 1 and len(fake.t("portas_dispositivo")) == 4
    assert len(fake.t("usuarios")) == 3 and len(fake.t("cartoes_rfid")) == 3
    assert len(fake.t("veiculos")) == 3 and len(fake.t("credenciais_usuario")) == 3
    d = fake.t("dispositivos")[0]
    assert (d["fator_escala"], d["porta_solar"], d["virtual"]) == (1000, 4, True)
    assert all(c["potencia_maxima_kw"] == 7.5 and c["perfil"] == "bancada" for c in fake.t("carregadores"))
    assert all(v["capacidade_bateria_kwh"] == 15 for v in fake.t("veiculos"))
    saldos = {u["nome"]: u["saldo"] for u in fake.t("usuarios")}
    assert saldos == {"Ana Totem": 100.0, "Bia Totem": 100.0, "Caio Totem": 0.0}, "bônus não repete"
    assert env1["APP_CONTAS"] == "Ana Totem:TotemNext#2026,Bia Totem:TotemNext#2026"

    placa = PlacaV2(CLIENTE, env1["DEVICE_ID"], env1["DEVICE_KEY_HEX"])
    hs = placa.handshake()
    assert hs.status_code == 200, hs.text
    assert hs.json()["fator_escala"] == 1000 and hs.json()["porta_solar"] == 4

    r = placa.rfid(1, env1["TAG_A"]).json()
    assert (r["motivo"], r["acao"]) == ("iniciada", "ligar"), r
    assert placa.rfid(2, env1["TAG_SEM_SALDO"]).json()["motivo"] == "saldo_insuficiente"
    t = placa.millis() + 1000
    resp = placa.chamar("POST", "/telemetria", {"t_envio_ms": t, "leituras": [
        {"porta": 1, "t_ms": t, "potencia_w": 7.5, "energia_wh": 2.0, "rele_ligado": True}]}).json()
    assert resp["portas"][0]["custo_ate_agora"] == 2.30, "2 Wh na bancada = 2 kWh x R$ 1,15"
    assert fake.t("leituras_hardware")[-1]["origem"] == "simulado"
    assert placa.rfid(1, env1["TAG_A"]).json()["motivo"] == "encerrada"

    login = CLIENTE.post("/login", json={"nome": "Ana Totem", "senha": "TotemNext#2026"})
    assert login.status_code == 200, "a conta de teste entra no app"


def test_recusa_senha_fraca(monkeypatch, tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        _rodar(monkeypatch, tmp_path, "--senha", "123")
