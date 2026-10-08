"""
preparar_totem.py - Deixa o banco REAL pronto para o Totem Central (virtual ou ESP32).
=====================================================================================

Rodar de dentro de backend/, com o backend/.env preenchido e o db/17 aplicado:

    python preparar_totem.py

Faz, sem duplicar nada se rodar de novo (idempotente):
  1. condomínio "Estande Next (totem)" - limite 20 kW, sem horário de ponta
  2. 4 vagas do totem: 7,5 kW, bancada, hardware (escala 1:1000, ADR-017)
  3. a placa v2 com as 4 portas: fator 1000, porta solar 4, virtual
  4. 3 moradores de teste com celular 1:1000 (15 kWh / 7,5 kW) e tag pessoal:
       Ana Totem  (R$ 100)   Bia Totem  (R$ 100)   Caio Totem (R$ 0)
  5. grava totem_virtual/.env com DEVICE_ID, chave, tags e contas do app
     (o .env anterior, se existir, vira .env.bak). O .env NÃO vai para o git.

Opções:
    --fisico        a placa é o ESP32 real (grava 'medido'); padrão: virtual ('simulado')
    --senha X       senha das contas de teste (padrão abaixo; são contas SIMULADAS)
    --sem-env       só imprime, não grava o totem_virtual/.env

Tudo aqui é dado SIMULADO de teste. Para apagar recargas e extratos depois:
    python provisionar.py limpar
"""

import argparse
import shutil
import sys
from pathlib import Path

import provisionar                                   # carrega o .env (load_dotenv)

ESTANDE = "e57a4de0-0000-4000-8000-000000000000"
VAGAS = {n: f"e57a4de0-0000-4000-8000-00000000000{n}" for n in (1, 2, 3, 4)}
NOME_PLACA = "Totem Central"
SENHA_PADRAO = "TotemNext#2026"
CONTAS = [  # nome, tag, bônus
    ("Ana Totem", "AA000001", 100.0),
    ("Bia Totem", "BB000002", 100.0),
    ("Caio Totem", "CC000003", 0.0),
]
CELULAR = {"modelo": "Celular 1:1000", "placa": None, "tipo": "celular",
           "capacidade_bateria_kwh": 15, "potencia_carro_kw": 7.5}
ENV_TOTEM = Path(__file__).resolve().parent.parent / "totem_virtual" / ".env"


def _ok(msg):
    print(f"  [ok] {msg}")


def checar_banco(sb):
    try:
        sb.table("dispositivos").select("id, fator_escala, virtual, porta_solar").limit(1).execute()
        sb.table("sessoes_recarga").select("id, percentual_origem, uid_inicio").limit(1).execute()
    except Exception as e:
        sys.exit("O banco ainda não tem a migration 17. Rode db/17_totem_escala_fontes.sql "
                 f"no SQL Editor do Supabase e tente de novo.\n(erro: {str(e)[:160]})")
    _ok("migration 17 presente")
    try:
        sb.table("condominios").select("perfil").limit(1).execute()
    except Exception as e:
        sys.exit("O banco ainda não tem a migration 19 (condominios.perfil). Rode "
                 f"db/19_condominio_perfil.sql no SQL Editor do Supabase.\n(erro: {str(e)[:160]})")
    _ok("migration 19 presente")


def condominio(sb):
    sb.table("condominios").upsert({
        "id": ESTANDE, "nome": "Estande Next (totem)", "endereco": "FIAP - Next 2026",
        "perfil": "bancada",          # cadastro: só celular, sem bloco/apto (db/19)
        "limite_potencia_kw": 20,
        # ponta 00:00-00:00 = nunca: o valor da demonstração não muda com a hora
        "ponta_inicio": "00:00", "ponta_fim": "00:00",
        "fv_potencia_kwp": 10, "preco_solar_kwh": 0.75, "custo_solar_kwh": 0.35,
    }).execute()
    _ok("condomínio 'Estande Next (totem)' - limite 20 kW, sem ponta (SIMULADO)")


