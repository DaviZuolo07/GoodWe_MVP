"""
test_next_sem_sensor.py - Totem Next de 22/10: sem INA219, sem solar, painel seguro.
===================================================================================

O que estes testes seguram:
  - porta de relé com o 10025 ligado é DIVIDIDA pelo water-filling (por tempo)
    e a fração vai para a placa, junto com o modelo de carga do celular;
  - a previsão de término usa a fração (vaga a 50% demora o dobro);
  - toda recarga ganha série (db/23) - a do totem rotulada 'simulado';
  - o % lido do celular ancora o modelo, só para a própria recarga;
  - operador entra pelo Google só depois de aprovado, preso ao condomínio, e
    com o segundo fator obrigatório; revogado, perde o acesso na hora;
  - o admin vê qualquer sessão; o operador, só as do condomínio dele (404);
  - provisionar admin-global: só nome, senha gerada, não recria/promove conta.

Rodar (de dentro de backend/):  python -m pytest testes/test_next_sem_sensor.py -q
"""

import ambiente                                    # precisa vir primeiro

fake = ambiente.usar_supabase_falso()

import sys                                         # noqa: E402

import pytest                                      # noqa: E402
from fastapi.testclient import TestClient          # noqa: E402

import demanda                                     # noqa: E402
import main                                        # noqa: E402
import main_admin                                  # noqa: E402
import preparar_totem                              # noqa: E402
import provisionar                                 # noqa: E402
import rotas_operadores                            # noqa: E402
import seguranca                                   # noqa: E402
import serie                                       # noqa: E402
from placa_v2 import PlacaV2                       # noqa: E402
from seguranca import codigo_totp, emitir_token, emitir_token_admin  # noqa: E402

APP = TestClient(main.app)
ADMIN = TestClient(main_admin.app)
ESTANDE = preparar_totem.ESTANDE
OUTRO = "c0000000-0000-0000-0000-0000000000aa"


def _preparar(monkeypatch, tmp_path, vagas: int = 4):
    """
    Prepara o estande com `vagas` vagas. O padrão do script é 2 (a montagem de
    24/10); estes testes pedem 4 de propósito, para o totem de quatro vagas
    continuar coberto. Uma e duas vagas têm testes próprios mais abaixo.
    """
    fake.limpar()
    monkeypatch.setattr(provisionar, "_supabase", lambda: fake)
    monkeypatch.setattr(preparar_totem, "ENV_TOTEM", tmp_path / ".env")
    monkeypatch.setattr(sys, "argv", ["preparar_totem.py", "--next", "--vagas", str(vagas)])
    preparar_totem.main()
    linhas = (tmp_path / ".env").read_text(encoding="utf-8").splitlines()
    return dict(x.split("=", 1) for x in linhas if "=" in x and not x.startswith("#"))


def _admin_global():
    fake.t("usuarios").append({"id": "u-davi", "nome": "Davi Admin", "tipo_usuario": "gestor",
                               "condominio_id": OUTRO, "saldo": 0})
    fake.t("admins_globais").append({"usuario_id": "u-davi"})
    return {"Authorization": f"Bearer {emitir_token_admin('u-davi', mfa=True)['token']}"}


@pytest.fixture(autouse=True)
def zerar():
    for lim in (seguranca.limitador_admin_nome, seguranca.limitador_admin_ip, rotas_operadores.limitador_google):
        lim._falhas.clear()
    serie._ultimo_envio.clear()
    yield


# --- 1. Water-filling por tempo ---------------------------------------------------

def porta(**extra):
    return {"id": "k", "origem": "hardware", "perfil": "bancada", "potencia_maxima_kw": 7.5,
            "controle_dinamico": True, **extra}


