"""
test_visao_geral.py - Visão geral do painel e chamados do Suporte (db/20).
=========================================================================

O que estes testes seguram:
  - só gestor que está em `admins_globais` entra na Visão geral;
  - gestor comum e token de morador são recusados;
  - morador abre chamado, vê só os dele, e tem limite de chamados em aberto;
  - responder chamado grava a resposta e avisa o morador no sino;
  - notificação em massa respeita o destino e nunca vai para gestor;
  - /condominios devolve coordenadas e o login do admin diz se é global.

Rodar (de dentro de backend/):  python -m pytest testes/test_visao_geral.py -q
"""

import ambiente                                    # precisa vir primeiro
import os
import uuid

os.environ.setdefault("ADMIN_MFA_KEY", "chave-de-teste-com-mais-de-32-caracteres-ok")
fake = ambiente.usar_supabase_falso()

import pytest                                      # noqa: E402
from fastapi.testclient import TestClient          # noqa: E402

import main                                        # noqa: E402
import main_admin                                  # noqa: E402
import rotas_suporte                               # noqa: E402
import seguranca                                   # noqa: E402
from seguranca import emitir_token, emitir_token_admin, gerar_hash_senha  # noqa: E402

APP = TestClient(main.app)
ADMIN = TestClient(main_admin.app)
SENHA = "senha-de-teste-123"
C1, C2 = "c-um", "c-dois"


@pytest.fixture(autouse=True)
def banco():
    fake.limpar()
    for lim in (seguranca.limitador_admin_nome, seguranca.limitador_admin_ip):
        lim._falhas.clear()
    fake.t("condominios").extend([
        {"id": C1, "nome": "Residencial Um", "endereco": "Rua 1", "perfil": "residencial",
         "latitude": -23.5, "longitude": -46.7},
        {"id": C2, "nome": "Estande", "endereco": "FIAP", "perfil": "bancada",
         "latitude": None, "longitude": None}])
    fake.t("carregadores").append({"id": "ch-1", "numero": 1, "condominio_id": C1, "status": "disponivel"})
    for uid, nome, tipo, cond in (("u-admin", "Admin Global", "gestor", C1),
                                  ("u-gestor", "Gestor Comum", "gestor", C1),
                                  ("u-ana", "Ana", "morador", C1),
                                  ("u-bia", "Bia", "visitante", C2)):
        fake.t("usuarios").append({"id": uid, "nome": nome, "tipo_usuario": tipo,
                                   "condominio_id": cond, "saldo": 10})
        fake.t("credenciais_usuario").append({"usuario_id": uid, "senha_hash": gerar_hash_senha(SENHA)})
    fake.t("admins_globais").append({"id": "x", "usuario_id": "u-admin"})
    yield


def cab_admin(uid):
    return {"Authorization": f"Bearer {emitir_token_admin(uid, mfa=True)['token']}"}


def cab_app(uid):
    return {"Authorization": f"Bearer {emitir_token(uid)['token']}"}


# --- acesso -----------------------------------------------------------------

def test_so_admin_global_entra_na_visao_geral():
    assert ADMIN.get("/gestor/geral/resumo", headers=cab_admin("u-admin")).status_code == 200
    assert ADMIN.get("/gestor/geral/resumo", headers=cab_admin("u-gestor")).status_code == 403
    # token de morador não vale na API administrativa
    assert ADMIN.get("/gestor/geral/resumo", headers=cab_app("u-ana")).status_code == 401
    # e a rota nem existe na API pública
    assert APP.get("/gestor/geral/resumo", headers=cab_app("u-ana")).status_code == 404


def test_sem_tabela_admins_globais_ninguem_e_global(monkeypatch):
    import rotas_geral

    def quebra(*_a, **_k):
        raise RuntimeError("relation admins_globais does not exist")
    monkeypatch.setattr(rotas_geral.supabase, "table",
                        lambda nome, _orig=rotas_geral.supabase.table:
                        quebra() if nome == "admins_globais" else _orig(nome))
    assert ADMIN.get("/gestor/geral/resumo", headers=cab_admin("u-admin")).status_code == 403


def test_login_do_admin_diz_se_e_global():
    r = ADMIN.post("/admin/login", json={"nome": "Admin Global", "senha": SENHA}).json()
    assert r["success"] and r["global"] is True
    r = ADMIN.post("/admin/login", json={"nome": "Gestor Comum", "senha": SENHA}).json()
    assert r["success"] and r["global"] is False


