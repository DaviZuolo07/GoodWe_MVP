"""
Verificador anti-alucinação numérica.

Regra do briefing: "sem inventar número". Isto aqui é a aplicação mecânica
dessa regra - não confiamos no modelo para cumprir a instrução, conferimos.

Todo número que aparece na resposta precisa existir nos fatos que vieram do
banco (com tolerância para arredondamento e para conversão de minutos em
horas). Se aparecer um número que não veio de lugar nenhum, a resposta do LLM
é descartada e o redator determinístico assume.

Custo: microssegundos, sem chamar modelo. É a checagem mais barata do sistema
e a que mais protege na frente da banca.
"""

import re

# Números que podem aparecer sem estar nos fatos: ordinais e valores triviais
# de linguagem ("os 4 pontos", "1 carro"), além de 100% como alvo padrão.
TOLERADOS = {0, 1, 2, 3, 4, 5, 10, 100}
TOLERANCIA = 0.06  # arredondamento de centavos e de uma casa decimal


def numeros_do_texto(texto: str):
    """Extrai números de um texto em formato BR (1.234,56) ou US (1234.56)."""
    achados = []
    for bruto in re.findall(r"\d[\d\.,]*", texto or ""):
        limpo = bruto.rstrip(".,")
        if "," in limpo:                      # 1.234,56 -> 1234.56
            limpo = limpo.replace(".", "").replace(",", ".")
        elif limpo.count(".") > 1:            # 1.234.567 -> 1234567
            limpo = limpo.replace(".", "")
        try:
            achados.append(float(limpo))
        except ValueError:
            continue
    return achados


def numeros_dos_fatos(fatos) -> set:
    """Percorre o dicionário de fatos recursivamente e junta todo número."""
    encontrados = set()

    def anda(valor):
        if isinstance(valor, bool) or valor is None:
            return
        if isinstance(valor, (int, float)):
            encontrados.add(float(valor))
        elif isinstance(valor, str):
            for n in numeros_do_texto(valor):
                encontrados.add(n)
        elif isinstance(valor, dict):
            for v in valor.values():
                anda(v)
        elif isinstance(valor, (list, tuple)):
            for v in valor:
                anda(v)

    anda(fatos)

    # Minutos viram horas na redação ("135 min" -> "2h15"), então os
    # componentes da conversão também são números legítimos.
    for n in list(encontrados):
        if n >= 60 and float(n).is_integer():
            encontrados.add(float(int(n) // 60))
            encontrados.add(float(int(n) % 60))
        encontrados.add(round(n))
        encontrados.add(round(n, 1))

    return encontrados


def aprovado(resposta: str, fatos) -> tuple:
    """
    Devolve (True, None) se todo número da resposta tem lastro nos fatos,
    ou (False, motivo) se algum número apareceu do nada.
    """
    if not resposta:
        return False, "resposta_vazia"

    permitidos = numeros_dos_fatos(fatos) | {float(n) for n in TOLERADOS}

    for n in numeros_do_texto(resposta):
        if any(abs(n - p) <= TOLERANCIA for p in permitidos):
            continue
        return False, f"numero_sem_lastro:{n}"

    return True, None