def test_porta_de_rele_com_10025_e_dividida_por_tempo():
    cel = {"potencia_carro_kw": 7.5, "capacidade_bateria_kwh": 15}
    itens = [demanda.item_de(porta(), cel, 30, {}, f"s{i}", i, medida_kw=7.5 if i % 2 else 0.0)
             for i in range(4)]
    assert all(it["controlavel"] and it["demanda_kw"] == 7.5 for it in itens), \
        "a medida que oscila 0/7,5 com o relé ciclando NÃO é a demanda"
    r = demanda.distribuir_fontes(22.5, 0.0, itens)
    fracoes = [demanda.fracao_de_tempo(r["itens"][f"s{i}"]["alocado_kw"], 7.5) for i in range(4)]
    assert fracoes == [0.75] * 4, "4 celulares, quadro para 3: 75% do tempo para cada um"
    assert r["rede_kw"] == 22.5 and r["estouro_kw"] == 0
    # Com o 10025 desligado, a mesma porta volta a ser carga fixa (só admissão).
    assert not demanda.item_de(porta(controle_dinamico=False), cel, 30, {}, "x", 0)["controlavel"]
    assert demanda.fracao_de_tempo(None, 7.5) == 1.0 and demanda.fracao_de_tempo(3, 0) == 1.0


def test_fatia_pequena_demais_pausa_a_ultima_e_a_nova_vai_para_a_fila():
    cel = {"potencia_carro_kw": 7.5}
    itens = [demanda.item_de(porta(), cel, 30, {}, f"s{i}", i) for i in range(4)]
    assert all(it["minimo_kw"] == 1.5 for it in itens), "20% de 7,5 kW"
    # 5 kW para 4 celulares = 1,25 cada, abaixo do mínimo: a última pausa, 3 ficam com 1,67.
    r = demanda.distribuir_fontes(5.0, 0.0, itens)
    assert r["itens"]["s3"]["pausado_motivo"] == demanda.PAUSA_LIMITE and r["itens"]["s3"]["alocado_kw"] == 0
    assert all(abs(r["itens"][f"s{i}"]["alocado_kw"] - 5 / 3) < 1e-3 for i in range(3))
    # Admissão: com 3 já dividindo 4 kW, uma quarta não cabe -> fila de energia.
    recebe, motivo = demanda.avaliar_admissao(4.0, itens[:3], itens[3])
    assert (recebe, motivo) == (None, "minimo")
    assert demanda.avaliar_admissao(22.5, itens[:3], itens[3])[1] is None


def test_na_ponta_o_limite_cai_e_a_fracao_acompanha():
    cond = {"limite_potencia_kw": 30, "ponta_inicio": "00:00", "ponta_fim": "23:59",
            "ponta_fator_limite": 0.5}
    from datetime import datetime
    from config import FUSO
    segunda = datetime(2026, 10, 19, 12, 0, tzinfo=FUSO)
    assert demanda.limite_efetivo(cond, segunda) == (15.0, True)
    cel = {"potencia_carro_kw": 7.5}
    itens = [demanda.item_de(porta(), cel, 30, {}, f"s{i}", i) for i in range(4)]
    r = demanda.distribuir_fontes(15.0, 0.0, itens)
    assert {round(x["alocado_kw"], 3) for x in r["itens"].values()} == {3.75}


# --- 2. Placa: fração, modelo de carga, série, previsão ---------------------------

