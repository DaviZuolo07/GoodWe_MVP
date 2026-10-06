"""
test_totem_v21.py - Totem v2.1 no servidor (ADR-017 escala, ADR-018 tag-primeiro).
==================================================================================

Roda o app real do FastAPI com o Supabase falso, falando o protocolo v2 pela
`placa_v2.py` (cliente de referência, sem alteração). Cobre:

  tag-primeiro inicia; a MESMA tag encerra; tag alheia (evento); já carregando
  em outra vaga; saldo insuficiente; cartões recusados; recarga do app + tag;
  aguardando_energia com promoção (o motor gerencia 7,5 kW); lote só com
  fontes; vaga solar no Modbus 10030/10024; escala 7,5 W -> 7,5 kW e
  12 Wh -> R$ 13,80 a R$ 1,15/kWh; replay e assinatura inválida viram evento.

Tudo aqui é SIMULADO. Rodar (de dentro de backend/):  python -m pytest testes -q
"""

import ambiente                                    # precisa vir primeiro

fake = ambiente.usar_supabase_falso()

import pytest                                      # noqa: E402
from fastapi.testclient import TestClient          # noqa: E402

import demanda                                     # noqa: E402
import dispositivos                                # noqa: E402
import main                                        # noqa: E402
import simulador                                   # noqa: E402
from fisica import soc_pela_tensao_18650           # noqa: E402
from placa_v2 import PlacaV2                       # noqa: E402
from seguranca import chave_dispositivo, gerar_hash_senha  # noqa: E402

CLIENTE = TestClient(main.app)
COND = "c0000000-0000-0000-0000-0000000000d1"
OUTRO_COND = "c0000000-0000-0000-0000-0000000000d2"
PLACA = "dddddddd-0000-0000-0000-0000000000d1"
VAGAS = {n: f"b0000000-0000-0000-0000-0000000000d{n}" for n in (1, 2, 3, 4)}
SENHA = "SenhaTotem#2026"
TAG = {"A": "A1A1A1A1", "B": "B2B2B2B2", "C": "C3C3C3C3", "D": "D4D4D4D4", "X": "E5E5E5E5",
       "CARRO": "F6F6F6F6", "COMPARTILHADO": "0C0C0C0C"}


def cenario(limite_kw=60.0, fv=0.0, garantir_minimo=False):
    """Totem Central em escala 1:1000: 4 vagas de 7,5 kW (vaga 4 solar), celulares de 15 kWh."""
    fake.limpar()
    dispositivos.limpar_memoria_de_eventos()
    for cid, nome in ((COND, "Estande Next"), (OUTRO_COND, "Outro Condomínio")):
        # ponta 00:00-00:00 = nunca: os valores não dependem da hora em que o teste roda
        fake.t("condominios").append({
            "id": cid, "nome": nome, "endereco": "Rua do Teste, 1", "limite_potencia_kw": limite_kw,
            "ponta_inicio": "00:00", "ponta_fim": "00:00", "ponta_fator_limite": 0.6,
            "ponta_multiplicador_tarifa": 1.5, "fv_potencia_kwp": fv, "preco_solar_kwh": 0.75,
            "custo_solar_kwh": 0.35})
    for n, cid in VAGAS.items():
        fake.t("carregadores").append({
            "id": cid, "condominio_id": COND, "numero": f"0{n}", "modelo": "Totem Central (maquete 1:1000)",
            "tipo": "DC", "potencia_maxima_kw": 7.5, "conector": "USB", "tensao_v": 5,
            "corrente_maxima_a": 3, "tarifa_kwh": 1.15, "status": "offline", "origem": "hardware",
            "perfil": "bancada", "temperatura_c": 26, "bateria_soc_minimo": 20,
            "garantir_minimo": garantir_minimo, "modo_carga": 0})
        fake.t("portas_dispositivo").append(
            {"id": f"pt{n}", "dispositivo_id": PLACA, "numero": n, "carregador_id": cid})
    fake.t("dispositivos").append({
        "id": PLACA, "carregador_id": None, "nome": "Totem Central", "token_hash": None,
        "online": False, "protocolo": 2, "chave_versao": 1, "boot_atual": None, "seq_atual": 0,
        "intervalo_telemetria_s": 2, "intervalo_comandos_s": 2,
        "fator_escala": 1000, "virtual": False, "porta_solar": 4})

    hash_senha = gerar_hash_senha(SENHA)
    contas = [("u-ana", "Ana Totem", "A", 50.0, COND, "celular"), ("u-bia", "Bia Totem", "B", 50.0, COND, "celular"),
              ("u-caio", "Caio Totem", "C", 0.5, COND, "celular"), ("u-duda", "Duda Totem", "D", 50.0, COND, "celular"),
              ("u-xavi", "Xavi Fora", "X", 50.0, OUTRO_COND, "celular"),
              ("u-carlos", "Carlos Carro", "CARRO", 50.0, COND, "carro")]
    for uid, nome, tag, saldo, cond, tipo in contas:
        fake.t("usuarios").append({"id": uid, "nome": nome, "tipo_usuario": "morador",
                                   "condominio_id": cond, "bloco_apto": "A1", "saldo": 0})
        fake.t("credenciais_usuario").append({"usuario_id": uid, "senha_hash": hash_senha})
        fake.rpc("creditar_saldo", {"p_usuario": uid, "p_valor": saldo, "p_tipo": "bonus",
                                    "p_descricao": "Saldo do teste (simulado)"}).execute()
        fake.t("veiculos").append({"id": f"v-{uid}", "usuario_id": uid, "modelo": "Celular 1:1000",
                                   "tipo": tipo, "capacidade_bateria_kwh": 15, "potencia_carro_kw": 7.5,
                                   "percentual_bateria": 20, "criado_em": "2026-10-01T00:00:00+00:00"})
        fake.t("condominios_favoritos").append({"id": f"f-{uid}", "usuario_id": uid, "condominio_id": cond})
        fake.t("cartoes_rfid").append({"uid": TAG[tag], "escopo": "pessoal", "usuario_id": uid,
                                       "condominio_id": None, "apelido": f"Tag {tag}", "ativo": True})
    fake.t("cartoes_rfid").append({"uid": TAG["COMPARTILHADO"], "escopo": "compartilhado", "usuario_id": None,
                                   "condominio_id": COND, "apelido": "Cartão do estande", "ativo": True})
    placa = PlacaV2(CLIENTE, PLACA, chave_dispositivo(PLACA, 1).hex())
    assert placa.handshake().status_code == 200
    return placa


