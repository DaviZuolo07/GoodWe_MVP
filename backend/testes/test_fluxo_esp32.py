"""
test_fluxo_esp32.py - O fluxo inteiro, sem banco e sem placa.
=============================================================

Roda contra o app real do FastAPI, com um Supabase falso em memória
(supabase_falso.py). Cobre exatamente a sequência que a banca vai ver:

  login -> preparar -> ESP32 recebe `solicitar_cartao` -> cartão de outro
  morador (recusado) -> cartão certo sem saldo (espera continua) -> morador
  adiciona saldo no app -> cartão de novo (aprovado, valor reservado) ->
  `liberar` -> telemetria medindo energia -> alvo atingido -> encerramento
  com estorno -> extrato e recibo.

E as travas de segurança do Bloco 2: ninguém encerra, cancela nem cobra a
recarga de outro.

Rodar:  python testes/test_fluxo_esp32.py
"""

import ambiente                                    # precisa vir primeiro

fake = ambiente.usar_supabase_falso()

from fastapi.testclient import TestClient          # noqa: E402

import main                                        # noqa: E402
from seguranca import gerar_hash_senha, hash_token_dispositivo  # noqa: E402

CLIENTE = TestClient(main.app)
TOKEN_ESP = "gw_dev_token_de_teste"
COND = "c0000000-0000-0000-0000-000000000002"
PONTO = "b0000000-0000-0000-0000-000000000001"
CARTAO_BANCADA = "A1B2C3D4"      # compartilhado: serve para todo mundo
CARTAO_PESSOAL = "FFFF0001"      # pessoal do "Outro Morador"
SENHA = "SenhaDemo#2026"

ok_total = falhas = 0


def checar(condicao, descricao, extra=""):
    global ok_total, falhas
    ok_total += bool(condicao)
    falhas += not condicao
    print(f"  {'PASSOU' if condicao else 'FALHOU'}  {descricao}{'' if condicao else f'  <- {extra}'}")


def semear():
    fake.t("condominios").append({
        "id": COND, "nome": "Portal dos Bandeirantes", "endereco": "Av. Teste, 1",
        "limite_potencia_kw": 60, "ponta_inicio": "18:00", "ponta_fim": "21:00",
        "ponta_fator_limite": 0.6, "ponta_multiplicador_tarifa": 1.5})
    fake.t("carregadores").append({
        "id": PONTO, "condominio_id": COND, "numero": "01", "modelo": "Bancada USB · ESP32",
        "tipo": "DC", "potencia_maxima_kw": 0.025, "conector": "USB", "tensao_v": 5,
        "corrente_maxima_a": 3, "tarifa_kwh": 1.95, "status": "disponivel",
        "origem": "hardware", "perfil": "bancada", "temperatura_c": 26})
    fake.t("dispositivos").append({
        "id": "d1", "carregador_id": PONTO, "nome": "ESP32 bancada",
        "token_hash": hash_token_dispositivo(TOKEN_ESP), "online": False,
        "intervalo_telemetria_s": 2, "intervalo_comandos_s": 2})

    for uid, nome, saldo in [("u-gus", "Gus Bancada", 0.0), ("u-outro", "Outro Morador", 50.0)]:
        fake.t("usuarios").append({"id": uid, "nome": nome, "tipo_usuario": "morador",
                                   "condominio_id": COND, "bloco_apto": "A1", "saldo": saldo})
        fake.t("credenciais_usuario").append({"usuario_id": uid, "senha_hash": gerar_hash_senha(SENHA)})
    fake.t("usuarios").append({"id": "u-sindico", "nome": "Sindico Portal", "tipo_usuario": "gestor",
                               "condominio_id": COND, "saldo": 0})

    # UM cartão físico, do CONDOMÍNIO, e um cartão pessoal do "Outro Morador".
    fake.t("cartoes_rfid").append({"uid": CARTAO_BANCADA, "escopo": "compartilhado",
                                   "condominio_id": COND, "apelido": "Cartão da bancada",
                                   "ativo": True, "usuario_id": None})
    fake.t("cartoes_rfid").append({"uid": CARTAO_PESSOAL, "escopo": "pessoal",
                                   "usuario_id": "u-outro", "apelido": "Cartão do Outro",
                                   "ativo": True, "condominio_id": None})
    fake.t("credenciais_usuario").append({"usuario_id": "u-sindico", "senha_hash": gerar_hash_senha(SENHA)})

    fake.t("veiculos").append({"id": "v-celular", "usuario_id": "u-gus",
                               "modelo": "Celular (bancada ESP32)", "tipo": "celular",
                               "capacidade_bateria_kwh": 0.015, "potencia_carro_kw": 0.018})
    fake.t("veiculos").append({"id": "v-carro", "usuario_id": "u-outro", "modelo": "BYD Dolphin",
                               "tipo": "carro", "capacidade_bateria_kwh": 40, "potencia_carro_kw": 7.4})
    fake.t("condominios_favoritos").append({"id": "f1", "usuario_id": "u-gus", "condominio_id": COND})