def test_totem_next_recebe_fracao_e_modelo_e_grava_serie(monkeypatch, tmp_path):
    env = _preparar(monkeypatch, tmp_path)
    d = fake.t("dispositivos")[0]
    assert d["porta_solar"] is None and d["virtual"] is True
    assert all(c["controle_dinamico"] is True and not c["garantir_minimo"] for c in fake.t("carregadores"))
    assert next(c for c in fake.t("condominios") if c["id"] == ESTANDE)["fv_potencia_kwp"] == 0

    placa = PlacaV2(APP, env["DEVICE_ID"], env["DEVICE_KEY_HEX"])
    hs = placa.handshake().json()
    assert hs["porta_solar"] is None
    r1 = placa.rfid(1, env["TAG_A"]).json()
    assert (r1["acao"], r1["fracao"]) == ("ligar", 1.0)
    assert r1["carga"]["capacidade_wh"] == 15.0 and r1["carga"]["potencia_max_w"] == 7.5
    assert placa.rfid(2, env["TAG_B"]).json()["acao"] == "ligar"

    # O gestor baixa o quadro para UM celular cheio: as duas vagas ficam com 50%.
    next(c for c in fake.t("condominios") if c["id"] == ESTANDE)["limite_potencia_kw"] = 7.5
    demanda.alocar(ESTANDE)
    t = placa.millis() + 1000

    def lote(e1, e2):
        return placa.chamar("POST", "/telemetria", {"t_envio_ms": t, "leituras": [
            {"porta": 1, "t_ms": t, "potencia_w": 7.5, "energia_wh": e1, "rele_ligado": True},
            {"porta": 2, "t_ms": t, "potencia_w": 0.0, "energia_wh": e2, "rele_ligado": False}]}).json()

    resp = lote(0.5, 0.4)
    p1, p2 = resp["portas"]
    assert p1["fracao"] == 0.5 and p2["fracao"] == 0.5, resp
    assert p1["deve_liberar"] and p2["deve_liberar"], "relé aberto pela divisão não encerra nada"
    # Previsão: 50% do tempo a 7,5 W = 3,75 W na janela.
    s1 = next(s for s in fake.t("sessoes_recarga") if s["carregador_id"] == preparar_totem.VAGAS[1])
    falta_kwh = 15 * (s1["alvo_percentual"] - p1["percentual"]) / 100 / 0.92
    assert abs(p1["tempo_restante_min"] - falta_kwh / 3.75 * 60) <= 1
    serie_1 = [x for x in fake.t("leituras_sessao") if x["sessao_id"] == s1["id"]]
    assert serie_1 and serie_1[-1]["origem"] == "simulado"


def _preparar_padrao(monkeypatch, tmp_path, *extra):
    fake.limpar()
    monkeypatch.setattr(provisionar, "_supabase", lambda: fake)
    monkeypatch.setattr(preparar_totem, "ENV_TOTEM", tmp_path / ".env")
    monkeypatch.setattr(sys, "argv", ["preparar_totem.py", "--next", *extra])
    preparar_totem.main()
    return dict(x.split("=", 1) for x in (tmp_path / ".env").read_text(encoding="utf-8").splitlines()
                if "=" in x and not x.startswith("#"))


def test_duas_vagas_e_o_padrao_e_os_numeros_do_roteiro(monkeypatch, tmp_path):
    """
    A montagem de 24/10: DUAS vagas, cada relé libera energia de verdade.
    `preparar_totem.py --next` sem `--vagas` já vem assim. Os números aqui são
    os que o roteiro da banca (docs/RODAR_NO_NOTEBOOK.md, seção 9) promete.
    """
    env = _preparar_padrao(monkeypatch, tmp_path)                              # sem --vagas
    assert [c["numero"] for c in fake.t("carregadores")] == ["T1", "T2"]
    assert [p["numero"] for p in fake.t("portas_dispositivo")] == [1, 2]
    estande = next(c for c in fake.t("condominios") if c["id"] == ESTANDE)
    assert estande["limite_potencia_kw"] == 15.0, "o quadro comporta as duas vagas cheias"

    placa = PlacaV2(APP, env["DEVICE_ID"], env["DEVICE_KEY_HEX"])
    hs = placa.handshake().json()
    assert [p["porta"] for p in hs["portas"]] == [1, 2], "o firmware compara este número com PORTAS = 2"
    assert placa.rfid(3, env["TAG_A"]).status_code == 422, "vaga que não existe é recusada"

    assert (placa.rfid(1, env["TAG_A"]).json()["acao"], 1) == ("ligar", 1)
    r2 = placa.rfid(2, env["TAG_B"]).json()
    assert (r2["acao"], r2["fracao"]) == ("ligar", 1.0), "15 kW: as duas cheias, relés fechados direto"

    def fracoes(limite_kw):
        estande["limite_potencia_kw"] = limite_kw
        demanda.alocar(ESTANDE)
        t = placa.millis() + 1000
        resp = placa.chamar("POST", "/telemetria", {"t_envio_ms": t, "leituras": [
            {"porta": p, "t_ms": t, "potencia_w": 7.5, "energia_wh": 0.5, "rele_ligado": True}
            for p in (1, 2)]}).json()
        return [(x["fracao"], x["estado"], x["deve_liberar"]) for x in resp["portas"]]

    assert fracoes(7.5) == [(0.5, "carregando", True)] * 2, "metade do quadro: 50% para cada, revezando"
    assert [f for f, *_ in fracoes(5.0)] == [0.3333] * 2
    assert [f for f, *_ in fracoes(3.0)] == [0.2] * 2, "o mínimo da vaga: 20% de 7,5 kW"
    (f1, e1, _), (f2, e2, l2) = fracoes(2.5)
    assert (f1, e1) == (0.3333, "carregando"), "a primeira a chegar fica com o quadro todo"
    # A segunda fica abaixo do mínimo: fração 0 (relé aberto a janela toda),
    # sessão viva e saldo reservado - não encerra; volta quando houver quadro.
    assert (f2, l2) == (0.0, True), "a segunda pausa (abaixo do mínimo), sem encerrar"
    assert fracoes(15.0) == [(1.0, "carregando", True)] * 2, "quadro cheio de novo: as duas voltam"

    # Pico: o painel liga a ponta (vale no sábado: o estande é bancada) e o limite cai à metade.
    from fisica import em_horario_de_ponta
    estande.update(ponta_inicio="00:00", ponta_fim="23:59")
    assert em_horario_de_ponta(estande) and demanda.limite_efetivo(estande)[0] == 7.5
    assert [f for f, *_ in fracoes(15.0)] == [0.5, 0.5], "pico: 15 -> 7,5 kW, os relés revezam"


