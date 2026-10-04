"""
provisionar.py - Tarefas de segurança que rodam UMA vez, fora da API.
=====================================================================

Rodar de dentro da pasta backend/, com o .env preenchido:

  python provisionar.py chave-jwt
      Gera o par de chaves ES256. Imprime a JWK privada para importar no
      Supabase e a linha pronta para o .env. Não grava nada em disco.

  python provisionar.py senhas-demo --senha "SuaSenhaDemo#2026"
      Dá senha a todo usuário do seed que ainda não tem credencial - inclui
      os síndicos e a conta de bancada criados pela migration 12.
      Nunca sobrescreve quem já tem (use --forcar para isso).

  python provisionar.py token-esp --carregador <uuid-do-carregador>
      Protocolo v1. Gera o token novo da placa que atende o carregador (pela
      porta), grava só o hash e mostra o token UMA vez.

  python provisionar.py chave-mestra
      Protocolo v2. Gera a DEVICE_MASTER_KEY para o .env. Trocar a chave-mestra
      invalida a chave de TODAS as placas v2 (cada uma é derivada dela).

  python provisionar.py placa-v2 --carregadores <uuid1>,<uuid2>,... [--nome ...]
      Protocolo v2. Cria UMA placa com N portas (a ordem da lista é a ordem das
      portas: 1, 2, 3...), marca os pontos como físicos e mostra o id da placa
      e a chave dela UMA vez. Com --dispositivo <id>, acrescenta portas a uma
      placa que já existe (inclusive uma v1 que vai migrar).

  python provisionar.py chave-v2 --dispositivo <uuid> [--rotacionar]
      Mostra de novo a chave v2 da placa (ela é derivada, não fica gravada).
      --rotacionar troca a versão: a chave antiga para de funcionar na hora.

  python provisionar.py limpar
      Mostra o que existe de operação no banco (recargas, fila, pagamentos,
      extrato, leituras). Repita com --sim para apagar, e --contas para
      remover também os cadastros de teste. Estrutura e cartões ficam.
      O saldo de cada conta é mantido e ganha uma linha de abertura no
      extrato (regra do db/15: saldo = soma do extrato). --saldo X leva todas
      as contas a X lançando a diferença como ajuste.

  python provisionar.py ponto-fisico --carregador <uuid> [--perfil bancada]
      Protocolo v1. Converte qualquer carregador em ponto físico: marca
      origem=hardware, cria a placa com a porta 1 apontando para ele e devolve
      o token. Não há carregador "especial" - é isto que faz um ponto virar ESP32.

  python provisionar.py cartao-compartilhado --uid A1B2C3D4 --condominio <uuid>
      Cadastra o cartão da bancada como cartão DO CONDOMÍNIO: autoriza a
      recarga preparada no ponto e cobra de quem preparou no app. Um cartão
      físico atende todos os moradores.

  python provisionar.py verificar
      Teste de invasão contra o banco real. Precisa de SUPABASE_ANON_KEY no
      .env (a mesma chave pública que o frontend usa). Imprime PASSOU/FALHOU.
      Inclui as RPCs do db/15 e a conferência saldo = extrato.

Por que um script e não um endpoint: nada disto deve existir como rota HTTP.
Uma rota "definir senha de todos" é uma porta que alguém um dia esquece aberta.
"""

import argparse
import base64
import json
import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()


def _b64(n: int) -> str:
    return base64.urlsafe_b64encode(n.to_bytes(32, "big")).rstrip(b"=").decode()


def _supabase():
    from supabase import create_client
    from seguranca import verificar_configuracao

    url, chave = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not chave:
        sys.exit("SUPABASE_URL e SUPABASE_KEY precisam estar no .env")
    verificar_configuracao(chave)
    return create_client(url, chave)


# ---------------------------------------------------------------------------

def cmd_chave_jwt(_args):
    from cryptography.hazmat.primitives.asymmetric import ec

    privada = ec.generate_private_key(ec.SECP256R1())
    n = privada.private_numbers()
    jwk = {
        "kty": "EC",
        "kid": str(uuid.uuid4()),
        "crv": "P-256",
        "d": _b64(n.private_value),
        "x": _b64(n.public_numbers.x),
        "y": _b64(n.public_numbers.y),
    }

    print("\n=== 1) Cole isto no Supabase: JWT Keys -> criar chave standby -> importar ===\n")
    print(json.dumps(jwk, indent=2))
    print("\n=== 2) Cole esta linha no backend/.env ===\n")
    print(f"JWT_PRIVATE_JWK='{json.dumps(jwk, separators=(',', ':'))}'")
    print("\nATENÇÃO: isto é uma chave PRIVADA. Não commite, não mande no grupo.")
    print("Quem tiver ela consegue se passar por qualquer morador.\n")


