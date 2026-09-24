"""
Camada 1 - ENTRADA.
===================

Roda antes de qualquer consulta ao banco ou chamada ao modelo. Se ela barra,
nada mais acontece: a resposta é a recusa padrão e a auditoria registra
`camada = entrada`.

1. Normalização    NFKC (letras "estilizadas" viram letras normais), remove
                   caracteres invisíveis de largura zero e de controle - o
                   truque clássico de esconder "ignore suas regras" entre
                   caracteres que o regex não vê.
2. Tamanho         500 caracteres. Mensagem de painel operacional não precisa
                   de mais; prompt de ataque longo precisa.
3. Injeção         regex de padrões conhecidos (router.PADROES_INJECAO) e
                   marcadores de formato de prompt: "system:", "[INST]",
                   "<|im_start|>", blocos de código, e blobs em base64.
"""

import re
import unicodedata

from . import router as R

INVISIVEIS = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MARCADORES = [
    r"^\s*(system|assistant|developer)\s*:",
    r"\[/?inst\]|<\|im_(start|end)\|>|<\|?system\|?>",
    r"```",
    r"</?(instru|system|prompt|fatos)",
    r"[a-z0-9+/]{48,}={0,2}",                    # base64 escondendo instrução
    r"jailbreak|\bdan\b\s+mode|sem\s+restri[cç][oõ]es",
    r"(mostre|liste|exiba)\s+(todos\s+os\s+)?(usuarios|moradores|saldos|tabelas)",
    r"token|senha\s+d[eo]|api[\s_-]?key|service[\s_]?role",
]


def processar(mensagem: str) -> dict:
    """{"texto": str limpo, "bloqueado": bool, "motivo": str|None}"""
    bruto = mensagem or ""
    texto = unicodedata.normalize("NFKC", bruto)
    texto = INVISIVEIS.sub("", texto)
    texto = CONTROLE.sub(" ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    if len(texto) > R.LIMITE_CARACTERES:
        return {"texto": texto[:R.LIMITE_CARACTERES], "bloqueado": True, "motivo": "mensagem_longa_demais"}

    teve_invisivel = texto != re.sub(r"\s+", " ", CONTROLE.sub(" ", unicodedata.normalize("NFKC", bruto))).strip()
    norm = R.normalizar(texto)

    for padrao in R.PADROES_INJECAO:
        if re.search(padrao, norm):
            return {"texto": texto, "bloqueado": True, "motivo": f"injecao:{padrao[:30]}"}
    for padrao in MARCADORES:
        if re.search(padrao, norm, flags=re.MULTILINE):
            return {"texto": texto, "bloqueado": True, "motivo": f"marcador:{padrao[:30]}"}
    if teve_invisivel and len(texto) > 40:
        return {"texto": texto, "bloqueado": True, "motivo": "caracteres_invisiveis"}

    return {"texto": texto, "bloqueado": False, "motivo": None}