def test_uma_vaga_continua_funcionando_e_o_estande_inteiro_cabe_nela(monkeypatch, tmp_path):
    """A montagem de 23/10: UMA vaga (`--vagas 1`)."""
    env = _preparar_padrao(monkeypatch, tmp_path, "--vagas", "1")

    assert [c["numero"] for c in fake.t("carregadores")] == ["T1"], "só a vaga 1 existe"
    assert [p["numero"] for p in fake.t("portas_dispositivo")] == [1]
    estande = next(c for c in fake.t("condominios") if c["id"] == ESTANDE)
    assert estande["limite_potencia_kw"] == 7.5, "o quadro comporta a vaga cheia"

    # O handshake diz UMA porta: é este número que o firmware compara com o PORTAS.
    placa = PlacaV2(APP, env["DEVICE_ID"], env["DEVICE_KEY_HEX"])
    hs = placa.handshake().json()
    assert len(hs["portas"]) == 1 and hs["portas"][0]["porta"] == 1
    assert placa.rfid(2, env["TAG_B"]).status_code == 422, "vaga que não existe é recusada"

    r = placa.rfid(1, env["TAG_A"]).json()
    assert (r["acao"], r["fracao"]) == ("ligar", 1.0), "sozinha no quadro: relé fechado direto"

    # O gestor baixa o quadro ao vivo: a MESMA vaga passa a ficar metade do
    # tempo com o relé fechado (water-filling de um ponto só).
    def fracao_com(limite_kw):
        estande["limite_potencia_kw"] = limite_kw
        demanda.alocar(ESTANDE)
        t = placa.millis() + 1000
        resp = placa.chamar("POST", "/telemetria", {"t_envio_ms": t, "leituras": [
            {"porta": 1, "t_ms": t, "potencia_w": 7.5, "energia_wh": 0.5, "rele_ligado": True}]}).json()
        return resp["portas"][0]

    assert fracao_com(3.75)["fracao"] == 0.5
    assert fracao_com(1.5)["fracao"] == 0.2, "o mínimo da vaga: 20% de 7,5 kW"
    sem_potencia = fracao_com(0.0)
    assert sem_potencia["estado"] == "pausada" or sem_potencia["fracao"] == 0.0

    # Quadro cheio de novo e a recarga volta: nada foi encerrado no caminho.
    assert fracao_com(7.5)["deve_liberar"] is True


