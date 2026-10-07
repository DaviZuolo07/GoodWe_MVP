"""
test_demanda_fontes.py - Gestão de demanda em duas fontes e cobrança por origem (ADR-016).
=========================================================================================

Funções puras (alocador, mínimo por modelo, disjuntor, recibo, curva solar) e
o backend em volta delas com o Supabase falso (progresso por fonte, geração
solar, API Modbus do gestor, painel por fonte, extrato), mais os cenários A-D.

Rodar:  python -m pytest testes -q
"""

import ambiente                                    # precisa vir primeiro

fake = ambiente.usar_supabase_falso()

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest                                      # noqa: E402
from fastapi.testclient import TestClient          # noqa: E402

import cenarios_demanda                            # noqa: E402
import demanda                                     # noqa: E402
import main                                        # noqa: E402
import main_admin                               # noqa: E402
import recarga                                     # noqa: E402
import simulador                                   # noqa: E402
from config import FUSO, agora                     # noqa: E402
from fisica import detalhar_custo, economia_vs_so_rede, minimo_kw, potencia_disjuntor_kw, teto_kw  # noqa: E402
from seguranca import gerar_hash_senha             # noqa: E402

CLIENTE = TestClient(main.app)
ADMIN = TestClient(main_admin.app)
SENHA = "SenhaDemo#2026"
COND = "c0000000-0000-0000-0000-000000000016"
OUTRO_COND = "c0000000-0000-0000-0000-000000000099"


def carro(i, demanda_kw=7.0, **extra):
    return {"id": f"c{i}", "demanda_kw": demanda_kw, "controlavel": True, "minimo_kw": 1.4,
            "modo": 0, "garantir_minimo": False, "ordem": i, **extra}


def hca(nominal=7, **extra):
    return {"id": "ch", "numero": "01", "perfil": "veicular", "origem": "simulado", "potencia_nominal_kw": nominal,
            "potencia_maxima_kw": nominal, "tensao_v": 230 if nominal == 7 else 400, "temperatura_c": 25, **extra}


# ===========================================================================
# 1. Alocador de duas fontes (puro)
# ===========================================================================

@pytest.mark.parametrize("limite, itens", [
    (30, [carro(i) for i in range(3)]),
    (15, [carro(i) for i in range(3)]),
    (12, [carro(0, 1.0), carro(1), carro(2)]),
    (5, [{"id": "esp", "demanda_kw": 0.009, "controlavel": False}, carro(1)]),
])
def test_sem_sol_e_igual_ao_alocador_antigo(limite, itens):
    novo = demanda.distribuir_fontes(limite, 0, itens)["itens"]
    antigo = demanda.distribuir(limite, itens)
    assert {k: round(v["alocado_kw"], 3) for k, v in novo.items()} == {k: round(v, 3) for k, v in antigo.items()}
    assert all(v["alocado_solar_kw"] == 0 for v in novo.values())


def test_abaixo_do_minimo_pausa_quem_chegou_por_ultimo():
    r = demanda.distribuir_fontes(4, 0, [carro(0), carro(1), carro(2)])["itens"]
    assert r["c2"]["pausado_motivo"] == demanda.PAUSA_LIMITE and r["c2"]["alocado_kw"] == 0
    assert r["c0"]["alocado_kw"] == r["c1"]["alocado_kw"] == 2.0


def test_sol_vai_primeiro_e_a_rede_completa():
    r = demanda.distribuir_fontes(10, 5, [carro(0), carro(1), carro(2)])
    assert r["solar_absorvido_kw"] == 5 and r["rede_kw"] == 10
    assert all(abs(x["alocado_kw"] - 5.0) < 1e-6 for x in r["itens"].values())


