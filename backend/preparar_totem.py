"""
preparar_totem.py - Deixa o banco REAL pronto para o Totem Central (virtual ou ESP32).
=====================================================================================

Rodar de dentro de backend/, com o backend/.env preenchido e o db/17 aplicado:

    python preparar_totem.py

Faz, sem duplicar nada se rodar de novo (idempotente):
  1. condomínio "Estande Next (totem)" - limite 7,5 kW POR VAGA, sem ponta
  2. as vagas do totem: 7,5 kW cada, bancada, hardware (escala 1:1000, ADR-017).
     Sem --next, T4 é a solar: modo FV (10032 = 1) e garantir mínimo (10024)
     ligado, para ir para a REDE - e não pausar - quando a 18650 chega no
     mínimo (10030)
  3. a placa v2 com uma porta por vaga: fator 1000, virtual
  4. 3 moradores de teste com celular 1:1000 (15 kWh / 7,5 kW) e tag pessoal:
       Ana Totem  (R$ 100)   Bia Totem  (R$ 100)   Caio Totem (R$ 0)
  5. grava totem_virtual/.env com DEVICE_ID, chave, tags e contas do app
     (o .env anterior, se existir, vira .env.bak). O .env NÃO vai para o git.

QUANTAS VAGAS (23/10)
    O totem montado tem UMA vaga, e o relé dela libera energia de verdade.
    `--vagas N` manda quantas o banco vai ter, e tem de bater com o `PORTAS`
    de firmware/totem_next/config.h. Diminuir o número APAGA as vagas que
    sobram (e as portas da placa), para o painel não mostrar vaga sem relé.

Opções:
<<<<<<< HEAD
    --next          TOTEM NEXT (o que vai para a banca): ESP32 SEM INA219 e SEM
                    solar. Vagas iguais, divisão por tempo ligada (Modbus 10025,
                    o water-filling cicla o relé), sem porta solar, sem FV no
                    estande. A energia vem do modelo de carga do ESP32: rótulo
                    'simulado' (dispositivos.virtual = true), nunca 'medido'.
    --vagas N       quantas vagas o totem tem, de 1 a 4. Padrão: 1 com --next,
                    4 sem (o totem_central tem a vaga solar no T4).
=======
    --next          TOTEM NEXT de 22/10 (o que vai para a banca): ESP32 SEM INA219 e
                    SEM solar. 4 vagas iguais, divisão por tempo ligada (Modbus 10025,
                    o water-filling cicla os relés), sem porta solar, sem FV no
                    estande. A energia vem do modelo de carga do ESP32: rótulo
                    'simulado' (dispositivos.virtual = true), nunca 'medido'.
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
    --fisico        a placa é o ESP32 com 5 INA219 (ADR-022, grava 'medido'); padrão: virtual ('simulado')
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
MAX_VAGAS = len(VAGAS)
POTENCIA_VAGA_KW = 7.5          # 5 V x 1,5 A = 7,5 W, na escala 1:1000 (ADR-017)
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


<<<<<<< HEAD
def condominio(sb, next_sem_sensor: bool = False, n_vagas: int = MAX_VAGAS):
    # O quadro do estande comporta todas as vagas cheias ao mesmo tempo: é o
    # ponto de partida da demonstração. Para mostrar o water-filling, o painel
    # BAIXA este limite ao vivo (Sala Next -> Demanda do estande). Com uma vaga:
    # 7,5 kW cheio -> 3,75 kW (50% do tempo) -> 1,5 kW (o mínimo) -> fila.
    limite = round(POTENCIA_VAGA_KW * n_vagas, 3)
=======
def condominio(sb, next_sem_sensor: bool = False):
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
    sb.table("condominios").upsert({
        "id": ESTANDE, "nome": "Estande Next (totem)", "endereco": "FIAP - Next 2026",
        "perfil": "bancada",          # cadastro: só celular, sem bloco/apto (db/19)
        "limite_potencia_kw": limite,
        # ponta 00:00-00:00 = nunca: o valor da demonstração não muda com a hora
        "ponta_inicio": "00:00", "ponta_fim": "00:00",
        # Totem Next sem painel: sem FV (o alocador não promete sol que não existe).
        "fv_potencia_kwp": 0 if next_sem_sensor else 10, "preco_solar_kwh": 0.75, "custo_solar_kwh": 0.35,
<<<<<<< HEAD
        # Na ponta o quadro do estande cai pela metade: a vaga que estava cheia
        # passa a ficar 50% do tempo com o relé fechado. Ponta 00:00-00:00 =
        # desligada; o painel liga a janela ao vivo para mostrar ("pico agora").
        "ponta_fator_limite": 0.5,
    }).execute()
    _ok(f"condomínio 'Estande Next (totem)' - limite {limite:g} kW "
        f"({limite / 2:g} na ponta), sem ponta ligada"
        + (", sem FV" if next_sem_sensor else "") + " (SIMULADO)")


def _apagar_vagas_sobrando(sb, n_vagas: int) -> None:
    """
    Diminuiu o número de vagas: tira do banco as que sobraram. Sem isto, o
    painel mostraria vaga que nenhum relé atende e o alocador dividiria o
    limite com uma vaga fantasma.
    """
    sobrando = {n: cid for n, cid in VAGAS.items() if n > n_vagas}
    if not sobrando:
        return
    ids = list(sobrando.values())
    existem = [c["id"] for c in sb.table("carregadores").select("id").in_("id", ids).execute().data or []]
    if not existem:
        return
    abertas = sb.table("sessoes_recarga").select("id").in_("carregador_id", existem) \
        .in_("status", ["carregando", "aguardando_energia", "aguardando_rfid"]).execute().data
    if abertas:
        sys.exit(f"As vagas T{n_vagas + 1}..T{MAX_VAGAS} têm recarga aberta. Encerre no painel "
                 "(ou rode: python provisionar.py limpar) e rode de novo.")
    sb.table("portas_dispositivo").delete().in_("carregador_id", existem).execute()
    try:
        sb.table("carregadores").delete().in_("id", existem).execute()
        _ok(f"vagas T{n_vagas + 1}..T{MAX_VAGAS} apagadas (o totem agora tem {n_vagas})")
    except Exception:
        # Histórico de recarga impede o delete: deixa a vaga fora da placa e
        # offline. O relé não existe, então ela nunca mais é liberada.
        sb.table("carregadores").update({"status": "offline", "controle_dinamico": False}) \
            .in_("id", existem).execute()
        _ok(f"vagas T{n_vagas + 1}..T{MAX_VAGAS} desligadas da placa e marcadas offline "
            "(têm histórico: não dá para apagar)")


def vagas(sb, next_sem_sensor: bool = False, n_vagas: int = MAX_VAGAS):
    _apagar_vagas_sobrando(sb, n_vagas)
    for n, cid in sorted(VAGAS.items()):
        if n > n_vagas:
            break
=======
        # Na ponta o quadro do estande cai pela metade: 30 -> 15 kW = 2 celulares
        # cheios, ou 4 a 50% do tempo (divisão por tempo). Ponta 00:00-00:00 =
        # desligada; o painel liga a janela ao vivo para mostrar.
        "ponta_fator_limite": 0.5,
    }).execute()
    _ok("condomínio 'Estande Next (totem)' - limite 30 kW (15 na ponta), sem ponta ligada"
        + (", sem FV" if next_sem_sensor else "") + " (SIMULADO)")


def vagas(sb, next_sem_sensor: bool = False):
    for n, cid in VAGAS.items():
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
        solar = n == 4 and not next_sem_sensor
        existente = sb.table("carregadores").select("id").eq("id", cid).execute().data
        dados = {
            "condominio_id": ESTANDE, "numero": f"T{n}",
            "modelo": f"Totem Central - vaga {n}" + (" (solar)" if solar else "") + " - maquete 1:1000",
            "tipo": "DC", "conector": "USB", "tensao_v": 5, "corrente_maxima_a": 3,
            "potencia_maxima_kw": POTENCIA_VAGA_KW, "tarifa_kwh": 1.15,
            "perfil": "bancada", "origem": "hardware",
            "bateria_soc_minimo": 20,                 # 10030
            # Vaga solar: FV (10032) + garantir mínimo (10024). Sem o 10024 a
            # vaga PAUSA quando a 18650 acaba, em vez de seguir pela rede.
            "modo_carga": 1 if solar else 0,
            "garantir_minimo": solar,
            # Modbus 10025: ligado = a placa divide por TEMPO (relé ciclado pelo
            # water-filling, demanda.por_tempo). Só o totem Next faz isso; a
            # placa com INA219 (ADR-022) é carga fixa.
            "controle_dinamico": next_sem_sensor,
        }
        if existente:
            sb.table("carregadores").update(dados).eq("id", cid).execute()
        else:
            sb.table("carregadores").insert({"id": cid, "status": "offline", **dados}).execute()
<<<<<<< HEAD
    faixa = "T1" if n_vagas == 1 else f"T1..T{n_vagas}"
    _ok(f"{n_vagas} vaga(s) {faixa} de {POTENCIA_VAGA_KW:g} kW (bancada, escala 1:1000; "
=======
    _ok("4 vagas T1..T4 de 7,5 kW (bancada, escala 1:1000; "
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
        + ("divisão por tempo ligada, sem vaga solar)" if next_sem_sensor
           else "T4 = solar, FV + garantir mínimo)"))


<<<<<<< HEAD
def placa(sb, virtual: bool, next_sem_sensor: bool = False, n_vagas: int = MAX_VAGAS) -> dict:
    usadas = {n: cid for n, cid in VAGAS.items() if n <= n_vagas}
=======
def placa(sb, virtual: bool, next_sem_sensor: bool = False) -> dict:
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
    portas = sb.table("portas_dispositivo").select("dispositivo_id, numero, carregador_id") \
        .in_("carregador_id", list(VAGAS.values())).execute().data or []
    donos = {p["dispositivo_id"] for p in portas}
    if len(donos) > 1:
        sys.exit("As vagas do totem estão em placas diferentes. Apague as portas antigas antes:\n"
                 f"  delete from portas_dispositivo where carregador_id in {tuple(VAGAS.values())};")
    ajustes = {"fator_escala": 1000, "virtual": virtual, "porta_solar": None if next_sem_sensor else 4,
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
    # `_apagar_vagas_sobrando` já tirou as portas das vagas que saíram; aqui só
    # entram as que faltam. O handshake devolve exatamente estas portas, e é
    # esse número que o firmware compara com o PORTAS dele.
    ja = {p["numero"] for p in portas if p["numero"] <= n_vagas}
    for n, cid in usadas.items():
        if n not in ja:
            sb.table("portas_dispositivo").insert(
                {"dispositivo_id": d["id"], "numero": n, "carregador_id": cid}).execute()
<<<<<<< HEAD
    faixa = "1 -> T1" if n_vagas == 1 else f"1-{n_vagas} -> T1..T{n_vagas}"
    _ok(f"porta(s) {faixa} | fator 1000 | porta solar {ajustes['porta_solar'] or 'nenhuma'} | origem "
=======
    _ok(f"portas 1-4 -> T1..T4 | fator 1000 | porta solar {ajustes['porta_solar'] or 'nenhuma'} | origem "
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
        + ("simulado (modelo de carga no ESP32, sem sensor)" if next_sem_sensor
           else "simulado (virtual)" if virtual else "medido (ESP32)"))
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


def escrever_env(d: dict, senha: str, gravar: bool, next_sem_sensor: bool = False) -> None:
    from seguranca import chave_dispositivo
    chave = chave_dispositivo(d["id"], d.get("chave_versao") or 1).hex()
    if next_sem_sensor:
        # O ESP32 não lê .env: a chave vai compilada no segredos.h (fora do git).
        id_placa = d["id"]
        print("\n--- firmware/totem_next/segredos.h (copie; o arquivo NÃO vai para o git) ---")
        print(f'#define DEVICE_ID      "{id_placa}"')
        print(f'#define DEVICE_KEY_HEX "{chave}"')
        print('#define BACKEND_URL    "http://<IP do notebook na rede do estande>:8000"')
        print('#define WIFI_SSID      "<rede do estande>"')
        print('#define WIFI_SENHA     "<senha da rede>"')
        print("--- (a chave é derivada da DEVICE_MASTER_KEY deste backend/.env) ---\n")
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
    ap.add_argument("--next", action="store_true",
                    help="totem Next: ESP32 sem INA219 e sem solar, divisão por tempo (origem 'simulado')")
<<<<<<< HEAD
    ap.add_argument("--vagas", type=int, default=None, metavar="N",
                    help=f"quantas vagas o totem tem, de 1 a {MAX_VAGAS} "
                         f"(padrão: 1 com --next, {MAX_VAGAS} sem). Tem de ser igual ao "
                         "PORTAS de firmware/totem_next/config.h")
=======
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
    ap.add_argument("--fisico", action="store_true", help="a placa é o ESP32 com INA219 (origem 'medido')")
    ap.add_argument("--senha", default=SENHA_PADRAO, help="senha das contas de teste")
    ap.add_argument("--sem-env", action="store_true", help="não grava o totem_virtual/.env")
    args = ap.parse_args()

    # Padrão: o totem montado tem UMA vaga; o totem_central de 4 continua em 4.
    n_vagas = args.vagas if args.vagas is not None else (1 if args.next else MAX_VAGAS)
    if not 1 <= n_vagas <= MAX_VAGAS:
        sys.exit(f"--vagas tem de ser de 1 a {MAX_VAGAS} (pedido: {n_vagas}).")
    if not args.next and n_vagas != MAX_VAGAS:
        sys.exit(f"Sem --next a vaga solar é a T4: --vagas só vale {MAX_VAGAS}. "
                 "Para o totem Next (sem solar), use --next.")

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
    if args.next and args.fisico:
        sys.exit("--next e --fisico não combinam: o totem Next não tem sensor (nunca grava 'medido').")
<<<<<<< HEAD
    condominio(sb, args.next, n_vagas)
    vagas(sb, args.next, n_vagas)
    d = placa(sb, virtual=not args.fisico, next_sem_sensor=args.next, n_vagas=n_vagas)
=======
    condominio(sb, args.next)
    vagas(sb, args.next)
    d = placa(sb, virtual=not args.fisico, next_sem_sensor=args.next)
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
    senha_hash = gerar_hash_senha(args.senha)
    for nome, tag, bonus in CONTAS:
        morador(sb, nome, tag, bonus, senha_hash)
    escrever_env(d, args.senha, gravar=not args.sem_env, next_sem_sensor=args.next)

    if args.next:
<<<<<<< HEAD
        limite = POTENCIA_VAGA_KW * n_vagas
        print(f"""