def test_diminuir_as_vagas_apaga_as_que_sobraram(monkeypatch, tmp_path):
    """Quem já rodou com 4 e passa para 1 não pode ficar com vaga sem relé."""
    _preparar(monkeypatch, tmp_path, vagas=4)
    assert len(fake.t("carregadores")) == 4 and len(fake.t("portas_dispositivo")) == 4

    monkeypatch.setattr(sys, "argv", ["preparar_totem.py", "--next", "--vagas", "1"])
    preparar_totem.main()                                   # sem limpar o banco
    assert [c["numero"] for c in fake.t("carregadores")] == ["T1"]
    assert [p["numero"] for p in fake.t("portas_dispositivo")] == [1]
    assert next(c for c in fake.t("condominios") if c["id"] == ESTANDE)["limite_potencia_kw"] == 7.5


def test_sem_next_a_vaga_solar_exige_quatro(monkeypatch, tmp_path):
    fake.limpar()
    monkeypatch.setattr(provisionar, "_supabase", lambda: fake)
    monkeypatch.setattr(preparar_totem, "ENV_TOTEM", tmp_path / ".env")
    monkeypatch.setattr(sys, "argv", ["preparar_totem.py", "--vagas", "1"])
    with pytest.raises(SystemExit):
        preparar_totem.main()


def test_serie_e_percentual_do_celular_so_para_o_dono(monkeypatch, tmp_path):
    env = _preparar(monkeypatch, tmp_path)
    placa = PlacaV2(APP, env["DEVICE_ID"], env["DEVICE_KEY_HEX"])
    placa.handshake()
    placa.rfid(1, env["TAG_A"])
    t = placa.millis() + 1000
    placa.chamar("POST", "/telemetria", {"t_envio_ms": t, "leituras": [
        {"porta": 1, "t_ms": t, "potencia_w": 7.5, "energia_wh": 1.0, "rele_ligado": True}]})
    s = fake.t("sessoes_recarga")[-1]
    ana = {"Authorization": f"Bearer {emitir_token(s['usuario_id'])['token']}"}
    bia_id = next(u["id"] for u in fake.t("usuarios") if u["nome"] == "Bia Totem")
    bia = {"Authorization": f"Bearer {emitir_token(bia_id)['token']}"}

    r = APP.get(f"/recargas/{s['id']}/serie", headers=ana).json()
    assert r["fator_escala"] == 1000 and r["pontos"] and r["origem"] == "simulado"
    assert APP.get(f"/recargas/{s['id']}/serie", headers=bia).status_code == 404

    atual = float(s["percentual_bateria_atual"])
    assert APP.post(f"/recargas/{s['id']}/bateria", json={"percentual": 99}, headers=ana).json()["aceito"] is False
    serie._ultimo_envio.clear()
    r = APP.post(f"/recargas/{s['id']}/bateria", json={"percentual": atual + 10}, headers=ana).json()
    assert r["aceito"] is True
    s = fake.t("sessoes_recarga")[-1]
    assert s["percentual_origem"] == "celular" and s["percentual_bateria_atual"] == round(atual + 10, 1)
    assert APP.post(f"/recargas/{s['id']}/bateria", json={"percentual": 50}, headers=bia).status_code == 404


# --- 3. Operadores pelo Google ------------------------------------------------------

def _google(monkeypatch, sub="g-123", email="op@condominio.com"):
    monkeypatch.setattr(rotas_operadores, "verificar_google",
                        lambda credencial: {"sub": sub, "email": email, "nome": "Olga Operadora"})


