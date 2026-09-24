"""
Prompt loader.

Os prompts moram em `chatbot/prompts/`, fora do código Python. Assim dá para
ajustar o tom do bot sem tocar em lógica, e cada mudança de prompt aparece
como diff no git - que é o que permite dizer para a banca "esta é a versão do
prompt que gravou o vídeo".

Em desenvolvimento (OLLAMA_DEV=1) o cache é desligado: salvou o .md, a próxima
mensagem já usa o texto novo, sem reiniciar o uvicorn.
"""

import os
import json
from pathlib import Path

PASTA = Path(__file__).parent / "prompts"
DEV = os.getenv("OLLAMA_DEV", "0") == "1"

_cache = {}


def carregar_prompt(nome: str) -> str:
    if not DEV and nome in _cache:
        return _cache[nome]

    caminho = PASTA / nome
    try:
        texto = caminho.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"[CHATBOT] prompt não encontrado: {caminho}")
        texto = ""

    _cache[nome] = texto
    return texto


def carregar_few_shot(nome: str = "few_shot.json") -> list:
    """
    Exemplos de conversa. Inclui recusas de propósito: um modelo que só viu
    acertos aprende a sempre responder, inclusive o que não devia.
    """
    if not DEV and nome in _cache:
        return _cache[nome]

    try:
        dados = json.loads((PASTA / nome).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[CHATBOT] few-shot indisponível ({e})")
        dados = []

    _cache[nome] = dados
    return dados
