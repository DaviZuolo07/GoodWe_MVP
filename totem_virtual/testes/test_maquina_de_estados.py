"""
Máquina de estados do totem com relógio manual.

Metade roda sobre o backend de verdade em memória (o que existe hoje) e
metade sobre o servidor v2.1 de referência (o que o contrato congela).
"""

import servidor_v21
from mesa import mesa_bolso, mesa_v21
from totem_virtual import config as K
from totem_virtual.rede import Resposta

A, B = "A1A1A1A1", "B2B2B2B2"


# ---------------------------------------------------------------------------
# Interface: tag -> escolha da vaga -> POST -> tela -> volta
# ---------------------------------------------------------------------------

def test_liga_com_reles_abertos_e_faz_handshake():
    m = mesa_bolso()
    e = m.e()
    assert e["link"] == "PRONTO" and e["ui"] == "AGUARDANDO_TAG" and e["online"]
    assert all(v["existe"] and not v["rele"] and v["estado"] == "livre" for v in e["vagas"])
    assert [x["rota"] for x in e["trocas"][:2]] == ["/hora", "/handshake"]
    assert all(len(x) == 16 and all(ord(c) < 127 for c in x) for x in e["lcd"]), "LCD 16x2"
    assert m.convite() == ["ChargeOps GoodWe", "Aproxime cartao"]
    assert m.quadro() == ["1:LIVRE 2:LIVRE", "3:LIVRE 4:LIVRE"], "a tela de espera alterna"


def test_timeout_de_15_s_na_escolha_da_vaga_sem_chamar_o_backend():
    m = mesa_bolso()
    m.t.aproximar_tag(A)
    m.andar(0.1)
    assert m.e()["ui"] == "ESCOLHA_VAGA" and m.lcd() == ["Escolha vaga 1-4", "Tempo: 15 s"]
    m.andar(14.7)
    assert m.e()["ui"] == "ESCOLHA_VAGA" and m.lcd()[1] == "Tempo:  1 s"
    m.andar(0.3)
    assert m.e()["ui"] == "MOSTRA_TELA" and m.lcd() == ["Tempo esgotado", "Aproxime de novo"]
    m.andar(K.AVISO_MS / 1000 + 0.1)
    assert m.e()["ui"] == "AGUARDANDO_TAG"
    assert m.t.trocas("/rfid") == [], "sem botão, nenhum POST /rfid"

    m.t.apertar_botao(2)                     # botão atrasado não vale mais
    m.andar(0.2)
    assert m.t.trocas("/rfid") == [] and m.lcd() == ["Aproxime o", "cartao primeiro"]


def test_botao_sem_tag_so_avisa():
    m = mesa_bolso()
    m.t.apertar_botao(3)
    m.andar(0.1)
    assert m.lcd() == ["Aproxime o", "cartao primeiro"] and m.t.trocas("/rfid") == []


def test_tag_e_botao_mandam_porta_e_uid_e_a_tela_volta_sozinha():
    m = mesa_bolso()
    troca = m.tag_na_vaga(A, 3)
    assert troca["status"] == 200 and troca["dados"]["porta"] == 3
    # Backend D1 (v2.1): a tag numa vaga livre inicia a recarga (tag-primeiro).
    assert (troca["dados"]["motivo"], troca["dados"]["acao"]) == ("iniciada", "ligar")
    assert m.e()["ui"] == "MOSTRA_TELA"
    assert m.lcd()[0] == "Vaga 3 liberada"
    assert m.vaga(3)["rele"] and m.vaga(3)["motivo_rele"] == "rfid", "acao=ligar fecha o relé na hora"
    m.andar(K.TELA_MS / 1000 + 0.1)
    assert m.e()["ui"] == "AGUARDANDO_TAG", "a tela volta sozinha; a vaga segue ligada"
    assert m.vaga(3)["rele"]


