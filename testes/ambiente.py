"""
Ambiente falso para os testes: gera uma chave JWT descartável e aponta o
Supabase para um endereço que nunca é chamado. Os testes daqui cobrem as
funções PURAS (física, demanda, camadas do chatbot, token); nenhum toca rede.
Importe este módulo ANTES de qualquer módulo do backend.
"""

import base64
import json
import os
import sys
import uuid

from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _b64(n: int) -> str:
    return base64.urlsafe_b64encode(n.to_bytes(32, "big")).rstrip(b"=").decode()


if not os.getenv("JWT_PRIVATE_JWK"):
    k = ec.generate_private_key(ec.SECP256R1()).private_numbers()
    os.environ["JWT_PRIVATE_JWK"] = json.dumps({
        "kty": "EC", "crv": "P-256", "kid": str(uuid.uuid4()), "d": _b64(k.private_value),
        "x": _b64(k.public_numbers.x), "y": _b64(k.public_numbers.y)})
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:9")
os.environ.setdefault("SUPABASE_KEY", "sb_secret_teste_local")
os.environ.setdefault("CHAT_MODO", "regras")


def usar_supabase_falso():
    """Troca o cliente ANTES de importar os módulos que fazem `from config import supabase`."""
    import config
    from supabase_falso import FakeSupabase
    config.supabase = FakeSupabase()
    return config.supabase