def tag(placa, porta, apelido_ou_uid):
    r = placa.rfid(porta, TAG.get(apelido_ou_uid, apelido_ou_uid))
    assert r.status_code == 200, r.text
    return r.json()


def lote(placa, leituras=(), fontes=None):
    t = placa.millis() + 1000
    corpo = {"t_envio_ms": t, "leituras": [{"t_ms": t, **x} for x in leituras]}
    if fontes is not None:
        corpo["fontes"] = [{"t_ms": t, **f} for f in fontes]
    r = placa.chamar("POST", "/telemetria", corpo)
    assert r.status_code == 200, r.text
    return r.json()


def porta_da_resposta(resp, porta):
    return next(p for p in resp["portas"] if p["porta"] == porta)


def comandos(placa):
    return [(c["acao"], c["porta"]) for c in placa.comandos().json()["comandos"]]


def sessao(sessao_id):
    return next(s for s in fake.t("sessoes_recarga") if s["id"] == sessao_id)


def viva(carregador_id):
    return [s for s in fake.t("sessoes_recarga") if s["carregador_id"] == carregador_id
            and s["status"] in ("aguardando_rfid", "carregando", "aguardando_energia")]


def saldo(uid):
    return next(u for u in fake.t("usuarios") if u["id"] == uid)["saldo"]


def tela_valida(linhas):
    return 1 <= len(linhas) <= 4 and all(len(x) <= 20 and x.isascii() for x in linhas)


CHAVES_CONTRATO = {"autorizado", "motivo", "acao", "tela", "mensagem", "sessao_id", "fila_posicao"}


# ---------------------------------------------------------------------------
# 1. Tag-primeiro, escala e cobrança
# ---------------------------------------------------------------------------

