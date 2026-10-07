"""
seguranca.py - Identidade e segredos do ChargeOps, num lugar só.
=================================================================

Cinco responsabilidades, cada uma com UMA implementação:

  1. Senha de morador   -> Argon2id (hash lento, com salt, resistente a GPU)
  2. Token de sessão    -> JWT ES256 assinado com a NOSSA chave privada
  3. Token do ESP32 v1  -> SHA-256 (o token é longo e aleatório, ver abaixo)
  3b. Assinatura v2     -> HMAC-SHA256 com chave DERIVADA, nunca gravada
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

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import threading
import time
from collections import defaultdict, deque
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from dotenv import load_dotenv
from fastapi import Header, HTTPException, Request
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
    Dependência do FastAPI (Bloco 2): TODO endpoint de morador recebe a
    identidade daqui, e só daqui. Nenhum modelo Pydantic tem `usuario_id`.
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
# 2b. TOKEN ADMINISTRATIVO (painel do gestor) - ADR-023
# ===========================================================================
# O painel do gestor é OUTRO aplicativo, com OUTRA API e OUTRO token. A
# audiência é o que separa os dois mundos:
#
#   token do morador   aud = "authenticated"     aceito só na API pública
#   token do gestor    aud = "chargeops-admin"   aceito só na API administrativa
#
# `jwt.decode(..., audience=...)` recusa o token do lado errado. Um morador
# que copie o próprio token para a API administrativa recebe 401, e o token
# do gestor não abre nada na API pública nem no Supabase (não leva `role`).
# Opcionalmente a assinatura usa uma chave SEPARADA (ADMIN_JWT_PRIVATE_JWK):
# aí nem vazando a chave dos moradores se forja um token de gestor.

AUDIENCIA_ADMIN = "chargeops-admin"
TTL_ADMIN_MIN = int(os.getenv("ADMIN_JWT_TTL_MIN", "30"))


def _jwk_privada(bruto: str, nome: str):
    jwk = json.loads(bruto)
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256" or "d" not in jwk:
        raise RuntimeError(f"{nome} precisa ser uma chave PRIVADA EC P-256.")
    privada = ECAlgorithm.from_jwk(json.dumps(jwk))
    return jwk["kid"], privada, privada.public_key()


@lru_cache(maxsize=1)
def _chaves_admin():
    bruto = os.getenv("ADMIN_JWT_PRIVATE_JWK")
    if bruto:
        return _jwk_privada(bruto, "ADMIN_JWT_PRIVATE_JWK")
    return _chaves()


def emitir_token_admin(usuario_id: str, mfa: bool) -> dict:
    kid, privada, _ = _chaves_admin()
    agora = int(time.time())
    expira = agora + TTL_ADMIN_MIN * 60
    token = jwt.encode(
        {
            "sub": str(usuario_id),
            "aud": AUDIENCIA_ADMIN,
            "papel": "gestor",
            # Como a pessoa provou quem é (RFC 8176): senha, e código do app.
            "amr": ["pwd", "otp"] if mfa else ["pwd"],
            "iat": agora,
            "exp": expira,
        },
        privada,
        algorithm=ALGORITMO,
        headers={"kid": kid},
    )
    return {"token": token, "expira_em": expira}


def validar_token_admin(token: str) -> dict:
    """Devolve as claims do token administrativo, ou levanta jwt.InvalidTokenError."""
    _, _, publica = _chaves_admin()
    dados = jwt.decode(
        token,
        publica,
        algorithms=[ALGORITMO],
        audience=AUDIENCIA_ADMIN,
        options={"require": ["sub", "exp", "iat", "aud"]},
    )
    if dados.get("papel") != "gestor":
        raise jwt.InvalidTokenError("papel")
    return dados


def admin_atual(authorization: str = Header(None)) -> dict:
    """Dependência da API administrativa: só aceita o token administrativo."""
    erro = HTTPException(status_code=401, detail="Sessão inválida. Entre novamente.",
                         headers={"WWW-Authenticate": "Bearer"})
    if not authorization or not authorization.lower().startswith("bearer "):
        raise erro
    try:
        return validar_token_admin(authorization[7:].strip())
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sessão expirada. Entre novamente.",
                            headers={"WWW-Authenticate": "Bearer"})
    except jwt.InvalidTokenError:
        raise erro


# --- Segundo fator: TOTP (RFC 6238), o código de 6 dígitos do app autenticador
# Só biblioteca padrão: HMAC-SHA1, passo de 30 s - o que Google Authenticator,
# Microsoft Authenticator, Authy e 1Password esperam.

TOTP_PASSO_S = 30
TOTP_DIGITOS = 6


def gerar_segredo_totp() -> str:
    """160 bits em base32, sem '=' (formato que os apps aceitam colar)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _totp_no_passo(segredo_b32: str, passo: int) -> str:
    limpo = segredo_b32.strip().replace(" ", "").upper()
    chave = base64.b32decode(limpo + "=" * (-len(limpo) % 8))
    mac = hmac.new(chave, struct.pack(">Q", passo), hashlib.sha1).digest()
    desloc = mac[-1] & 0x0F
    numero = struct.unpack(">I", mac[desloc:desloc + 4])[0] & 0x7FFFFFFF
    return str(numero % 10 ** TOTP_DIGITOS).zfill(TOTP_DIGITOS)


