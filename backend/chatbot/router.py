"""
Router de intenções.

Duas velocidades:
  1. Regex determinístico - resolve a maioria das perguntas da demo em ~0 ms,
     sem chamar modelo nenhum. É o que garante latência de vídeo.
  2. Se o regex não decidir, o classificador LLM entra (ver llm.py) e devolve
     uma intenção do enum. Qualquer coisa fora do enum vira FORA_DE_ESCOPO.

A ORDEM DAS REGRAS IMPORTA. O bug que apareceu na tela ("qual o preço por kWh"
respondido com o custo da sessão) era exatamente isso: `preço` batia em CUSTO
antes de qualquer regra conseguir ver que a pergunta era sobre TARIFA. Por isso
TARIFA é testada antes de CUSTO - a regra mais específica ganha da mais geral.
"""

import re
import unicodedata

# --- Enum fechado de intenções -------------------------------------------
TEMPO_RESTANTE = "tempo_restante"
STATUS_RECARGA = "status_recarga"
CUSTO_ATUAL = "custo_atual"
TARIFA = "tarifa"
CARREGADORES_DISPONIVEIS = "carregadores_disponiveis"
INFO_CARREGADOR = "info_carregador"
FILA_STATUS = "fila_status"
MEU_SALDO = "meu_saldo"
MEUS_VEICULOS = "meus_veiculos"
SIMULAR_RECARGA = "simular_recarga"
HISTORICO_RECENTE = "historico_recente"
AJUDA = "ajuda"
FORA_DE_ESCOPO = "fora_de_escopo"
TENTATIVA_INJECAO = "tentativa_injecao"

INTENCOES = {
    TEMPO_RESTANTE, STATUS_RECARGA, CUSTO_ATUAL, TARIFA,
    CARREGADORES_DISPONIVEIS, INFO_CARREGADOR, FILA_STATUS, MEU_SALDO,
    MEUS_VEICULOS, SIMULAR_RECARGA, HISTORICO_RECENTE, AJUDA,
    FORA_DE_ESCOPO, TENTATIVA_INJECAO,
}

LIMITE_CARACTERES = 500


def normalizar(texto: str) -> str:
    """Minúsculas e sem acento - para o regex não precisar de 'preço|preco'."""
    texto = (texto or "").strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


# --- Prompt injection: primeiro filtro, antes de qualquer outra coisa -----
PADROES_INJECAO = [
    r"ignor[ae]\s+(as\s+|todas\s+as\s+)?(instru|regra|orienta)",
    r"desconsidere\s+(as\s+|tudo)",
    r"esque[cç]a\s+(as\s+|suas\s+|tudo)",
    r"system\s*prompt",
    r"suas?\s+(instru[cç][oõ]es|regras|diretrizes)",
    r"revele?\s+(seu|o)\s+prompt",
    r"(voce|vc)\s+agora\s+(e|eh|sera)\s+",
    r"aja\s+como\s+(se\s+)?(um|uma|outro)",
    r"finja\s+que",
    r"modo\s+(desenvolvedor|dev|admin|debug)",
    # tentativa de trocar de identidade por prosa
    r"sou\s+o\s+(usuario|user|admin|morador)\s+[0-9a-f\-]{6,}",
    r"(me\s+)?mostre?\s+o\s+saldo\s+d[eo]\s+(outro|outra|usuario)",
    r"em\s+nome\s+d[eo]\s+outr",
    r"drop\s+table|select\s+\*\s+from|delete\s+from|insert\s+into",
]

# Assuntos que se parecem com os nossos mas não são. "previsão do TEMPO" tem a
# palavra "tempo"; "quanto custa a gasolina" tem "custa". Sem esta guarda, a
# regra genérica engole a pergunta e o bot responde algo sem sentido.
PADROES_FORA_DE_ESCOPO = [
    r"previsao\s+do\s+tempo|vai\s+chover|clima\b|temperatura\s+(em|de)\s+[a-z]",
    r"futebol|jogo\s+d[eo]|receita\s+de|piada|politica|presidente\s+d",
    r"gasolina|etanol|diesel|combustivel",
    r"traduz|escreva?\s+(um|uma)\s+(codigo|programa|poema|texto)|codigo\s+python",
    r"quem\s+(e|eh|foi)\s+[a-z]",
]