Pronto (totem Next, {n_vagas} vaga(s)). Login no app: Ana Totem / Bia Totem / Caio Totem,
senha {args.senha}
  1. Confira firmware/totem_next/config.h:  constexpr uint8_t PORTAS = {n_vagas};
  2. Cole o bloco acima em firmware/totem_next/segredos.h e grave a placa.
  3. backend\\   uvicorn main:app --host 0.0.0.0 --port 8000   (0.0.0.0: o ESP32 vem pela rede)
  4. Monitor serial a 115200: "handshake ok: {n_vagas} porta(s) no backend, {n_vagas} nesta placa".
  Limite do estande: {limite:g} kW. Para mostrar o water-filling, baixe no painel
  (Sala Next -> Demanda do estande) para {limite / 2:g} kW = 50% do tempo com o relé fechado.
=======
        print(f"""
Pronto (totem Next). Login no app: Ana Totem / Bia Totem / Caio Totem, senha {args.senha}
  1. Cole o bloco acima em firmware/totem_next/segredos.h e grave a placa.
  2. backend\\   uvicorn main:app --host 0.0.0.0 --port 8000   (0.0.0.0: o ESP32 vem pela rede)
  3. Monitor serial a 115200: "handshake ok: 4 porta(s)".
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
  Roteiro completo: docs/RODAR_NO_NOTEBOOK.md
""")
        return
    print(f"""
Pronto. Login no app: Ana Totem / Bia Totem / Caio Totem, senha {args.senha}
Próximos passos (cada um num terminal):
  backend\\       uvicorn main:app --reload
  GoodWe_MVP\\    python -m totem_virtual painel        (abre http://127.0.0.1:8765)
  GoodWe_MVP\\    python -m totem_virtual roteiro       (validação automática)
""")


if __name__ == "__main__":
    main()
