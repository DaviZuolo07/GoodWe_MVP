"""
GoodWe ChargeOps AI Assistant - assistente de recarga, em camadas (Bloco 4).

    entrada.py    Camada 1: limpa, limita e barra injeção ANTES de tudo
    contexto.py   Camada 2: identidade do token + local da allowlist
    router.py     classifica a intenção (regex; LLM só se o regex não decidir)
    dados.py      funções de leitura whitelisted - o modelo nunca escreve SQL
    llm.py        redação pelo modelo, a partir de fatos prontos
    saida.py      Camada 3: número sem lastro, vazamento, tamanho -> reprova
    respostas.py  redator determinístico (fallback e rede de segurança)
    auditoria.py  Camada 4: grava pergunta, resposta e QUAL camada decidiu
    servico.py    orquestra as camadas

Uso no main.py:
    configurar_chatbot(supabase=..., calcular_estimativa=..., ...)
    responder_chatbot(mensagem, usuario_id, charger_id, condominio_id)
"""

from .deps import configurar as configurar_chatbot
from .servico import responder as responder_chatbot

__all__ = ["configurar_chatbot", "responder_chatbot"]