def test_segunda_tag_troca_a_primeira_e_reinicia_o_tempo():
    m = mesa_v21()
    m.t.aproximar_tag("FFFFFFFF")
    m.andar(10)
    m.t.aproximar_tag(A)
    m.andar(10)
    assert m.e()["ui"] == "ESCOLHA_VAGA", "os 15 s recomeçaram na segunda tag"
    m.t.plugar(1)
    m.t.apertar_botao(1)
    m.andar(0.2)
    assert m.t.trocas("/rfid")[-1]["dados"]["motivo"] == "iniciada", "valeu a tag A, não a primeira"


# ---------------------------------------------------------------------------
# Backend de hoje: recarga preparada no app, relé pelo comando `liberar`
# ---------------------------------------------------------------------------

def test_duas_vagas_carregam_juntas_pelo_fluxo_do_app():
    m = mesa_bolso()
    m.preparar_no_app(0, 1)
    m.andar(1.5)
    assert m.vaga(1)["aguarda_tag"] and m.convite()[1] == "Vaga 1: aproxime"
    m.t.plugar(1, 3.0, 30)
    troca = m.tag_na_vaga(A, 1)
    d = troca["dados"]
    # v2.1: "confirmada_app" é o MOTIVO; a ação é "ligar" e fecha o relé na hora.
    assert (d["autorizado"], d["motivo"], d["acao"]) == (True, "confirmada_app", "ligar")
    assert m.lcd()[:2] == ["Vaga 1 liberada", "Recarga do app"]
    assert m.vaga(1)["rele"] and m.vaga(1)["motivo_rele"] == "rfid"
    m.andar(1.5)
    assert m.vaga(1)["rele"] and m.vaga(1)["motivo_rele"] == "rfid", \
        "o liberar que chega depois em /v2/comandos é idempotente"

    m.carregar_pelo_app(1, 2, "B")
    m.andar(6)
    v1, v2 = m.vaga(1), m.vaga(2)
    assert v1["potencia_w"] > 7 and v2["potencia_w"] > 7, "as duas ao mesmo tempo"
    assert v1["backend"]["deve_liberar"] and v2["backend"]["deve_liberar"]
    assert v1["backend"]["percentual"] > 30, "o backend calcula o % a partir da energia do totem"
    assert not m.vaga(3)["rele"] and not m.vaga(4)["rele"]
    assert m.quadro()[0].startswith("1:7.") and "2:7." in m.quadro()[0]


def test_fila_de_energia_autorizado_sem_ligar_e_liga_sozinha_depois():
    """A demonstração de gestão de demanda, do lado do totem, contra o backend D1."""
    import sys
    m = mesa_bolso()
    fake = sys.modules["config"].supabase
    fake.t("condominios")[0]["limite_potencia_kw"] = 0.01      # menos que uma vaga (0,025 kW)
    m.t.plugar(1, 3.0, 30)
    d = m.tag_na_vaga(A, 1)["dados"]
    assert (d["autorizado"], d["motivo"], d["acao"]) == (True, "aguardando_energia", "nenhuma")
    m.andar(4)
    v = m.vaga(1)
    assert not v["rele"], "autorizado NÃO fecha o relé: na fila de energia ele fica aberto"
    assert v["estado"] == "aguardando_energia" and v["estado_do_backend"]
    assert m.quadro()[0].startswith("1:FILA")

    fake.t("condominios")[0]["limite_potencia_kw"] = 60      # sobrou energia
    import simulador
    simulador.ciclo()                                          # o laço de 10 s do backend
    m.andar(4)
    v = m.vaga(1)
    assert v["rele"] and v["motivo_rele"] == "comando" and v["sessao_id"] == d["sessao_id"], \
        "liga sozinha, pelo liberar, na MESMA sessão"
    assert v["estado"] == "carregando" and v["potencia_w"] > 5


