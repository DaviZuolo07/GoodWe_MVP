"""
test_protocolo_v2.py - Protocolo v2, multiporta e cadastro atômico (ADR-015).
=============================================================================

Roda contra o app real do FastAPI com o Supabase falso em memória. O
comportamento das RPCs no Postgres de verdade é provado pelo
db/15_verificacao.sql; aqui se testa o backend em volta delas: assinatura,
códigos de erro, roteamento por porta, lote e o cadastro pela RPC.

Rodar:  python -m pytest testes -q
"""

import ambiente                                    # precisa vir primeiro

fake = ambiente.usar_supabase_falso()

from datetime import timedelta                     # noqa: E402

from fastapi.testclient import TestClient          # noqa: E402

import dispositivos                                # noqa: E402
import main                                        # noqa: E402
from config import agora                           # noqa: E402
from placa_v2 import PlacaV2                       # noqa: E402
from seguranca import chave_dispositivo, gerar_hash_senha, hash_token_dispositivo  # noqa: E402

CLIENTE = TestClient(main.app)
COND = "c0000000-0000-0000-0000-000000000002"
P1 = "b0000000-0000-0000-0000-000000000001"
P2 = "b0000000-0000-0000-0000-000000000002"
PLACA = "dddddddd-0000-0000-0000-000000000001"
TOKEN_V1 = "gw_dev_token_v1_de_teste"
CARTAO = "A1B2C3D4"
SENHA = "SenhaDemo#2026"


def cenario():
    """Uma placa de DUAS portas (bancada USB), um morador com saldo e o cartão do condomínio."""
    fake.limpar()
    fake.t("condominios").append({
        "id": COND, "nome": "Portal dos Bandeirantes", "endereco": "Av. Teste, 1",
        "limite_potencia_kw": 60, "ponta_inicio": "18:00", "ponta_fim": "21:00",
        "ponta_fator_limite": 0.6, "ponta_multiplicador_tarifa": 1.5})
    for cid, numero in ((P1, "01"), (P2, "02")):
        fake.t("carregadores").append({
            "id": cid, "condominio_id": COND, "numero": numero, "modelo": "Bancada USB · ESP32",
            "tipo": "DC", "potencia_maxima_kw": 0.025, "conector": "USB", "tensao_v": 5,
            "corrente_maxima_a": 3, "tarifa_kwh": 1.95, "status": "offline",
            "origem": "hardware", "perfil": "bancada", "temperatura_c": 26})
    # Placa que já foi v1 (tem token) e vai migrar: o handshake v2 aposenta o token.
    fake.t("dispositivos").append({
        "id": PLACA, "carregador_id": None, "nome": "ESP32 duas portas",
        "token_hash": hash_token_dispositivo(TOKEN_V1), "online": False, "protocolo": 1,
        "chave_versao": 1, "boot_atual": None, "seq_atual": 0,
        "intervalo_telemetria_s": 2, "intervalo_comandos_s": 2})
    fake.t("portas_dispositivo").extend([
        {"id": "pt1", "dispositivo_id": PLACA, "numero": 1, "carregador_id": P1},
        {"id": "pt2", "dispositivo_id": PLACA, "numero": 2, "carregador_id": P2}])

    fake.t("usuarios").append({"id": "u-gus", "nome": "Gus Bancada", "tipo_usuario": "morador",
                               "condominio_id": COND, "bloco_apto": "A1", "saldo": 0})
    fake.t("credenciais_usuario").append({"usuario_id": "u-gus", "senha_hash": gerar_hash_senha(SENHA)})
    fake.rpc("creditar_saldo", {"p_usuario": "u-gus", "p_valor": 10, "p_tipo": "credito",
                                "p_descricao": "saldo do teste"}).execute()
    fake.t("veiculos").append({"id": "v-cel", "usuario_id": "u-gus", "modelo": "Celular de teste",
                               "tipo": "celular", "capacidade_bateria_kwh": 0.015,
                               "potencia_carro_kw": 0.018})
    fake.t("condominios_favoritos").append({"id": "f1", "usuario_id": "u-gus", "condominio_id": COND})
    fake.t("cartoes_rfid").append({"uid": CARTAO, "escopo": "compartilhado", "condominio_id": COND,
                                   "apelido": "Cartão da bancada", "ativo": True, "usuario_id": None})
    return PlacaV2(CLIENTE, PLACA, chave_dispositivo(PLACA, 1).hex())


def entrar(nome):
    r = CLIENTE.post("/login", json={"nome": nome, "senha": SENHA})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def disp():
    return next(d for d in fake.t("dispositivos") if d["id"] == PLACA)


# ---------------------------------------------------------------------------
# 1. Assinatura, janela, sequência e downgrade
# ---------------------------------------------------------------------------

def test_hora_e_publica():
    r = CLIENTE.get("/hardware/v2/hora")
    assert r.status_code == 200 and r.json()["janela_s"] == 120 and r.json()["ts"] > 0