def cmd_senhas_demo(args):
    from seguranca import gerar_hash_senha, validar_forca_senha
    from fastapi import HTTPException

    try:
        validar_forca_senha(args.senha)
    except HTTPException as e:
        sys.exit(e.detail)

    sb = _supabase()
    usuarios = sb.table("usuarios").select("id, nome").execute().data or []
    com_senha = {
        c["usuario_id"]
        for c in (sb.table("credenciais_usuario").select("usuario_id").execute().data or [])
    }

    feitos = 0
    for u in usuarios:
        if u["id"] in com_senha and not args.forcar:
            continue
        sb.table("credenciais_usuario").upsert({
            "usuario_id": u["id"],
            "senha_hash": gerar_hash_senha(args.senha),  # salt novo a cada hash
        }).execute()
        feitos += 1
        print(f"  senha definida: {u['nome']}")

    print(f"\n{feitos} usuário(s) atualizados. {len(usuarios) - feitos} mantidos.")


def _placa_do_carregador(sb, carregador_id):
    p = sb.table("portas_dispositivo").select("dispositivo_id, numero") \
        .eq("carregador_id", carregador_id).execute().data
    if not p:
        return None, None
    d = sb.table("dispositivos").select("id, nome, protocolo, chave_versao") \
        .eq("id", p[0]["dispositivo_id"]).execute().data
    return (d[0] if d else None), p[0]["numero"]


def cmd_token_esp(args):
    from seguranca import gerar_token_dispositivo, hash_token_dispositivo

    sb = _supabase()
    d, porta = _placa_do_carregador(sb, args.carregador)
    if not d:
        sys.exit("Nenhuma placa atende esse carregador (portas_dispositivo).")
    if d.get("protocolo") == 2:
        sys.exit(f"A placa '{d['nome']}' já fala o protocolo v2 e não aceita mais token v1.\n"
                 f"Use: python provisionar.py chave-v2 --dispositivo {d['id']}")

    token = gerar_token_dispositivo()
    sb.table("dispositivos").update({
        "token_hash": hash_token_dispositivo(token),
    }).eq("id", d["id"]).execute()

    print(f"\nDispositivo: {d['nome']} (porta {porta})")
    print("\nToken NOVO (aparece só agora; o banco guardou apenas o hash):\n")
    print(f"  {token}\n")
    print("Cole em DEVICE_TOKEN no firmware/chargeops_esp32/segredos.h e grave na placa.")
    print("O token antigo deixou de funcionar.\n")


def _imprimir_chave_v2(d):
    from seguranca import chave_dispositivo
    chave = chave_dispositivo(d["id"], d.get("chave_versao") or 1).hex()
    print("\nCole no firmware (segredos.h). Aparece só agora; o banco NÃO guarda a chave:\n")
    print(f'  #define DEVICE_ID      "{d["id"]}"')
    print(f'  #define DEVICE_KEY_HEX "{chave}"\n')
    print("A chave é derivada da DEVICE_MASTER_KEY do .env. Sem essa chave-mestra")
    print("igual no backend que vai rodar, a placa não autentica.\n")


def cmd_chave_mestra(_args):
    from seguranca import gerar_chave_mestra
    print("\nCole esta linha no backend/.env:\n")
    print(f"  DEVICE_MASTER_KEY={gerar_chave_mestra()}\n")
    print("ATENÇÃO: se já existe uma, trocar invalida TODAS as placas v2.")
    print("Não commite, não mande no grupo.\n")