def test_tag_primeiro_inicia_escala_cobra_e_a_mesma_tag_encerra():
    placa = cenario()
    r = tag(placa, 1, "A")
    assert CHAVES_CONTRATO <= set(r) and r["porta"] == 1
    assert (r["autorizado"], r["motivo"], r["acao"]) == (True, "iniciada", "ligar"), r
    assert tela_valida(r["tela"]) and r["tela"][0] == "Vaga 1 liberada"
    s = sessao(r["sessao_id"])
    assert s["status"] == "carregando" and s["percentual_origem"] == "estimado"
    assert s["percentual_bateria_inicial"] == 20 and s["uid_inicio"] == TAG["A"]
    # reserva no pior caso (bateria vazia): 15 kWh / 0,92 x 1,15 = R$ 18,75
    assert s["valor_pre_autorizado"] == 18.75 and saldo("u-ana") == 31.25
    assert ("liberar", 1) in comandos(placa), "o mesmo ligar também chega por /v2/comandos"

    # 7,5 W brutos -> 7,5 kW: o alocador enxerga a carga de um ponto de verdade
    resp = lote(placa, [{"porta": 1, "potencia_w": 7.5, "energia_wh": 12.0, "rele_ligado": True}])
    p1 = porta_da_resposta(resp, 1)
    assert p1["deve_liberar"] is True and p1["estado"] == "carregando"
    assert p1["energia_wh"] == 12.0, "a placa recebe de volta o BRUTO"
    assert p1["potencia_media_w"] == 7.5 and p1["alocado_kw"] == pytest.approx(0.0075)
    assert p1["percentual_origem"] == "estimado"
    s = sessao(r["sessao_id"])
    assert s["energia_entregue_kwh"] == pytest.approx(12.0) and s["potencia_atual_kw"] == pytest.approx(7.5)
    leitura = fake.t("leituras_hardware")[-1]
    assert (leitura["potencia_w"], leitura["potencia_escalada_kw"], leitura["energia_escalada_kwh"]) == (7.5, 7.5, 12.0)
    estado = demanda.alocar(COND, gravar=False)
    assert estado["demanda_kw"] == pytest.approx(7.5), "o motor gerencia 7,5 kW, não 0,0075"

    # reboot: o handshake devolve o contador BRUTO (12 Wh, não 12000)
    placa.reiniciar()
    porta1 = next(p for p in placa.handshake().json()["portas"] if p["porta"] == 1)
    assert porta1["sessao_ativa"]["energia_wh"] == 12.0 and porta1["rele_esperado"] is True
    assert porta1["estado"] == "carregando"

    r = tag(placa, 1, "A")
    assert (r["autorizado"], r["motivo"], r["acao"]) == (True, "encerrada", "desligar"), r
    assert tela_valida(r["tela"]) and "13,80" in r["tela"][1]
    s = sessao(r["sessao_id"])
    assert s["status"] == "finalizada" and s["encerrado_por"] == "tag"
    assert s["custo_final"] == 13.80, "12 kWh x R$ 1,15"
    assert s["valor_estornado"] == 4.95 and saldo("u-ana") == pytest.approx(36.20)
    assert ("bloquear", 1) in comandos(placa)
    assert fake.conferir_carteira() == []
    assert porta_da_resposta(lote(placa, [{"porta": 1, "potencia_w": 0, "energia_wh": 12.0,
                                           "rele_ligado": False}]), 1)["estado"] == "livre"


def test_percentual_estimado_nao_encerra_a_recarga():
    placa = cenario()
    r = tag(placa, 1, "A")
    # 20% + 15 kWh entregues passaria de 100%: com % estimado, quem encerra é a medição/tag
    resp = lote(placa, [{"porta": 1, "potencia_w": 7.5, "energia_wh": 14.9, "rele_ligado": True}])
    p1 = porta_da_resposta(resp, 1)
    assert p1["percentual"] == 100.0 and p1["sessao_ativa"] is True, p1
    assert sessao(r["sessao_id"])["status"] == "carregando"


# ---------------------------------------------------------------------------
# 2. Recusas
# ---------------------------------------------------------------------------

def test_tag_alheia_na_vaga_ocupada_recusa_e_vira_evento():
    placa = cenario()
    r = tag(placa, 1, "A")
    alheia = tag(placa, 1, "B")
    assert (alheia["autorizado"], alheia["motivo"], alheia["acao"]) == (False, "vaga_ocupada", "nenhuma")
    assert tela_valida(alheia["tela"])
    assert sessao(r["sessao_id"])["status"] == "carregando", "a tag alheia não derruba a recarga"
    desconhecida = tag(placa, 1, "0BADF00D")
    assert desconhecida["motivo"] == "vaga_ocupada"
    eventos = [e for e in fake.t("eventos_seguranca") if e["tipo"] == "tag_alheia"]
    assert len(eventos) == 2 and {e["uid"] for e in eventos} == {TAG["B"], "0BADF00D"}
    assert all(e["condominio_id"] == COND and e["porta"] == 1 and e["dispositivo_id"] == PLACA for e in eventos)


