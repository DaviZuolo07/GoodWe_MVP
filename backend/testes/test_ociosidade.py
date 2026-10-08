"""
test_ociosidade.py - Taxa de ociosidade dos pontos simulados (db/21).
=====================================================================

O que estes testes seguram:
  - recarga simulada que termina sozinha deixa a vaga OCUPADA (carro plugado);
  - encerrar pelo app libera na hora, e ponto físico (totem) nunca entra na regra;
  - tolerância sem custo, depois R$/min por minuto começado, parando no teto;
  - "Já retirei o carro" debita a taxa UMA vez, libera o ponto e o extrato fecha;
  - sem saldo, cobra o que houver e registra o resto como pendente;
  - o laço do simulador avisa quando a tolerância acaba e libera depois de 6 h.

Rodar (de dentro de backend/):  python -m pytest testes/test_ociosidade.py -q
"""

import ambiente                                    # precisa vir primeiro
fake = ambiente.usar_supabase_falso()

from datetime import timedelta                     # noqa: E402

import pytest                                      # noqa: E402
from fastapi.testclient import TestClient          # noqa: E402

import main                                        # noqa: E402
import recarga                                     # noqa: E402
from config import agora                           # noqa: E402
from seguranca import emitir_token                 # noqa: E402

APP = TestClient(main.app)
COND = "c-ocio"


@pytest.fixture(autouse=True)
def banco(monkeypatch):
    fake.limpar()
    monkeypatch.setattr(recarga, "_ociosidade_no_banco", True)
    fake.t("condominios").append({
        "id": COND, "nome": "Residencial Ocioso", "limite_potencia_kw": 20, "ponta_inicio": "18:00",
        "ponta_fim": "21:00", "ponta_fator_limite": 0.6, "ponta_multiplicador_tarifa": 1.5,
        "fv_potencia_kwp": 0, "tolerancia_ociosidade_min": 15, "taxa_ociosidade_min": 0.50,
        "teto_ociosidade": 60.00})
    for cid, origem in (("k-sim", "simulado"), ("k-hw", "hardware")):
        fake.t("carregadores").append({
            "id": cid, "condominio_id": COND, "numero": "01" if origem == "simulado" else "02",
            "origem": origem, "perfil": "veicular", "status": "em_uso", "potencia_maxima_kw": 7,
            "potencia_nominal_kw": 7, "tensao_v": 230, "tarifa_kwh": 1.15, "temperatura_c": 25})
    fake.t("usuarios").append({"id": "u1", "nome": "Ana", "tipo_usuario": "morador",
                               "condominio_id": COND, "saldo": 100})
    fake.t("movimentacoes_carteira").append(fake.nova_linha("movimentacoes_carteira", {
        "usuario_id": "u1", "tipo": "credito", "valor": 100, "saldo_apos": 100, "descricao": "abertura"}))
    fake.t("veiculos").append({"id": "v1", "usuario_id": "u1", "modelo": "BYD Dolphin", "tipo": "carro",
                               "capacidade_bateria_kwh": 50, "potencia_carro_kw": 7})
    yield


def cab():
    return {"Authorization": f"Bearer {emitir_token('u1')['token']}"}


def carregando(carregador="k-sim"):
    s = fake.nova_linha("sessoes_recarga", {
        "id": "s1", "carregador_id": carregador, "veiculo_id": "v1", "usuario_id": "u1",
        "status": "carregando", "percentual_bateria_inicial": 20, "percentual_bateria_atual": 80,
        "alvo_percentual": 80, "energia_entregue_kwh": 0, "tarifa_kwh": 1.15,
        "multiplicador_ponta": 1.5, "valor_pre_autorizado": 0, "iniciado_em": agora().isoformat()})
    fake.t("sessoes_recarga").append(s)
    return s


def ociosa(minutos_atras, saldo=None):
    """Recarga já terminada, carro na vaga há `minutos_atras` minutos."""
    if saldo is not None:
        fake.t("usuarios")[0]["saldo"] = saldo
        fake.t("movimentacoes_carteira")[0].update(valor=saldo, saldo_apos=saldo)
    s = carregando()
    s.update(status="finalizada", vaga_ocupada_desde=(agora() - timedelta(minutes=minutos_atras)).isoformat(),
             taxa_ociosidade=0)
    return s


def charger(cid):
    return next(c for c in fake.t("carregadores") if c["id"] == cid)


# --- quando a vaga fica ocupada ---------------------------------------------

def test_recarga_simulada_que_termina_sozinha_deixa_a_vaga_ocupada():
    recarga.encerrar(carregando(), "alvo_atingido")
    s = fake.t("sessoes_recarga")[0]
    assert s["status"] == "finalizada" and s["vaga_ocupada_desde"]
    assert charger("k-sim")["status"] == "em_uso", "o carro continua plugado"
    assert any("Retire o carro" in n["mensagem"] for n in fake.t("notificacoes"))


