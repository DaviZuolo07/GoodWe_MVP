"""
lcd.py - A tela do totem: LCD de caracteres 16x2, só ASCII (ADR-022 D3).
=========================================================================

O HD44780 não tem acento. Tudo que vai para a tela passa por `sem_acento`,
venha do backend ("tela") ou do próprio totem. O firmware faz o mesmo.

O backend manda "tela" com até 4 linhas de 20 colunas (contrato v2.1). Aqui
cada linha é re-quebrada em 16 colunas sem cortar palavra e o resultado é
mostrado em páginas de 2 linhas.
"""

import unicodedata

COLUNAS, LINHAS = 16, 2
LINHAS_DO_BACKEND = 4            # "tela" do contrato v2.1: até 4 linhas


def sem_acento(texto: str) -> str:
    """'Não cadastrado' -> 'Nao cadastrado'. O que sobrar fora do ASCII visível vira '?'."""
    decomposto = unicodedata.normalize("NFKD", str(texto))
    saida = []
    for c in decomposto:
        if unicodedata.combining(c):
            continue
        saida.append(c if 32 <= ord(c) <= 126 else "?")
    return "".join(saida)


def limpar_linha(texto) -> str:
    return sem_acento("" if texto is None else texto)[:COLUNAS].ljust(COLUNAS)


def formatar(linhas) -> list[str]:
    """Qualquer coisa -> exatamente 2 linhas de 16 caracteres ASCII."""
    if not isinstance(linhas, (list, tuple)):
        linhas = [linhas]
    linhas = [limpar_linha(x) for x in linhas[:LINHAS]]
    return linhas + [" " * COLUNAS] * (LINHAS - len(linhas))


def quebrar(texto: str) -> list[str]:
    """Texto livre -> linhas de até 16 colunas, sem cortar palavra (a não ser maior que a tela)."""
    linhas, atual = [], ""
    for palavra in sem_acento(texto).split():
        while len(palavra) > COLUNAS:                 # palavra maior que a tela
            if atual:
                linhas.append(atual)
                atual = ""
            linhas.append(palavra[:COLUNAS])
            palavra = palavra[COLUNAS:]
        if not atual:
            atual = palavra
        elif len(atual) + 1 + len(palavra) <= COLUNAS:
            atual += " " + palavra
        else:
            linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


def reflow(linhas) -> list[str]:
    """Cada linha (até 20 colunas, do backend) re-quebrada em 16. Linha vazia continua vazia."""
    saida = []
    for linha in linhas:
        saida.extend(quebrar(linha) or [""])
    return saida or [""]


def paginas(tela: list[str]) -> int:
    return max(1, (len(tela) + LINHAS - 1) // LINHAS)


def pagina(tela: list[str], n: int) -> list[str]:
    n = max(0, min(n, paginas(tela) - 1))
    return tela[n * LINHAS:(n + 1) * LINHAS]


def tela_valida(tela) -> bool:
    """O campo "tela" do contrato: lista de até 4 textos."""
    return isinstance(tela, list) and 0 < len(tela) <= LINHAS_DO_BACKEND and \
        all(isinstance(x, str) for x in tela)


class Lcd:
    def __init__(self):
        self.linhas = formatar([])

    def escrever(self, linhas) -> None:
        self.linhas = formatar(linhas)

    def apagar(self) -> None:
        self.linhas = formatar([])
