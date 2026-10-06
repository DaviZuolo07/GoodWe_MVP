"""Física de referência do contrato (seção C), sensor, bateria e LCD. Sem rede."""

import random

from totem_virtual import fisica
from totem_virtual.bancada import Bancada, RelogioManual
from totem_virtual.lcd import COLUNAS, formatar, quebrar, sem_acento, tela_valida


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


def test_bateria_18650_tensao_cresce_com_a_carga():
    tensoes = [fisica.tensao_aberta_18650(s) for s in range(0, 101)]
    assert tensoes == sorted(tensoes) and tensoes[0] == 3.0 and tensoes[-1] == 4.2
    bat = fisica.Bateria18650(soc=50)
    assert bat.tensao_v(saida_w=8) < bat.tensao_v() < bat.tensao_v(entrada_w=5), \
        "cede descarregando, sobe carregando"


def test_painel_segue_a_luz_e_afunda_sobrecarregado():
    painel = fisica.PainelVirtual(luz=0.5)
    assert painel.disponivel_w() == 5.0
    assert painel.tensao_v(7.5) < painel.tensao_v(0)
    painel.luz = 0
    assert painel.disponivel_w() == 0 and painel.tensao_v() == 0


def test_vaga_4_nunca_soma_painel_e_bateria():
    b = Bancada(RelogioManual(), random.Random(3))
    b.painel.luz, b.bateria.soc = 1.0, 60
    b.plugar(4, 15, 20)
    b.rele(4, True)
    for fonte, quem_fornece, quem_nao in (("painel", "painel", "bateria"), ("bateria", "bateria", "painel")):
        b.selecionar_fonte(fonte)
        b.avancar(0.2)
        assert b.ler_fonte(quem_fornece)["potencia_w"] > 5
        assert b.ler_fonte(quem_nao)["potencia_w"] == 0
    b.selecionar_fonte("nenhuma")
    b.avancar(0.2)
    assert b.ler_ina(4)["potencia_w"] == 0, "sem fonte, a vaga não entrega nada"
    assert b.ler_fonte("painel")["potencia_w"] > 0 and b.ler_fonte("bateria")["potencia_w"] == 0, \
        "vaga parada: o painel carrega a bateria (e a bateria não fornece)"


def test_lcd_e_20x4_ascii():
    linhas = formatar(["Não cadastrado: ação inválida no condomínio", "Olá", "ç~^", "4", "5"])
    assert len(linhas) == 4 and all(len(x) == COLUNAS for x in linhas)
    assert all(ord(c) < 127 for x in linhas for c in x)
    assert linhas[0] == "Nao cadastrado: acao"
    assert sem_acento("maçã € 中") == "maca ? ?"
    assert formatar("uma linha")[0].rstrip() == "uma linha"


def test_quebrar_mensagem_livre():
    linhas = quebrar("Saldo insuficiente para reservar R$ 1,00. Recarga recusada pelo servidor agora mesmo")
    assert len(linhas) <= 4 and all(len(x) <= COLUNAS for x in linhas)
    assert linhas[0] == "Saldo insuficiente"
    assert quebrar("x" * 45) == ["x" * 20, "x" * 20, "x" * 5]


def test_tela_do_contrato():
    assert tela_valida(["a", "b"]) and tela_valida(["1", "2", "3", "4"])
    assert not tela_valida([]) and not tela_valida("texto") and not tela_valida(["a"] * 5)
    assert not tela_valida([1, 2])