def test_resumo_e_listas_cobrem_todos_os_locais():
    fake.t("sessoes_recarga").append({"id": "s1", "usuario_id": "u-ana", "carregador_id": "ch-1",
                                      "status": "finalizada", "energia_entregue_kwh": 5,
                                      "custo_final": 7.5, "criado_em": "2999-01-01T10:00:00+00:00"})
    fake.t("movimentacoes_carteira").append({"id": "m1", "usuario_id": "u-bia", "tipo": "credito",
                                             "valor": 50, "saldo_apos": 60,
                                             "criado_em": "2999-01-01T10:00:00+00:00"})
    h = cab_admin("u-admin")
    r = ADMIN.get("/gestor/geral/resumo", headers=h).json()
    assert r["total"]["usuarios"] == 4
    assert r["total"]["faturamento_mes"] == 7.5
    assert {l["nome"] for l in r["por_local"]} == {"Residencial Um", "Estande"}
    nomes = {u["nome"] for u in ADMIN.get("/gestor/geral/usuarios", headers=h).json()}
    assert nomes == {"Admin Global", "Gestor Comum", "Ana", "Bia"}
    assert ADMIN.get("/gestor/geral/pagamentos", headers=h).json()[0]["usuario"] == "Bia"
    rec = ADMIN.get("/gestor/geral/recargas", headers=h).json()[0]
    assert rec["usuario"] == "Ana" and rec["local"] == "Residencial Um" and rec["carregador_numero"] == 1


# --- chamados ----------------------------------------------------------------

def test_morador_abre_e_ve_so_os_proprios_chamados():
    r = APP.post("/me/chamados", headers=cab_app("u-ana"),
                 json={"assunto": "Carregador 2", "mensagem": "Não liberou com o cartão."})
    assert r.status_code == 200 and r.json()["chamado"]["status"] == "aberto"
    APP.post("/me/chamados", headers=cab_app("u-bia"), json={"assunto": "Saldo", "mensagem": "Não entrou o crédito."})
    meus = APP.get("/me/chamados", headers=cab_app("u-ana")).json()
    assert [c["assunto"] for c in meus] == ["Carregador 2"]
    assert APP.get("/me/chamados").status_code == 401


def test_limite_de_chamados_em_aberto():
    for i in range(rotas_suporte.MAX_ABERTOS):
        assert APP.post("/me/chamados", headers=cab_app("u-ana"),
                        json={"assunto": f"Dúvida {i}", "mensagem": "Texto da dúvida."}).status_code == 200
    r = APP.post("/me/chamados", headers=cab_app("u-ana"), json={"assunto": "Mais uma", "mensagem": "Texto."})
    assert r.status_code == 429


def test_responder_chamado_avisa_o_morador():
    cid = str(uuid.uuid4())
    fake.t("chamados").append({"id": cid, "usuario_id": "u-ana", "condominio_id": C1,
                               "assunto": "Carregador 2", "mensagem": "Não liberou.", "status": "aberto"})
    h = cab_admin("u-admin")
    lista = ADMIN.get("/gestor/geral/chamados", headers=h).json()
    assert lista[0]["usuario"] == "Ana" and lista[0]["local"] == "Residencial Um"
    r = ADMIN.patch(f"/gestor/geral/chamados/{cid}", headers=h, json={"resposta": "Já reiniciamos o leitor."})
    assert r.status_code == 200
    c = fake.t("chamados")[0]
    assert c["status"] == "resolvido" and c["respondido_por"] == "u-admin"
    assert any(n["usuario_id"] == "u-ana" and "respondido" in n["mensagem"] for n in fake.t("notificacoes"))
    # gestor comum não responde
    assert ADMIN.patch(f"/gestor/geral/chamados/{cid}", headers=cab_admin("u-gestor"),
                       json={"status": "aberto"}).status_code == 403
    assert ADMIN.patch("/gestor/geral/chamados/nao-e-uuid", headers=h,
                       json={"status": "aberto"}).status_code == 404


# --- notificações ------------------------------------------------------------

def test_notificacao_respeita_destino_e_pula_gestor():
    h = cab_admin("u-admin")
    r = ADMIN.post("/gestor/geral/notificacoes", headers=h, json={"mensagem": "Manutenção amanhã.", "destino": "todos"})
    assert r.json()["enviadas"] == 2                       # Ana e Bia; gestores não
    fake.t("notificacoes").clear()
    r = ADMIN.post("/gestor/geral/notificacoes", headers=h,
                   json={"mensagem": "Só no Um.", "destino": "local", "condominio_id": C1})
    assert r.json()["enviadas"] == 1 and fake.t("notificacoes")[0]["usuario_id"] == "u-ana"
    assert ADMIN.post("/gestor/geral/notificacoes", headers=h,
                      json={"mensagem": "Sem local.", "destino": "local"}).status_code == 422


# --- mapa --------------------------------------------------------------------

def test_condominios_traz_coordenadas():
    locais = {c["nome"]: c for c in APP.get("/condominios").json()}
    assert locais["Residencial Um"]["latitude"] == -23.5
    assert locais["Estande"]["latitude"] is None