def test_handshake_v2_e_fim_do_v1():
    placa = cenario()
    r = placa.handshake()
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert [p["porta"] for p in corpo["portas"]] == [1, 2]
    assert corpo["portas"][1]["carregador"]["id"] == P2
    assert disp()["protocolo"] == 2 and disp()["token_hash"] is None
    assert disp()["online"] is True
    assert all(c["status"] == "disponivel" for c in fake.t("carregadores")), "as DUAS portas voltam ao ar"

    # Sem downgrade: o token v1 da mesma placa não entra mais.
    r = CLIENTE.post("/hardware/handshake", json={}, headers={"X-Device-Token": TOKEN_V1})
    assert r.status_code == 401


def test_assinatura_errada_corpo_adulterado_e_placa_inexistente_dao_o_mesmo_401():
    placa = cenario()
    placa.handshake()
    casos = {
        "chave errada": placa.montar("GET", "/comandos", chave=b"\x01" * 32),
        "corpo adulterado": placa.montar("POST", "/rfid", {"porta": 1, "uid": "00000000"},
                                         corpo_enviado=b'{"porta":2,"uid":"00000000"}'),
        "placa inexistente": placa.montar("GET", "/comandos",
                                          dispositivo_id="dddddddd-0000-0000-0000-00000000ffff"),
        "id que nem é uuid": placa.montar("GET", "/comandos", dispositivo_id="1 or 1=1"),
    }
    for nome, req in casos.items():
        r = placa.enviar(req)
        assert r.status_code == 401 and r.json()["detail"] == "assinatura_invalida", (nome, r.text)

    r = CLIENTE.get("/hardware/v2/comandos", headers={"X-Device-Id": PLACA})
    assert r.status_code == 401, "cabeçalhos faltando"


def test_replay_janela_e_boot():
    placa = cenario()
    placa.handshake()

    req = placa.montar("GET", "/comandos")
    assert placa.enviar(req).status_code == 200
    r = placa.enviar(req)
    assert r.status_code == 409 and r.json()["detail"] == "replay", "a MESMA requisição de novo"

    r = placa.chamar("GET", "/comandos", ts=placa.agora_ts() - 300)
    assert r.status_code == 401 and r.json()["detail"] == "fora_da_janela"

    r = placa.chamar("GET", "/comandos", boot=placa.boot + 1)
    assert r.status_code == 409 and r.json()["detail"] == "boot_desconhecido", "precisa refazer o handshake"

    # Reinício de verdade: boot novo aceito. O handshake do boot ANTIGO, não.
    assert placa.handshake().status_code == 200, "re-handshake no MESMO boot, seq seguindo"
    antigo = placa.boot
    placa.reiniciar()
    assert placa.handshake().status_code == 200
    r = placa.chamar("POST", "/handshake", {}, boot=antigo, seq=99)
    assert r.status_code == 409 and r.json()["detail"] == "replay"


# ---------------------------------------------------------------------------
# 2. Multiporta: recarga na porta 2, lote com as duas portas
# ---------------------------------------------------------------------------

def test_recarga_na_porta_2_com_telemetria_em_lote():
    placa = cenario()
    placa.handshake()
    gus = entrar("Gus Bancada")

    r = CLIENTE.post("/recargas/preparar", json={"charger_id": P2, "veiculo_id": "v-cel",
                                                 "percentual_bateria_atual": 40, "alvo_percentual": 80},
                     headers=gus)
    assert r.status_code == 200, r.text
    sessao_id = r.json()["sessao"]["id"]

    cmds = placa.comandos().json()["comandos"]
    assert [(c["acao"], c["porta"]) for c in cmds] == [("solicitar_cartao", 2)]
    assert cmds[0]["payload"]["porta"] == 2
    assert placa.confirmar(cmds[0]["id"]).json()["ok"]

    r = placa.rfid(1, CARTAO).json()
    assert r["porta"] == 1 and not r["autorizado"] and r["motivo"] == "sem_recarga_preparada", \
        "cartão na porta errada não confirma a recarga da porta 2"
    r = placa.rfid(2, CARTAO).json()
    assert r["porta"] == 2 and r["autorizado"], r
    assert placa.rfid(5, CARTAO).status_code == 422

    cmds = placa.comandos().json()["comandos"]
    assert [(c["acao"], c["porta"]) for c in cmds] == [("liberar", 2)]

    # Lotes de 30 leituras (60 s de medição a cada 2 s). Porta 1 parada, porta 2 carregando.
    energia_wh, t, ultimo = 0.0, 0, None
    for _ in range(200):
        lote = []
        for _ in range(15):
            t += 2000
            energia_wh += 9.0 * 2 / 3600
            lote.append({"porta": 1, "t_ms": t, "potencia_w": 0, "energia_wh": 0, "rele_ligado": False})
            lote.append({"porta": 2, "t_ms": t, "potencia_w": 9.0, "energia_wh": round(energia_wh, 4),
                         "tensao_v": 5.05, "corrente_a": 1.78, "temperatura_c": 31, "rele_ligado": True})
        r = placa.telemetria(lote, t_envio_ms=t)
        assert r.status_code == 200, r.text
        ultimo = {p["porta"]: p for p in r.json()["portas"]}
        assert r.json()["gravadas"] == 30
        assert ultimo[1]["deve_liberar"] is False and ultimo[1]["sessao_ativa"] is False
        # ADR-016 D11: cada porta diz quanto o alocador liberou (porta parada = 0).
        assert ultimo[1]["alocado_kw"] == 0
        if not ultimo[2]["deve_liberar"]:
            break
        assert ultimo[2]["alocado_kw"] > 0

    assert ultimo[2]["motivo"] == "alvo_atingido", ultimo[2]
    s = next(x for x in fake.t("sessoes_recarga") if x["id"] == sessao_id)
    assert s["status"] == "finalizada"

    leituras_p2 = [l for l in fake.t("leituras_hardware") if l["porta"] == 2]
    assert leituras_p2 and all(l["sessao_id"] == sessao_id for l in leituras_p2)
    assert all(l["sessao_id"] is None for l in fake.t("leituras_hardware") if l["porta"] == 1)
    # A ordem das leituras vem do servidor: dentro de um lote, a mais antiga tem medido_em menor.
    primeiro_lote = leituras_p2[:15]
    assert primeiro_lote[0]["medido_em"] < primeiro_lote[-1]["medido_em"]

    cmds = placa.comandos().json()["comandos"]
    assert ("bloquear", 2) in [(c["acao"], c["porta"]) for c in cmds]
    assert fake.conferir_carteira() == [], "saldo = soma do extrato depois de reserva e estorno"


