"""
lcd.py - A tela do totem: LCD de caracteres 20x4, só ASCII.
===========================================================

O HD44780 não tem acento. Tudo que vai para a tela passa por `limpar_linha`,
venha do backend ("tela") ou do próprio totem. O firmware faz o mesmo corte.
"""

import unicodedata

COLUNAS, LINHAS = 20, 4


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
    """Qualquer coisa -> exatamente 4 linhas de 20 caracteres ASCII."""
    if not isinstance(linhas, (list, tuple)):
        linhas = [linhas]
    linhas = [limpar_linha(x) for x in linhas[:LINHAS]]
    return linhas + [" " * COLUNAS] * (LINHAS - len(linhas))


def quebrar(texto: str) -> list[str]:
    """Texto livre (a 'mensagem' do backend) -> até 4 linhas, sem cortar palavra no meio."""
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
    return linhas[:LINHAS]


def tela_valida(tela) -> bool:
    """O campo "tela" do contrato: lista de até 4 textos."""
    return isinstance(tela, list) and 0 < len(tela) <= LINHAS and all(isinstance(x, str) for x in tela)


class Lcd:
    def __init__(self):
        self.linhas = formatar([])

    def escrever(self, linhas) -> None:
        self.linhas = formatar(linhas)

    def apagar(self) -> None:
        self.linhas = formatar([])