def test_operador_pede_e_so_entra_depois_de_aprovado_com_mfa(monkeypatch, tmp_path):
    _preparar(monkeypatch, tmp_path)
    fake.t("condominios").append({"id": OUTRO, "nome": "Residencial Outro", "endereco": "Rua 2"})
    davi = _admin_global()
    _google(monkeypatch)
    cred = {"credencial": "x" * 40}

    r = ADMIN.post("/admin/google", json=cred).json()
    assert r["precisa_condominio"] and any(c["id"] == ESTANDE for c in r["condominios"])
    r = ADMIN.post("/admin/google", json={**cred, "condominio_id": ESTANDE}).json()
    assert r == {"success": False, "pedido": "pendente", "email": "op@condominio.com"}
    assert not [u for u in fake.t("usuarios") if u.get("papel") == "Operador"], "pedido não cria conta"
    assert ADMIN.post("/admin/google", json=cred).json()["pedido"] == "pendente"

    pedido = fake.t("operadores_google")[0]
    gestor_comum = {"Authorization": f"Bearer {emitir_token_admin('u-davi-x', mfa=True)['token']}"}
    assert ADMIN.post(f"/admin/operadores/{pedido['id']}/aprovar", headers=gestor_comum).status_code in (401, 403)
    assert ADMIN.post(f"/admin/operadores/{pedido['id']}/aprovar", headers=davi).status_code == 200
    op = next(u for u in fake.t("usuarios") if u.get("papel") == "Operador")
    assert op["condominio_id"] == ESTANDE and op["tipo_usuario"] == "gestor"
    assert not [c for c in fake.t("credenciais_usuario") if c["usuario_id"] == op["id"]], "sem senha"

    # Primeiro acesso: token que só cadastra o autenticador.
    r = ADMIN.post("/admin/google", json=cred).json()
    assert r["success"] and r["mfa_cadastro_necessario"] and r["global"] is False
    tok = {"Authorization": f"Bearer {r['token']}"}
    assert ADMIN.get("/gestor/sessoes", headers=tok).status_code == 403
    segredo = ADMIN.post("/admin/mfa/iniciar", headers=tok).json()["segredo"]
    r = ADMIN.post("/admin/mfa/confirmar", json={"codigo": codigo_totp(segredo)}, headers=tok).json()
    assert r["mfa"] is True and r["global"] is False
    op_tok = {"Authorization": f"Bearer {r['token']}"}
    assert ADMIN.get("/gestor/sessoes", headers=op_tok).status_code == 200
    assert ADMIN.get("/gestor/geral/resumo", headers=op_tok).status_code == 403
    assert ADMIN.get("/admin/operadores", headers=op_tok).status_code == 403

    # Daqui em diante, Google + código.
    fake.t("gestor_mfa")[0]["ultimo_passo"] -= 2
    assert ADMIN.post("/admin/google", json=cred).json() == {"success": False, "mfa_necessario": True}
    assert ADMIN.post("/admin/google", json={**cred, "codigo": "000000"}).status_code == 401
    assert ADMIN.post("/admin/google", json={**cred, "codigo": codigo_totp(segredo)}).json()["mfa"] is True

    # Revogado: o token aberto morre na chamada seguinte.
    assert ADMIN.post(f"/admin/operadores/{pedido['id']}/revogar", headers=davi).status_code == 200
    assert ADMIN.get("/gestor/sessoes", headers=op_tok).status_code == 403
    assert ADMIN.post("/admin/google", json=cred).status_code == 403


def test_operador_recusado_nao_entra(monkeypatch, tmp_path):
    _preparar(monkeypatch, tmp_path)
    davi = _admin_global()
    _google(monkeypatch, sub="g-999", email="curioso@x.com")
    ADMIN.post("/admin/google", json={"credencial": "y" * 40, "condominio_id": ESTANDE})
    pid = fake.t("operadores_google")[0]["id"]
    assert ADMIN.post(f"/admin/operadores/{pid}/recusar", headers=davi).status_code == 200
    assert ADMIN.post("/admin/google", json={"credencial": "y" * 40}).status_code == 403


def test_google_sem_client_id_nao_abre_nada(monkeypatch):
    monkeypatch.setattr(rotas_operadores, "GOOGLE_CLIENT_ID", "")
    assert ADMIN.post("/admin/google", json={"credencial": "z" * 40}).status_code == 503


# --- 4. Sessões e Sala Next ---------------------------------------------------------