def cmd_placa_v2(args):
    sb = _supabase()
    ids = [x.strip() for x in (args.carregadores or "").split(",") if x.strip()]
    if not ids and not args.dispositivo:
        sys.exit("Informe --carregadores (e/ou --dispositivo).")
    if len(ids) != len(set(ids)):
        sys.exit("Carregador repetido na lista.")

    if args.dispositivo:
        r = sb.table("dispositivos").select("*").eq("id", args.dispositivo).execute().data
        if not r:
            sys.exit("Dispositivo não encontrado.")
        d = r[0]
    else:
        d = sb.table("dispositivos").insert({
            "nome": args.nome or "ESP32 multiporta",
            "intervalo_telemetria_s": 2, "intervalo_comandos_s": 2,
        }).execute().data[0]

    usadas = {p["numero"] for p in (sb.table("portas_dispositivo").select("numero")
                                    .eq("dispositivo_id", d["id"]).execute().data or [])}
    proxima = 1
    for cid in ids:
        c = sb.table("carregadores").select("id, numero").eq("id", cid).execute().data
        if not c:
            sys.exit(f"Carregador {cid} não encontrado.")
        dono, _ = _placa_do_carregador(sb, cid)
        if dono and dono["id"] != d["id"]:
            sys.exit(f"Ponto {c[0]['numero']} já é atendido pela placa '{dono['nome']}'.")
        if dono:
            continue
        while proxima in usadas:
            proxima += 1
        if proxima > 8:
            sys.exit("Placa com 8 portas: não cabe mais nenhuma.")
        sb.table("portas_dispositivo").insert(
            {"dispositivo_id": d["id"], "numero": proxima, "carregador_id": cid}).execute()
        mudancas = {"origem": "hardware", "status": "offline"}
        if args.perfil:
            mudancas["perfil"] = args.perfil
        sb.table("carregadores").update(mudancas).eq("id", cid).execute()
        usadas.add(proxima)
        print(f"  porta {proxima} -> ponto {c[0]['numero']}")

    print(f"\nPlaca '{d['nome']}' pronta para o protocolo v2.")
    _imprimir_chave_v2(d)


def cmd_chave_v2(args):
    sb = _supabase()
    r = sb.table("dispositivos").select("id, nome, chave_versao").eq("id", args.dispositivo).execute().data
    if not r:
        sys.exit("Dispositivo não encontrado.")
    d = r[0]
    if args.rotacionar:
        d["chave_versao"] = int(d.get("chave_versao") or 1) + 1
        sb.table("dispositivos").update({"chave_versao": d["chave_versao"]}).eq("id", d["id"]).execute()
        print(f"\nChave rotacionada (versão {d['chave_versao']}). A anterior parou de valer.")
    _imprimir_chave_v2(d)


# Contas que nascem das migrations. Tudo fora desta lista é cadastro de
# teste e pode ser apagado pelo comando `limpar --contas`.
USUARIOS_DO_SEED = (
    "22222222-2222-2222-2222-222222222222",   # Davi Zuolo        (02_seed)
    "e0000000-0000-0000-0000-000000000001",   # Sindico Portal    (12_produto)
    "e0000000-0000-0000-0000-000000000002",   # Sindico FIAP      (12_produto)
    "e0000000-0000-0000-0000-000000000003",   # Gus Bancada       (12_produto)
)

# Tabelas de OPERAÇÃO: o histórico do que aconteceu. Apagar não quebra nada -
# condomínios, carregadores, dispositivos e cartões ficam de pé.
TABELAS_OPERACIONAIS = (
    ("comandos_dispositivo", "id"),
    ("leituras_hardware", "id"),
    ("movimentacoes_carteira", "id"),
    ("pagamentos", "id"),
    ("fila", "id"),
    ("notificacoes", "id"),
    ("chat_mensagens", "id"),
    ("sessoes_recarga", "id"),
    ("consumo_horario", "hora"),
    ("eventos_demanda", "id"),          # migration 14
)


def _contar(sb, tabela, coluna):
    try:
        r = sb.table(tabela).select(coluna, count="exact").limit(1).execute()
        if getattr(r, "count", None) is not None:
            return r.count
    except Exception:
        pass
    try:                                  # sem count exato: conta as linhas
        return len(sb.table(tabela).select(coluna).execute().data or [])
    except Exception:
        return 0


def _apagar_tudo(sb, tabela, coluna):
    """PostgREST exige um filtro em DELETE. Este casa com qualquer linha."""
    if coluna == "hora":
        return sb.table(tabela).delete().gte("hora", "1970-01-01").execute()
    return sb.table(tabela).delete().neq(coluna, "00000000-0000-0000-0000-000000000000").execute()


