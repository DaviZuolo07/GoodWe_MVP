"""
roteiro.py - Modo roteiro: o teste de aceitação do totem, sozinho.
==================================================================

Liga um totem virtual, executa os cenários e imprime, para cada um:

  PASSOU              o backend respondeu o que o contrato manda
  FALHOU              respondeu outra coisa (o roteiro sai com código 1)
  AGUARDANDO BACKEND  o backend ainda responde no formato de hoje, sem o
                      Totem v2.1 (ADR-018). Não é falha.
  PULADO              falta configuração (uma tag ou uma conta no .env)

O veredito vem SEMPRE da resposta do backend (ou, nos cenários locais, do
que o totem mediu). O roteiro age como uma pessoa na bancada: encosta tag,
aperta botão, pluga e despluga - nunca força um relé.

Como saber se o backend já tem o v2.1: a resposta de POST /v2/rfid traz a
chave "acao". Sem ela (ou com "sem_recarga_preparada" numa vaga livre), os
cenários tag-primeiro ficam "aguardando backend".

    python -m totem_virtual roteiro            # backend do .env
    python -m totem_virtual roteiro --bolso    # backend em memória
"""

import time

from . import config as K
from .totem import TotemVirtual

PASSOU, FALHOU, AGUARDANDO, PULADO = "PASSOU", "FALHOU", "AGUARDANDO BACKEND", "PULADO"
ESTADOS_COMPLETA = ("completa_tolerancia", "completa_taxa")
TAG_INEXISTENTE = "0BADF00D"


class Abortar(Exception):
    pass