# --- Regras de intenção, da mais específica para a mais geral -------------
# Cada tupla: (intenção, regex). A primeira que casar vence.
REGRAS = [
    # TARIFA antes de CUSTO. Esta ordem é o conserto do bug da tela.
    (TARIFA, r"tarifa|por\s*kwh|/\s*kwh|do\s+kwh|o\s+kwh\s+(custa|sai)|"
             r"pre[c]o\s+(do|por|da)\s+(kwh|energia)|valor\s+(do|por)\s+kwh|"
             r"quanto\s+(custa|sai)\s+o\s+kwh|cobran[c]a\s+por"),

    (CUSTO_ATUAL, r"custo|pre[c]o|quanto\s+(ja\s+)?(gastei|paguei|vou\s+pagar)|"
                  r"quanto\s+(esta|ta)\s+custando|gasto\s+ate|valor\s+da\s+recarga"),

    (SIMULAR_RECARGA, r"simul|estimativa|previsao\s+d[eo]\s+(custo|gasto|carga|recarga)|"
                      r"se\s+eu\s+(carregar|ligar|usar)|"
                      r"quanto\s+(ficaria|custaria|demoraria)|ate\s+\d{1,3}\s*%"),

    (TEMPO_RESTANTE, r"quanto\s+falta|falta\s+(quanto|muito|pouco)|tempo\s+restante|"
                     r"tempo|demora|quando\s+(termina|acaba|fica\s+pronto)|"
                     r"que\s+horas?\s+(termina|acaba)"),

    (FILA_STATUS, r"\bfila\b|espera|na\s+frente|minha\s+posicao|aguardando"),

    (CARREGADORES_DISPONIVEIS, r"disponivel|disponiveis|livre|vago|desocupado|"
                               r"tem\s+carregador|algum\s+(carregador|ponto)|"
                               r"quais\s+(carregadores|pontos)"),

    (INFO_CARREGADOR, r"carregador\s*\d+|ponto\s*\d+|conector|tipo\s*2|tensao|"
                      r"amper|corrente|ficha\s+tecnica|especifica"),

    (MEU_SALDO, r"saldo|credito|quanto\s+(eu\s+)?tenho|minha\s+carteira|"
                r"tenho\s+dinheiro"),

    (MEUS_VEICULOS, r"meu\s+(carro|veiculo)|meus\s+(carros|veiculos)|"
                    r"\bveiculo\b|placa\s+d"),

    (HISTORICO_RECENTE, r"historico|recargas?\s+(anterior|passad|ultim)|"
                        r"ultimas\s+recargas|ja\s+carreguei|meu\s+consumo"),

    (STATUS_RECARGA, r"status|como\s+(esta|ta|vai)\s+(a\s+)?(minha\s+)?(recarga|carga)|"
                     r"bateria|porcentagem|quantos?\s*%|potencia|"
                     r"esta\s+carregando|kw\b"),

    (AJUDA, r"^(oi|ola|opa|bom\s+dia|boa\s+tarde|boa\s+noite|e\s+ai)\b|"
            r"ajuda|o\s+que\s+(voce|vc)\s+(faz|pode|sabe)|como\s+(voce\s+)?funciona|"
            r"quais\s+(suas|as)\s+(funcoes|capacidades)"),
]


def rotear(mensagem: str) -> dict:
    """
    Classifica a mensagem. Devolve sempre:
        {"intencao": <enum>, "parametros": {...}, "metodo": "regex"|"nenhum"}

    `metodo == "nenhum"` significa que o regex não decidiu - aí o serviço
    tenta o classificador LLM antes de desistir para FORA_DE_ESCOPO.
    """
    original = (mensagem or "")[:LIMITE_CARACTERES]
    texto = normalizar(original)

    if not texto:
        return {"intencao": AJUDA, "parametros": {}, "metodo": "regex"}

    for padrao in PADROES_INJECAO:
        if re.search(padrao, texto):
            return {"intencao": TENTATIVA_INJECAO, "parametros": {},
                    "metodo": "regex"}

    for padrao in PADROES_FORA_DE_ESCOPO:
        if re.search(padrao, texto):
            return {"intencao": FORA_DE_ESCOPO, "parametros": {},
                    "metodo": "regex"}

    for intencao, padrao in REGRAS:
        if re.search(padrao, texto):
            return {"intencao": intencao,
                    "parametros": extrair_parametros(texto, intencao),
                    "metodo": "regex"}

    return {"intencao": FORA_DE_ESCOPO, "parametros": {}, "metodo": "nenhum"}


def extrair_parametros(texto: str, intencao: str) -> dict:
    """
    Parâmetros inócuos e validados. Nada aqui vira consulta livre: são só
    números clampados que as funções de dados aceitam.
    """
    params = {}

    m = re.search(r"(?:carregador|ponto|vaga)\s*(?:n[uo]?\.?\s*)?(\d{1,3})", texto)
    if m:
        params["numero_carregador"] = m.group(1).zfill(2)

    if intencao == SIMULAR_RECARGA:
        m = re.search(r"(?:ate|para|a)\s+(\d{1,3})\s*%", texto)
        if not m:
            m = re.search(r"(\d{1,3})\s*%", texto)
        if m:
            params["alvo"] = max(1.0, min(100.0, float(m.group(1))))

    if intencao == HISTORICO_RECENTE:
        m = re.search(r"ultim[ao]s?\s+(\d{1,2})", texto)
        if m:
            params["limite"] = max(1, min(10, int(m.group(1))))

    return params


def validar_intencao(nome: str) -> str:
    """Qualquer coisa fora do enum vira FORA_DE_ESCOPO. Sem exceção."""
    nome = (nome or "").strip().lower()
    return nome if nome in INTENCOES else FORA_DE_ESCOPO