def cmd_limpar(args):
    """
    Zera a operação: recargas, fila, pagamentos, extrato, notificações,
    leituras do ESP32, comandos e histórico do chat.

    O que NUNCA é apagado: condomínios, carregadores, dispositivos (e portanto
    o token da placa) e os cartões cadastrados. A estrutura fica de pé; some
    só o que "aconteceu".

    Com --contas, apaga também os cadastros de teste - qualquer usuário que
    não venha das migrations. O CASCADE do banco leva junto os veículos,
    credenciais, cartões pessoais e favoritos dessas contas.

    Sem --sim, só mostra o que seria apagado.
    """
    sb = _supabase()

    print("\nInventário atual:\n")
    total = 0
    for tabela, coluna in TABELAS_OPERACIONAIS:
        n = _contar(sb, tabela, coluna)
        total += n
        print(f"  {tabela:<24} {n:>6} linha(s)")

    ativas = sb.table("sessoes_recarga").select(
        "id, status, carregador_id, veiculos(modelo)"
    ).in_("status", ["carregando", "aguardando_rfid"]).execute().data or []
    if ativas:
        print("\n  Recargas presas (é o que trava o carregador na tela):")
        for a in ativas:
            print(f"    {a['id']}  {a['status']:<17} {(a.get('veiculos') or {}).get('modelo', '?')}")

    usuarios = sb.table("usuarios").select("id, nome, tipo_usuario").execute().data or []
    extras = [u for u in usuarios if u["id"] not in USUARIOS_DO_SEED]
    print(f"\n  Contas do seed ...: {len(usuarios) - len(extras)}")
    print(f"  Cadastros de teste: {len(extras)}")
    for u in extras:
        print(f"    {u['nome']} ({u['tipo_usuario']})")

    if not args.sim:
        print("\nNada foi apagado. Para executar de verdade, repita com --sim")
        print("  (e acrescente --contas para remover também os cadastros de teste).\n")
        return

    print("\nApagando...")
    for tabela, coluna in TABELAS_OPERACIONAIS:
        try:
            _apagar_tudo(sb, tabela, coluna)
            print(f"  {tabela} limpo")
        except Exception as e:           # ex.: migration 14 ainda não rodou
            print(f"  {tabela} ignorada ({type(e).__name__})")

    if args.contas and extras:
        for u in extras:
            sb.table("usuarios").delete().eq("id", u["id"]).execute()
        print(f"  {len(extras)} cadastro(s) de teste removido(s)")

    # Carregador preso em 'em_uso' por causa de sessão que não existe mais.
    # Ponto físico volta a 'offline' até a placa fazer handshake de novo.
    fisicos = {c["id"] for c in (sb.table("carregadores").select("id")
                                 .eq("origem", "hardware").execute().data or [])}
    for c in (sb.table("carregadores").select("id").execute().data or []):
        sb.table("carregadores").update({
            "status": "offline" if c["id"] in fisicos else "disponivel",
            "temperatura_c": 25,
        }).eq("id", c["id"]).execute()
    print("  carregadores liberados")

    sb.table("dispositivos").update({"online": False}).neq(
        "id", "00000000-0000-0000-0000-000000000000").execute()

    # O extrato foi apagado, o saldo não: sem isto a regra do db/15
    # (saldo = soma do extrato) quebraria. Cada conta ganha uma linha de
    # abertura com o saldo que tem agora.
    abertos = 0
    for u in (sb.table("usuarios").select("id, saldo").execute().data or []):
        saldo = round(float(u.get("saldo") or 0), 2)
        if saldo == 0:
            continue
        sb.table("movimentacoes_carteira").insert({
            "usuario_id": u["id"], "tipo": "ajuste" if saldo > 0 else "ajuste_debito",
            "valor": abs(saldo), "saldo_apos": saldo,
            "descricao": "Saldo de abertura (limpeza do banco)",
        }).execute()
        abertos += 1
    print(f"  extrato reaberto com o saldo atual de {abertos} conta(s)")

    if args.saldo is not None:
        for u in (sb.table("usuarios").select("id").execute().data or []):
            sb.rpc("ajustar_saldo", {"p_usuario": u["id"], "p_saldo_alvo": round(args.saldo, 2),
                                     "p_descricao": "Ajuste da limpeza do banco"}).execute()
        print(f"  saldo de todas as contas ajustado para R$ {args.saldo:.2f} (via extrato)")

    divergentes = sb.rpc("conferir_carteira", {}).execute().data or []
    print(f"  carteira: {'íntegra' if not divergentes else f'{len(divergentes)} conta(s) divergentes!'}")

    print("\nBanco limpo. A estrutura (condomínios, carregadores, dispositivos,")
    print("cartões) continua intacta - token v1 e chave v2 das placas seguem valendo.\n")