def test_modo_fv_so_com_sol_e_pausa_sem_excedente():
    fv = [carro(0, modo=1), carro(1, modo=1)]
    r = demanda.distribuir_fontes(10, 2.0, fv)
    assert r["rede_kw"] == 0, "modo FV sem 10024 nunca usa a rede"
    assert r["itens"]["c1"]["pausado_motivo"] == demanda.PAUSA_SEM_SOL
    assert r["itens"]["c0"]["alocado_solar_kw"] == 2.0
    noite = demanda.distribuir_fontes(10, 0, fv)
    assert all(x["pausado_motivo"] == demanda.PAUSA_SEM_SOL for x in noite["itens"].values())


def test_garantir_minimo_completa_da_rede_so_ate_o_minimo():
    r = demanda.distribuir_fontes(10, 0.5, [carro(0, modo=1, garantir_minimo=True)])["itens"]["c0"]
    assert r["alocado_solar_kw"] == 0.5 and abs(r["alocado_rede_kw"] - 0.9) < 1e-6 and r["pausado_motivo"] is None


def test_fv_tem_prioridade_no_sol_sobre_o_rapido():
    r = demanda.distribuir_fontes(10, 3, [carro(0, modo=0), carro(1, modo=1)])["itens"]
    assert r["c1"]["alocado_solar_kw"] == 3 and r["c0"]["alocado_solar_kw"] == 0 and r["c0"]["alocado_rede_kw"] == 7


def test_carga_fixa_estoura_na_ponta_e_o_alocador_avisa():
    r = demanda.distribuir_fontes(6, 0, [carro(0, controlavel=False)])
    assert r["estouro_kw"] == 1.0 and r["itens"]["c0"]["alocado_kw"] == 7


def test_10025_desligado_vira_carga_fixa():
    it = demanda.item_de(hca(controle_dinamico=False), {"potencia_carro_kw": 7}, 30, {}, "s", 0)
    assert not it["controlavel"] and it["demanda_kw"] == 7
    assert demanda.item_de(hca(controle_dinamico=True), {"potencia_carro_kw": 7}, 30, {}, "s", 0)["controlavel"]


def test_modo_fv_sem_fv_no_condominio_vira_rapido():
    c = hca(modo_carga=1)
    assert demanda.item_de(c, {}, 30, {"fv_potencia_kwp": 0}, "s", 0)["modo"] == 0
    assert demanda.item_de(c, {}, 30, {"fv_potencia_kwp": 10}, "s", 0)["modo"] == 1
    assert demanda.item_de(hca(modo_carga=2), {}, 30, {"fv_potencia_kwp": 10}, "s", 0)["modo"] == 1


def test_admissao_conta_so_a_rede():
    ativos = [carro(0)]
    _, motivo = demanda.avaliar_admissao(2.5, ativos, carro(1))
    assert motivo == "minimo", "2 carros em 2,5 kW ficariam abaixo de 1,4 kW - sol não entra na conta"
    assert demanda.avaliar_admissao(2.5, ativos, carro(1, modo=1)) == (None, None), \
        "modo FV puro não depende da rede"
    _, motivo = demanda.avaliar_admissao(10, [carro(0, controlavel=False)], carro(1, controlavel=False))
    assert motivo == "limite", "duas cargas fixas de 7 kW não cabem em 10 kW"


# ===========================================================================
# 2. Física: mínimo por modelo e disjuntor
# ===========================================================================

def test_minimo_por_modelo():
    assert minimo_kw(hca(7)) == 1.4
    assert minimo_kw(hca(22), {"potencia_carro_kw": 22}) == 4.2
    assert minimo_kw(hca(22), {"potencia_carro_kw": 7}) == 1.4, "carro monofásico num ponto trifásico"
    assert minimo_kw({"perfil": "bancada"}) == 0


def test_disjuntor_so_vale_com_controle_dinamico():
    c = hca(7, controle_dinamico=True, limite_disjuntor_a=16)
    assert potencia_disjuntor_kw(c) == 3.68
    assert abs(teto_kw(c, {"potencia_carro_kw": 7}) - 3.68) < 1e-9
    assert potencia_disjuntor_kw({**c, "controle_dinamico": False}) is None
    assert abs(potencia_disjuntor_kw(hca(22, controle_dinamico=True, limite_disjuntor_a=32)) - 22.17) < 0.01