def test_admin_ve_tudo_e_operador_so_o_proprio_condominio(monkeypatch, tmp_path):
    env = _preparar(monkeypatch, tmp_path)
    davi = _admin_global()
    placa = PlacaV2(APP, env["DEVICE_ID"], env["DEVICE_KEY_HEX"])
    placa.handshake()
    placa.rfid(1, env["TAG_A"])
    sid = fake.t("sessoes_recarga")[-1]["id"]

    lista = ADMIN.get("/gestor/sessoes", headers=davi).json()
    assert [x["id"] for x in lista] == [sid] and lista[0]["local"] == "Estande Next (totem)"
    det = ADMIN.get(f"/gestor/sessoes/{sid}", headers=davi).json()
    assert det["usuario"]["nome"] == "Ana Totem" and det["local"]["id"] == ESTANDE
    assert det["fonte_dos_dados"]["tipo"] == "modelo" and det["carregador"]["divisao_por_tempo"] is True
    assert det["carregador"]["temperatura_c"] is None and det["energia"]["fator_escala"] == 1000

    # Operador de OUTRO condomínio: a sessão "não existe".
    fake.t("usuarios").append({"id": "u-op2", "nome": "Op Outro", "tipo_usuario": "gestor",
                               "condominio_id": OUTRO, "saldo": 0})
    op = {"Authorization": f"Bearer {emitir_token_admin('u-op2', mfa=True)['token']}"}
    assert ADMIN.get("/gestor/sessoes", headers=op).json() == []
    assert ADMIN.get(f"/gestor/sessoes/{sid}", headers=op).status_code == 404
    assert ADMIN.get("/gestor/next", headers=op).status_code == 404

    sala = ADMIN.get("/gestor/next", headers=davi).json()
    assert sala["totais"]["cadastros"] == 3 and sala["totais"]["ativas"] == 1
    assert {v["numero"] for v in sala["vagas"]} == {"T1", "T2", "T3", "T4"}
    ana = next(c for c in sala["cadastros"] if c["nome"] == "Ana Totem")
    assert ana["celulares"][0]["bateria_wh"] == 15.0 and ana["tags"] == 1

    # Demanda do estande pela Sala Next (o admin tem OUTRO condomínio-base).
    r = ADMIN.patch("/gestor/next/demanda", json={"limite_potencia_kw": 22.5}, headers=davi).json()
    assert r["limite_kw"] == 22.5
    r = ADMIN.patch("/gestor/next/demanda", json={"pico": "pico_agora"}, headers=davi).json()
    # O estande é bancada: o pico do painel vale em qualquer dia (o Next é num sábado).
    assert r["em_ponta"] is True and r["limite_kw"] == 11.25, "ponta = metade de 22,5"
    assert ADMIN.patch("/gestor/next/demanda", json={"pico": "sem_pico"}, headers=davi).json()["em_ponta"] is False
    assert ADMIN.patch("/gestor/next/demanda", json={"limite_potencia_kw": 1}, headers=op).status_code == 404

    # Divisão por tempo: o gestor desliga e liga a 10025 de uma porta do totem.
    cid = preparar_totem.VAGAS[2]
    assert ADMIN.patch(f"/gestor/carregadores/{cid}/divisao", json={"ligada": False}, headers=davi).status_code == 200
    assert next(c for c in fake.t("carregadores") if c["id"] == cid)["controle_dinamico"] is False
    assert ADMIN.patch(f"/gestor/carregadores/{cid}/divisao", json={"ligada": True}, headers=op).status_code == 404


# --- 5. provisionar admin-global --------------------------------------------------

