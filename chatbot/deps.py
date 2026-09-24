"""
deps.py - Dependências injetadas pelo main.py no startup.

O chatbot NÃO importa o main.py (import circular). O main chama
`configurar_chatbot(...)` uma vez e entrega aqui o cliente do Supabase e as
funções de física que já existem - o chatbot nunca recalcula tempo, energia
ou custo por conta própria. Duas contas divergentes é pior que nenhuma.
"""


class _Deps:
    supabase = None
    calcular_estimativa = None
    custo_da_sessao = None
    condominio_padrao = None
    locais_do_usuario = None


CTX = _Deps()


def configurar(supabase, calcular_estimativa=None, custo_da_sessao=None,
               condominio_padrao=None, locais_do_usuario=None):
    CTX.supabase = supabase
    CTX.calcular_estimativa = calcular_estimativa
    CTX.custo_da_sessao = custo_da_sessao
    CTX.condominio_padrao = condominio_padrao
    CTX.locais_do_usuario = locais_do_usuario


def sb():
    if CTX.supabase is None:
        raise RuntimeError("chatbot não configurado: chame configurar_chatbot(...) no main.py")
    return CTX.supabase