def test_ja_carregando_em_outra_vaga():
    placa = cenario()
    tag(placa, 1, "A")
    r = tag(placa, 3, "A")
    assert (r["autorizado"], r["motivo"], r["acao"]) == (False, "ja_carregando_em_outra_vaga", "nenhuma")
    assert not viva(VAGAS[3])


def test_saldo_insuficiente_nao_cria_sessao_nem_liga():
    placa = cenario()
    r = tag(placa, 2, "C")
    assert (r["autorizado"], r["motivo"], r["acao"]) == (False, "saldo_insuficiente", "nenhuma")
    assert tela_valida(r["tela"]) and r["tela"][1] == "Precisa R$ 18,75"
    assert not viva(VAGAS[2]) and saldo("u-caio") == 0.5
    assert ("liberar", 2) not in comandos(placa)


def test_cartoes_que_nao_iniciam_recarga():
    placa = cenario()
    r = tag(placa, 2, "0BADF00D")
    assert (r["motivo"], r["acao"], r["uid"]) == ("cartao_nao_cadastrado", "nenhuma", "0BADF00D")
    assert tag(placa, 2, "X")["motivo"] == "cartao_de_outro_condominio"
    assert tag(placa, 2, "CARRO")["motivo"] == "sem_veiculo", "a bancada só aceita celular"
    r = tag(placa, 2, "COMPARTILHADO")
    assert (r["autorizado"], r["motivo"]) == (False, "sem_recarga_preparada"), \
        "cartão do condomínio não identifica quem paga: só confirma recarga do app"
    assert placa.rfid(2, "A1:-").json()["motivo"] == "uid_invalido"
    assert not viva(VAGAS[2])


# ---------------------------------------------------------------------------
# 3. Recarga preparada no app + tag (continua funcionando)
# ---------------------------------------------------------------------------

def test_recarga_do_app_confirmada_pela_tag():
    placa = cenario()
    login = CLIENTE.post("/login", json={"nome": "Bia Totem", "senha": SENHA}).json()
    cab = {"Authorization": f"Bearer {login['token']}"}
    r = CLIENTE.post("/recargas/preparar", headers=cab, json={
        "charger_id": VAGAS[2], "veiculo_id": "v-u-bia", "percentual_bateria_atual": 40, "alvo_percentual": 80})
    assert r.status_code == 200, r.text
    assert comandos(placa) == [("solicitar_cartao", 2)]

    assert tag(placa, 2, "A")["motivo"] == "cartao_de_outro_usuario", "vaga reservada para quem preparou"
    r = tag(placa, 2, "B")
    assert (r["autorizado"], r["motivo"], r["acao"]) == (True, "confirmada_app", "ligar"), r
    assert "saldo_atual" in r and "valor_reservado" in r, "campos antigos continuam (só aditivo)"
    s = sessao(r["sessao_id"])
    assert s["status"] == "carregando" and s["uid_inicio"] == TAG["B"] and s["percentual_origem"] == "informado"
    assert tag(placa, 2, "B")["motivo"] == "encerrada", "a mesma tag que confirmou encerra"


# ---------------------------------------------------------------------------
# 4. Sem orçamento de energia: espera com relé desligado, liga sozinha depois
# ---------------------------------------------------------------------------

def test_aguardando_energia_e_promocao_quando_libera():
    placa = cenario(limite_kw=20)
    tag(placa, 1, "A")
    tag(placa, 2, "B")
    lote(placa, [{"porta": 1, "potencia_w": 7.5, "energia_wh": 1, "rele_ligado": True},
                 {"porta": 2, "potencia_w": 7.4, "energia_wh": 1, "rele_ligado": True}])
    comandos(placa)                                         # esvazia os liberar das vagas 1 e 2

    r = tag(placa, 3, "D")                                  # 7,5 + 7,4 + 7,5 > 20 kW
    assert (r["autorizado"], r["motivo"], r["acao"]) == (True, "aguardando_energia", "nenhuma"), r
    assert r["fila_posicao"] == 1 and tela_valida(r["tela"])
    espera = sessao(r["sessao_id"])
    assert espera["status"] == "aguardando_energia" and saldo("u-duda") == 31.25, "saldo já reservado"
    p3 = porta_da_resposta(lote(placa, [{"porta": 3, "potencia_w": 0, "energia_wh": 0, "rele_ligado": False}]), 3)
    assert (p3["deve_liberar"], p3["estado"]) == (False, "aguardando_energia")
    assert tag(placa, 3, "C")["motivo"] == "vaga_ocupada", "quem espera energia ocupa a vaga"

    tag(placa, 1, "A")                                      # libera 7,5 kW
    assert sessao(r["sessao_id"])["status"] == "carregando"
    assert ("liberar", 3) in comandos(placa), "o backend liga depois por /v2/comandos"
    assert any("Energia liberada" in n["mensagem"] for n in fake.t("notificacoes") if n["usuario_id"] == "u-duda")