def test_encerrar_pelo_app_libera_na_hora():
    recarga.encerrar(carregando(), "usuario")
    assert not fake.t("sessoes_recarga")[0].get("vaga_ocupada_desde")
    assert charger("k-sim")["status"] == "disponivel"


def test_ponto_fisico_nao_entra_na_regra():
    recarga.encerrar(carregando("k-hw"), "bateria_cheia")
    assert not fake.t("sessoes_recarga")[0].get("vaga_ocupada_desde")


# --- a conta -----------------------------------------------------------------

@pytest.mark.parametrize("minutos, esperado", [
    (10, 0.0),          # dentro da tolerância
    (15, 0.0),          # exatamente no fim da tolerância
    (15.2, 0.50),       # minuto começado conta inteiro
    (25, 5.00),         # 10 min x R$ 0,50
    (500, 60.00),       # parou no teto
])
def test_tolerancia_taxa_por_minuto_e_teto(minutos, esperado):
    cond = fake.t("condominios")[0]
    desde = agora() - timedelta(minutes=minutos)
    conta = recarga.calcular_ociosidade({"vaga_ocupada_desde": desde.isoformat()}, cond,
                                        ate=desde + timedelta(minutes=minutos))
    assert conta["valor"] == esperado


def test_politica_vem_do_condominio():
    cond = {**fake.t("condominios")[0], "tolerancia_ociosidade_min": 0, "taxa_ociosidade_min": 1.0}
    desde = agora()
    conta = recarga.calcular_ociosidade({"vaga_ocupada_desde": desde.isoformat()}, cond,
                                        ate=desde + timedelta(minutes=3))
    assert conta["valor"] == 3.0


# --- liberar a vaga ------------------------------------------------------------

def test_ja_retirei_o_carro_cobra_uma_vez_e_libera():
    ociosa(24.5)                                      # 10 min cobrados
    vaga = APP.get("/recargas/vaga-ocupada", headers=cab()).json()["vaga"]
    assert vaga["sessao_id"] == "s1" and vaga["valor"] == 5.0

    r = APP.post("/recargas/s1/liberar-vaga", headers=cab()).json()
    assert r["cobrado"] == 5.0 and r["pendente"] == 0
    assert fake.t("usuarios")[0]["saldo"] == 95.0
    assert charger("k-sim")["status"] == "disponivel"
    assert fake.conferir_carteira() == [], "saldo = soma do extrato"

    de_novo = APP.post("/recargas/s1/liberar-vaga", headers=cab()).json()
    assert de_novo.get("ja_liberada") and fake.t("usuarios")[0]["saldo"] == 95.0
    assert APP.get("/recargas/vaga-ocupada", headers=cab()).json()["vaga"] is None


def test_dentro_da_tolerancia_sai_de_graca():
    ociosa(5)
    r = APP.post("/recargas/s1/liberar-vaga", headers=cab()).json()
    assert r["taxa"] == 0 and fake.t("usuarios")[0]["saldo"] == 100


def test_sem_saldo_cobra_o_que_tem_e_registra_pendente():
    ociosa(34.5, saldo=4)                             # 20 min cobrados = R$ 10,00; saldo R$ 4,00
    r = APP.post("/recargas/s1/liberar-vaga", headers=cab()).json()
    assert (r["taxa"], r["cobrado"], r["pendente"]) == (10.0, 4.0, 6.0)
    assert fake.t("usuarios")[0]["saldo"] == 0
    assert fake.conferir_carteira() == []


def test_outra_pessoa_nao_libera_a_vaga():
    ociosa(24.5)                                      # 10 min cobrados
    fake.t("usuarios").append({"id": "u2", "nome": "Bia", "tipo_usuario": "morador",
                               "condominio_id": COND, "saldo": 0})
    outro = {"Authorization": f"Bearer {emitir_token('u2')['token']}"}
    assert APP.post("/recargas/s1/liberar-vaga", headers=outro).status_code in (403, 404)
    assert charger("k-sim")["status"] == "em_uso"


# --- laço do simulador -----------------------------------------------------------

def test_laco_avisa_fim_da_tolerancia_uma_vez():
    ociosa(16)
    recarga.atualizar_ociosas()
    recarga.atualizar_ociosas()
    avisos = [n for n in fake.t("notificacoes") if "tolerância" in n["mensagem"]]
    assert len(avisos) == 1
    assert fake.t("sessoes_recarga")[0]["taxa_ociosidade"] == 1.0


def test_laco_libera_carro_esquecido_depois_de_6h():
    ociosa(6 * 60 + 1)
    recarga.atualizar_ociosas()
    assert fake.t("sessoes_recarga")[0]["vaga_liberada_em"]
    assert charger("k-sim")["status"] == "disponivel"
    assert fake.t("usuarios")[0]["saldo"] == 40.0, "teto de R$ 60"