def test_energia_acumulada_bate_com_potencia_vezes_tempo():
    m = mesa_bolso()
    m.carregar_pelo_app(0, 1, "A")
    antes = m.vaga(1)["energia_wh"]
    m.andar(60)
    ganho = m.vaga(1)["energia_wh"] - antes
    assert abs(ganho - 7.5 * 60 / 3600) < 0.004, ganho      # 0,125 Wh em 1 min


def test_telemetria_em_lote_com_w_brutos_e_fontes():
    m = mesa_bolso()
    m.carregar_pelo_app(0, 1, "A")
    enviados = []
    original = m.t.enlace.telemetria
    m.t.enlace.telemetria = lambda corpo: enviados.append(corpo) or original(corpo)
    m.andar(4.1)
    assert len(enviados) == 2, "um lote a cada envio_ms"
    lote = enviados[-1]
    assert sorted({x["porta"] for x in lote["leituras"]}) == [1, 2, 3, 4]
    assert len(lote["leituras"]) == 8, "2 amostras x 4 vagas"
    da_1 = [x for x in lote["leituras"] if x["porta"] == 1][-1]
    assert 7 < da_1["potencia_w"] < 8, "W brutos da bancada, sem escala 1:1000"
    assert da_1["rele_ligado"] and da_1["energia_wh"] > 0 and 4.9 < da_1["tensao_v"] < 5.1
    assert [x["fonte"] for x in lote["fontes"]] == ["bateria", "bateria"], \
        "uma leitura da bateria por amostra; o painel não tem sensor (ADR-022 D2)"
    assert all(set(x) == {"fonte", "t_ms", "potencia_w", "tensao_v", "corrente_a"} for x in lote["fontes"])
    assert all(x["potencia_w"] < 0 for x in lote["fontes"]), \
        "vaga 4 parada e sol: o painel carrega a bateria, e o sinal diz isso"
    assert lote["t_envio_ms"] >= max(x["t_ms"] for x in lote["leituras"])
    assert m.t.trocas("/telemetria")[-1]["dados"]["gravadas"] == 8


def test_encerrar_no_app_abre_o_rele_pelo_comando():
    m = mesa_bolso()
    sessao, cab = m.carregar_pelo_app(0, 1, "A")
    assert m.http.post(f"/recargas/{sessao}/encerrar", headers=cab).status_code == 200
    m.andar(1.5)
    assert not m.vaga(1)["rele"] and m.vaga(1)["estado"] == "livre"


# ---------------------------------------------------------------------------
# Falhas: Wi-Fi, reboot, numeração, chave
# ---------------------------------------------------------------------------

def test_wifi_cai_guarda_e_reenvia_em_lotes_respeitando_boot_e_seq():
    m = mesa_bolso()
    m.carregar_pelo_app(0, 1, "A")
    m.andar(3)
    boot, marca = m.e()["boot"], m.t.marca()

    m.t.wifi(False)
    m.andar(40)
    e = m.e()
    assert not e["online"] and m.convite()[1] == "Sem rede: espere"
    assert e["fila_leituras"] >= 39 * 4, "uma leitura por vaga por segundo, guardadas"
    assert m.t.trocas(None, marca) == [], "com o Wi-Fi caído não sai nada"
    assert m.vaga(1)["rele"], "a recarga continua"
    energia = m.vaga(1)["energia_wh"]

    m.t.wifi(True)
    m.andar(5)
    lotes = m.t.trocas("/telemetria", marca)
    assert all(x["status"] == 200 for x in lotes), [x["resumo"] for x in lotes]
    assert max(x["leituras"] for x in lotes) == 30, "lotes cheios na volta"
    assert all(x["leituras"] <= 30 for x in lotes)
    assert sum(x["dados"]["gravadas"] for x in lotes) >= e["fila_leituras"]
    seqs = [x["seq"] for x in m.t.trocas(None, marca)]
    assert seqs == sorted(set(seqs)), "cada reenvio é requisição nova, com seq novo"
    assert m.e()["boot"] == boot and m.e()["fila_leituras"] <= 8 and m.e()["online"]
    assert m.vaga(1)["rele"] and m.vaga(1)["backend"]["deve_liberar"]
    assert m.t.trocas("/telemetria")[-1]["dados"]["portas"][0]["energia_wh"] >= energia - 0.01