def entrar(nome):
    r = CLIENTE.post("/login", json={"nome": nome, "senha": SENHA})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def esp(metodo, caminho, corpo=None):
    return CLIENTE.request(metodo, caminho, json=corpo, headers={"X-Device-Token": TOKEN_ESP})


def main_teste():
    semear()
    gus, outro, sindico = entrar("Gus Bancada"), entrar("Outro Morador"), entrar("Sindico Portal")

    print("\n1. Segurança da identidade (Bloco 2)")
    checar(CLIENTE.get("/me").status_code == 401, "sem token, /me recusa")
    checar(CLIENTE.post("/me/carteira/creditar", json={"valor": 10}).status_code == 401,
           "sem token, não dá para creditar saldo")
    r = CLIENTE.post("/me/cartao", json={"rfid_uid": CARTAO_PESSOAL}, headers=gus)
    checar(r.status_code == 409, "cartão pessoal de outro morador não pode ser roubado", r.text)
    r = CLIENTE.post("/me/cartao", json={"rfid_uid": CARTAO_BANCADA}, headers=gus)
    checar(r.status_code == 409, "cartão compartilhado não vira cartão pessoal de ninguém", r.text)
    checar(CLIENTE.get("/gestor/painel", headers=gus).status_code == 403,
           "morador não abre o painel do gestor")

    print("\n2. Handshake do ESP32")
    r = esp("POST", "/hardware/handshake", {"mac": "AA:BB", "ip": "192.168.0.50", "firmware": "2.0.0"})
    checar(r.status_code == 200 and r.json()["carregador"]["numero"] == "01", "placa se apresenta", r.text)
    checar(r.json()["intervalo_comandos_s"] == 2, "ritmo de polling vem do banco")
    checar(esp("GET", "/hardware/comandos").json()["comandos"] == [], "nada na fila ainda")
    checar(CLIENTE.post("/hardware/handshake", json={}, headers={"X-Device-Token": "errado"}).status_code == 401,
           "token de dispositivo errado é recusado")

    print("\n3. Prévia e compatibilidade")
    r = CLIENTE.post("/recargas/previa", json={"charger_id": PONTO, "veiculo_id": "v-carro",
                                               "percentual_bateria_atual": 40, "alvo_percentual": 80},
                     headers=outro)
    checar(r.status_code == 400, "carro não entra na bancada USB", r.text)
    r = CLIENTE.post("/recargas/previa", json={"charger_id": PONTO, "veiculo_id": "v-celular",
                                               "percentual_bateria_atual": 40, "alvo_percentual": 80},
                     headers=gus)
    previa = r.json()
    checar(r.status_code == 200 and previa["energia_necessaria_kwh"] > 0, "prévia do celular sai", r.text)
    checar(not previa["saldo_suficiente"], "prévia avisa que o saldo não cobre")
    r = CLIENTE.post("/recargas/previa", json={"charger_id": PONTO, "veiculo_id": "v-celular",
                                               "percentual_bateria_atual": 40, "alvo_percentual": 80},
                     headers=outro)
    checar(r.status_code == 404, "veículo de outro morador não é encontrado", r.text)

    print("\n4. Preparar: o pedido chega ao ESP32")
    r = CLIENTE.post("/recargas/preparar", json={"charger_id": PONTO, "veiculo_id": "v-celular",
                                                 "percentual_bateria_atual": 40, "alvo_percentual": 80},
                     headers=gus)
    checar(r.status_code == 200 and r.json()["aguardando_cartao"], "recarga preparada", r.text)
    sessao_id = r.json()["sessao"]["id"]

    cmds = esp("GET", "/hardware/comandos").json()["comandos"]
    checar(len(cmds) == 1 and cmds[0]["acao"] == "solicitar_cartao", "ESP32 recebe solicitar_cartao", cmds)
    p = cmds[0]["payload"]
    checar(p["usuario"] == "Gus" and p["veiculo"].startswith("Celular") and p["carregador"] == "01"
           and p["local"] == "Portal dos Bandeirantes" and p["alvo"] == 80,
           "payload traz morador, veículo, ponto, local e alvo", p)
    esp("POST", f"/hardware/comandos/{cmds[0]['id']}/confirmar", {"sucesso": True})

    print("\n5. Cartão: dono, saldo e nova tentativa")
    r = esp("POST", "/hardware/rfid", {"uid": "DEADBEEF"}).json()
    checar(not r["autorizado"] and r["motivo"] == "cartao_nao_cadastrado" and r["uid"] == "DEADBEEF",
           "cartão desconhecido: recusa e devolve o uid para cadastro", r)
    s_espera = [x for x in fake.t("sessoes_recarga") if x["status"] == "aguardando_rfid"][0]
    checar(s_espera.get("ultimo_uid_lido") == "DEADBEEF", "uid lido fica na sessão para o app mostrar")

    r = esp("POST", "/hardware/rfid", {"uid": CARTAO_PESSOAL}).json()
    checar(not r["autorizado"] and r["motivo"] == "cartao_de_outro_usuario",
           "cartão PESSOAL de outro morador não libera", r)
    checar(round(float([u for u in fake.t("usuarios") if u["id"] == "u-outro"][0]["saldo"]), 2) == 50.0,
           "e não toca no saldo do dono do cartão")

    r = esp("POST", "/hardware/rfid", {"uid": CARTAO_BANCADA}).json()
    checar(not r["autorizado"] and r["motivo"] == "saldo_insuficiente" and r["continuar_aguardando"],
           "sem saldo: pede para adicionar e continua esperando", r)

    r = CLIENTE.post("/me/carteira/creditar", json={"valor": 5}, headers=gus)
    checar(r.status_code == 200 and r.json()["saldo_atual"] == 5.0, "morador adiciona saldo pelo app", r.text)

    r = esp("POST", "/hardware/rfid", {"uid": CARTAO_BANCADA}).json()
    checar(r["autorizado"], "cartão compartilhado aprovado depois do crédito", r)
    reservado = r["valor_reservado"]
    checar(0 < reservado <= 5, f"valor reservado: R$ {reservado}")
    checar(CLIENTE.get("/me", headers=gus).json()["usuario"]["saldo"] == round(5 - reservado, 2),
           "saldo cai pelo valor reservado")

    cmds = esp("GET", "/hardware/comandos").json()["comandos"]
    checar(len(cmds) == 1 and cmds[0]["acao"] == "liberar", "ESP32 recebe liberar", cmds)

    print("\n6. Telemetria: energia medida vira dado")
    energia_wh = 0.0
    ultimo = {}
    for passo in range(2000):
        energia_wh += 9.0 * (2 / 3600)             # 9 W durante 2 s
        ultimo = esp("POST", "/hardware/telemetria", {
            "potencia_w": 9.0, "energia_wh": round(energia_wh, 4), "tensao_v": 5.05,
            "corrente_a": 1.78, "temperatura_c": 31.2, "rele_ligado": True}).json()
        if not ultimo["deve_liberar"]:
            break
    checar(ultimo.get("percentual") is not None and ultimo["percentual"] >= 79,
           f"SoC subiu pela energia medida até {ultimo.get('percentual')}%", ultimo)
    checar(ultimo["motivo"] == "alvo_atingido", "recarga para no alvo de 80%, não em 100%", ultimo)
    checar(ultimo["deve_liberar"] is False, "resposta manda abrir o relé")

    leituras = CLIENTE.get(f"/recargas/{sessao_id}/leituras", headers=gus).json()
    checar(len(leituras) > 10, f"{len(leituras)} leituras gravadas para o gráfico")
    checar(CLIENTE.get(f"/recargas/{sessao_id}/leituras", headers=outro).status_code == 404,
           "outro morador não lê as leituras da minha recarga")

    print("\n7. Cobrança: custo real e estorno")
    s = [x for x in fake.t("sessoes_recarga") if x["id"] == sessao_id][0]
    checar(s["status"] == "finalizada" and s["encerrado_por"] == "alvo_atingido", "sessão finalizada", s["status"])
    checar(s["custo_final"] <= reservado, f"custo real R$ {s['custo_final']} <= reservado R$ {reservado}")
    checar(round(s["valor_estornado"] + s["custo_final"], 2) == round(reservado, 2),
           f"estorno de R$ {s['valor_estornado']} fecha a conta")
    saldo_final = CLIENTE.get("/me", headers=gus).json()["usuario"]["saldo"]
    checar(saldo_final == round(5 - s["custo_final"], 2),
           f"saldo final R$ {saldo_final} = 5 - custo real")
    tipos = [m["tipo"] for m in fake.t("movimentacoes_carteira")]
    checar(tipos == ["credito", "pre_autorizacao", "estorno"], f"extrato completo: {tipos}")
    checar(any("finalizada" in n["mensagem"] for n in fake.t("notificacoes")), "recibo chega como notificação")

    cmds = esp("GET", "/hardware/comandos").json()["comandos"]
    checar(any(c["acao"] == "bloquear" for c in cmds), "ESP32 recebe bloquear", cmds)
    checar([c for c in fake.t("carregadores") if c["id"] == PONTO][0]["status"] == "disponivel",
           "ponto volta a disponível")

    print("\n7.1 Recibo linha a linha")
    rec = CLIENTE.get(f"/recargas/{sessao_id}/recibo", headers=gus)
    checar(rec.status_code == 200, "recibo abre para o dono", rec.text)
    rec = rec.json()
    checar(rec["valor_cobrado"] == s["custo_final"] and rec["valor_estornado"] == s["valor_estornado"],
           f"recibo: cobrado R$ {rec['valor_cobrado']}, estornado R$ {rec['valor_estornado']}")
    checar(rec["linhas"]["total"] == round(rec["linhas"]["subtotal_fora_ponta"] + rec["linhas"]["subtotal_ponta"], 2),
           "linhas do recibo somam o total")
    checar([m["tipo"] for m in rec["movimentacoes"]] == ["pre_autorizacao", "estorno"],
           "recibo traz a reserva e o estorno da carteira")
    checar(CLIENTE.get(f"/recargas/{sessao_id}/recibo", headers=outro).status_code == 404,
           "outro morador não vê meu recibo")

    print("\n8. Travas em recarga de outro morador")
    CLIENTE.post("/recargas/preparar", json={"charger_id": PONTO, "veiculo_id": "v-celular",
                                             "percentual_bateria_atual": 50, "alvo_percentual": 60},
                 headers=gus)
    nova = [x for x in fake.t("sessoes_recarga") if x["status"] == "aguardando_rfid"][0]
    checar(CLIENTE.post(f"/recargas/{nova['id']}/cancelar", headers=outro).status_code == 404,
           "outro morador não cancela minha espera")
    checar(CLIENTE.post(f"/recargas/{nova['id']}/cancelar", headers=gus).json()["success"],
           "o dono cancela")

    print("\n9. Painel do gestor (Bloco 3)")
    r = CLIENTE.get("/gestor/painel", headers=sindico)
    painel = r.json()
    checar(r.status_code == 200 and painel["condominio"]["limite_potencia_kw"] == 60, "painel abre", r.text)
    checar(painel["hoje"]["recargas"] == 1 and painel["hoje"]["faturamento"] > 0,
           f"hoje: {painel['hoje']['recargas']} recarga, R$ {painel['hoje']['faturamento']}")
    checar(painel["agora"]["limite_kw"] > 0 and "folga_kw" in painel["agora"], "estado de demanda agora")
    r = CLIENTE.patch("/gestor/condominio", json={"limite_potencia_kw": 30}, headers=sindico)
    checar(r.status_code == 200, "gestor muda o limite de potência", r.text)
    checar(CLIENTE.patch("/gestor/condominio", json={"limite_potencia_kw": 30},
                         headers=gus).status_code == 403, "morador não muda o limite")
    checar(CLIENTE.patch("/gestor/condominio", json={"ponta_inicio": "25:99"},
                         headers=sindico).status_code == 422, "horário de ponta inválido é recusado")
    checar("valor" in painel and "premissas" in painel["valor"] and "demanda" in painel,
           "painel traz valor (receita x custo) e indicadores de demanda")
    cen = CLIENTE.post("/gestor/simular-demanda", json={"carros": 6, "potencia_carro_kw": 7.4},
                       headers=sindico)
    checar(cen.status_code == 200 and cen.json()["pico_sem_gestao_kw"] == 44.4,
           f"simulação: 6 carros = 44,4 kW sem gestão, {cen.json().get('kw_por_carro')} kW cada com gestão")
    checar(CLIENTE.post("/gestor/simular-demanda", json={"carros": 6}, headers=gus).status_code == 403,
           "morador não acessa a simulação do síndico")

    print("\n10. O MESMO cartão, outro morador, outra carteira")
    CLIENTE.post(f"/fila/{PONTO}/entrar", headers=outro)
    checar(any(f["usuario_id"] == "u-outro" for f in fake.t("fila")), "Outro entra na fila do ponto")
    fake.t("veiculos").append({"id": "v-celular2", "usuario_id": "u-outro",
                               "modelo": "Celular do Outro", "tipo": "celular",
                               "capacidade_bateria_kwh": 0.015, "potencia_carro_kw": 0.018})
    saldo_gus_antes = CLIENTE.get("/me", headers=gus).json()["usuario"]["saldo"]

    r = CLIENTE.post("/recargas/preparar", json={"charger_id": PONTO, "veiculo_id": "v-celular2",
                                                 "percentual_bateria_atual": 30, "alvo_percentual": 50},
                     headers=outro)
    checar(r.status_code == 200, "agora quem prepara é o Outro Morador", r.text)
    esp("GET", "/hardware/comandos")
    r = esp("POST", "/hardware/rfid", {"uid": CARTAO_BANCADA}).json()
    checar(r["autorizado"], "o MESMO cartão da bancada autoriza a recarga do Outro", r)

    saldo_outro = CLIENTE.get("/me", headers=outro).json()["usuario"]["saldo"]
    saldo_gus = CLIENTE.get("/me", headers=gus).json()["usuario"]["saldo"]
    checar(saldo_outro < 50.0, f"a reserva saiu da carteira do Outro (saldo {saldo_outro})")
    checar(saldo_gus == saldo_gus_antes, "e não encostou no saldo do Gus")
    sessao_outro = [x for x in fake.t("sessoes_recarga") if x["status"] == "carregando"][0]
    checar(sessao_outro["usuario_id"] == "u-outro", "a sessão ativa é do Outro Morador")
    checar(not any(f["usuario_id"] == "u-outro" for f in fake.t("fila")),
           "começou a carregar: saiu da fila sozinho")

    print(f"\n{ok_total} verificações passaram, {falhas} falharam.\n")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main_teste())