def test_mesma_tag_cancela_a_espera_e_devolve_a_reserva_inteira():
    placa = cenario(limite_kw=5)
    r = tag(placa, 1, "A")
    assert r["motivo"] == "aguardando_energia"
    assert saldo("u-ana") == 31.25
    c = tag(placa, 1, "A")
    assert (c["motivo"], c["acao"]) == ("encerrada", "desligar")
    assert sessao(r["sessao_id"])["status"] == "cancelada" and saldo("u-ana") == 50.0
    assert fake.conferir_carteira() == []


def test_simulador_promove_a_fila_quando_o_limite_sobe(monkeypatch):
    placa = cenario(limite_kw=5)
    r = tag(placa, 1, "A")
    assert r["motivo"] == "aguardando_energia"
    fake.t("condominios")[0]["limite_potencia_kw"] = 20
    simulador.ciclo()
    assert sessao(r["sessao_id"])["status"] == "carregando"
    assert ("liberar", 1) in comandos(placa)


# ---------------------------------------------------------------------------
# 5. Fontes: lote só com fontes, painel medido, bateria estimada
# ---------------------------------------------------------------------------

def test_lote_so_com_fontes_grava_painel_medido_e_soc_estimado():
    placa = cenario(fv=10)
    resp = lote(placa, [], fontes=[
        {"fonte": "painel", "potencia_w": 7.4, "tensao_v": 5.88, "corrente_a": 1.26},
        {"fonte": "bateria", "potencia_w": 0.0, "tensao_v": 3.95, "corrente_a": 0.0}])
    assert (resp["gravadas"], resp["fontes_gravadas"], resp["portas"]) == (0, 2, [])
    fontes = {f["fonte"]: f for f in fake.t("leituras_fonte")}
    assert fontes["painel"]["potencia_escalada_kw"] == pytest.approx(7.4)
    assert fontes["bateria"]["soc_estimado"] == 70.0 and fontes["painel"]["origem"] == "medido"
    g = fake.t("geracao_solar")
    assert len(g) == 1 and g[0]["potencia_kw"] == pytest.approx(7.4) and g[0]["origem"] == "medido"
    assert g[0]["dispositivo_id"] == PLACA
    assert demanda.excedente_solar(fake.t("condominios")[0]) == (pytest.approx(7.4), "medido")
    simulador.gravar_geracao_solar(fake.t("condominios")[0])
    assert len(fake.t("geracao_solar")) == 1 and fake.t("geracao_solar")[0]["origem"] == "medido", \
        "o simulador vira fallback: não sobrescreve a placa"

    # lote vazio e fonte fora da lista: 422, nada gravado
    t = placa.millis()
    assert placa.chamar("POST", "/telemetria", {"t_envio_ms": t, "leituras": []}).status_code == 422
    assert placa.chamar("POST", "/telemetria", {"t_envio_ms": t, "fontes": [
        {"fonte": "eolica", "t_ms": t, "potencia_w": 1}]}).status_code == 422
    assert len(fake.t("leituras_fonte")) == 2


def test_placa_virtual_grava_simulado():
    placa = cenario()
    next(d for d in fake.t("dispositivos") if d["id"] == PLACA)["virtual"] = True
    lote(placa, [{"porta": 1, "potencia_w": 0, "energia_wh": 0, "rele_ligado": False}],
         fontes=[{"fonte": "painel", "potencia_w": 3.0, "tensao_v": 5.9}])
    assert fake.t("leituras_hardware")[-1]["origem"] == "simulado"
    assert fake.t("leituras_fonte")[-1]["origem"] == "simulado"
    assert fake.t("geracao_solar")[-1]["origem"] == "simulado"


