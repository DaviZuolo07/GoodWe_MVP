"""
GoodWe ChargeOps AI Assistant - módulo do chatbot.

Uso no main.py (duas linhas, nada mais):

    from chatbot import configurar_chatbot, responder_chatbot

    configurar_chatbot(
        supabase=supabase,
        calcular_estimativa=calcular_estimativa,
        condominio_padrao=CONDOMINIO_PADRAO,
    )

    @app.post("/chatbot")
    def chatbot(payload: ChatRequest):
        return responder_chatbot(payload.message, payload.usuario_id,
                                 payload.charger_id, payload.condominio_id)
"""

from .contexto import configurar as configurar_chatbot
from .servico import responder as responder_chatbot

__all__ = ["configurar_chatbot", "responder_chatbot"]
