"""
Camada 4 - AUDITORIA.
=====================

Cada troca vira duas linhas em `chat_mensagens`: a pergunta e a resposta. A
linha da resposta carrega o "porquê" - intenção, QUAL camada decidiu
(entrada, contexto, redacao_llm, redacao_regras, saida), se foi bloqueada,
o motivo, o modelo e a latência.

É com isso que se responde, depois do fato: "quantas tentativas de injeção
tivemos esta semana?", "quantas respostas do modelo a camada de saída
reprovou?", "o modelo de nuvem está lento?".

Falha de log NUNCA derruba a resposta.
"""

from .deps import sb


def registrar(usuario_id, charger_id, pergunta: str, resposta: str, *, intencao: str,
              camada: str, bloqueado: bool, motivo: str | None, modelo: str,
              latencia_ms: int) -> None:
    try:
        sb().table("chat_mensagens").insert([
            {"usuario_id": usuario_id, "carregador_id": charger_id,
             "remetente": "usuario", "mensagem": (pergunta or "")[:2000]},
            {"usuario_id": usuario_id, "carregador_id": charger_id,
             "remetente": "bot", "mensagem": resposta,
             "intencao": intencao, "camada": camada, "bloqueado": bloqueado,
             "motivo": motivo, "modelo": modelo, "latencia_ms": latencia_ms},
        ]).execute()
    except Exception as e:
        print(f"[CHATBOT/AUDITORIA] falhou: {e}")
