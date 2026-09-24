"""
config.py - Ambiente, cliente do Supabase e constantes, num lugar só.
=====================================================================

Todo módulo do backend importa daqui. Antes, cada arquivo lia o .env por
conta própria e o MODO_DEMO existia em duas cópias (main.py e
hardware_api.py) - dava para ligar num e esquecer no outro.
"""

import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from supabase import Client, create_client

from seguranca import verificar_configuracao

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_URL e SUPABASE_KEY precisam estar no backend/.env "
        "(copie o backend/.env.example)."
    )

# Recusa subir com a chave anon ou com a JWK inválida (ver seguranca.py).
verificar_configuracao(SUPABASE_KEY)


# --- Transporte HTTP até o Supabase ----------------------------------------
# O supabase-py abre UMA conexão HTTP/2 e a divide entre todas as threads.
# Aqui há pelo menos duas ao mesmo tempo: o laço do simulador (a cada 10 s) e
# as requisições dos moradores. Quando o Supabase fecha essa conexão (ociosa
# ou GOAWAY), as duas caem juntas com "RemoteProtocolError: Server
# disconnected" - foi o 500 no /login.
#
# A troca: HTTP/1.1 com um POOL de conexões (cada thread pega a sua), conexão
# ociosa descartada antes de o servidor derrubá-la, e nova tentativa só
# quando repetir é seguro.

# Métodos que podem ser repetidos sem efeito duplicado. POST fica de fora:
# `debitar_saldo` e os INSERTs não podem rodar duas vezes. PATCH entra porque
# todo UPDATE do projeto grava valores absolutos (status = 'x', saldo vem por
# RPC), nunca "some 1".
_REPETIVEIS = {"GET", "HEAD", "PATCH", "DELETE", "OPTIONS"}
# Falhas em que a requisição comprovadamente NÃO saiu da máquina: qualquer
# método pode repetir.
_NUNCA_ENVIADA = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
# Conexão caiu no meio: só repete o que é repetível.
_CONEXAO_CAIU = (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)
TENTATIVAS_SUPABASE = 3


class TransporteComRetry(httpx.BaseTransport):
    """Embrulha o transporte real e repete o que é seguro repetir."""

    def __init__(self, interno: httpx.BaseTransport, tentativas: int = TENTATIVAS_SUPABASE,
                 espera_s: float = 0.2):
        self.interno = interno
        self.tentativas = max(1, tentativas)
        self.espera_s = espera_s

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        for tentativa in range(1, self.tentativas + 1):
            try:
                return self.interno.handle_request(request)
            except _NUNCA_ENVIADA:
                if tentativa == self.tentativas:
                    raise
            except _CONEXAO_CAIU:
                if request.method not in _REPETIVEIS or tentativa == self.tentativas:
                    raise
            print(f"[SUPABASE] conexão caiu ({request.method}), tentativa {tentativa + 1}"
                  f"/{self.tentativas}")
            time.sleep(self.espera_s * tentativa)
        raise RuntimeError("inalcançável")

    def close(self) -> None:
        self.interno.close()


def _sessao_http(base_url: str, headers) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        headers=headers,
        http2=False,
        follow_redirects=True,
        timeout=httpx.Timeout(20.0, connect=10.0),
        transport=TransporteComRetry(httpx.HTTPTransport(
            http2=False,
            # Descarta a conexão ociosa ANTES de o Supabase derrubá-la.
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10,
                                keepalive_expiry=15.0),
        )),
    )


supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Troca a sessão do PostgREST (tabelas e RPC - tudo que o backend usa) pela
# de cima, copiando endereço e cabeçalhos da original. Funciona em qualquer
# versão 2.x do supabase-py, com ou sem a opção `httpx_client`.
_postgrest = supabase.postgrest
_original = _postgrest.session
_postgrest.session = _sessao_http(str(_original.base_url), _original.headers)
_original.close()

# --- Modo de demonstração -------------------------------------------------
# MODO_DEMO=1 suspende a varredura de ESP32 mortos e libera as rotas /debug.
# NUNCA ligar com a placa conectada: as travas existem para não cobrar uma
# recarga que não vai acontecer.
MODO_DEMO = os.getenv("MODO_DEMO", "0") == "1"

# --- CORS -----------------------------------------------------------------
# Lista fechada de origens do frontend. Para abrir no celular, acrescente o
# endereço que o Vite mostra (ex.: http://192.168.0.10:5173).
FRONTEND_ORIGINS = [
    o.strip() for o in os.getenv(
        "FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if o.strip()
]

# Qualquer endereço de rede local na porta do Vite (celular, notebook do Gus,
# IP que muda a cada WiFi) sem editar o .env. Só IPs privados (RFC 1918) e
# localhost: nada da internet pública entra por aqui. Vazio desliga.
FRONTEND_ORIGIN_REGEX = os.getenv(
    "FRONTEND_ORIGIN_REGEX",
    r"http://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}):5173",
) or None

# --- Fuso ----------------------------------------------------------------
# Horário de ponta é local. O `tzdata` do requirements garante que isto
# funcione no Windows, que não traz a base de fusos do sistema.
try:
    FUSO = ZoneInfo(os.getenv("FUSO_HORARIO", "America/Sao_Paulo"))
except Exception:
    # tzdata não instalado (comum no Windows na primeira vez). Rode:
    #   pip install tzdata
    # Enquanto isso, usa UTC como fallback de segurança.
    from datetime import timezone as _tz
    FUSO = _tz.utc                      # type: ignore[assignment]
    print(
        "[CONFIG] AVISO: fuso 'America/Sao_Paulo' nao encontrado. "
        "Usando UTC como fallback.\n"
        "         Para corrigir: pip install tzdata\n"
        "         (o horario de ponta ficara desabilitado enquanto isso)"
    )

CONDOMINIO_PADRAO = "11111111-1111-1111-1111-111111111111"

# Prazo para aproximar o cartão depois de preparar a recarga.
SEGUNDOS_ESPERA_CARTAO = 120
# Tentativas de cartão com saldo insuficiente antes de recusar de vez.
MAX_TENTATIVAS_CARTAO = 3
# Sem contato por mais que isto, o ponto físico cai para offline.
SEGUNDOS_ATE_OFFLINE = 30
# Crédito máximo por operação na carteira simulada.
CREDITO_MAXIMO = 500.0

# Reserva mínima no cartão, como num posto ou num eletroposto de verdade:
# segura-se um valor de piso e devolve-se a diferença no fim. Sem piso, uma
# recarga de bancada reservaria R$ 0,01 e qualquer arredondamento de centavo
# já bateria no teto, encerrando a recarga cedo demais.
RESERVA_MINIMA = 1.00


def agora() -> datetime:
    """Sempre com fuso. `datetime.utcnow()` é ingênuo e está deprecado."""
    return datetime.now(timezone.utc)


def agora_iso() -> str:
    return agora().isoformat()


def para_datetime(valor) -> datetime | None:
    """Converte o timestamptz que o PostgREST devolve em datetime com fuso."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    texto = str(valor).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(texto)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def um(resposta) -> dict | None:
    """Primeira linha de uma consulta, ou None. Evita `.data[0]` explodindo."""
    dados = getattr(resposta, "data", None)
    return dados[0] if dados else None