# ===========================================================================
# 3. Recibo por fonte (puro)
# ===========================================================================

SESSAO = {"energia_entregue_kwh": 10, "energia_solar_kwh": 6, "energia_ponta_kwh": 1.5,
          "tarifa_kwh": 1.15, "multiplicador_ponta": 1.5, "tarifa_solar_kwh": 0.75, "origem_solar": "simulado"}


def test_recibo_tem_uma_linha_por_fonte_e_fecha_o_total():
    d = detalhar_custo(SESSAO)
    assert [(i["origem"], i["faixa"]) for i in d["itens"]] == [
        ("solar_simulado", None), ("rede", "fora_ponta"), ("rede", "ponta")]
    # Cada linha arredonda no centavo; o total é a soma das linhas: 4,50 + 2,88 + 2,59.
    assert [i["subtotal"] for i in d["itens"]] == [4.5, 2.88, 2.59]
    assert d["total"] == round(sum(i["subtotal"] for i in d["itens"]), 2) == 9.97
    assert d["energia_fora_ponta_kwh"] == 2.5
    assert d["total"] == round(d["subtotal_solar"] + d["subtotal_fora_ponta"] + d["subtotal_ponta"], 2)


def test_ponta_nunca_come_energia_solar():
    d = detalhar_custo({**SESSAO, "energia_ponta_kwh": 99})
    assert d["energia_ponta_kwh"] == 4 and d["energia_solar_kwh"] == 6 and d["energia_fora_ponta_kwh"] == 0


def test_sem_solar_o_recibo_e_o_de_antes():
    d = detalhar_custo({"energia_entregue_kwh": 10, "energia_ponta_kwh": 4, "tarifa_kwh": 2.0,
                        "multiplicador_ponta": 1.5})
    assert d["total"] == 24.0 and [i["origem"] for i in d["itens"]] == ["rede", "rede"]


def test_economia_vs_so_rede():
    assert economia_vs_so_rede(SESSAO) == round(6 * (1.15 - 0.75), 2)


# ===========================================================================
# 4. Curva solar simulada (pura)
# ===========================================================================

def test_curva_solar():
    dia = datetime(2026, 10, 7, tzinfo=FUSO)
    assert simulador.potencia_solar_kw(10, dia.replace(hour=3)) == 0
    assert simulador.potencia_solar_kw(10, dia.replace(hour=20)) == 0
    assert abs(simulador.potencia_solar_kw(10, dia.replace(hour=12)) - 7.5) < 1e-9
    total = simulador.energia_solar_kwh(1, dia, dia + timedelta(hours=23, minutes=59))
    assert abs(total - 4.5) < 1e-6, "≈ 4,5 kWh/kWp/dia"
    b1 = simulador.balde_solar(10, dia.replace(hour=11, minute=2))
    b2 = simulador.balde_solar(10, dia.replace(hour=11, minute=4, second=30))
    assert b1 == b2, "reescrever o mesmo balde dá o mesmo valor"
    assert abs(b1["potencia_kw"] - b1["energia_kwh"] * 12) < 1e-3
    assert simulador.balde_solar(10, dia.replace(hour=22)) is None


# ===========================================================================
# 5. Backend com o Supabase falso
# ===========================================================================

