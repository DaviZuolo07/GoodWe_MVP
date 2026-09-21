"""
seguranca.py - Identidade e segredos do ChargeOps, num lugar só.
=================================================================

Quatro responsabilidades, cada uma com UMA implementação:

  1. Senha de morador   -> Argon2id (hash lento, com salt, resistente a GPU)
  2. Token de sessão    -> JWT ES256 assinado com a NOSSA chave privada
  3. Token do ESP32     -> SHA-256 (o token é longo e aleatório, ver abaixo)
  4. Força bruta        -> limitador de tentativas no /login

POR QUE DOIS HASHES DIFERENTES (Argon2 para senha, SHA-256 para o ESP32)
-----------------------------------------------------------------------
Senha humana é fraca: "goodwe123" cai em segundos num ataque de dicionário
se o hash for rápido. O Argon2 é lento DE PROPÓSITO e gasta memória, o que
torna cada chute caro.

O token do ESP32 é gerado por `secrets.token_urlsafe(32)`: 256 bits de
aleatoriedade. Não existe dicionário para isso, então um hash rápido basta.
E precisa ser rápido: a placa autentica a cada 2 segundos.

POR QUE O SUPABASE ACEITA NOSSO TOKEN
------------------------------------
A chave pública correspondente à JWT_PRIVATE_JWK foi importada no painel do
Supabase (Settings -> JWT Keys) e rotacionada para "em uso". O PostgREST e
o Realtime verificam a assinatura, leem `sub` como auth.uid() e aplicam as
políticas de RLS em nome do morador. A chave privada NUNCA sai do backend.
"""

import hashlib
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from dotenv import load_dotenv
from fastapi import Header, HTTPException
from jwt.algorithms import ECAlgorithm

# O main.py importa módulos que importam este ANTES de chamar load_dotenv().
# Carregar aqui também é idempotente e remove a dependência de ordem.
load_dotenv()

ALGORITMO = "ES256"
AUDIENCIA = "authenticated"          # a mesma dos tokens do Supabase Auth
TTL_MIN = int(os.getenv("JWT_TTL_MIN", "120"))

SENHA_MIN = 8
SENHA_MAX = 128                      # Argon2 de string gigante vira DoS


# ===========================================================================
# 1. SENHA
# ===========================================================================

# Parâmetros padrão da argon2-cffi (Argon2id, RFC 9106 perfil "low memory").
_hasher = PasswordHasher()


def gerar_hash_senha(senha: str) -> str:
    return _hasher.hash(senha)


def conferir_senha(hash_salvo: str, senha: str) -> bool:
    try:
        return _hasher.verify(hash_salvo, senha)
    except (VerificationError, InvalidHashError):
        return False


def precisa_rehash(hash_salvo: str) -> bool:
    """True se os parâmetros do Argon2 ficaram mais fortes desde o hash."""
    return _hasher.check_needs_rehash(hash_salvo)


@lru_cache(maxsize=1)
def hash_ficticio() -> str:
    """
    Usado quando o nome digitado não existe. O backend confere a senha contra
    este hash mesmo assim, para a resposta demorar o mesmo tanto nos dois
    casos. Sem isso, medir o tempo de resposta revelaria quais nomes estão
    cadastrados (enumeração de usuários).
    """
    return _hasher.hash(secrets.token_urlsafe(16))


def validar_forca_senha(senha: str, nome: str = "") -> None:
    if len(senha) < SENHA_MIN:
        raise HTTPException(status_code=400,
                            detail=f"A senha precisa ter pelo menos {SENHA_MIN} caracteres.")
    if len(senha) > SENHA_MAX:
        raise HTTPException(status_code=400, detail="Senha longa demais.")
    if nome and senha.strip().lower() == nome.strip().lower():
        raise HTTPException(status_code=400, detail="A senha não pode ser igual ao nome.")


# ===========================================================================
# 2. TOKEN DE SESSÃO (JWT)
# ===========================================================================

@lru_cache(maxsize=1)
def _chaves():
    """Carrega a chave uma vez, na primeira utilização."""
    bruto = os.getenv("JWT_PRIVATE_JWK")
    if not bruto:
        raise RuntimeError(
            "JWT_PRIVATE_JWK não definida no .env. Gere com: "
            "python provisionar.py chave-jwt"
        )
    jwk = json.loads(bruto)
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256" or "d" not in jwk:
        raise RuntimeError("JWT_PRIVATE_JWK precisa ser uma chave PRIVADA EC P-256.")
    privada = ECAlgorithm.from_jwk(json.dumps(jwk))
    return jwk["kid"], privada, privada.public_key()


def emitir_token(usuario_id: str) -> dict:
    """
    Token curto, amarrado a um usuário. `role` e `aud` são os que o Supabase
    espera para tratar a requisição como um morador logado.
    """
    kid, privada, _ = _chaves()
    agora = int(time.time())
    expira = agora + TTL_MIN * 60
    token = jwt.encode(
        {
            "sub": str(usuario_id),
            "role": "authenticated",
            "aud": AUDIENCIA,
            "iat": agora,
            "exp": expira,
        },
        privada,
        algorithm=ALGORITMO,
        headers={"kid": kid},
    )
    return {"token": token, "expira_em": expira}


