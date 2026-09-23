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
      Gera o token novo do ESP32, grava só o hash e mostra o token UMA vez.

  python provisionar.py ponto-fisico --carregador <uuid> [--perfil bancada]
      Converte qualquer carregador em ponto físico: marca origem=hardware,
      cria o dispositivo e devolve o token da placa. Não há carregador
      "especial" - é isto que faz um ponto virar ESP32.

  python provisionar.py cartao-compartilhado --uid A1B2C3D4 --condominio <uuid>
      Cadastra o cartão da bancada como cartão DO CONDOMÍNIO: autoriza a
      recarga preparada no ponto e cobra de quem preparou no app. Um cartão
      físico atende todos os moradores.

  python provisionar.py verificar
      Teste de invasão contra o banco real. Precisa de SUPABASE_ANON_KEY no
      .env (a mesma chave pública que o frontend usa). Imprime PASSOU/FALHOU.

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


def cmd_token_esp(args):
    from seguranca import gerar_token_dispositivo, hash_token_dispositivo

    sb = _supabase()
    d = sb.table("dispositivos").select("id, nome").eq(
        "carregador_id", args.carregador
    ).execute()
    if not d.data:
        sys.exit("Nenhum dispositivo cadastrado nesse carregador.")

    token = gerar_token_dispositivo()
    sb.table("dispositivos").update({
        "token_hash": hash_token_dispositivo(token),
    }).eq("id", d.data[0]["id"]).execute()

    print(f"\nDispositivo: {d.data[0]['nome']}")
    print("\nToken NOVO (aparece só agora; o banco guardou apenas o hash):\n")
    print(f"  {token}\n")
    print("Cole em DEVICE_TOKEN no firmware/chargeops_esp32/segredos.h e grave na placa.")
    print("O token antigo deixou de funcionar.\n")


def cmd_ponto_fisico(args):
    """
    Converte QUALQUER carregador do catálogo em ponto físico com ESP32.

    Não existe carregador "especial": o b0000000-...-0001 é só o que veio
    marcado no seed. Um ponto vira físico quando três coisas são verdade:
      1. `carregadores.origem = 'hardware'` (o simulador para de mexer nele)
      2. existe uma linha em `dispositivos` apontando para ele, com o hash
         do token
      3. uma placa foi gravada com esse token

    Este comando faz 1 e 2 e imprime o token para você fazer o 3. Rode uma
    vez por placa; cada placa atende UM carregador (a coluna carregador_id
    em dispositivos é única).
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
    existente = sb.table("dispositivos").select("id").eq("carregador_id", args.carregador).execute()
    dados = {"nome": args.nome or f"ESP32 - ponto {carregador['numero']}",
             "token_hash": hash_token_dispositivo(token),
             "intervalo_telemetria_s": 2, "intervalo_comandos_s": 2}
    if existente.data:
        sb.table("dispositivos").update(dados).eq("id", existente.data[0]["id"]).execute()
        acao = "atualizado"
    else:
        sb.table("dispositivos").insert({**dados, "carregador_id": args.carregador}).execute()
        acao = "criado"

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
    usuarios = sb.table("usuarios").select("id, nome").limit(2).execute().data or []
    if len(usuarios) < 2:
        sys.exit("Preciso de pelo menos 2 usuários no banco para testar isolamento.")
    a, b = usuarios
    token_a = emitir_token(a["id"])["token"]

    def get(caminho, token=None):
        h = {"apikey": anon, "Authorization": f"Bearer {token or anon}"}
        return httpx.get(f"{url}/rest/v1/{caminho}", headers=h, timeout=15)

    def bloqueado(r):
        return r.status_code in (401, 403) or (r.status_code == 200 and r.json() == [])

    casos = [
        ("anon lê usuarios", lambda: bloqueado(get("usuarios?select=id&limit=1"))),
        ("anon lê credenciais", lambda: bloqueado(get("credenciais_usuario?select=usuario_id&limit=1"))),
        ("anon lê pagamentos", lambda: bloqueado(get("pagamentos?select=id&limit=1"))),
        ("anon lê sessões", lambda: bloqueado(get("sessoes_recarga?select=id&limit=1"))),
        ("anon lê dispositivos", lambda: bloqueado(get("dispositivos?select=id&limit=1"))),
        ("anon lê a carteira", lambda: bloqueado(get("movimentacoes_carteira?select=id&limit=1"))),
        ("anon lê o consumo do condomínio", lambda: bloqueado(get("consumo_horario?select=hora&limit=1"))),
        (f"{a['nome']} lê usuarios", lambda: bloqueado(get("usuarios?select=id&limit=1", token_a))),
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
        ("token forjado (assinatura errada)",
         lambda: get("carregadores?select=id&limit=1", token_a[:-4] + "AAAA").status_code in (401, 403)),
        # Controle positivo: se isto falhar, o token não está sendo aceito
        # e todos os "bloqueios" acima podem ser falsos positivos.
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
