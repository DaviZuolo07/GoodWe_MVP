"""
backend_de_bolso.py - O backend DE VERDADE, em memória, com um totem semeado.
=============================================================================

Sobe o FastAPI de backend/ com o supabase_falso.py de backend/testes/ - os
dois IMPORTADOS, sem alteração. Não precisa de Supabase, .env nem chave real:
a chave-mestra é a descartável de backend/testes/ambiente.py.

Serve para: pytest, `roteiro --bolso` antes de cada merge e `painel --bolso`
para mexer no totem sem depender de ninguém. NÃO substitui rodar contra o
backend local com o banco de verdade (as RPCs reais só rodam lá).

Limite conhecido: o laço de 10 s do simulador não roda aqui (sem lifespan),
então esperas de cartão não expiram sozinhas.

Tudo que sai daqui é SIMULADO.
"""

import sys

from .config import RAIZ, Config

COND = "c0000000-0000-0000-0000-0000000000aa"
PLACA = "dddddddd-0000-0000-0000-0000000000aa"
VAGAS = {n: f"b0000000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3, 4)}
SENHA = "SenhaBolso#2026"
TAGS = {"A": "A1A1A1A1", "B": "B2B2B2B2", "SEM_SALDO": "C3C3C3C3", "DESCONHECIDA": "DEADBEEF"}
MORADORES = [("u-ana", "Ana Bolso", "A", 50.0), ("u-bia", "Bia Bolso", "B", 50.0),
             ("u-caio", "Caio Bolso", "SEM_SALDO", 0.0)]
CAPACIDADE_CELULAR_KWH = 0.003      # 3 Wh: celular pequeno, cenário rápido


def subir():
    """Devolve (cliente_http, config) prontos para um TotemVirtual."""
    for pasta in ("backend", "backend/testes"):
        caminho = str(RAIZ / pasta)
        if caminho not in sys.path:
            sys.path.insert(0, caminho)
    import ambiente                                  # precisa vir antes do backend
    fake = ambiente.usar_supabase_falso()
    from fastapi.testclient import TestClient
    import main
    from seguranca import chave_dispositivo, gerar_hash_senha

    fake.limpar()
    fake.t("condominios").append({
        "id": COND, "nome": "Condominio de Bolso", "endereco": "Rua do Teste, 1",
        "limite_potencia_kw": 60, "ponta_inicio": "18:00", "ponta_fim": "21:00",
        "ponta_fator_limite": 0.6, "ponta_multiplicador_tarifa": 1.5})
    for n, cid in VAGAS.items():
        fake.t("carregadores").append({
            "id": cid, "condominio_id": COND, "numero": f"0{n}", "modelo": "Totem virtual",
            "tipo": "DC", "potencia_maxima_kw": 0.025, "conector": "USB", "tensao_v": 5,
            "corrente_maxima_a": 3, "tarifa_kwh": 1.95, "status": "offline",
            "origem": "hardware", "perfil": "bancada", "temperatura_c": 26})
        fake.t("portas_dispositivo").append(
            {"id": f"pt{n}", "dispositivo_id": PLACA, "numero": n, "carregador_id": cid})
    fake.t("dispositivos").append({
        "id": PLACA, "carregador_id": None, "nome": "Totem virtual (bolso)", "token_hash": None,
        "online": False, "protocolo": 2, "chave_versao": 1, "boot_atual": None, "seq_atual": 0,
        "intervalo_telemetria_s": 2, "intervalo_comandos_s": 1})

    hash_senha = gerar_hash_senha(SENHA)
    for uid, nome, tag, saldo in MORADORES:
        fake.t("usuarios").append({"id": uid, "nome": nome, "tipo_usuario": "morador",
                                   "condominio_id": COND, "bloco_apto": "A1", "saldo": 0})
        fake.t("credenciais_usuario").append({"usuario_id": uid, "senha_hash": hash_senha})
        if saldo:
            fake.rpc("creditar_saldo", {"p_usuario": uid, "p_valor": saldo, "p_tipo": "bonus",
                                        "p_descricao": "Saldo do bolso (simulado)"}).execute()
        fake.t("veiculos").append({"id": f"v-{uid}", "usuario_id": uid, "modelo": "Celular virtual",
                                   "tipo": "celular",
                                   "capacidade_bateria_kwh": CAPACIDADE_CELULAR_KWH,
                                   "potencia_carro_kw": 0.018})
        fake.t("condominios_favoritos").append({"id": f"f-{uid}", "usuario_id": uid,
                                                "condominio_id": COND})
        fake.t("cartoes_rfid").append({"uid": TAGS[tag], "escopo": "pessoal", "usuario_id": uid,
                                       "condominio_id": None, "apelido": f"Tag {tag}", "ativo": True})

    cfg = Config(backend_url="", dispositivo_id=PLACA,
                 chave_hex=chave_dispositivo(PLACA, 1).hex(),
                 tags=dict(TAGS),
                 app_contas=[(nome, SENHA) for _, nome, tag, _ in MORADORES if tag != "SEM_SALDO"])
    return TestClient(main.app), cfg