def cmd_ponto_fisico(args):
    """
    Converte QUALQUER carregador do catálogo em ponto físico com ESP32.

    Não existe carregador "especial": o b0000000-...-0001 é só o que veio
    marcado no seed. Um ponto vira físico quando três coisas são verdade:
      1. `carregadores.origem = 'hardware'` (o simulador para de mexer nele)
      2. existe uma placa em `dispositivos`, com o hash do token, e a
         porta 1 dela aponta para ele (`portas_dispositivo`)
      3. uma placa foi gravada com esse token

    Este comando faz 1 e 2 e imprime o token para você fazer o 3. No v1 a
    placa atende UM carregador, na porta 1. Para várias portas, use placa-v2.
    """
    from seguranca import gerar_token_dispositivo, hash_token_dispositivo

    sb = _supabase()
    c = sb.table("carregadores").select("id, numero, condominio_id, origem, perfil") \
        .eq("id", args.carregador).execute()
    if not c.data:
        sys.exit("Carregador não encontrado. Confira o UUID em `select id, numero from carregadores`.")
    carregador = c.data[0]

    mudancas = {"origem": "hardware"}
    if args.perfil:
        mudancas["perfil"] = args.perfil
    if args.potencia_kw:
        mudancas["potencia_maxima_kw"] = args.potencia_kw
    sb.table("carregadores").update(mudancas).eq("id", args.carregador).execute()

    token = gerar_token_dispositivo()
    existente, porta = _placa_do_carregador(sb, args.carregador)
    if existente and existente.get("protocolo") == 2:
        sys.exit(f"O ponto já é atendido pela placa v2 '{existente['nome']}'. "
                 f"Use chave-v2 --dispositivo {existente['id']}")
    dados = {"nome": args.nome or f"ESP32 - ponto {carregador['numero']}",
             "token_hash": hash_token_dispositivo(token),
             "intervalo_telemetria_s": 2, "intervalo_comandos_s": 2}
    if existente and porta == 1:
        sb.table("dispositivos").update(dados).eq("id", existente["id"]).execute()
        acao = "atualizado"
    elif existente:
        sys.exit(f"O ponto está na porta {porta} de uma placa multiporta; o v1 só fala com a porta 1.")
    else:
        novo = sb.table("dispositivos").insert(dados).execute().data[0]
        sb.table("portas_dispositivo").insert(
            {"dispositivo_id": novo["id"], "numero": 1, "carregador_id": args.carregador}).execute()
        acao = "criado, porta 1"

    print(f"\nPonto {carregador['numero']} agora é FÍSICO (dispositivo {acao}).")
    print(f"Perfil: {mudancas.get('perfil', carregador.get('perfil'))}")
    print("\nToken (aparece só agora; o banco guardou apenas o hash):\n")
    print(f"  {token}\n")
    print("Cole em DEVICE_TOKEN no segredos.h da placa que vai atender este ponto.")
    print("Enquanto a placa não fizer handshake, o ponto aparece como offline.\n")


def cmd_cartao_compartilhado(args):
    """
    Cadastra o cartão físico da bancada como CARTÃO DO CONDOMÍNIO.

    Ele não pertence a ninguém: autoriza a recarga que estiver preparada no
    ponto e a cobrança sai de quem preparou no app. É isso que faz um único
    cartão atender todos os moradores na demonstração.
    """
    import cartoes
    cartao = cartoes.registrar_compartilhado(args.condominio, args.uid, args.apelido)
    print(f"\nCartão {cartao['uid']} cadastrado como compartilhado "
          f"({cartao.get('apelido')}) no condomínio {args.condominio}.")
    print("Agora qualquer morador desse condomínio pode preparar a recarga no app,")
    print("encostar este cartão e ser cobrado na própria carteira.\n")