def semear(fv=0.0):
    fake.limpar()
    for cid, nome in ((COND, "Solar Teste"), (OUTRO_COND, "Outro")):
        fake.t("condominios").append({
            "id": cid, "nome": nome, "limite_potencia_kw": 10, "ponta_inicio": "18:00", "ponta_fim": "21:00",
            "ponta_fator_limite": 0.6, "ponta_multiplicador_tarifa": 1.5, "custo_energia_kwh": 0.95,
            "custo_energia_ponta_kwh": 1.45, "custo_solar_kwh": 0.35, "preco_solar_kwh": 0.75,
            "fv_potencia_kwp": fv if cid == COND else 0})
    for cid, cond, numero, perfil, nominal in (("k1", COND, "01", "veicular", 7), ("k2", COND, "02", "veicular", 22),
                                               ("kb", COND, "03", "bancada", None),
                                               ("kx", OUTRO_COND, "01", "veicular", 7)):
        fake.t("carregadores").append({
            "id": cid, "condominio_id": cond, "numero": numero, "modelo": f"GoodWe HCA G2 {nominal}kW",
            "perfil": perfil, "origem": "simulado", "status": "disponivel", "potencia_nominal_kw": nominal,
            "potencia_maxima_kw": nominal or 0.025, "tensao_v": 230, "tarifa_kwh": 1.15, "temperatura_c": 25,
            "controle_dinamico": True, "garantir_minimo": False, "limite_disjuntor_a": None, "modo_carga": 0})
    for uid, nome, tipo in (("u-sind", "Sindica Solar", "gestor"), ("u-mor", "Morador Solar", "morador")):
        fake.t("usuarios").append({"id": uid, "nome": nome, "tipo_usuario": tipo, "condominio_id": COND,
                                   "saldo": 0})
        fake.t("credenciais_usuario").append({"usuario_id": uid, "senha_hash": gerar_hash_senha(SENHA)})
    fake.t("veiculos").append({"id": "v1", "usuario_id": "u-mor", "modelo": "BYD Dolphin", "tipo": "carro",
                               "capacidade_bateria_kwh": 50, "potencia_carro_kw": 7})


def entrar(nome):
    r = CLIENTE.post("/login", json={"nome": nome, "senha": SENHA})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def entrar_gestor(nome):
    """O gestor entra pela API ADMINISTRATIVA (ADR-023): outro app, outro token."""
    r = ADMIN.post("/admin/login", json={"nome": nome, "senha": SENHA})
    assert r.status_code == 200 and r.json().get("success"), r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def sessao_ativa(**extra):
    s = fake.nova_linha("sessoes_recarga", {
        "id": "s1", "carregador_id": "k1", "veiculo_id": "v1", "usuario_id": "u-mor", "status": "carregando",
        "percentual_bateria_inicial": 20, "percentual_bateria_atual": 20, "alvo_percentual": 80,
        "tarifa_kwh": 1.15, "multiplicador_ponta": 1.5, "tarifa_solar_kwh": 0.75,
        "valor_pre_autorizado": 100, "iniciado_em": agora().isoformat(), **extra})
    fake.t("sessoes_recarga").append(s)
    return s


def test_excedente_solar_le_so_a_tabela_de_geracao():
    semear(fv=10)
    cond = fake.t("condominios")[0]
    assert demanda.excedente_solar(cond) == (0.0, None), "sem leitura recente = sem sol"
    fake.t("geracao_solar").append({"condominio_id": COND, "momento": (agora() - timedelta(minutes=30)).isoformat(),
                                    "potencia_kw": 9, "energia_kwh": 0.75, "origem": "simulado"})
    assert demanda.excedente_solar(cond) == (0.0, None), "leitura velha não vale"
    fake.t("geracao_solar").append({"condominio_id": COND, "momento": (agora() - timedelta(minutes=2)).isoformat(),
                                    "potencia_kw": 6.5, "energia_kwh": 0.54, "origem": "medido"})
    assert demanda.excedente_solar(cond) == (6.5, "medido")
    assert demanda.excedente_solar({**cond, "fv_potencia_kwp": 0}) == (0.0, None), "FV = 0 desliga tudo"