def test_admin_global_so_nome_senha_gerada_e_nao_recria(monkeypatch, capsys):
    fake.limpar()
    monkeypatch.setattr(provisionar, "_supabase", lambda: fake)
    monkeypatch.setattr(sys, "argv", ["provisionar.py", "admin-global", "--nome", "Davi Admin"])
    provisionar.main()
    saida = capsys.readouterr().out
    senha = saida.split("guarde no gerenciador de senhas):")[1].split()[0]
    u = fake.t("usuarios")[0]
    assert u["tipo_usuario"] == "gestor" and fake.t("admins_globais")[0]["usuario_id"] == u["id"]
    assert seguranca.conferir_senha(fake.t("credenciais_usuario")[0]["senha_hash"], senha)

    # Rodar de novo NÃO troca a senha (não há como gerar senha para conta existente).
    hash_antes = fake.t("credenciais_usuario")[0]["senha_hash"]
    with pytest.raises(SystemExit):
        provisionar.main()
    assert fake.t("credenciais_usuario")[0]["senha_hash"] == hash_antes

    for proibido in (["admin-global", "--nome", "X Y", "--senha", "Qualquer#2026"], ["senha-gestor", "--nome", "X"]):
        monkeypatch.setattr(sys, "argv", ["provisionar.py", *proibido])
        with pytest.raises(SystemExit):
            provisionar.main()

    # Com a senha gerada, o painel abre SÓ o cadastro do autenticador.
    r = ADMIN.post("/admin/login", json={"nome": "Davi Admin", "senha": senha}).json()
    assert r["success"] and r["mfa"] is False and r["global"] is False
    tok = {"Authorization": f"Bearer {r['token']}"}
    assert ADMIN.get("/gestor/geral/resumo", headers=tok).status_code == 403


def test_senhas_demo_nao_toca_conta_de_gestor(monkeypatch):
    fake.limpar()
    monkeypatch.setattr(provisionar, "_supabase", lambda: fake)
    fake.t("usuarios").extend([{"id": "g", "nome": "Sindico", "tipo_usuario": "gestor"},
                               {"id": "m", "nome": "Morador", "tipo_usuario": "morador"}])
    monkeypatch.setattr(sys, "argv", ["provisionar.py", "senhas-demo", "--senha", "DemoForte#2026"])
    provisionar.main()
    assert [c["usuario_id"] for c in fake.t("credenciais_usuario")] == ["m"]


def test_duas_vagas_fila_de_energia_e_volta_sozinha(monkeypatch, tmp_path):
    """Roteiro da banca: quadro de 2,5 kW com a vaga 1 carregando -> a tag na vaga 2 vai para a fila."""
    env = _preparar_padrao(monkeypatch, tmp_path)
    estande = next(c for c in fake.t("condominios") if c["id"] == ESTANDE)
    estande["limite_potencia_kw"] = 2.5
    placa = PlacaV2(APP, env["DEVICE_ID"], env["DEVICE_KEY_HEX"])
    placa.handshake()
    r1 = placa.rfid(1, env["TAG_A"]).json()
    assert (r1["acao"], r1["fracao"]) == ("ligar", 0.3333), "sozinha: 2,5 de 7,5 kW = 33% do tempo"
    r2 = placa.rfid(2, env["TAG_B"]).json()
    assert (r2["acao"], r2["motivo"], r2["fila_posicao"]) == ("nenhuma", "aguardando_energia", 1),         "1,25 kW cada < 1,5 kW: fila, com o saldo já reservado"
    assert r2["tela"][:3] == ["Vaga 2 na espera", "Sem energia agora", "Fila: 1"]
    s2 = next(s for s in fake.t("sessoes_recarga") if s["carregador_id"] == preparar_totem.VAGAS[2])
    assert s2["status"] == "aguardando_energia"

    # O laço de 10 s do simulador (dentro do uvicorn) promove a fila.
    estande["limite_potencia_kw"] = 15.0
    import recarga
    assert recarga.promover_aguardando_energia(ESTANDE) == 1
    s2 = next(s for s in fake.t("sessoes_recarga") if s["carregador_id"] == preparar_totem.VAGAS[2])
    assert s2["status"] == "carregando", "sobrou quadro: a fila liga sozinha"
    assert any(c["porta"] == 2 and c["acao"] == "liberar" for c in fake.t("comandos_dispositivo")),         "a placa recebe o liberar da vaga 2 pelo GET /comandos"