def test_vaga_solar_pausa_abaixo_do_10030_e_retoma():
    placa = cenario()
    r = tag(placa, 4, "A")
    assert r["acao"] == "ligar"
    comandos(placa)
    # sem sol, bateria a ~10% (3,45 V) descarregando na vaga: abaixo do 10030 (20%)
    resp = lote(placa, [{"porta": 4, "potencia_w": 7.5, "energia_wh": 1.0, "rele_ligado": True}],
                fontes=[{"fonte": "painel", "potencia_w": 0, "tensao_v": 0},
                        {"fonte": "bateria", "potencia_w": 7.6, "tensao_v": 3.45, "corrente_a": 2.2}])
    p4 = porta_da_resposta(resp, 4)
    assert (p4["deve_liberar"], p4["estado"], p4["sessao_ativa"]) == (False, "pausada", True), p4
    assert ("bloquear", 4) in comandos(placa)
    s = sessao(r["sessao_id"])
    assert s["modo_vaga_solar"] == "pausada"
    assert s["energia_solar_kwh"] == pytest.approx(1.0) and s["origem_solar"] == "medido", \
        "o kWh que veio da bateria é solar MEDIDO"

    # o painel recarregou a bateria a ~50% (3,80 V): retoma
    resp = lote(placa, [{"porta": 4, "potencia_w": 0, "energia_wh": 1.0, "rele_ligado": False}],
                fontes=[{"fonte": "bateria", "potencia_w": 0, "tensao_v": 3.80}])
    p4 = porta_da_resposta(resp, 4)
    assert (p4["deve_liberar"], p4["estado"], p4["fonte"]) == (True, "carregando", "solar")
    assert ("liberar", 4) in comandos(placa)


def test_vaga_solar_vai_para_a_rede_com_10024_ligado():
    placa = cenario(garantir_minimo=True)
    tag(placa, 4, "A")
    resp = lote(placa, [{"porta": 4, "potencia_w": 7.5, "energia_wh": 1.0, "rele_ligado": True}],
                fontes=[{"fonte": "bateria", "potencia_w": 7.6, "tensao_v": 3.45}])
    p4 = porta_da_resposta(resp, 4)
    assert (p4["deve_liberar"], p4["estado"], p4["fonte"]) == (True, "carregando", "rede")


def test_politica_da_vaga_solar_e_curva_da_bateria():
    d = demanda.decidir_vaga_solar
    assert d("solar", 15, 7.0, 20, False) == "pausada"
    assert d("solar", 15, 7.0, 20, True) == "rede"
    assert d("solar", 15, 0.0, 20, False) == "solar", "bateria parada: o painel dá conta"
    assert d("pausada", 22, 0.0, 20, False) == "pausada", "histerese: só volta em 25%"
    assert d("pausada", 25, 0.0, 20, False) == "solar"
    assert d("rede", None, 7.0, 20, True) == "rede", "sem leitura, não decide no escuro"
    assert soc_pela_tensao_18650(3.80) == 50.0 and soc_pela_tensao_18650(4.3) == 100.0
    assert soc_pela_tensao_18650(None) is None


def test_vizinha_da_vaga_solar_nao_recebe_sol_atribuido():
    itens = [{"id": "vaga1", "demanda_kw": 7.5, "controlavel": False, "so_rede": True},
             {"id": "vaga4", "demanda_kw": 7.5, "controlavel": False}]
    r = demanda.distribuir_fontes(60, 7.5, itens)
    assert r["itens"]["vaga1"]["alocado_solar_kw"] == 0 and r["itens"]["vaga1"]["alocado_rede_kw"] == 7.5
    assert r["itens"]["vaga4"]["alocado_solar_kw"] == 7.5
    cenario()
    assert dispositivos.carregadores_so_rede(list(VAGAS.values())) == {VAGAS[1], VAGAS[2], VAGAS[3]}


# ---------------------------------------------------------------------------
# 6. Eventos de segurança do protocolo
# ---------------------------------------------------------------------------

def test_replay_e_assinatura_invalida_viram_evento_sem_inundar():
    placa = cenario()
    req = placa.montar("GET", "/comandos")
    assert placa.enviar(req).status_code == 200
    for _ in range(3):
        assert placa.enviar(req).json()["detail"] == "replay"
    for _ in range(3):
        r = placa.chamar("GET", "/comandos", chave=b"\x01" * 32)
        assert r.json()["detail"] == "assinatura_invalida"
    tipos = [e["tipo"] for e in fake.t("eventos_seguranca")]
    assert tipos.count("replay") == 1 and tipos.count("assinatura_invalida") == 1, \
        "o mesmo evento repetido não enche a tabela"
    assert all(e["dispositivo_id"] == PLACA and e["condominio_id"] == COND for e in fake.t("eventos_seguranca"))