def test_simulador_grava_balde_e_respeita_leitura_medida():
    semear(fv=10)
    cond = fake.t("condominios")[0]
    meio_dia = datetime(2026, 10, 7, 12, 1, tzinfo=FUSO)
    simulador.gravar_geracao_solar(cond, meio_dia)
    simulador.gravar_geracao_solar(cond, meio_dia + timedelta(minutes=2))
    assert len(fake.t("geracao_solar")) == 1 and fake.t("geracao_solar")[0]["origem"] == "simulado"
    simulador.gravar_geracao_solar({**cond, "fv_potencia_kwp": 0}, meio_dia + timedelta(minutes=5))
    assert len(fake.t("geracao_solar")) == 1, "FV = 0: o simulador não grava nada"


def test_progresso_separa_sol_rede_e_ponta(monkeypatch):
    semear(fv=10)
    s = sessao_ativa()
    cond = fake.t("condominios")[0]
    monkeypatch.setattr(recarga, "em_horario_de_ponta", lambda c, m=None: True)
    recarga.registrar_progresso(s, {"capacidade_bateria_kwh": 50}, cond, 2.0, 7, 30, 60,
                                fracao_solar=0.25, origem_solar="simulado")
    linha = next(x for x in fake.t("sessoes_recarga") if x["id"] == "s1")
    assert linha["energia_solar_kwh"] == 0.5 and linha["energia_ponta_kwh"] == 1.5
    assert linha["origem_solar"] == "simulado"
    hora = fake.t("consumo_horario")[0]
    assert hora["energia_kwh"] == 2.0 and hora["energia_solar_kwh"] == 0.5 and hora["energia_ponta_kwh"] == 1.5


def test_alocador_grava_a_parcela_solar_da_sessao():
    semear(fv=10)
    sessao_ativa(potencia_alocada_kw=None)
    fake.t("geracao_solar").append({"condominio_id": COND, "momento": agora().isoformat(),
                                    "potencia_kw": 3.0, "energia_kwh": 0.25, "origem": "simulado"})
    estado = demanda.alocar(COND)
    s = next(x for x in fake.t("sessoes_recarga") if x["id"] == "s1")
    assert s["potencia_alocada_solar_kw"] == 3.0 and estado["origem_solar"] == "solar_simulado"
    assert estado["solar_absorvido_kw"] == 3.0 and estado["fv_ativo"]


def test_api_modbus_do_gestor():
    semear(fv=0)
    g = entrar_gestor("Sindica Solar")
    r = ADMIN.get("/gestor/carregadores/k1/modbus", headers=g)
    assert r.status_code == 200 and [x["registrador"] for x in r.json()["registradores"]] == \
        [10024, 10025, 10026, 10029, 10032]
    assert "simulados" in r.json()["aviso"]

    patch = lambda cid, corpo: ADMIN.patch(f"/gestor/carregadores/{cid}/modbus", json=corpo, headers=g)  # noqa: E731
    assert patch("k1", {"potencia_maxima_kw": 9}).status_code == 422, "7 kW: 10029 vai até 7"
    assert patch("k1", {"potencia_maxima_kw": 1.2}).status_code == 422
    assert patch("k2", {"potencia_maxima_kw": 3}).status_code == 422, "22 kW: mínimo 4,2"
    assert patch("k2", {"potencia_maxima_kw": 11}).status_code == 200
    assert patch("k1", {"modo_carga": 2}).status_code == 422, "sem bateria modelada"
    assert patch("k1", {"modo_carga": 1}).status_code == 422, "modo FV sem FV"
    assert patch("kb", {"controle_dinamico": False}).status_code == 409, "bancada não é HCA G2"
    assert patch("kx", {"controle_dinamico": False}).status_code == 404, "carregador de outro condomínio"
    assert patch("k1", {"controle_dinamico": None}).status_code == 422

    assert ADMIN.patch("/gestor/condominio", json={"fv_potencia_kwp": 10}, headers=g).status_code == 200
    r = patch("k1", {"modo_carga": 1, "garantir_minimo": True, "limite_disjuntor_a": 16})
    assert r.status_code == 200, r.text
    assert r.json()["carregador"]["registradores"][2]["equivale_kw"] == 3.68
    assert patch("k1", {"limite_disjuntor_a": None}).status_code == 200
    assert next(c for c in fake.t("carregadores") if c["id"] == "k1")["limite_disjuntor_a"] is None

    assert ADMIN.patch("/gestor/condominio", json={"fv_potencia_kwp": 0}, headers=g).status_code == 200
    r = ADMIN.get("/gestor/carregadores/k1/modbus", headers=g).json()
    assert r["efeito"]["modo_efetivo"] == "Rápido" and "Sem FV" in r["efeito"]["observacao"]
    morador = entrar("Morador Solar")
    # Morador: na API administrativa o token dele não vale (401), e na API
    # pública a rota nem existe (404).
    assert ADMIN.get("/gestor/carregadores", headers=morador).status_code == 401
    assert CLIENTE.get("/gestor/carregadores", headers=morador).status_code == 404


