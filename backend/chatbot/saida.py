"""
Camada 3 - SAÍDA.
=================

Não confiamos que o modelo cumpriu as regras do prompt: conferimos. Se a
resposta do LLM reprova em qualquer item, ela é DESCARTADA e o redator
determinístico responde no lugar. O morador nunca vê a resposta reprovada; a
auditoria registra o motivo.

1. Número sem lastro   todo número precisa existir nos FATOS do banco (com
                       tolerância de arredondamento e minutos -> horas).
2. Vazamento           trechos do prompt, marcadores internos, UUIDs, chaves
                       e tokens não podem aparecer.
3. Tamanho             acima de 600 caracteres é prolixo para um painel.
4. Formato             markdown é removido (o chat mostra texto corrido).
"""

import re

TOLERADOS = {0, 1, 2, 3, 4, 5, 10, 100}
TOLERANCIA = 0.06
MAX_CARACTERES = 600

VAZAMENTOS = [
    r"FATOS DO BANCO", r"<<<|>>>", r"PERGUNTA DO MORADOR",
    r"system\s*prompt", r"minhas instru[cç][oõ]es (internas|s[aã]o)",
    r"A regra que n[aã]o se quebra", r"Identidade do morador n[aã]o se negocia",
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",   # UUID
    r"eyJ[A-Za-z0-9_\-]{10,}",                                         # JWT
    r"sb_secret_|service_role|gw_dev_|OLLAMA_API_KEY",
    r"<think>|</think>|\bthinking\b",
]


def numeros_do_texto(texto: str) -> list:
    achados = []
    for bruto in re.findall(r"\d[\d\.,]*", texto or ""):
        limpo = bruto.rstrip(".,")
        if "," in limpo:
            limpo = limpo.replace(".", "").replace(",", ".")
        elif limpo.count(".") > 1:
            limpo = limpo.replace(".", "")
        try:
            achados.append(float(limpo))
        except ValueError:
            continue
    return achados


def numeros_dos_fatos(fatos) -> set:
    encontrados = set()

    def anda(valor):
        if isinstance(valor, bool) or valor is None:
            return
        if isinstance(valor, (int, float)):
            encontrados.add(float(valor))
        elif isinstance(valor, str):
            encontrados.update(numeros_do_texto(valor))
        elif isinstance(valor, dict):
            for v in valor.values():
                anda(v)
        elif isinstance(valor, (list, tuple)):
            for v in valor:
                anda(v)

    anda(fatos)
    for n in list(encontrados):
        if n >= 60 and float(n).is_integer():          # 135 min -> 2h15
            encontrados.update({float(int(n) // 60), float(int(n) % 60)})
        encontrados.update({round(n), round(n, 1), round(n, 2)})
        if 0 < n < 1:                                   # 0,0065 kWh -> 6,5 Wh
            encontrados.update({round(n * 1000, 1), round(n * 1000)})
        if 0 < n <= 1:                                  # 0,6 -> 60%
            encontrados.add(round(n * 100))
    return encontrados


def limpar_formato(texto: str) -> str:
    texto = re.sub(r"\*\*|__|`|^#+\s*", "", texto or "", flags=re.MULTILINE)
    texto = re.sub(r"^\s*[-*•]\s+", "", texto, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", texto).strip()


def verificar(resposta: str, fatos) -> tuple:
    """(True, texto_limpo, None) ou (False, None, motivo)."""
    if not resposta or not resposta.strip():
        return False, None, "resposta_vazia"

    for padrao in VAZAMENTOS:
        if re.search(padrao, resposta, flags=re.IGNORECASE):
            return False, None, f"vazamento:{padrao[:25]}"

    texto = limpar_formato(resposta)
    if len(texto) > MAX_CARACTERES:
        return False, None, "prolixa"

    permitidos = numeros_dos_fatos(fatos) | {float(n) for n in TOLERADOS}
    for n in numeros_do_texto(texto):
        if not any(abs(n - p) <= TOLERANCIA for p in permitidos):
            return False, None, f"numero_sem_lastro:{n}"

    return True, texto, None
