"""
config.py - Ambiente, cliente do Supabase e constantes, num lugar só.
=====================================================================

Todo módulo do backend importa daqui. Antes, cada arquivo lia o .env por
conta própria e o MODO_DEMO existia em duas cópias (main.py e
hardware_api.py) - dava para ligar num e esquecer no outro.
"""

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

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

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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