def test_gestor_muda_preco_da_rede_e_premissas_solares():
    semear()
    g = entrar_gestor("Sindica Solar")
    r = ADMIN.patch("/gestor/condominio", json={"tarifa_rede_kwh": 1.3, "preco_solar_kwh": 0.8,
                                                   "custo_solar_kwh": 0.3}, headers=g)
    assert r.status_code == 200
    assert {c["tarifa_kwh"] for c in fake.t("carregadores") if c["condominio_id"] == COND} == {1.3}
    assert next(c for c in fake.t("carregadores") if c["id"] == "kx")["tarifa_kwh"] == 1.15
    assert fake.t("condominios")[0]["preco_solar_kwh"] == 0.8


def test_painel_separa_fontes_e_extrato_mostra_a_origem():
    semear(fv=10)
    fake.t("sessoes_recarga").append(fake.nova_linha("sessoes_recarga", {
        "id": "sf", "carregador_id": "k1", "veiculo_id": "v1", "usuario_id": "u-mor", "status": "finalizada",
        **SESSAO, "custo_final": detalhar_custo(SESSAO)["total"], "valor_estornado": 0}))
    fake.t("movimentacoes_carteira").append(fake.nova_linha("movimentacoes_carteira", {
        "usuario_id": "u-mor", "sessao_id": "sf", "tipo": "pre_autorizacao", "valor": 9.96,
        "saldo_apos": 0, "descricao": "Reserva"}))
    fake.t("geracao_solar").append({"condominio_id": COND, "momento": agora().isoformat(),
                                    "potencia_kw": 7, "energia_kwh": 8.0, "origem": "simulado"})
    fake.rpc("registrar_consumo", {"p_cond": COND, "p_kwh": 10, "p_ponta": False, "p_carga_kw": 7,
                                   "p_demanda_kw": 9, "p_solar_kwh": 6, "p_rede_kw": 3}).execute()

    p = ADMIN.get("/gestor/painel", headers=entrar_gestor("Sindica Solar")).json()
    mes = p["energia"]["mes"]
    assert [(l["origem"], l["faixa"]) for l in mes["linhas"]] == [
        ("rede", "fora_ponta"), ("rede", "ponta"), ("solar_simulado", None)]
    assert mes["total"]["receita"] == p["valor"]["receita_mes"] == detalhar_custo(SESSAO)["total"] == 9.97
    assert mes["total"]["custo"] == round(2.5 * 0.95 + 1.5 * 1.45 + 6 * 0.35, 2) == p["valor"]["custo_energia_mes"]
    assert mes["economia_vs_so_rede"] == {"morador": 2.4, "condominio": 3.6, "origem": "estimado"}
    assert mes["solar"]["gerado_kwh"] == 8.0 and mes["solar"]["absorvido_kwh"] == 6.0
    assert mes["pico"]["evitado_pela_gestao_kw"] == 2 and mes["pico"]["coberto_pelo_sol_kw"] == 4
    assert p["energia"]["incentivo_solar"]["alinhado"] is True
    assert p["carregadores"][0]["modbus"]["controle_dinamico"] is True

    ext = CLIENTE.get("/me/extrato", headers=entrar("Morador Solar")).json()
    assert ext["movimentos"][0]["energia_por_fonte"][0]["origem"] == "solar_simulado"