def validar_token(token: str) -> str:
    """Devolve o usuario_id do token, ou levanta jwt.InvalidTokenError."""
    _, _, publica = _chaves()
    dados = jwt.decode(
        token,
        publica,
        algorithms=[ALGORITMO],          # lista fechada: impede o ataque alg=none
        audience=AUDIENCIA,
        options={"require": ["sub", "exp", "iat"]},
    )
    return dados["sub"]


def usuario_atual(authorization: str = Header(None)) -> str:
    """
    Dependência do FastAPI. No Bloco 2 ela entra em todo endpoint que hoje
    recebe `usuario_id` no corpo: a identidade passa a vir daqui, e só daqui.
    """
    erro = HTTPException(
        status_code=401,
        detail="Sessão inválida. Entre novamente.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise erro
    try:
        return validar_token(authorization[7:].strip())
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sessão expirada. Entre novamente.",
                            headers={"WWW-Authenticate": "Bearer"})
    except jwt.InvalidTokenError:
        raise erro


# ===========================================================================
# 3. TOKEN DO DISPOSITIVO (ESP32)
# ===========================================================================

def gerar_token_dispositivo() -> str:
    return "gw_dev_" + secrets.token_urlsafe(32)


def hash_token_dispositivo(token: str) -> str:
    """
    O banco guarda só isto. Quem ler a tabela `dispositivos` não consegue se
    passar pela placa. E como a busca é pelo hash, o tempo da consulta não
    revela nada sobre o token enviado.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ===========================================================================
# 4. LIMITADOR DE TENTATIVAS
# ===========================================================================

class LimitadorTentativas:
    """
    Conta falhas por chave numa janela deslizante. Vive na memória do
    processo: correto para o backend rodando localmente num processo só.
    Com vários processos ou servidores, o contador precisaria ir para um
    armazenamento compartilhado (Redis).
    """

    def __init__(self, maximo: int, janela_s: int):
        self.maximo = maximo
        self.janela_s = janela_s
        self._falhas = defaultdict(deque)
        self._lock = threading.Lock()

    def _limpar_velhas(self, chave: str, agora: float) -> deque:
        fila = self._falhas[chave]
        while fila and agora - fila[0] > self.janela_s:
            fila.popleft()
        return fila

    def verificar(self, *chaves: str) -> None:
        agora = time.monotonic()
        with self._lock:
            for chave in chaves:
                fila = self._limpar_velhas(chave, agora)
                if len(fila) >= self.maximo:
                    espera = int(self.janela_s - (agora - fila[0])) + 1
                    raise HTTPException(
                        status_code=429,
                        detail=f"Muitas tentativas. Tente de novo em {espera} segundos.",
                        headers={"Retry-After": str(espera)},
                    )

    def registrar_falha(self, *chaves: str) -> None:
        agora = time.monotonic()
        with self._lock:
            for chave in chaves:
                self._falhas[chave].append(agora)

    def limpar(self, *chaves: str) -> None:
        with self._lock:
            for chave in chaves:
                self._falhas.pop(chave, None)


# 5 erros por nome em 5 min protege uma conta; 20 por IP freia quem testa
# muitos nomes com a mesma senha (password spraying).
limitador_por_nome = LimitadorTentativas(maximo=5, janela_s=300)
limitador_por_ip = LimitadorTentativas(maximo=20, janela_s=300)


# ===========================================================================
# 5. CHECAGEM DE CONFIGURAÇÃO (fail fast no boot)
# ===========================================================================

def verificar_configuracao(chave_supabase: str) -> None:
    """
    Chamada no início do main.py. Com o RLS ligado, um backend usando a chave
    anon não quebra: ele recebe listas VAZIAS e parece que o banco sumiu.
    Melhor recusar subir com uma mensagem clara.
    """
    if chave_supabase.startswith("sb_publishable_"):
        raise RuntimeError(
            "SUPABASE_KEY do backend é a chave PUBLICÁVEL. O backend precisa da "
            "chave secreta (sb_secret_...) ou da service_role."
        )
    if not chave_supabase.startswith("sb_secret_"):
        try:
            papel = jwt.decode(chave_supabase, options={"verify_signature": False}).get("role")
        except jwt.InvalidTokenError:
            raise RuntimeError("SUPABASE_KEY não parece uma chave do Supabase.")
        if papel != "service_role":
            raise RuntimeError(
                f"SUPABASE_KEY do backend tem papel '{papel}'. Use a service_role "
                "(Settings -> API Keys). Com a anon, o RLS devolve tudo vazio."
            )
    _chaves()  # falha agora, e não no primeiro login, se a JWK estiver errada
