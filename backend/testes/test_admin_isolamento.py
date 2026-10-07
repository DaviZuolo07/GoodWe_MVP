"""
test_admin_isolamento.py - O painel do gestor é OUTRA aplicação (ADR-023).
=========================================================================

O que estes testes seguram:
  - a API pública não tem nenhuma rota de gestor/admin;
  - o token de um lado não vale do outro;
  - conta de morador não entra no painel, conta de gestor não entra no app;
  - segundo fator: cadastro, exigência, código de uso único, modo obrigatório;
  - auditoria de acesso e de alteração;
  - CORS, cabeçalhos, /docs em produção, IP atrás de proxy, código de convite.

Rodar (de dentro de backend/):  python -m pytest testes/test_admin_isolamento.py -q
"""

import ambiente                                    # precisa vir primeiro
import os

os.environ.setdefault("ADMIN_MFA_KEY", "chave-de-teste-com-mais-de-32-caracteres-ok")
fake = ambiente.usar_supabase_falso()

import pytest                                      # noqa: E402
from fastapi import FastAPI                        # noqa: E402
from fastapi.testclient import TestClient          # noqa: E402

import endurecimento                               # noqa: E402
import main                                        # noqa: E402
import main_admin                                  # noqa: E402
import rotas_admin                                 # noqa: E402
import rotas_conta                                 # noqa: E402
import seguranca                                   # noqa: E402
from seguranca import (codigo_totp, emitir_token, emitir_token_admin,  # noqa: E402
                       gerar_hash_senha)

CLIENTE = TestClient(main.app)
ADMIN = TestClient(main_admin.app)
SENHA = "senha-de-teste-123"
COND = "c-admin"


def _zerar_limitadores():
    for lim in (seguranca.limitador_admin_nome, seguranca.limitador_admin_ip,
                seguranca.limitador_por_nome, seguranca.limitador_por_ip,
                seguranca.limitador_cadastro):
        lim._falhas.clear()


@pytest.fixture(autouse=True)
def banco():
    fake.limpar()
    _zerar_limitadores()
    fake.t("condominios").append({"id": COND, "nome": "Residencial Teste", "endereco": "Rua 1",
                                  "limite_potencia_kw": 30})
    for uid, nome, tipo in (("u-g", "Gestora Teste", "gestor"), ("u-m", "Morador Teste", "morador")):
        fake.t("usuarios").append({"id": uid, "nome": nome, "tipo_usuario": tipo,
                                   "condominio_id": COND, "saldo": 0})
        fake.t("credenciais_usuario").append({"usuario_id": uid, "senha_hash": gerar_hash_senha(SENHA)})
    yield
    _zerar_limitadores()      # os outros arquivos de teste rodam no mesmo processo


def cab(token):
    return {"Authorization": f"Bearer {token}"}


def login_admin(codigo=None, nome="Gestora Teste", senha=SENHA):
    corpo = {"nome": nome, "senha": senha}
    if codigo:
        corpo["codigo"] = codigo
    return ADMIN.post("/admin/login", json=corpo)


# --- 1. Rotas ---------------------------------------------------------------

def test_api_publica_nao_tem_rota_de_gestor_nem_de_admin():
    caminhos = set(main.app.openapi()["paths"])
    proibidos = [c for c in caminhos if c.startswith(("/gestor", "/admin"))
                 or c.startswith(("/hardware/status", "/hardware/ping"))]
    assert proibidos == []
    for caminho in ("/gestor/painel", "/admin/login", "/admin/me", "/hardware/status/x"):
        assert CLIENTE.get(caminho).status_code in (404, 405)
    assert CLIENTE.post("/admin/login", json={"nome": "Gestora Teste", "senha": SENHA}).status_code == 404


def test_api_administrativa_nao_tem_rota_de_morador_nem_de_totem():
    caminhos = set(main_admin.app.openapi()["paths"])
    assert not [c for c in caminhos if c.startswith(("/me", "/login", "/cadastro", "/recargas",
                                                     "/chatbot", "/hardware/v2", "/debug"))]


# --- 2. Tokens ----------------------------------------------------------------