def test_lote_repetido_e_porta_inexistente():
    placa = cenario()
    placa.handshake()
    lote = [{"porta": 1, "t_ms": 1000, "potencia_w": 0, "energia_wh": 0, "rele_ligado": False}]

    req = placa.montar("POST", "/telemetria", {"t_envio_ms": 1000, "leituras": lote})
    assert placa.enviar(req).status_code == 200
    antes = len(fake.t("leituras_hardware"))
    r = placa.enviar(req)
    assert r.status_code == 409 and r.json()["detail"] == "replay"
    assert len(fake.t("leituras_hardware")) == antes, "replay não grava nada"

    # Porta que a placa não tem derruba o lote inteiro, sem gastar o seq.
    seq = placa.seq + 1
    ruim = lote + [{"porta": 7, "t_ms": 1000, "potencia_w": 0}]
    r = placa.telemetria(ruim, t_envio_ms=1000, seq=seq)
    assert r.status_code == 422 and r.json()["detail"] == "porta_inexistente"
    assert len(fake.t("leituras_hardware")) == antes
    r = placa.telemetria(lote, t_envio_ms=1000, seq=seq)
    assert r.status_code == 200, "o mesmo seq continua valendo depois da recusa"

    r = placa.telemetria(lote * 31)
    assert r.status_code == 422, "mais de 30 leituras por lote"


def test_placa_sem_contato_derruba_todas_as_portas():
    placa = cenario()
    placa.handshake()
    disp()["ultimo_contato"] = (agora() - timedelta(minutes=5)).isoformat()
    dispositivos.marcar_offline_sem_contato()
    assert disp()["online"] is False
    assert {c["id"]: c["status"] for c in fake.t("carregadores")} == {P1: "offline", P2: "offline"}


# ---------------------------------------------------------------------------
# 3. Cadastro atômico pela RPC
# ---------------------------------------------------------------------------

def test_cadastro_pela_rpc_com_bonus_rotulado():
    cenario()
    corpo = {"nome": "Visitante Next", "senha": "SenhaForte#2026", "condominio_id": COND,
             "tipo_usuario": "visitante", "veiculo_modelo": "Celular do estande",
             "veiculo_tipo": "celular", "capacidade_bateria_kwh": 0.015, "potencia_carro_kw": 0.018}
    r = CLIENTE.post("/cadastro", json=corpo)
    assert r.status_code == 200, r.text
    u = r.json()["usuario"]
    assert u["saldo"] == 100.0 and r.json()["token"]

    extrato = [m for m in fake.t("movimentacoes_carteira") if m["usuario_id"] == u["id"]]
    assert [(m["tipo"], m["valor"], m["descricao"]) for m in extrato] == \
        [("bonus", 100.0, "Crédito de boas-vindas (simulado)")]
    assert fake.conferir_carteira() == []
    assert any(f["usuario_id"] == u["id"] and f["condominio_id"] == COND
               for f in fake.t("condominios_favoritos"))

    r = CLIENTE.post("/cadastro", json={**corpo, "nome": "VISITANTE NEXT"})
    assert r.status_code == 409, "nome repetido, ignorando maiúsculas"
    r = CLIENTE.post("/cadastro", json={**corpo, "nome": "Outro Nome",
                                        "condominio_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 400
    r = CLIENTE.post("/cadastro", json={**corpo, "nome": "Quer Ser Gestor", "tipo_usuario": "gestor"})
    assert r.status_code == 422, "o cadastro público não cria gestor"