def vagas(sb):
    for n, cid in VAGAS.items():
        existente = sb.table("carregadores").select("id").eq("id", cid).execute().data
        dados = {
            "condominio_id": ESTANDE, "numero": f"T{n}",
            "modelo": f"Totem Central - vaga {n}" + (" (solar)" if n == 4 else "") + " - maquete 1:1000",
            "tipo": "DC", "conector": "USB", "tensao_v": 5, "corrente_maxima_a": 3,
            "potencia_maxima_kw": 7.5, "tarifa_kwh": 1.15, "perfil": "bancada", "origem": "hardware",
            "bateria_soc_minimo": 20, "garantir_minimo": False,
        }
        if existente:
            sb.table("carregadores").update(dados).eq("id", cid).execute()
        else:
            sb.table("carregadores").insert({"id": cid, "status": "offline", **dados}).execute()
    _ok("4 vagas T1..T4 de 7,5 kW (bancada, escala 1:1000; T4 = solar)")


def placa(sb, virtual: bool) -> dict:
    portas = sb.table("portas_dispositivo").select("dispositivo_id, numero, carregador_id") \
        .in_("carregador_id", list(VAGAS.values())).execute().data or []
    donos = {p["dispositivo_id"] for p in portas}
    if len(donos) > 1:
        sys.exit("As vagas do totem estão em placas diferentes. Apague as portas antigas antes:\n"
                 f"  delete from portas_dispositivo where carregador_id in {tuple(VAGAS.values())};")
    ajustes = {"fator_escala": 1000, "virtual": virtual, "porta_solar": 4,
               "intervalo_telemetria_s": 2, "intervalo_comandos_s": 2}
    if donos:
        d = sb.table("dispositivos").select("*").eq("id", donos.pop()).execute().data[0]
        abertas = sb.table("sessoes_recarga").select("id").in_("carregador_id", list(VAGAS.values())) \
            .in_("status", ["carregando", "aguardando_energia"]).execute().data
        if abertas and float(d.get("fator_escala") or 1) != 1000:
            sys.exit("Há recarga aberta no totem: encerre antes de trocar o fator de escala.")
        sb.table("dispositivos").update(ajustes).eq("id", d["id"]).execute()
        d = {**d, **ajustes}
        _ok(f"placa existente reaproveitada ({d['id']})")
    else:
        d = sb.table("dispositivos").insert({"nome": NOME_PLACA, **ajustes}).execute().data[0]
        _ok(f"placa nova criada ({d['id']})")
    ja = {p["numero"] for p in portas}
    for n, cid in VAGAS.items():
        if n not in ja:
            sb.table("portas_dispositivo").insert(
                {"dispositivo_id": d["id"], "numero": n, "carregador_id": cid}).execute()
    _ok(f"portas 1-4 -> T1..T4 | fator 1000 | porta solar 4 | origem "
        f"{'simulado (virtual)' if virtual else 'medido (ESP32)'}")
    return d


def morador(sb, nome, tag, bonus, senha_hash) -> str:
    try:
        r = sb.rpc("cadastrar_usuario", {
            "p_nome": nome, "p_senha_hash": senha_hash, "p_condominio": ESTANDE,
            "p_tipo": "morador", "p_bloco": "Estande", "p_veiculo": CELULAR, "p_bonus": bonus,
        }).execute()
        uid = r.data[0] if isinstance(r.data, list) else r.data
        criado = True
    except Exception as e:
        if "nome_em_uso" not in str(e):
            raise
        uid = sb.table("usuarios").select("id").ilike("nome", nome).execute().data[0]["id"]
        sb.table("credenciais_usuario").upsert({"usuario_id": uid, "senha_hash": senha_hash},
                                                on_conflict="usuario_id").execute()
        sb.table("usuarios").update({"condominio_id": ESTANDE}).eq("id", uid).execute()
        criado = False
    # celular sempre em unidades de produto (ADR-017 D3)
    vs = sb.table("veiculos").select("id").eq("usuario_id", uid).eq("tipo", "celular").execute().data
    if vs:
        sb.table("veiculos").update({k: v for k, v in CELULAR.items() if k != "placa"}) \
            .eq("id", vs[0]["id"]).execute()
    else:
        sb.table("veiculos").insert({"usuario_id": uid, **CELULAR}).execute()
    sb.table("condominios_favoritos").upsert({"usuario_id": uid, "condominio_id": ESTANDE},
                                             on_conflict="usuario_id,condominio_id").execute()
    cartao = sb.table("cartoes_rfid").select("uid, escopo, usuario_id").eq("uid", tag).execute().data
    if cartao and cartao[0].get("usuario_id") != uid:
        sys.exit(f"A tag {tag} já é de outra pessoa. Apague: delete from cartoes_rfid where uid = '{tag}';")
    if cartao:
        sb.table("cartoes_rfid").update({"ativo": True}).eq("uid", tag).execute()
    else:
        sb.table("cartoes_rfid").insert({"uid": tag, "escopo": "pessoal", "usuario_id": uid, "ativo": True,
                                         "apelido": f"Tag de teste {nome.split()[0]}"}).execute()
    _ok(f"{nome:<11} tag {tag}  " + (f"criado com R$ {bonus:.2f}" if criado else "já existia (senha redefinida)"))
    return uid