def test_token_de_um_lado_nao_vale_do_outro():
    morador = emitir_token("u-m")["token"]
    gestor_no_app = emitir_token("u-g")["token"]          # gestor com token de MORADOR
    admin = emitir_token_admin("u-g", mfa=False)["token"]
    assert ADMIN.get("/gestor/painel", headers=cab(morador)).status_code == 401
    assert ADMIN.get("/gestor/painel", headers=cab(gestor_no_app)).status_code == 401
    assert ADMIN.get("/admin/me", headers=cab(admin)).status_code == 200
    assert CLIENTE.get("/me", headers=cab(admin)).status_code == 401
    assert ADMIN.get("/admin/me").status_code == 401


def test_token_admin_de_quem_deixou_de_ser_gestor_para_de_valer():
    token = login_admin().json()["token"]
    assert ADMIN.get("/admin/me", headers=cab(token)).status_code == 200
    next(u for u in fake.t("usuarios") if u["id"] == "u-g")["tipo_usuario"] = "morador"
    assert ADMIN.get("/admin/me", headers=cab(token)).status_code == 403


def test_token_admin_forjado_para_morador_e_recusado_pelo_banco():
    # Mesmo que alguém emitisse um token administrativo para um morador, o
    # papel é relido do banco.
    assert ADMIN.get("/gestor/painel", headers=cab(emitir_token_admin("u-m", True)["token"])).status_code == 403


# --- 3. Login -------------------------------------------------------------------

def test_morador_nao_entra_no_painel_e_gestor_nao_entra_no_app():
    r = login_admin(nome="Morador Teste")
    assert r.status_code == 401 and r.json()["detail"] == "Credenciais inválidas."
    assert login_admin(senha="errada-errada").json()["detail"] == "Credenciais inválidas."
    assert login_admin(nome="Ninguem Aqui").json()["detail"] == "Credenciais inválidas."
    assert CLIENTE.post("/login", json={"nome": "Gestora Teste", "senha": SENHA}).status_code == 401
    assert CLIENTE.post("/login", json={"nome": "Morador Teste", "senha": SENHA}).status_code == 200


def test_login_admin_trava_depois_de_cinco_erros():
    for _ in range(5):
        assert login_admin(senha="errada-errada").status_code == 401
    assert login_admin().status_code == 429          # nem a senha certa passa


# --- 4. Segundo fator ------------------------------------------------------------

def _cadastrar_mfa():
    token = login_admin().json()["token"]
    r = ADMIN.post("/admin/mfa/iniciar", headers=cab(token))
    assert r.status_code == 200 and r.json()["uri"].startswith("otpauth://totp/")
    segredo = r.json()["segredo"]
    guardado = fake.t("gestor_mfa")[0]["segredo_cifrado"]
    assert segredo not in guardado, "o segredo vai CIFRADO para o banco"
    assert ADMIN.post("/admin/mfa/confirmar", json={"codigo": "000000"}, headers=cab(token)).status_code == 400
    r = ADMIN.post("/admin/mfa/confirmar", json={"codigo": codigo_totp(segredo)}, headers=cab(token))
    assert r.status_code == 200 and r.json()["mfa"] is True
    return segredo


def test_mfa_cadastro_exigencia_e_codigo_de_uso_unico():
    segredo = _cadastrar_mfa()
    # Agora a senha sozinha não basta.
    r = login_admin()
    assert r.status_code == 200 and r.json() == {"success": False, "mfa_necessario": True}
    assert login_admin(codigo="123456").status_code == 401
    # O código usado na confirmação já foi queimado.
    assert login_admin(codigo=codigo_totp(segredo)).status_code == 401
    seguranca.limitador_admin_nome._falhas.clear()
    # "30 s depois": o passo gravado fica para trás e o código atual volta a ser novo.
    fake.t("gestor_mfa")[0]["ultimo_passo"] -= 2
    bom = codigo_totp(segredo)
    r = login_admin(codigo=bom)
    assert r.status_code == 200 and r.json()["mfa"] is True
    assert ADMIN.get("/admin/me", headers=cab(r.json()["token"])).json()["mfa"] is True
    assert login_admin(codigo=bom).status_code == 401, "o mesmo código não vale duas vezes"
    # Com MFA ativo, não se troca o segredo só com o token.
    assert ADMIN.post("/admin/mfa/iniciar", headers=cab(r.json()["token"])).status_code == 409


def test_mfa_obrigatorio_recusa_gestor_sem_cadastro(monkeypatch):
    monkeypatch.setattr(rotas_admin, "ADMIN_MFA_OBRIGATORIO", True)
    r = login_admin()
    assert r.status_code == 403 and "gestor-mfa" in r.json()["detail"]


