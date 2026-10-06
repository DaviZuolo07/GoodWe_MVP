"""
config.py - Configuração do totem virtual.
==========================================

Tudo vem de `totem_virtual/.env` (que NÃO vai para o git) ou do ambiente.
A chave da placa sai de `provisionar.py placa-v2`, rodado pelo Daniel, e
chega por canal privado. Ela fica só neste processo: nunca vai para a página.

As constantes de tempo estão em milissegundos porque é assim que o firmware
vai escrevê-las (comparações com millis()).
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

PASTA = Path(__file__).resolve().parent
RAIZ = PASTA.parent

# --- Tempos da máquina de estados (iguais no firmware) ----------------------
TIMEOUT_ESCOLHA_MS = 15_000      # contrato: 15 s para apertar o botão da vaga
TELA_MS = 4_000                  # quanto tempo a resposta fica no LCD
AVISO_MS = 2_000                 # avisos curtos ("aproxime a tag primeiro")
MEDICAO_MS = 200                 # lê o INA219 e integra energia
TROCA_FONTE_MS = 200             # abre uma fonte antes de fechar a outra
QUEDA_MS = 1_000                 # tensão baixa precisa durar isto para valer
RETENTATIVA_MIN_MS = 1_000       # espera entre tentativas de rede (dobra até o teto)
RETENTATIVA_MAX_MS = 10_000

# --- Limites do protocolo v2 (ADR-015 D4) ------------------------------------
MAX_LEITURAS_LOTE = 30
MAX_FONTES_LOTE = 20
CORPO_MAX_BYTES = 7_000          # o servidor recusa acima de 8 KB; margem para o JSON
FILA_LEITURAS_MAX = 240          # o que cabe guardar sem rede (RAM do ESP32)
FILA_FONTES_MAX = 120

# --- Fontes da vaga 4: limiares a CALIBRAR na bancada real -------------------
PORTA_SOLAR = 4
V_PAINEL_ENTRA = 5.60            # painel assume a vaga a partir desta tensão
V_BARRA_MINIMA = 4.75            # abaixo disto por QUEDA_MS, o painel não aguenta
V_BATERIA_CORTE = 3.30           # protege a 18650
V_BATERIA_VOLTA = 3.60


def _ler_env(caminho: Path) -> dict:
    """Leitor mínimo de .env (CHAVE=valor, # comentário). Evita uma dependência."""
    dados = {}
    if not caminho.is_file():
        return dados
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        valor = valor.split(" #", 1)[0].strip().strip('"').strip("'")
        dados[chave.strip()] = valor
    return dados


@dataclass
class Config:
    backend_url: str = "http://127.0.0.1:8000"
    dispositivo_id: str = ""
    chave_hex: str = ""
    amostra_ms: int = 2_000          # uma leitura por vaga a cada N ms
    envio_ms: int = 6_000            # um lote a cada N ms
    comandos_ms: int = 2_000         # o handshake pode trocar este valor
    offline_corte_ms: int = 120_000  # ADR-020 P2
    http_timeout_s: float = 3.0
    painel_porta: int = 8765
    roteiro_espera_s: float = 90.0
    tags: dict = field(default_factory=dict)        # apelido -> uid
    app_contas: list = field(default_factory=list)  # [(nome, senha)] - só para o roteiro

    def pronta(self) -> bool:
        return bool(self.dispositivo_id and self.chave_hex)


def carregar(caminho: Path | None = None) -> Config:
    env = {**_ler_env(caminho or PASTA / ".env"), **os.environ}

    def n(chave, padrao):
        try:
            return float(env.get(chave, padrao))
        except ValueError:
            raise SystemExit(f"{chave} precisa ser um número (veio '{env.get(chave)}').")

    tags = {apelido: env[f"TAG_{apelido}"].strip().upper()
            for apelido in ("A", "B", "SEM_SALDO", "DESCONHECIDA") if env.get(f"TAG_{apelido}")}
    contas = [tuple(par.split(":", 1)) for par in env.get("APP_CONTAS", "").split(",") if ":" in par]
    return Config(
        backend_url=env.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/"),
        dispositivo_id=env.get("DEVICE_ID", "").strip(),
        chave_hex=env.get("DEVICE_KEY_HEX", "").strip(),
        amostra_ms=int(n("TOTEM_AMOSTRA_S", 2) * 1000),
        envio_ms=int(n("TOTEM_ENVIO_S", 6) * 1000),
        offline_corte_ms=int(n("TOTEM_OFFLINE_CORTE_S", 120) * 1000),
        painel_porta=int(n("PAINEL_PORTA", 8765)),
        roteiro_espera_s=n("ROTEIRO_ESPERA_S", 90),
        tags=tags, app_contas=contas)