def cmd_verificar(_args):
    """
    Cada caso tenta algo que deveria ser PROIBIDO. Passar = foi bloqueado.
    Bloqueado significa: erro de permissão (401/403) ou lista vazia (RLS).
    """
    import httpx
    from seguranca import emitir_token

    url = os.getenv("SUPABASE_URL")
    anon = os.getenv("SUPABASE_ANON_KEY")
    if not anon:
        sys.exit("Coloque SUPABASE_ANON_KEY no .env (a chave pública do frontend).")

    sb = _supabase()
    usuarios = sb.table("usuarios").select("id, nome, condominio_id").limit(2).execute().data or []
    if len(usuarios) < 2:
        sys.exit("Preciso de pelo menos 2 usuários no banco para testar isolamento.")
    a, b = usuarios
    token_a = emitir_token(a["id"])["token"]

    def get(caminho, token=None):
        h = {"apikey": anon, "Authorization": f"Bearer {token or anon}"}
        return httpx.get(f"{url}/rest/v1/{caminho}", headers=h, timeout=15)

    def bloqueado(r):
        return r.status_code in (401, 403) or (r.status_code == 200 and r.json() == [])

    def rpc_bloqueada(nome, corpo, token):
        r = httpx.post(f"{url}/rest/v1/rpc/{nome}",
                       headers={"apikey": anon, "Authorization": f"Bearer {token}",
                                "Content-Type": "application/json"},
                       json=corpo, timeout=15)
        return r.status_code in (401, 403, 404)

    casos = [
        ("anon lê usuarios", lambda: bloqueado(get("usuarios?select=id&limit=1"))),
        ("anon lê credenciais", lambda: bloqueado(get("credenciais_usuario?select=usuario_id&limit=1"))),
        ("anon lê pagamentos", lambda: bloqueado(get("pagamentos?select=id&limit=1"))),
        ("anon lê sessões", lambda: bloqueado(get("sessoes_recarga?select=id&limit=1"))),
        ("anon lê dispositivos", lambda: bloqueado(get("dispositivos?select=id&limit=1"))),
        ("anon lê a carteira", lambda: bloqueado(get("movimentacoes_carteira?select=id&limit=1"))),
        ("anon lê o consumo do condomínio", lambda: bloqueado(get("consumo_horario?select=hora&limit=1"))),
        ("anon lê eventos de demanda", lambda: bloqueado(get("eventos_demanda?select=id&limit=1"))),
        (f"{a['nome']} lê usuarios", lambda: bloqueado(get("usuarios?select=id&limit=1", token_a))),
        (f"{a['nome']} lê eventos de demanda",
         lambda: bloqueado(get("eventos_demanda?select=id&limit=1", token_a))),
        (f"{a['nome']} lê notificações de {b['nome']}",
         lambda: bloqueado(get(f"notificacoes?select=id&usuario_id=eq.{b['id']}", token_a))),
        (f"{a['nome']} lê veículos de {b['nome']}",
         lambda: bloqueado(get(f"veiculos?select=id&usuario_id=eq.{b['id']}", token_a))),
        (f"{a['nome']} lê sessões de {b['nome']}",
         lambda: bloqueado(get(f"sessoes_recarga?select=id&usuario_id=eq.{b['id']}", token_a))),
        (f"{a['nome']} lê a carteira de {b['nome']}",
         lambda: bloqueado(get(f"movimentacoes_carteira?select=id&usuario_id=eq.{b['id']}", token_a))),
        (f"{a['nome']} se dá crédito pelo RPC",
         lambda: httpx.post(f"{url}/rest/v1/rpc/creditar_saldo",
                            headers={"apikey": anon, "Authorization": f"Bearer {token_a}",
                                     "Content-Type": "application/json"},
                            json={"p_usuario": a["id"], "p_valor": 999, "p_tipo": "credito",
                                  "p_descricao": "teste de invasão"},
                            timeout=15).status_code in (401, 403, 404)),
        (f"{a['nome']} se cadastra direto pelo RPC (sem o backend)",
         lambda: rpc_bloqueada("cadastrar_usuario", {
             "p_nome": "invasor", "p_senha_hash": "$argon2id$x", "p_condominio": a.get("condominio_id"),
             "p_tipo": "morador", "p_bloco": None, "p_veiculo": {"modelo": "x"}}, token_a)),
        (f"{a['nome']} mexe no anti-replay da placa pelo RPC",
         lambda: rpc_bloqueada("consumir_seq", {
             "p_dispositivo": a["id"], "p_boot": 1, "p_seq": 1, "p_ts": "2026-01-01T00:00:00Z"}, token_a)),
        (f"{a['nome']} ajusta o próprio saldo pelo RPC",
         lambda: rpc_bloqueada("ajustar_saldo", {
             "p_usuario": a["id"], "p_saldo_alvo": 9999, "p_descricao": "x"}, token_a)),
        ("anon lê as portas das placas", lambda: bloqueado(get("portas_dispositivo?select=id&limit=1"))),
        (f"{a['nome']} lê as portas das placas",
         lambda: bloqueado(get("portas_dispositivo?select=id&limit=1", token_a))),
        (f"{a['nome']} lê a tabela fila direto (só pela view)",
         lambda: bloqueado(get("fila?select=id&limit=1", token_a))),
        ("anon lê a geração solar", lambda: bloqueado(get("geracao_solar?select=momento&limit=1"))),
        ("token forjado (assinatura errada)",
         lambda: get("carregadores?select=id&limit=1", token_a[:-4] + "AAAA").status_code in (401, 403)),
        # Controle positivo: se isto falhar, o token não está sendo aceito
        # e todos os "bloqueios" acima podem ser falsos positivos.
        ("CONTROLE: carteira íntegra (saldo = soma do extrato)",
         lambda: (sb.rpc("conferir_carteira", {}).execute().data or []) == []),
        ("CONTROLE: logado lê carregadores",
         lambda: (lambda r: r.status_code == 200 and len(r.json()) > 0)(
             get("carregadores?select=id&limit=1", token_a))),
    ]

    falhas = 0
    print()
    for nome, teste in casos:
        try:
            ok = teste()
        except Exception as e:  # rede, JSON inválido etc. contam como falha
            ok, nome = False, f"{nome} ({e.__class__.__name__})"
        falhas += not ok
        print(f"  {'PASSOU' if ok else 'FALHOU'}  {nome}")
    print(f"\n{len(casos) - falhas}/{len(casos)} verificações passaram.\n")
    sys.exit(1 if falhas else 0)


# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Provisionamento de segurança do ChargeOps")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("chave-jwt").set_defaults(fn=cmd_chave_jwt)

    s = sub.add_parser("senhas-demo")
    s.add_argument("--senha", required=True)
    s.add_argument("--forcar", action="store_true")
    s.set_defaults(fn=cmd_senhas_demo)

    t = sub.add_parser("token-esp")
    t.add_argument("--carregador", required=True)
    t.set_defaults(fn=cmd_token_esp)

    sub.add_parser("chave-mestra").set_defaults(fn=cmd_chave_mestra)

    v2 = sub.add_parser("placa-v2")
    v2.add_argument("--carregadores", help="UUIDs separados por vírgula, na ordem das portas")
    v2.add_argument("--dispositivo", help="acrescenta portas a uma placa existente")
    v2.add_argument("--nome", help="nome da placa nova (ex.: 'ESP32 do estande')")
    v2.add_argument("--perfil", choices=["veicular", "bancada"])
    v2.set_defaults(fn=cmd_placa_v2)

    k = sub.add_parser("chave-v2")
    k.add_argument("--dispositivo", required=True)
    k.add_argument("--rotacionar", action="store_true", help="invalida a chave atual")
    k.set_defaults(fn=cmd_chave_v2)

    l = sub.add_parser("limpar")
    l.add_argument("--sim", action="store_true", help="executa de verdade (sem isto, só mostra)")
    l.add_argument("--contas", action="store_true", help="apaga também os cadastros de teste")
    l.add_argument("--saldo", type=float, help="ajusta o saldo de todas as contas (ex.: 0)")
    l.set_defaults(fn=cmd_limpar)

    f = sub.add_parser("ponto-fisico")
    f.add_argument("--carregador", required=True, help="UUID do carregador que ganhará uma placa")
    f.add_argument("--nome", help="Nome do dispositivo (ex.: 'ESP32 do Gus')")
    f.add_argument("--perfil", choices=["veicular", "bancada"],
                   help="bancada = porta USB de celular; veicular = wallbox")
    f.add_argument("--potencia-kw", type=float, dest="potencia_kw",
                   help="Potência máxima real do ponto (ex.: 0.025 para bancada USB)")
    f.set_defaults(fn=cmd_ponto_fisico)

    c = sub.add_parser("cartao-compartilhado")
    c.add_argument("--uid", required=True, help="UID lido pelo leitor (ex.: A1B2C3D4)")
    c.add_argument("--condominio", required=True, help="UUID do condomínio")
    c.add_argument("--apelido", default="Cartão da bancada")
    c.set_defaults(fn=cmd_cartao_compartilhado)

    sub.add_parser("verificar").set_defaults(fn=cmd_verificar)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