def test_tag_sem_rede_nao_e_guardada_para_depois():
    m = mesa_bolso()
    m.t.wifi(False)
    m.andar(1)
    m.t.aproximar_tag(A)
    m.andar(0.2)
    m.t.apertar_botao(1)
    m.andar(0.2)
    assert m.lcd()[:2] == ["Sem conexao", "Tente de novo"]
    m.t.wifi(True)
    m.andar(10)
    assert m.t.trocas("/rfid") == [], "a leitura antiga não é reenviada"


def test_trava_offline_abre_os_reles_e_o_handshake_religa():
    m = mesa_bolso(offline_corte_ms=20_000)
    m.carregar_pelo_app(0, 1, "A")
    m.t.wifi(False)
    m.andar(19)
    assert m.vaga(1)["rele"]
    m.andar(2)
    assert not m.vaga(1)["rele"] and m.vaga(1)["motivo_rele"] == "trava offline"
    m.t.wifi(True)
    m.andar(3)
    assert m.t.trocas("/handshake")[-1]["status"] == 200
    assert m.vaga(1)["rele"] and m.vaga(1)["motivo_rele"] == "handshake", \
        "o servidor ainda considera a sessão ativa: religa"


def test_fila_sem_rede_tem_teto_e_descarta_as_mais_antigas():
    m = mesa_bolso(offline_corte_ms=10_000_000)
    m.t.wifi(False)
    m.andar(125)                             # 4 leituras/s enchem em 60 s; 1 da bateria/s, em 120 s
    e = m.e()
    assert e["fila_leituras"] == K.FILA_LEITURAS_MAX and e["descartadas"] > 0
    assert e["fila_fontes"] == K.FILA_FONTES_MAX
    m.t.wifi(True)
    m.andar(30)
    assert m.e()["fila_leituras"] <= 8 and m.e()["lotes_descartados"] == 0


def test_reboot_no_meio_da_recarga():
    m = mesa_bolso()
    m.carregar_pelo_app(0, 1, "A")
    m.andar(20)
    antes = m.e()
    energia = m.vaga(1)["energia_wh"]
    assert energia > 0.03

    m.t.reiniciar()
    logo = m.e()
    assert not any(v["rele"] for v in logo["vagas"]), "relés desligados no boot"
    assert logo["boot"] != antes["boot"] and logo["seq"] == 0 and logo["millis"] == 0
    assert logo["fila_leituras"] == 0 and logo["ui"] == "INICIANDO"

    m.andar(1)
    e = m.e()
    assert e["link"] == "PRONTO" and e["seq"] >= 1
    v = m.vaga(1)
    assert v["rele"] and v["motivo_rele"] == "handshake", "o handshake reconcilia"
    assert energia - 0.02 <= v["energia_wh"] <= energia + 0.01, "o contador continua de onde parou"
    assert not m.vaga(2)["rele"]
    m.andar(4)
    assert m.vaga(1)["backend"]["deve_liberar"]
    assert all(x["status"] == 200 for x in m.t.trocas("/telemetria")[-2:])


def test_chave_errada_avisa_na_tela_e_nao_metralha_o_servidor():
    m = mesa_bolso(chave_hex="11" * 32)
    m.andar(30)
    e = m.e()
    assert e["chave_recusada"] and e["link"] == "SEM_HANDSHAKE" and e["ui"] == "INICIANDO"
    assert m.lcd() == ["ChargeOps GoodWe", "Chave invalida"]
    assert len(m.t.trocas("/handshake")) == K.RECUSAS_PARA_BLOQUEAR, "bloqueia e espera (ADR-021)"
    assert "11" * 32 not in str(e), "a chave não aparece no retrato que vai para a página"


