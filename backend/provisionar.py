"""
provisionar.py - Tarefas de segurança que rodam UMA vez, fora da API.
=====================================================================

Rodar de dentro da pasta backend/, com o .env preenchido:

  python provisionar.py chave-jwt
      Gera o par de chaves ES256. Imprime a JWK privada para importar no
      Supabase e a linha pronta para o .env. Não grava nada em disco.

  python provisionar.py senhas-demo --senha "SuaSenhaDemo#2026"
      Dá senha a todo usuário do seed que ainda não tem credencial.
      Nunca sobrescreve quem já tem (use --forcar para isso).

  python provisionar.py token-esp --carregador <uuid-do-carregador>
      Gera o token novo do ESP32, grava só o hash e mostra o token UMA vez.

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
    print("Cole em DEVICE_TOKEN no firmware/chargeops_esp32.ino e grave na placa.")
    print("O token antigo deixou de funcionar.\n")


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
        (f"{a['nome']} lê usuarios", lambda: bloqueado(get("usuarios?select=id&limit=1", token_a))),
        (f"{a['nome']} lê notificações de {b['nome']}",
         lambda: bloqueado(get(f"notificacoes?select=id&usuario_id=eq.{b['id']}", token_a))),
        (f"{a['nome']} lê veículos de {b['nome']}",
         lambda: bloqueado(get(f"veiculos?select=id&usuario_id=eq.{b['id']}", token_a))),
        (f"{a['nome']} lê sessões de {b['nome']}",
         lambda: bloqueado(get(f"sessoes_recarga?select=id&usuario_id=eq.{b['id']}", token_a))),
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

    sub.add_parser("verificar").set_defaults(fn=cmd_verificar)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