def escrever_env(d: dict, senha: str, gravar: bool) -> None:
    from seguranca import chave_dispositivo
    chave = chave_dispositivo(d["id"], d.get("chave_versao") or 1).hex()
    linhas = [
        "# Gerado por backend/preparar_totem.py - NÃO comitar.",
        "BACKEND_URL=http://127.0.0.1:8000",
        f"DEVICE_ID={d['id']}",
        f"DEVICE_KEY_HEX={chave}",
        f"TAG_A={CONTAS[0][1]}",
        f"TAG_B={CONTAS[1][1]}",
        f"TAG_SEM_SALDO={CONTAS[2][1]}",
        f"APP_CONTAS={CONTAS[0][0]}:{senha},{CONTAS[1][0]}:{senha}",
        "ROTEIRO_ESPERA_S=90",
        "",
    ]
    if not gravar:
        print("\n--- conteúdo para totem_virtual/.env (não gravado) ---\n" + "\n".join(linhas))
        return
    if ENV_TOTEM.exists():
        shutil.copy(ENV_TOTEM, ENV_TOTEM.parent / ".env.bak")
    ENV_TOTEM.write_text("\n".join(linhas), encoding="utf-8")
    _ok(f"{ENV_TOTEM} gravado (chave derivada da DEVICE_MASTER_KEY deste .env)")


def main():
    ap = argparse.ArgumentParser(description="Prepara o banco real para o Totem Central.")
    ap.add_argument("--fisico", action="store_true", help="a placa é o ESP32 real (origem 'medido')")
    ap.add_argument("--senha", default=SENHA_PADRAO, help="senha das contas de teste")
    ap.add_argument("--sem-env", action="store_true", help="não grava o totem_virtual/.env")
    args = ap.parse_args()

    from fastapi import HTTPException
    from seguranca import gerar_hash_senha, protocolo_v2_configurado, validar_forca_senha
    try:
        validar_forca_senha(args.senha)
    except HTTPException as e:
        sys.exit(f"Senha fraca: {e.detail}")
    if not protocolo_v2_configurado():
        sys.exit("Falta DEVICE_MASTER_KEY no backend/.env (gere com: python provisionar.py chave-mestra).")

    print("\nPreparando o Totem Central no banco (dados SIMULADOS de teste)\n")
    sb = provisionar._supabase()
    checar_banco(sb)
    condominio(sb)
    vagas(sb)
    d = placa(sb, virtual=not args.fisico)
    senha_hash = gerar_hash_senha(args.senha)
    for nome, tag, bonus in CONTAS:
        morador(sb, nome, tag, bonus, senha_hash)
    escrever_env(d, args.senha, gravar=not args.sem_env)

    print(f"""
Pronto. Login no app: Ana Totem / Bia Totem / Caio Totem, senha {args.senha}
Próximos passos (cada um num terminal):
  backend\\       uvicorn main:app --reload
  GoodWe_MVP\\    python -m totem_virtual painel        (abre http://127.0.0.1:8765)
  GoodWe_MVP\\    python -m totem_virtual roteiro       (validação automática)
""")


if __name__ == "__main__":
    main()
