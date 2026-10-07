"""Física de referência do contrato (seção C), sensor, bateria e LCD. Sem rede."""

import random

from totem_virtual import fisica
from totem_virtual.bancada import Bancada, RelogioManual
from totem_virtual.lcd import (COLUNAS, LINHAS, formatar, pagina, paginas, quebrar, reflow,
                               sem_acento, tela_valida)


def test_curva_do_celular_e_a_do_contrato():
    assert fisica.potencia_do_celular(0) == 7.5
    assert fisica.potencia_do_celular(80) == 7.5
    assert abs(fisica.potencia_do_celular(90) - 4.0) < 1e-9, "cai em linha reta entre 80% e 100%"
    assert abs(fisica.potencia_do_celular(99.999) - 0.5) < 0.01
    assert fisica.potencia_do_celular(100) == 0.1, "manutenção"


def test_celular_enche_e_para_em_100():
    cel = fisica.CelularVirtual(capacidade_wh=1.0, soc=79.0)
    for _ in range(20000):
        cel.absorver(cel.pede_w(), 1.0)
    assert cel.soc == 100.0 and cel.pede_w() == 0.1


def test_ruido_fica_em_2_por_cento_e_desplugar_zera_com_rele_fechado():
    relogio = RelogioManual()
    b = Bancada(relogio, random.Random(7))
    b.plugar(1, 15, 20)
    b.rele(1, True)
    potencias = []
    for _ in range(300):
        b.avancar(0.05)
        potencias.append(b.ler_ina(1)["potencia_w"])
    assert min(potencias) >= 7.5 * 0.98 - 0.01 and max(potencias) <= 7.5 * 1.02 + 0.01
    assert max(potencias) - min(potencias) > 0.1, "tem ruído de verdade"

    b.desplugar(1)
    b.avancar(0.05)
    m = b.ler_ina(1)
    assert m["corrente_a"] == 0 and m["potencia_w"] == 0 and b.rele_ligado(1), \
        "corrente zero IMEDIATA, e o relé continua fechado"
    assert m["tensao_v"] > 4.9, "o barramento continua energizado"


def test_rele_aberto_nao_passa_corrente():
    b = Bancada(RelogioManual(), random.Random(1))
    b.plugar(2, 15, 20)
    b.avancar(1.0)
    assert b.ler_ina(2) == {"tensao_v": 0.0, "corrente_a": 0.0, "potencia_w": 0.0}
    assert b.celulares[2].soc == 20.0


def test_ina219_quantiza_como_o_sensor():
    m = fisica.ina219(5.0031, 1.48263)
    assert m["tensao_v"] == 5.004 and m["corrente_a"] == 1.4826
    assert fisica.ina219(-1, -1) == {"tensao_v": 0.0, "corrente_a": 0.0, "potencia_w": 0.0}
    carregando = fisica.ina219(3.7, -0.27, assinado=True)
    assert carregando["corrente_a"] == -0.27 and carregando["potencia_w"] < 0, \
        "o sensor em série com a bateria mede nos dois sentidos (ADR-022 D2)"


def test_bateria_18650_tensao_cresce_com_a_carga():
    tensoes = [fisica.tensao_aberta_18650(s) for s in range(0, 101)]
    assert tensoes == sorted(tensoes) and tensoes[0] == 3.0 and tensoes[-1] == 4.2
    bat = fisica.Bateria18650(soc=50)
    assert bat.tensao_v(saida_w=8) < bat.tensao_v() < bat.tensao_v(entrada_w=5), \
        "cede descarregando, sobe carregando"


def test_painel_de_1_w_segue_a_luz_e_afunda_sobrecarregado():
    painel = fisica.PainelVirtual(luz=0.5)
    assert painel.disponivel_w() == 0.5, "painel 5 V 1 W da bancada"
    assert painel.tensao_v(7.5) < painel.tensao_v(0)
    painel.luz = 0
    assert painel.disponivel_w() == 0 and painel.tensao_v() == 0


def test_vaga_4_e_solar_ou_rede_pelo_reversor():
    b = Bancada(RelogioManual(), random.Random(3))
    b.painel.luz, b.bateria.soc = 0.0, 60
    b.plugar(4, 15, 20)
    b.rele(4, True)

    b.selecionar_fonte("solar")
    b.avancar(0.2)
    assert b.ler_ina(4)["potencia_w"] > 7 and b.ler_bateria()["potencia_w"] > 7, \
        "na solar, a 18650 fornece (MT3608): potência positiva"
    b.selecionar_fonte("rede")
    b.avancar(0.2)
    assert b.ler_ina(4)["potencia_w"] > 7 and b.ler_bateria()["potencia_w"] == 0, \
        "na rede, a bateria não fornece nada: as duas nunca se somam"

    b.painel.luz = 1.0
    b.avancar(0.2)
    assert b.ler_bateria()["potencia_w"] < 0, "com sol, o painel carrega a bateria: potência negativa"

    b.bateria.soc = 0
    b.selecionar_fonte("solar")
    b.avancar(0.2)
    assert b.ler_ina(4)["potencia_w"] == 0, "bateria vazia: o MT3608 não entrega nada"
    try:
        b.selecionar_fonte("nenhuma")
        raise AssertionError("o reversor só tem duas posições")
    except ValueError:
        pass


def test_lcd_e_16x2_ascii():
    linhas = formatar(["Não cadastrado: ação inválida no condomínio", "Olá", "3", "4"])
    assert len(linhas) == LINHAS == 2 and all(len(x) == COLUNAS == 16 for x in linhas)
    assert all(ord(c) < 127 for x in linhas for c in x)
    assert linhas[0] == "Nao cadastrado: "
    assert sem_acento("maçã € 中") == "maca ? ?"
    assert formatar("uma linha")[0].rstrip() == "uma linha"


def test_quebrar_mensagem_livre_em_16_colunas():
    linhas = quebrar("Saldo insuficiente para reservar R$ 1,00. Recarga recusada pelo servidor")
    assert all(len(x) <= COLUNAS for x in linhas)
    assert linhas[:2] == ["Saldo", "insuficiente"]
    assert quebrar("x" * 35) == ["x" * 16, "x" * 16, "x" * 3]


def test_tela_do_backend_vira_paginas_de_2_linhas():
    tela = reflow(["Vaga 1 liberada", "Boa recarga, Ana!", "", "Saldo R$ 31,25"])
    assert tela == ["Vaga 1 liberada", "Boa recarga,", "Ana!", "", "Saldo R$ 31,25"]
    assert paginas(tela) == 3 and pagina(tela, 1) == ["Ana!", ""] and pagina(tela, 9) == ["Saldo R$ 31,25"]
    assert paginas(reflow(["Vaga 2 ocupada"])) == 1


def test_tela_do_contrato():
    assert tela_valida(["a", "b"]) and tela_valida(["1", "2", "3", "4"])
    assert not tela_valida([]) and not tela_valida("texto") and not tela_valida(["a"] * 5)
    assert not tela_valida([1, 2])


def test_telas_do_totem_cabem_em_16_colunas():
    from totem_virtual.firmware import DIAGNOSTICO, TELA_DA_RECUSA, TELA_DO_MOTIVO, TELA_SEM_CONEXAO
    linhas = [x.format(n=4) for t in TELA_DO_MOTIVO.values() for x in t] + TELA_SEM_CONEXAO + \
        list(TELA_DA_RECUSA.values())
    assert all(len(x) <= COLUNAS for x in linhas), [x for x in linhas if len(x) > COLUNAS]
    assert set(DIAGNOSTICO) == set(TELA_DA_RECUSA)