def codigo_totp(segredo_b32: str, quando: float | None = None) -> str:
    """O código que o app mostra agora. Usado pelos testes e pelo provisionar."""
    return _totp_no_passo(segredo_b32, int((quando if quando is not None else time.time())
                                           // TOTP_PASSO_S))


def conferir_totp(segredo_b32: str, codigo: str, ultimo_passo: int | None = None,
                  quando: float | None = None) -> int | None:
    """
    Devolve o PASSO que casou (para gravar e impedir reuso), ou None.

    Aceita o passo atual e um vizinho de cada lado (relógio do celular até
    30 s fora). `ultimo_passo` é o último código já usado: o mesmo código não
    vale duas vezes, então quem olhou a tela por cima do ombro não entra.
    """
    codigo = re.sub(r"\s", "", codigo or "")
    if not (codigo.isdigit() and len(codigo) == TOTP_DIGITOS):
        return None
    atual = int((quando if quando is not None else time.time()) // TOTP_PASSO_S)
    achado = None
    for passo in (atual - 1, atual, atual + 1):
        try:
            esperado = _totp_no_passo(segredo_b32, passo)
        except (ValueError, TypeError):
            return None
        # Sem `break`: compara os três sempre, em tempo constante.
        if hmac.compare_digest(esperado, codigo) and (ultimo_passo is None or passo > ultimo_passo):
            achado = passo if achado is None else achado
    return achado


def uri_totp(segredo_b32: str, conta: str, emissor: str = "GoodWe ChargeOps ADM") -> str:
    """O endereço otpauth:// que vira QR code no app autenticador."""
    from urllib.parse import quote
    return (f"otpauth://totp/{quote(emissor)}:{quote(conta)}?secret={segredo_b32}"
            f"&issuer={quote(emissor)}&algorithm=SHA1&digits={TOTP_DIGITOS}&period={TOTP_PASSO_S}")


# O segredo do TOTP precisa ser legível pelo servidor (não dá para guardar só
# o hash, como a senha). Por isso vai CIFRADO para o banco, com uma chave que
# mora só no ambiente: vazou só o banco, ninguém gera código.

@lru_cache(maxsize=1)
def _cofre_mfa():
    from cryptography.fernet import Fernet
    bruto = (os.getenv("ADMIN_MFA_KEY") or "").strip()
    if len(bruto) < 32:
        raise RuntimeError("ADMIN_MFA_KEY não definida (mínimo 32 caracteres). Gere com: "
                           "python provisionar.py chave-mfa")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(bruto.encode("utf-8")).digest()))


def mfa_configurado() -> bool:
    try:
        _cofre_mfa()
        return True
    except RuntimeError:
        return False


def cifrar_segredo_mfa(segredo_b32: str) -> str:
    return _cofre_mfa().encrypt(segredo_b32.encode("ascii")).decode("ascii")


def decifrar_segredo_mfa(cifrado: str) -> str:
    return _cofre_mfa().decrypt(cifrado.encode("ascii")).decode("ascii")


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
# 3b. PROTOCOLO v2 DO ESP32 - HMAC com chave derivada (ADR-015, D2)
# ===========================================================================
# HMAC exige que o servidor conheça o segredo. Se o banco guardasse só o hash
# do token e esse hash fosse a chave, o hash VIRARIA a chave: vazou o banco,
# forja-se qualquer placa. Por isso a chave de cada placa é DERIVADA:
#
#     K = HMAC-SHA256(DEVICE_MASTER_KEY, "chargeops-v2|<dispositivo_id>|<versao>")
#
# A chave-mestra mora só no .env. O banco guarda o id e a versão - nada
# secreto. Vazou só o banco: não forja. Vazou o .env: forja (mesmo nível da
# JWT_PRIVATE_JWK, que já mora lá). Rotação: `chave_versao + 1`.
#
# O que é assinado (uma linha por campo, nesta ordem):
#     MÉTODO \n caminho \n boot \n seq \n ts \n sha256_hex(corpo)
# Caminho sem query string (ex.: /hardware/v2/telemetria). Corpo vazio = b"".

PREFIXO_DERIVACAO = "chargeops-v2"


@lru_cache(maxsize=1)
def _chave_mestra() -> bytes:
    bruto = (os.getenv("DEVICE_MASTER_KEY") or "").strip()
    if not bruto:
        raise RuntimeError("DEVICE_MASTER_KEY não definida no .env. Gere com: "
                           "python provisionar.py chave-mestra")
    try:
        chave = bytes.fromhex(bruto)
    except ValueError:
        raise RuntimeError("DEVICE_MASTER_KEY precisa ser hexadecimal (64 caracteres).")
    if len(chave) < 32:
        raise RuntimeError("DEVICE_MASTER_KEY precisa ter pelo menos 32 bytes (64 hex).")
    return chave


def protocolo_v2_configurado() -> bool:
    try:
        _chave_mestra()
        return True
    except RuntimeError:
        return False


def gerar_chave_mestra() -> str:
    return secrets.token_hex(32)


def chave_dispositivo(dispositivo_id: str, versao: int) -> bytes:
    """A chave que a placa usa. Calculada a cada requisição, nunca gravada."""
    rotulo = f"{PREFIXO_DERIVACAO}|{dispositivo_id}|{int(versao)}".encode("utf-8")
    return hmac.new(_chave_mestra(), rotulo, hashlib.sha256).digest()


def mensagem_v2(metodo: str, caminho: str, boot: int, seq: int, ts: int, corpo: bytes) -> bytes:
    return "\n".join([metodo.upper(), caminho, str(int(boot)), str(int(seq)), str(int(ts)),
                      hashlib.sha256(corpo or b"").hexdigest()]).encode("utf-8")


def assinar_v2(chave: bytes, metodo: str, caminho: str, boot: int, seq: int, ts: int,
               corpo: bytes) -> str:
    """Mesma conta que o firmware faz. Usado pelos testes e pelo simulador."""
    return hmac.new(chave, mensagem_v2(metodo, caminho, boot, seq, ts, corpo),
                    hashlib.sha256).hexdigest()


def assinatura_v2_confere(chave: bytes, assinatura_hex: str, metodo: str, caminho: str,
                          boot: int, seq: int, ts: int, corpo: bytes) -> bool:
    esperada = assinar_v2(chave, metodo, caminho, boot, seq, ts, corpo)
    # Tempo constante: comparar com == vazaria quantos caracteres batem.
    return hmac.compare_digest(esperada, (assinatura_hex or "").strip().lower())


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

    def consumir(self, *chaves: str) -> None:
        """Conta TODA chamada, não só falha: vira limite de taxa (rate limit)."""
        self.verificar(*chaves)
        self.registrar_falha(*chaves)


# 5 erros por nome em 5 min protege uma conta; 20 por IP freia quem testa
# muitos nomes com a mesma senha (password spraying).
limitador_por_nome = LimitadorTentativas(maximo=5, janela_s=300)
limitador_por_ip = LimitadorTentativas(maximo=20, janela_s=300)

# Cadastro: 5 contas por IP a cada 10 min. Sem isto, um script cria milhares
# de contas e cada uma ganha o crédito inicial.
limitador_cadastro = LimitadorTentativas(maximo=5, janela_s=600)

# Painel do gestor: mais apertado que o do morador. 5 erros por nome em 15 min
# e 10 por IP - quem administra não erra a senha vinte vezes.
limitador_admin_nome = LimitadorTentativas(maximo=5, janela_s=900)
limitador_admin_ip = LimitadorTentativas(maximo=10, janela_s=900)

# Chatbot: 20 mensagens por minuto por morador. Cada mensagem pode virar
# chamada paga ao modelo na nuvem - sem teto, um laço esgota a cota da demo.
limitador_chat = LimitadorTentativas(maximo=20, janela_s=60)


# ===========================================================================
# 4b. IP DE QUEM CHAMA (atrás de proxy)
# ===========================================================================
# Publicado, o backend fica atrás do proxy da hospedagem: `request.client.host`
# passa a ser o IP do PROXY, igual para todo mundo. O limite por IP viraria um
# limite global - 20 senhas erradas de qualquer pessoa trancariam o login de
# todos. O IP real vem em X-Forwarded-For, mas esse cabeçalho é texto livre:
# só vale a parte que os NOSSOS proxies escreveram. Cada proxy acrescenta o IP
# de quem falou com ele no FIM da lista; com N proxies confiáveis, o cliente
# é o N-ésimo a partir do fim. O que estiver antes foi o cliente que mandou e
# pode ser mentira.
#
# PROXIES_CONFIAVEIS=0 (padrão, rede local): ignora o cabeçalho.
# PROXIES_CONFIAVEIS=1: Render, Railway, Fly, um Nginx/Caddy na frente.

PROXIES_CONFIAVEIS = max(0, int(os.getenv("PROXIES_CONFIAVEIS", "0") or 0))


def ip_do_cliente(request: Request, proxies: int | None = None) -> str:
    direto = request.client.host if request.client else "desconhecido"
    n = PROXIES_CONFIAVEIS if proxies is None else proxies
    if n <= 0:
        return direto
    partes = [p.strip() for p in (request.headers.get("x-forwarded-for") or "").split(",")
              if p.strip()]
    if len(partes) < n:
        return direto
    return partes[-n][:64]


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
    _chaves_admin()