class Roteiro:
    def __init__(self, totem: TotemVirtual, http, base: str = "", espera_s: float | None = None,
                 wifi_s: float = 10.0, saida=print):
        self.t, self.http, self.base = totem, http, base.rstrip("/")
        self.cfg = totem.cfg
        self.espera_s = self.cfg.roteiro_espera_s if espera_s is None else espera_s
        self.wifi_s = wifi_s
        self.saida = saida
        self.resultados: list[tuple[str, str, str]] = []
        self.v21: bool | None = None        # None = ainda não deu para saber
        self.sessoes_app: list[tuple[str, dict]] = []   # (sessao_id, cabeçalho)
        self.falhas_feitas = False

    # ===================================================================
    # Ferramentas
    # ===================================================================

    def esperar(self, condicao, limite_s: float, passo_s: float = 0.05) -> bool:
        fim = time.monotonic() + limite_s
        while time.monotonic() < fim:
            if condicao():
                return True
            time.sleep(passo_s)
        return bool(condicao())

    def vaga(self, porta: int) -> dict:
        return self.t.estado()["vagas"][porta - 1]

    def tag(self, apelido: str) -> str | None:
        return self.cfg.tags.get(apelido)

    def tag_na_vaga(self, uid: str, porta: int) -> dict | None:
        """Encosta a tag, aperta o botão e devolve a troca com o backend (ou None)."""
        marca = self.t.marca()
        self.t.aproximar_tag(uid)
        if not self.esperar(lambda: self.t.estado()["ui"] == "ESCOLHA_VAGA", 3):
            return None
        self.t.apertar_botao(porta)
        achou = []
        self.esperar(lambda: achou.extend(self.t.trocas("/rfid", marca)) or bool(achou), 8)
        if achou and "acao" in (achou[0].get("dados") or {}):
            self.v21 = True
        return achou[0] if achou else None

    def telemetrias(self, desde: int) -> list[dict]:
        return self.t.trocas("/telemetria", desde)

    def resposta_da_porta(self, porta: int, desde: int) -> dict | None:
        """A resposta mais recente do backend para a porta, em lotes depois de `desde`."""
        for troca in reversed(self.telemetrias(desde)):
            for p in (troca.get("dados") or {}).get("portas") or []:
                if p.get("porta") == porta:
                    return p
        return None

    def liberar(self, porta: int, apelido: str) -> None:
        """Limpeza entre cenários: se a vaga ficou com sessão, a mesma tag encerra."""
        v = self.vaga(porta)
        if (v["rele"] or v["estado"] != "livre") and self.tag(apelido):
            self.tag_na_vaga(self.tag(apelido), porta)
            self.esperar(lambda: not self.vaga(porta)["rele"], 8)
        self.t.desplugar(porta)
        self.esperar(lambda: self.t.estado()["ui"] == "AGUARDANDO_TAG", 6)

    def _precisa(self, *apelidos) -> tuple[str, str] | None:
        faltam = [a for a in apelidos if not self.tag(a)]
        if faltam:
            return PULADO, "falta " + ", ".join(f"TAG_{a}" for a in faltam) + " no totem_virtual/.env"
        if self.v21 is False:
            return AGUARDANDO, "backend ainda sem o Totem v2.1 (RFID responde sem \"acao\")"
        return None

    def _recusa(self, troca: dict | None, motivos: tuple, porta: int) -> tuple[str, str]:
        """Confere uma resposta de recusa: não autoriza, motivo esperado, relé não liga."""
        if not troca or troca["status"] != 200:
            return FALHOU, f"sem resposta 200 do RFID ({troca and troca['resumo']})"
        d = troca["dados"]
        if "acao" not in d:
            self.v21 = False if self.v21 is None else self.v21
            return AGUARDANDO, f"backend respondeu no formato antigo (motivo={d.get('motivo')})"
        if d.get("autorizado") or d.get("motivo") not in motivos or d.get("acao") in ("ligar",):
            return FALHOU, f"esperava {'/'.join(motivos)} sem ligar; veio {troca['resumo']}"
        return PASSOU, f"backend: motivo={d['motivo']}, acao={d['acao']}"

    def rodar(self, nome: str, funcao) -> None:
        try:
            status, detalhe = funcao()
        except Abortar:
            raise
        except Exception as e:                       # cenário quebrado não derruba os outros
            status, detalhe = FALHOU, f"erro no roteiro: {type(e).__name__}: {e}"
        self.resultados.append((nome, status, detalhe))
        self.saida(f"  {status:<18} {nome:<26} {detalhe}")

    # ===================================================================
    # Cenários que valem com qualquer backend
    # ===================================================================

    def conexao(self):
        if not self.esperar(lambda: self.t.estado()["link"] == "PRONTO", 15):
            e = self.t.estado()
            motivo = "chave recusada (confira DEVICE_ID e DEVICE_KEY_HEX)" if e["chave_recusada"] \
                else "backend não respondeu em 15 s (está rodando? BACKEND_URL certo?)"
            self.resultados.append(("conexao", FALHOU, motivo))
            self.saida(f"  {FALHOU:<18} {'conexao':<26} {motivo}")
            raise Abortar(motivo)
        vagas = [v for v in self.t.estado()["vagas"] if v["existe"]]
        if len(vagas) != 4:
            return FALHOU, f"o handshake devolveu {len(vagas)} porta(s); o totem tem 4"
        ocupadas = [v["porta"] for v in vagas if v["rele"]]
        if ocupadas:
            motivo = (f"vaga(s) {ocupadas} já com recarga ativa no backend. Limpe antes "
                      "(backend: python provisionar.py limpar --sim).")
            self.resultados.append(("conexao", FALHOU, motivo))
            self.saida(f"  {FALHOU:<18} {'conexao':<26} {motivo}")
            raise Abortar(motivo)
        return PASSOU, "hora acertada, handshake v2 assinado, 4 portas, relés abertos"

    def timeout_escolha(self):
        marca = self.t.marca()
        self.t.aproximar_tag(self.tag("A") or TAG_INEXISTENTE)
        if not self.esperar(lambda: self.t.estado()["ui"] == "ESCOLHA_VAGA", 3):
            return FALHOU, "a tag não levou à tela de escolha da vaga"
        limite = K.TIMEOUT_ESCOLHA_MS / 1000
        time.sleep(limite * 0.8)
        if self.t.estado()["ui"] != "ESCOLHA_VAGA":
            return FALHOU, f"saiu da escolha antes dos {limite:.0f} s"
        if not self.esperar(lambda: self.t.estado()["ui"] == "AGUARDANDO_TAG", limite * 0.2 + 4):
            return FALHOU, f"não voltou a aguardar tag depois de {limite:.0f} s"
        if self.t.trocas("/rfid", marca):
            return FALHOU, "mandou POST /rfid sem ninguém escolher a vaga"
        return PASSOU, f"voltou sozinho em {limite:.0f} s, sem chamar o backend (local)"

    def solar_na_telemetria(self):
        marca = self.t.marca()
        self.t.luz(100)
        espera = self.cfg.envio_ms / 1000 * 2 + 3
        com_fontes = lambda: [x for x in self.telemetrias(marca) if x.get("fontes")]  # noqa: E731
        if not self.esperar(lambda: bool(com_fontes()), espera):
            return FALHOU, "nenhum lote com \"fontes\" saiu do totem"
        troca = com_fontes()[-1]
        if troca["status"] != 200:
            return FALHOU, f"backend recusou o lote com \"fontes\": {troca['status']} {troca['resumo']}"
        dados = troca["dados"]
        if "fontes_gravadas" in dados or "fontes" in dados:
            return PASSOU, f"lote com painel e bateria aceito e confirmado ({troca['fontes']} leituras de fonte)"
        return AGUARDANDO, ("o totem manda painel e bateria e o backend aceita (200), mas a resposta "
                            "ainda não confirma que gravou as fontes")

    def app_duas_vagas(self):
        """Fluxo de hoje (confirmada_app): duas pessoas preparam no app e encostam a tag."""
        if len(self.cfg.app_contas) < 2:
            return PULADO, "falta APP_CONTAS=nome1:senha1,nome2:senha2 no totem_virtual/.env"
        if not (self.tag("A") and self.tag("B")):
            return PULADO, "falta TAG_A / TAG_B no totem_virtual/.env"
        aperto = next((x for x in reversed(self.t.trocas("/handshake")) if x["status"] == 200), None)
        pontos = {p["porta"]: p["carregador"]["id"] for p in aperto["dados"]["portas"]}

        for (nome, senha), apelido, porta in zip(self.cfg.app_contas, ("A", "B"), (1, 2)):
            r = self.http.post(f"{self.base}/login", json={"nome": nome, "senha": senha})
            if r.status_code != 200:
                return FALHOU, f"login de '{nome}' recusado ({r.status_code})"
            cab = {"Authorization": f"Bearer {r.json()['token']}"}
            veiculos = self.http.get(f"{self.base}/me/veiculos", headers=cab).json()
            celular = next((v for v in veiculos if v.get("tipo") == "celular"), None)
            if not celular:
                return PULADO, f"'{nome}' não tem veículo do tipo celular cadastrado"
            r = self.http.post(f"{self.base}/recargas/preparar", headers=cab, json={
                "charger_id": pontos[porta], "veiculo_id": celular["id"],
                "percentual_bateria_atual": 30, "alvo_percentual": 100})
            if r.status_code != 200:
                return FALHOU, f"preparar na vaga {porta} recusado: {r.status_code} {r.text[:120]}"
            self.sessoes_app.append((r.json()["sessao"]["id"], cab))
            if not self.esperar(lambda: self.vaga(porta)["aguarda_tag"], 8):
                return FALHOU, f"o totem não recebeu o pedido de cartão da vaga {porta}"
            self.t.plugar(porta, float(celular["capacidade_bateria_kwh"]) * 1000, 30)
            troca = self.tag_na_vaga(self.tag(apelido), porta)
            if not troca or not troca["dados"].get("autorizado"):
                return FALHOU, f"tag na vaga {porta} não confirmou: {troca and troca['resumo']}"
            self.esperar(lambda: self.t.estado()["ui"] == "AGUARDANDO_TAG", 6)

        return self._duas_carregando("confirmadas pelo app")

    def _duas_carregando(self, como: str):
        marca = self.t.marca()
        if not self.esperar(lambda: self.vaga(1)["rele"] and self.vaga(2)["rele"], 10):
            return FALHOU, "os dois relés não ligaram por ordem do backend"
        if not self.esperar(lambda: self.vaga(1)["potencia_w"] > 5 and self.vaga(2)["potencia_w"] > 5, 5):
            return FALHOU, "as duas vagas não mediram carga ao mesmo tempo"
        espera = self.cfg.envio_ms / 1000 * 2 + 3

        def backend_confirma():
            a, b = self.resposta_da_porta(1, marca), self.resposta_da_porta(2, marca)
            return bool(a and b and a.get("deve_liberar") and b.get("deve_liberar"))
        if not self.esperar(backend_confirma, espera):
            return FALHOU, "a telemetria não voltou com as duas portas em recarga"
        w1, w2 = self.vaga(1)["potencia_w"], self.vaga(2)["potencia_w"]
        return PASSOU, f"vagas 1 e 2 carregando juntas ({w1:.1f} W e {w2:.1f} W, simulado), {como}"

    def encerrar_app(self):
        for sessao_id, cab in self.sessoes_app:
            self.http.post(f"{self.base}/recargas/{sessao_id}/encerrar", headers=cab)
        self.sessoes_app = []
        self.esperar(lambda: not any(v["rele"] for v in self.t.estado()["vagas"]), 10)
        for porta in (1, 2):
            self.t.desplugar(porta)

    # -- falhas ------------------------------------------------------------

    def wifi_caiu(self):
        antes = self.t.estado()
        ligados = [v["porta"] for v in antes["vagas"] if v["rele"]]
        marca, boot = self.t.marca(), antes["boot"]
        self.t.wifi(False)
        time.sleep(self.wifi_s)
        durante = self.t.estado()
        guardadas = durante["fila_leituras"]
        self.t.wifi(True)
        if self.t.trocas(None, marca):
            return FALHOU, "o totem falou com o backend com o Wi-Fi caído"
        # Folga de duas amostras: o laço e o relógio de parede não são cravados.
        minimo = max(1, int(self.wifi_s * 1000 / self.cfg.amostra_ms) - 2) * 4
        if guardadas < minimo:
            return FALHOU, f"guardou só {guardadas} leituras em {self.wifi_s:.0f} s (esperado >= {minimo})"
        if [v["porta"] for v in durante["vagas"] if v["rele"]] != ligados:
            return FALHOU, "um relé mudou sozinho com o Wi-Fi caído"

        normal = self.cfg.envio_ms // self.cfg.amostra_ms * 4 + 4
        if not self.esperar(lambda: self.t.estado()["online"]
                            and self.t.estado()["fila_leituras"] <= normal, self.cfg.envio_ms / 1000 + 25):
            return FALHOU, f"não esvaziou a fila ({self.t.estado()['fila_leituras']} leituras paradas)"
        lotes = self.telemetrias(marca)
        ruins = [x for x in lotes if x["status"] != 200]
        gravadas = sum((x["dados"] or {}).get("gravadas", 0) for x in lotes)
        seqs = [x["seq"] for x in self.t.trocas(None, marca)]
        if ruins:
            return FALHOU, f"lote recusado na volta: {ruins[0]['status']} {ruins[0]['resumo']}"
        if gravadas < guardadas:
            return FALHOU, f"backend gravou {gravadas} de {guardadas} leituras guardadas"
        if self.t.estado()["boot"] != boot or seqs != sorted(set(seqs)):
            return FALHOU, "boot mudou ou a sequência não cresceu"
        if [v["porta"] for v in self.t.estado()["vagas"] if v["rele"]] != ligados:
            return FALHOU, "a recarga não sobreviveu à queda do Wi-Fi"
        com = f", {len(ligados)} recarga(s) seguiram" if ligados else " (sem recarga ativa)"
        return PASSOU, (f"{guardadas} leituras guardadas, {gravadas} gravadas em {len(lotes)} lote(s), "
                        f"mesmo boot{com}")

    def reboot(self):
        antes = self.t.estado()
        ligados = {v["porta"]: v["energia_wh"] for v in antes["vagas"] if v["rele"]}
        if ligados:      # garante que o servidor já viu energia antes de puxar a tomada
            time.sleep(self.cfg.envio_ms / 1000 + 1)
            ligados = {p: self.vaga(p)["energia_wh"] for p in ligados}
        self.t.reiniciar()
        logo = self.t.estado()
        if any(v["rele"] for v in logo["vagas"]) and logo["link"] != "PRONTO":
            return FALHOU, "relé fechado logo depois do reboot, antes do handshake"
        if not self.esperar(lambda: self.t.estado()["link"] == "PRONTO", 15):
            return FALHOU, "não refez o handshake em 15 s"
        depois = self.t.estado()
        if depois["boot"] == antes["boot"]:
            return FALHOU, "o boot não mudou"
        aperto = self.t.trocas("/handshake")[-1]
        if aperto["status"] != 200:
            return FALHOU, f"handshake do boot novo recusado: {aperto['resumo']}"
        for porta, energia in ligados.items():
            v = self.vaga(porta)
            if not v["rele"]:
                return FALHOU, f"vaga {porta} tinha recarga e não religou pelo handshake"
            if energia > 0.01 and v["energia_wh"] < energia * 0.5:
                return FALHOU, (f"vaga {porta}: energia voltou para {v['energia_wh']} Wh "
                                f"(era {energia} Wh)")
        if [v["porta"] for v in depois["vagas"] if v["rele"]] != sorted(ligados):
            return FALHOU, "relé ligado em vaga que o backend não mandou"
        com = (f"{len(ligados)} recarga(s) religadas e energia retomada" if ligados
               else "nenhuma recarga ativa, relés seguem abertos")
        return PASSOU, f"boot novo aceito, handshake reconciliou: {com}"

    def falhas(self):
        if self.falhas_feitas:
            return
        self.falhas_feitas = True
        self.rodar("wifi_caiu", self.wifi_caiu)
        self.rodar("reboot", self.reboot)

    # ===================================================================
    # Cenários do Totem v2.1 (tag primeiro)
    # ===================================================================

    def inicia_pela_tag(self):
        falta = self._precisa("A")
        if falta:
            return falta
        self.t.plugar(1, 15, 30)
        troca = self.tag_na_vaga(self.tag("A"), 1)
        if not troca or troca["status"] != 200:
            return FALHOU, f"sem resposta 200 do RFID ({troca and troca['resumo']})"
        d = troca["dados"]
        if "acao" not in d:
            self.v21 = False
            return AGUARDANDO, f"tag em vaga livre respondeu motivo={d.get('motivo')}, sem \"acao\""
        if not (d.get("autorizado") and d.get("motivo") == "iniciada" and d.get("acao") == "ligar"):
            return FALHOU, f"esperava iniciada/ligar; veio {troca['resumo']}"
        if not self.esperar(lambda: self.vaga(1)["rele"] and self.vaga(1)["potencia_w"] > 5, 5):
            return FALHOU, "o relé da vaga 1 não ligou / não há carga"
        tela = "com tela do backend" if d.get("tela") else "tela montada no totem"
        return PASSOU, f"backend: iniciada, ligar ({tela})"

    def vaga_ocupada(self):
        falta = self._precisa("A", "B")
        if falta:
            return falta
        status, detalhe = self._recusa(self.tag_na_vaga(self.tag("B"), 1), ("vaga_ocupada",), 1)
        if status == PASSOU and not self.vaga(1)["rele"]:
            return FALHOU, "a tag alheia derrubou a recarga da vaga 1"
        return status, detalhe

    def duas_vagas_tag(self):
        falta = self._precisa("A", "B")
        if falta:
            return falta
        self.t.plugar(2, 15, 50)
        troca = self.tag_na_vaga(self.tag("B"), 2)
        d = (troca or {}).get("dados") or {}
        if not (d.get("autorizado") and d.get("acao") == "ligar"):
            return FALHOU, f"tag B na vaga 2 não iniciou: {troca and troca['resumo']}"
        return self._duas_carregando("iniciadas pela tag")

    def mesma_tag_outra_vaga(self):
        falta = self._precisa("A")
        if falta:
            return falta
        status, detalhe = self._recusa(self.tag_na_vaga(self.tag("A"), 3),
                                       ("ja_carregando_em_outra_vaga",), 3)
        if status == PASSOU and self.vaga(3)["rele"]:
            return FALHOU, "ligou a vaga 3 para quem já carrega na 1"
        return status, detalhe

    def desplugado(self):
        falta = self._precisa("B")
        if falta:
            return falta
        if not self.vaga(2)["rele"]:
            return FALHOU, "pré-condição: a vaga 2 deveria estar carregando"
        self.t.desplugar(2)
        if not self.esperar(lambda: self.vaga(2)["potencia_w"] == 0, 3):
            return FALHOU, "a corrente não zerou ao desplugar"
        inicio = time.monotonic()
        if not self.esperar(lambda: not self.vaga(2)["rele"], self.espera_s):
            return FALHOU, f"backend não liberou a vaga em {self.espera_s:.0f} s com corrente zero"
        v = self.vaga(2)
        return PASSOU, (f"backend liberou a vaga em {time.monotonic() - inicio:.0f} s "
                        f"(relé aberto por {v['motivo_rele']}, estado {v['estado']})")

    def encerra_pela_tag(self):
        falta = self._precisa("A")
        if falta:
            return falta
        troca = self.tag_na_vaga(self.tag("A"), 1)
        d = (troca or {}).get("dados") or {}
        if not (d.get("motivo") == "encerrada" and d.get("acao") == "desligar"):
            return FALHOU, f"esperava encerrada/desligar; veio {troca and troca['resumo']}"
        if not self.esperar(lambda: not self.vaga(1)["rele"], 3):
            return FALHOU, "o relé da vaga 1 não abriu"
        return PASSOU, "backend: encerrada, desligar; vaga 1 livre"

    def saldo_insuficiente(self):
        falta = self._precisa("SEM_SALDO")
        if falta:
            return falta
        self.t.plugar(3, 15, 40)
        status, detalhe = self._recusa(self.tag_na_vaga(self.tag("SEM_SALDO"), 3),
                                       ("saldo_insuficiente",), 3)
        if status == PASSOU and self.vaga(3)["rele"]:
            return FALHOU, "ligou a vaga sem saldo"
        return status, detalhe

    def tag_alheia(self):
        falta = self._precisa()
        if falta:
            return falta
        uid = self.tag("DESCONHECIDA") or TAG_INEXISTENTE
        status, detalhe = self._recusa(
            self.tag_na_vaga(uid, 3),
            ("cartao_nao_cadastrado", "cartao_de_outro_condominio", "cartao_de_outro_usuario"), 3)
        if status == PASSOU and self.vaga(3)["rele"]:
            return FALHOU, "ligou a vaga para uma tag de fora"
        return status, detalhe

    def vaga_sem_celular(self):
        falta = self._precisa("A")
        if falta:
            return falta
        self.t.desplugar(3)
        troca = self.tag_na_vaga(self.tag("A"), 3)
        d = (troca or {}).get("dados") or {}
        if d.get("acao") != "ligar":
            if d.get("autorizado") is False and d.get("motivo") == "sem_veiculo":
                return PASSOU, "backend recusou de saída: sem_veiculo"
            return FALHOU, f"esperava ligar (ou sem_veiculo); veio {troca and troca['resumo']}"
        inicio = time.monotonic()
        if not self.esperar(lambda: not self.vaga(3)["rele"], self.espera_s):
            return FALHOU, f"backend deixou a vaga vazia ligada por mais de {self.espera_s:.0f} s"
        return PASSOU, f"sem corrente, o backend liberou a vaga em {time.monotonic() - inicio:.0f} s"

    def celular_cheio(self):
        falta = self._precisa("A")
        if falta:
            return falta
        self.t.plugar(3, 15, 100)
        troca = self.tag_na_vaga(self.tag("A"), 3)
        d = (troca or {}).get("dados") or {}
        if d.get("acao") != "ligar":
            return FALHOU, f"esperava ligar; veio {troca and troca['resumo']}"
        inicio = time.monotonic()
        pronto = lambda: self.vaga(3)["estado"] in ESTADOS_COMPLETA or not self.vaga(3)["rele"]  # noqa: E731
        if not self.esperar(pronto, self.espera_s):
            return FALHOU, f"backend não percebeu o celular cheio em {self.espera_s:.0f} s"
        v = self.vaga(3)
        como = f"estado {v['estado']}" if v["estado"] in ESTADOS_COMPLETA else "vaga liberada"
        return PASSOU, f"celular a 100% puxando ~0,1 W: {como} em {time.monotonic() - inicio:.0f} s"

    def bateria_solar_baixa(self):
        falta = self._precisa("A")
        if falta:
            return falta
        self.t.luz(0)
        self.t.bateria(10.5)
        self.t.plugar(4, 15, 30)
        troca = self.tag_na_vaga(self.tag("A"), 4)
        d = (troca or {}).get("dados") or {}
        if d.get("acao") != "ligar":
            return FALHOU, f"esperava ligar na vaga 4; veio {troca and troca['resumo']}"
        if not self.esperar(lambda: self.t.estado()["solar"]["fonte"] == "bateria"
                            and self.vaga(4)["potencia_w"] > 5, 5):
            return FALHOU, "sem luz, a vaga 4 não passou a ser alimentada pela bateria"
        marca = self.t.marca()
        if not self.esperar(lambda: self.t.estado()["solar"]["fonte"] == "nenhuma", 90):
            return FALHOU, "a bateria baixa não foi cortada"

        def lote_com_bateria_baixa():
            for x in self.telemetrias(marca):
                if x["status"] == 200 and x.get("fontes"):
                    return True
            return False
        if not self.esperar(lote_com_bateria_baixa, self.cfg.envio_ms / 1000 * 2 + 3):
            return FALHOU, "o backend não recebeu as fontes depois do corte"
        soc = self.t.estado()["solar"]["bateria_soc"]
        self.t.luz(100)
        time.sleep(1.5)
        if self.vaga(4)["rele"]:
            if not self.esperar(lambda: self.t.estado()["solar"]["fonte"] == "painel"
                                and self.vaga(4)["potencia_w"] > 5, 8):
                return FALHOU, "a luz voltou e a vaga 4 não retomou pelo painel"
            fim = "com a luz de volta, retomou pelo painel"
        else:
            fim = "o backend liberou a vaga enquanto estava sem fonte"
        return PASSOU, f"bateria cortada a {soc:.0f}% (simulado), fontes reportadas; {fim}"

    # ===================================================================
    # A sequência
    # ===================================================================

    def executar(self) -> int:
        self.saida("\nModo roteiro do totem virtual  -  todos os valores de bancada são SIMULADOS\n")
        try:
            self.rodar("conexao", self.conexao)
            self.rodar("timeout_escolha", self.timeout_escolha)
            self.rodar("solar_na_telemetria", self.solar_na_telemetria)

            self.rodar("app_duas_vagas", self.app_duas_vagas)
            if self.resultados[-1][1] == PASSOU:
                self.falhas()
            self.encerrar_app()

            self.rodar("inicia_pela_tag", self.inicia_pela_tag)
            self.rodar("vaga_ocupada", self.vaga_ocupada)
            self.rodar("duas_vagas_pela_tag", self.duas_vagas_tag)
            self.rodar("mesma_tag_outra_vaga", self.mesma_tag_outra_vaga)
            self.falhas()                # se o app não rodou, as falhas entram aqui
            self.rodar("desplugado", self.desplugado)
            self.rodar("encerra_pela_tag", self.encerra_pela_tag)
            if self.v21:
                self.liberar(1, "A")
                self.liberar(2, "B")
            self.rodar("saldo_insuficiente", self.saldo_insuficiente)
            self.rodar("tag_alheia", self.tag_alheia)
            self.rodar("vaga_sem_celular", self.vaga_sem_celular)
            if self.v21:
                self.liberar(3, "A")
            self.rodar("celular_cheio", self.celular_cheio)
            if self.v21:
                self.liberar(3, "A")
            self.rodar("bateria_solar_baixa", self.bateria_solar_baixa)
            if self.v21:
                self.liberar(4, "A")
        except Abortar:
            pass
        finally:
            self.t.luz(100)
            self.t.bateria(60)
            self.t.wifi(True)

        conta = {s: sum(1 for _, x, _ in self.resultados if x == s)
                 for s in (PASSOU, FALHOU, AGUARDANDO, PULADO)}
        self.saida(f"\n{conta[PASSOU]} passou, {conta[FALHOU]} falhou, "
                   f"{conta[AGUARDANDO]} aguardando backend, {conta[PULADO]} pulado(s).")
        if conta[AGUARDANDO]:
            self.saida("Aguardando backend = depende do Totem v2.1 (ADR-018) no servidor; não é falha.")
        self.saida("")
        return 1 if conta[FALHOU] else 0


def rodar(cfg, http=None, base: str | None = None, **opcoes) -> int:
    totem = TotemVirtual(cfg, http=http, base=base)
    totem.iniciar()
    try:
        return Roteiro(totem, totem.http, totem.base, **opcoes).executar()
    finally:
        totem.parar()