def test_boot_desconhecido_e_replay_se_recuperam_com_handshake():
    m = mesa_v21()
    m.app.state.boot = 123                   # o servidor "esqueceu" a placa
    m.andar(3)
    assert m.e()["link"] == "PRONTO" and m.t.trocas("/handshake")[-1]["n"] > 2
    assert m.app.state.boot == m.e()["boot"]

    boot = m.e()["boot"]
    m.app.state.seq = 10 ** 9                # numeração fora de sincronia
    m.andar(4)
    assert m.e()["boot"] != boot, "replay: sorteia boot novo"
    assert m.e()["link"] == "PRONTO" and m.e()["online"]
    assert m.t.trocas("/telemetria")[-1]["status"] == 200


def test_lote_que_o_servidor_nunca_aceita_e_descartado_e_a_fila_anda():
    m = mesa_bolso()
    original, vezes = m.t.enlace.telemetria, []

    def recusar(corpo):
        if not vezes:
            vezes.append(1)
            return Resposta(True, 422, {"detail": "lote_invalido"}, "lote_invalido")
        return original(corpo)
    m.t.enlace.telemetria = recusar
    m.andar(6)
    e = m.e()
    assert e["lotes_descartados"] == 1 and e["lotes_enviados"] >= 1 and e["fila_leituras"] <= 8


# ---------------------------------------------------------------------------
# Totem v2.1 (servidor de referência): acao, tela, estado
# ---------------------------------------------------------------------------

def test_v21_tag_em_vaga_livre_inicia_e_a_mesma_tag_encerra():
    m = mesa_v21()
    m.t.plugar(1)
    troca = m.tag_na_vaga(A, 1)
    assert troca["dados"]["acao"] == "ligar" and troca["dados"]["motivo"] == "iniciada"
    assert m.vaga(1)["rele"] and m.vaga(1)["motivo_rele"] == "rfid"
    assert m.lcd()[:2] == ["Vaga 1 liberada", "Recarga iniciada"], "a tela é a que o backend mandou"
    m.andar(5)
    assert m.vaga(1)["estado"] == "carregando" and m.vaga(1)["estado_do_backend"]

    troca = m.tag_na_vaga(A, 1)
    assert troca["dados"]["acao"] == "desligar" and troca["dados"]["motivo"] == "encerrada"
    assert not m.vaga(1)["rele"]
    m.andar(3)
    assert m.vaga(1)["estado"] == "livre" and m.vaga(1)["sessao_id"] is None


def test_v21_recusas_nao_ligam_o_rele():
    m = mesa_v21()
    m.t.plugar(1)
    m.tag_na_vaga(A, 1)
    casos = [(B, 1, "vaga_ocupada"), (A, 2, "ja_carregando_em_outra_vaga"),
             ("C3C3C3C3", 2, "saldo_insuficiente"), ("DEADBEEF", 2, "cartao_nao_cadastrado")]
    for uid, porta, motivo in casos:
        m.andar(K.TELA_MS / 1000 + 0.2)
        d = m.tag_na_vaga(uid, porta)["dados"]
        assert (d["motivo"], d["acao"], d["autorizado"]) == (motivo, "nenhuma", False)
    assert m.vaga(1)["rele"] and not m.vaga(2)["rele"], "a tag alheia não derruba nem liga nada"


def test_v21_desplugar_o_backend_libera_a_vaga(monkeypatch):
    monkeypatch.setattr(servidor_v21, "PRAZO_S", 0.0)
    m = mesa_v21()
    m.t.plugar(2)
    m.tag_na_vaga(B, 2)
    m.andar(4)
    assert m.vaga(2)["potencia_w"] > 7
    m.t.desplugar(2)
    m.andar(0.3)
    assert m.vaga(2)["potencia_w"] == 0 and m.vaga(2)["rele"], "o totem só mede; quem decide é o backend"
    m.andar(4)
    assert not m.vaga(2)["rele"] and m.vaga(2)["estado"] == "livre"