# --- 5. Auditoria ------------------------------------------------------------------

def test_auditoria_registra_acesso_recusa_e_alteracao():
    login_admin(senha="errada-errada")
    token = login_admin().json()["token"]
    assert ADMIN.patch("/gestor/condominio", json={"limite_potencia_kw": 25},
                       headers=cab(token)).status_code == 200
    ADMIN.post("/gestor/simular-demanda", json={"carros": 3}, headers=cab(token))
    acoes = [(a["acao"], a.get("detalhe")) for a in fake.t("auditoria_admin")]
    assert ("login_recusado", "senha: Gestora Teste") in acoes
    assert ("login", "sem_mfa") in acoes
    assert ("alteracao", "PATCH /gestor/condominio") in acoes
    assert not any("simular" in (d or "") for _, d in acoes), "simulação não altera nada"
    r = ADMIN.get("/admin/auditoria", headers=cab(token))
    assert r.status_code == 200 and len(r.json()["eventos"]) >= 2


# --- 6. Borda: CORS, cabeçalhos, /docs, proxy, convite ---------------------------------

def _preflight(cliente, origem, caminho):
    return cliente.options(caminho, headers={"Origin": origem, "Access-Control-Request-Method": "GET"})


def test_cors_cada_api_so_aceita_a_origem_do_seu_app():
    morador, painel = "http://localhost:5173", "http://localhost:5174"
    assert _preflight(CLIENTE, morador, "/me").headers.get("access-control-allow-origin") == morador
    assert "access-control-allow-origin" not in _preflight(CLIENTE, painel, "/me").headers
    assert _preflight(ADMIN, painel, "/admin/me").headers.get("access-control-allow-origin") == painel
    assert "access-control-allow-origin" not in _preflight(ADMIN, morador, "/admin/me").headers
    assert "access-control-allow-origin" not in _preflight(ADMIN, "https://qualquer.exemplo", "/admin/me").headers


def test_cabecalhos_de_seguranca_nas_duas_apis():
    for cliente in (CLIENTE, ADMIN):
        h = cliente.get("/").headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
        assert h["cache-control"] == "no-store" and "frame-ancestors 'none'" in h["content-security-policy"]


def test_producao_desliga_docs_e_liga_hsts(monkeypatch):
    monkeypatch.setattr(endurecimento, "PRODUCAO", True)
    app = FastAPI(**endurecimento.opcoes_fastapi())
    endurecimento.aplicar(app)
    c = TestClient(app)
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
    assert "max-age" in c.get("/").headers["strict-transport-security"]


class _Req:
    def __init__(self, direto, xff=None):
        self.client = type("C", (), {"host": direto})()
        self.headers = {"x-forwarded-for": xff} if xff else {}


def test_ip_real_atras_de_proxy_nao_aceita_cabecalho_forjado():
    ip = seguranca.ip_do_cliente
    assert ip(_Req("10.0.0.1", "1.2.3.4"), proxies=0) == "10.0.0.1", "sem proxy, o cabeçalho é ignorado"
    assert ip(_Req("10.0.0.1", "203.0.113.7"), proxies=1) == "203.0.113.7"
    # O cliente escreveu "9.9.9.9" por conta própria; o proxy acrescentou o IP real no fim.
    assert ip(_Req("10.0.0.1", "9.9.9.9, 203.0.113.7"), proxies=1) == "203.0.113.7"
    assert ip(_Req("10.0.0.1"), proxies=1) == "10.0.0.1"


def test_codigo_de_convite_no_cadastro(monkeypatch):
    corpo = {"nome": "Visitante Next", "senha": SENHA, "veiculo_modelo": "BYD Dolphin"}
    assert CLIENTE.get("/config-publica").json() == {"cadastro_exige_codigo": False}
    monkeypatch.setattr(rotas_conta, "CODIGO_CADASTRO", "NEXT2026")
    assert CLIENTE.get("/config-publica").json() == {"cadastro_exige_codigo": True}
    assert CLIENTE.post("/cadastro", json=corpo).status_code == 403
    assert CLIENTE.post("/cadastro", json={**corpo, "codigo_convite": "errado"}).status_code == 403
    # Com o código certo passa da checagem (o resto do cadastro é coberto em test_protocolo_v2).
    assert CLIENTE.post("/cadastro", json={**corpo, "codigo_convite": "NEXT2026"}).status_code != 403