def test_incentivo_invertido_aparece_no_painel():
    semear()
    for c in fake.t("carregadores"):
        c["tarifa_kwh"] = 2.10
    inc = ADMIN.get("/gestor/painel", headers=entrar_gestor("Sindica Solar")).json()["energia"]["incentivo_solar"]
    assert inc["alinhado"] is False and inc["alerta"]


# ===========================================================================
# 6. Cenários do critério de pronto
# ===========================================================================

@pytest.fixture(scope="module")
def cenarios():
    return cenarios_demanda.todos()


def test_cenarios_concluem_e_recibos_fecham(cenarios):
    for r in cenarios.values():
        assert r["concluidas"] == 3, r["codigo"]
        for c in r["carros"]:
            d = c["detalhe"]
            assert d["total"] == round(sum(i["subtotal"] for i in d["itens"]), 2)
            assert abs(d["energia_kwh"] - sum(i["energia_kwh"] for i in d["itens"])) < 1e-5


def test_cenario_a_x_b_controle_dinamico(cenarios):
    a, b = cenarios["A"], cenarios["B"]
    assert a["min_estouro"] > 0 and a["estouro_max_kw"] > 0, "sem 10025 a ponta estoura o quadro"
    assert b["min_estouro"] == 0 and b["pico_rede_kw"] <= 10 + 1e-6
    assert b["ultimo_fim"] < a["ultimo_fim"], "com controle dinâmico, as 3 terminam antes"
    assert a["carros"][1]["espera_min"] > 0 and b["carros"][1]["espera_min"] == 0


def test_cenarios_com_sol(cenarios):
    c, d = cenarios["C"], cenarios["D"]
    assert c["pico_rede_kw"] <= 3 * 1.4 + 1e-6, "modo FV + 10024: a rede só completa o mínimo"
    assert d["ultimo_fim"].hour < 18, "modo rápido com sol termina antes da ponta"
    for r in (c, d):
        assert r["solar_absorvido_kwh"] > 0 and r["economia_morador"] > 0
        assert all(x["detalhe"]["itens"][0]["origem"] == "solar_simulado" for x in r["carros"])
    assert c["margem"] > cenarios["B"]["margem"], "com o incentivo alinhado, o sol aumenta a margem"


def test_ciclo_do_simulador_ao_meio_dia(monkeypatch):
    """Integração: o ciclo grava o sol, o alocador lê da tabela e a sessão recebe kWh solar."""
    semear(fv=10)
    sessao_ativa(potencia_alocada_kw=None)
    meio_dia = datetime(2026, 10, 7, 12, 0, tzinfo=FUSO)
    monkeypatch.setattr(simulador, "agora", lambda: meio_dia)
    monkeypatch.setattr(demanda, "agora", lambda: meio_dia)
    monkeypatch.setattr(simulador, "_horas_decorridas", lambda: 10 / 3600)
    simulador.ciclo()
    s = next(x for x in fake.t("sessoes_recarga") if x["id"] == "s1")
    assert len(fake.t("geracao_solar")) == 1
    assert s["potencia_alocada_solar_kw"] == 7.0, "7,5 kW de sol, carro de 7 kW: tudo do sol"
    assert s["energia_solar_kwh"] > 0 and abs(s["energia_solar_kwh"] - s["energia_entregue_kwh"]) < 1e-6
    hora = fake.t("consumo_horario")
    assert any(h["pico_kw"] == 7 and h["pico_rede_kw"] == 0 for h in hora), hora