def test_v21_trava_de_sessao_quando_o_comando_se_perde(monkeypatch):
    monkeypatch.setattr(servidor_v21, "PRAZO_S", 0.0)
    m = mesa_v21()
    m.app.state.perder_proximo_comando = True
    m.tag_na_vaga(A, 3)                      # vaga sem celular
    assert m.vaga(3)["rele"]
    m.andar(5)
    assert not m.vaga(3)["rele"] and m.vaga(3)["motivo_rele"] == "trava de sessao", \
        "o desligar se perdeu, mas a telemetria respondeu deve_liberar=false"


def test_v21_celular_cheio_vira_completa_tolerancia(monkeypatch):
    monkeypatch.setattr(servidor_v21, "PRAZO_S", 0.0)
    m = mesa_v21()
    m.t.plugar(1, 15, 100)
    m.tag_na_vaga(A, 1)
    m.andar(5)
    v = m.vaga(1)
    assert v["estado"] == "completa_tolerancia" and v["estado_do_backend"]
    assert 0.05 < v["potencia_w"] < 0.15 and v["rele"], "manutenção de ~0,1 W, relé segue fechado"
    assert m.quadro()[0] == "1:CHEIO 2:LIVRE"


def test_v21_servidor_acha_que_carrega_e_o_rele_esta_aberto_reconcilia():
    m = mesa_v21()
    m.app.state.sessoes[2] = {"id": "s-fantasma", "uid": B, "energia_wh": 1.25,
                              "baixa_desde": None, "estado": "carregando"}
    m.t.plugar(2)
    m.andar(8)
    assert not m.vaga(2)["rele"], "deve_liberar=true NÃO fecha o relé por conta própria"
    m.andar(8)
    v = m.vaga(2)
    assert v["rele"] and v["motivo_rele"] == "handshake" and v["sessao_id"] == "s-fantasma"
    assert v["energia_wh"] >= 1.25, "retoma a energia que o servidor tinha"


def test_v21_pausa_e_retomada_da_mesma_sessao_nao_zera_a_energia():
    m = mesa_v21()
    m.t.plugar(1)
    sessao = m.tag_na_vaga(A, 1)["dados"]["sessao_id"]
    m.andar(30)
    energia = m.vaga(1)["energia_wh"]
    fw = m.t.firmware
    assert fw._executar({"acao": "desligar", "porta": 1, "sessao_id": sessao}, 0) is None
    assert not m.vaga(1)["rele"]
    assert fw._executar({"acao": "ligar", "porta": 1, "sessao_id": sessao}, 0) is None
    assert m.vaga(1)["rele"] and m.vaga(1)["energia_wh"] == energia
    assert fw._executar({"acao": "ligar", "porta": 1, "sessao_id": "outra"}, 0) is None
    assert m.vaga(1)["energia_wh"] == 0, "sessão nova: contador do zero"
    assert fw._executar({"acao": "dancar", "porta": 1}, 0) == "acao_desconhecida"


# ---------------------------------------------------------------------------
# Vaga 4: solar OU rede, pelo relé reversor (ADR-022 D1)
# ---------------------------------------------------------------------------

def _trocas_de_fonte(m) -> list[str]:
    return [x["texto"].rsplit(" ", 1)[-1] for x in m.e()["eventos"] if "fonte da vaga 4" in x["texto"]]


