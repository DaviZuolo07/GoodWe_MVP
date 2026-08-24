"""
Contexto injetado pelo main.py no startup.

O módulo do chatbot NÃO importa o main.py - se importasse, teríamos import
circular (main importa chatbot, chatbot importaria main). Em vez disso, o
main.py chama `configurar_chatbot(...)` uma vez e entrega aqui o cliente do
Supabase e as funções de física que já existem.

Consequência importante: o chatbot NUNCA recalcula tempo, energia ou custo por
conta própria. Ele chama a mesma `calcular_estimativa` que o /charge/start usa.
Duas contas divergentes é pior que nenhuma.
"""


class _Contexto:
    supabase = None
    calcular_estimativa = None
    custo_da_sessao = None
    condominio_padrao = None


CTX = _Contexto()


def configurar(supabase, calcular_estimativa=None, custo_da_sessao=None,
               condominio_padrao=None):
    CTX.supabase = supabase
    CTX.calcular_estimativa = calcular_estimativa
    CTX.custo_da_sessao = custo_da_sessao
    CTX.condominio_padrao = condominio_padrao


def sb():
    """Cliente do Supabase, ou erro claro se o startup esqueceu de configurar."""
    if CTX.supabase is None:
        raise RuntimeError(
            "chatbot não configurado: chame configurar_chatbot(supabase=...) "
            "no main.py antes de usar o endpoint /chatbot."
        )
    return CTX.supabase