def test_vaga_solar_comeca_pela_bateria_e_o_backend_manda_para_a_rede():
    m = mesa_v21()
    m.app.state.garantir_minimo = True       # Modbus 10024 ligado
    m.t.luz(0)
    m.t.bateria(60)
    m.t.plugar(4)
    m.tag_na_vaga(A, 4)
    m.andar(2)
    s = m.e()["solar"]
    assert s["fonte"] == "solar" and m.vaga(4)["potencia_w"] > 7
    assert s["bateria"]["potencia_w"] > 7, "a 18650 fornece a vaga (sinal positivo)"
    assert m.quadro()[1].endswith("S"), "S = vaga 4 na solar"

    m.t.bateria(15)                          # abaixo do 10030 (20%), descarregando
    m.andar(5)
    s = m.e()["solar"]
    assert s["fonte_backend"] == "rede" and s["fonte"] == "rede"
    assert m.vaga(4)["rele"] and m.vaga(4)["potencia_w"] > 7, "segue carregando, agora pela rede"
    assert s["bateria"]["potencia_w"] == 0, "nunca as duas: a bateria parou de fornecer"
    assert m.quadro()[1].endswith("R")

    m.t.bateria(60)                          # bateria boa: o backend volta a pedir solar
    m.andar(10)
    assert m.e()["solar"]["fonte_backend"] == "solar" and m.e()["solar"]["fonte"] == "rede", \
        "forçada para a rede, segura FONTE_MIN_MS antes de voltar (sem vai-e-volta no relé)"
    m.andar(K.FONTE_MIN_MS / 1000)
    assert m.e()["solar"]["fonte"] == "solar"
    assert _trocas_de_fonte(m) == ["solar", "rede", "solar"]


def test_backend_pausa_a_vaga_solar_e_retoma_a_mesma_sessao():
    m = mesa_v21()                           # 10024 desligado: bateria baixa = pausa
    m.t.luz(0)
    m.t.bateria(15)
    m.t.plugar(4)
    sessao = m.tag_na_vaga(A, 4)["dados"]["sessao_id"]
    m.andar(6)
    v = m.vaga(4)
    assert not v["rele"] and v["estado"] == "pausada" and v["sessao_id"] == sessao
    assert m.e()["solar"]["fonte"] == "rede", "relé aberto: reversor desligado, o painel carrega a 18650"
    assert m.quadro()[1].endswith("4:PAUSA")
    energia = v["energia_wh"]

    m.t.bateria(60)
    m.andar(6)
    v = m.vaga(4)
    assert v["rele"] and v["estado"] == "carregando" and v["sessao_id"] == sessao
    assert m.e()["solar"]["fonte"] == "solar", "retomada sem atraso: a rede não tinha sido forçada"
    assert v["energia_wh"] >= energia, "a mesma sessão não zera a energia"


def test_bateria_baixa_vai_para_a_rede_mesmo_offline():
    m = mesa_v21(offline_corte_ms=10_000_000)
    m.t.luz(0)
    m.t.bateria(60)
    m.t.plugar(4)
    m.tag_na_vaga(A, 4)
    m.andar(2)
    assert m.e()["solar"]["fonte"] == "solar"
    m.t.wifi(False)                          # sem backend: a proteção da 18650 é local
    m.t.bateria(10.3)
    m.andar(40)
    s = m.e()["solar"]
    assert s["fonte"] == "rede" and not s["bateria_ok"], "abaixo de 3,30 V a 18650 sai da vaga"
    assert m.vaga(4)["rele"] and m.vaga(4)["potencia_w"] > 7, "o celular segue carregando pela rede"

    m.t.bateria(60)                          # bateria trocada
    m.andar(5)
    assert m.e()["solar"]["bateria_ok"] and m.e()["solar"]["fonte"] == "rede"
    m.andar(K.FONTE_MIN_MS / 1000)
    assert m.e()["solar"]["fonte"] == "solar"


def test_vaga_4_parada_o_painel_carrega_a_bateria():
    m = mesa_v21()
    m.t.bateria(50)
    m.andar(120)
    s = m.e()["solar"]
    assert s["fonte"] == "rede", "sem recarga na vaga 4, a bobina do reversor fica desligada"
    assert s["bateria_soc"] > 50.3, "1 W do painel por 2 min, pelo TP4056"
    assert s["bateria"]["potencia_w"] < 0, "carregando: sinal negativo"
