"""
firmware.py - A lógica do totem. É ISTO que o firmware C++ vai copiar.
======================================================================

Regras deste arquivo (para a tradução ser direta):
  - só enxerga o hardware pela HAL (bancada.py) e a rede pelo Enlace (rede.py);
  - não dorme: nada de sleep/delay. Tudo é "já passaram X ms desde a marca?";
    a única chamada que bloqueia é o HTTP, com timeout curto, como no ESP32;
  - setup() roda uma vez ao ligar; loop() roda sem parar.

DUAS MÁQUINAS DE ESTADO
-----------------------
Interface (uma: há um leitor e uma tela)
    INICIANDO -> AGUARDANDO_TAG -> ESCOLHA_VAGA (15 s) -> [POST /v2/rfid]
              -> MOSTRA_TELA (4 s) -> AGUARDANDO_TAG

Vaga (quatro, cada uma com o próprio relógio)
    estado = o último que o BACKEND informou, da lista fechada do contrato:
    livre | aguardando_energia | carregando | pausada | completa_tolerancia |
    completa_taxa. Enquanto o backend não manda "estado", vale o relé:
    fechado = carregando, aberto = livre. O totem não inventa estado.

QUEM MANDA NO RELÉ (ADR-020 D3)
-------------------------------
Fecha: "acao": "ligar" na resposta do RFID, comando liberar/ligar, ou
       rele_esperado no handshake. Sempre ordem do backend.
Abre:  "acao": "desligar", comando bloquear/desligar, handshake, e duas
       travas locais - telemetria respondeu deve_liberar=false (sessão
       acabou) ou o totem ficou tempo demais sem servidor.

O pseudocódigo equivalente está em docs/contratos/maquina_de_estados_totem.md.
"""

import json
from collections import deque

from . import VERSAO
from . import config as K
from .lcd import pagina, paginas, quebrar, reflow, tela_valida

# Interface
INICIANDO, AGUARDANDO_TAG, ESCOLHA_VAGA, MOSTRA_TELA = \
    "INICIANDO", "AGUARDANDO_TAG", "ESCOLHA_VAGA", "MOSTRA_TELA"
# Enlace
SEM_HORA, SEM_HANDSHAKE, PRONTO = "SEM_HORA", "SEM_HANDSHAKE", "PRONTO"

ESTADOS_DA_VAGA = ("livre", "aguardando_energia", "carregando", "pausada",
                   "completa_tolerancia", "completa_taxa")
ROTULO = {"livre": "LIVRE", "aguardando_energia": "FILA", "pausada": "PAUSA",
          "completa_tolerancia": "CHEIO", "completa_taxa": "TAXA"}

LIGAR = ("ligar", "liberar")           # v2.1 e o nome de hoje (ADR-015)
DESLIGAR = ("desligar", "bloquear")

# Tela montada no totem quando a resposta não traz "tela". {n} = número da vaga.
# Cobre a lista fechada do contrato e os motivos legados. Cada linha cabe em 16
# colunas (LCD 16x2, ADR-022); mais de 2 linhas viram 2 páginas.
TELA_DO_MOTIVO = {
    "iniciada":                    ["Vaga {n} liberada", "Boa recarga!"],
    "encerrada":                   ["Vaga {n} encerrou", "Retire o celular"],
    "confirmada_app":              ["Vaga {n} liberada", "Recarga do app"],
    "aguardando_energia":          ["Vaga {n} na fila", "Limite atingido", "Liga sozinha", "quando liberar"],
    "vaga_ocupada":                ["Vaga {n} ocupada", "Escolha outra"],
    "ja_carregando_em_outra_vaga": ["Voce ja carrega", "em outra vaga"],
    "saldo_insuficiente":          ["Sem saldo", "Adicione no app"],
    "taxa_pendente":               ["Taxa pendente", "Quite no app"],
    "cartao_nao_cadastrado":       ["Tag desconhecida", "Cadastre no app"],
    "cartao_de_outro_usuario":     ["Tag de outro", "morador"],
    "cartao_de_outro_condominio":  ["Tag de outro", "condominio"],
    "sem_veiculo":                 ["Sem veiculo", "Cadastre no app"],
    "uid_invalido":                ["Leitura falhou", "Aproxime de novo"],
    "sem_recarga_preparada":       ["Sem recarga", "preparada no app"],
    "limite_de_potencia":          ["Sem energia", "Tente mais tarde"],
    "espera_encerrada":            ["Espera encerrada", "Prepare de novo"],
}
TELA_SEM_CONEXAO = ["Sem conexao", "Tente de novo"]

# Recusa de autenticação (ADR-021): 401 que insistir não resolve.
RECUSAS = ("assinatura_invalida", "fora_da_janela")
TELA_DA_RECUSA = {"assinatura_invalida": "Chave invalida", "fora_da_janela": "Relogio servidor"}
DIAGNOSTICO = {
    "assinatura_invalida": (
        "handshake recusado (401 assinatura_invalida) {n} vezes seguidas: a chave do "
        "totem_virtual/.env nao bate com a DEVICE_MASTER_KEY do backend (ou o DEVICE_ID nao "
        "existe no banco que o backend usa). Rode backend/preparar_totem.py de novo e "
        "reinicie o totem. Nova tentativa a cada {s} s."),
    "fora_da_janela": (
        "handshake recusado (401 fora_da_janela) {n} vezes seguidas, mesmo logo depois de "
        "acertar a hora pelo /hora: o relogio do computador do backend discorda do relogio "
        "do banco (Supabase) em mais que a janela anti-replay. Sincronize o relogio do "
        "Windows (Configuracoes > Hora e idioma > Sincronizar agora, ou 'w32tm /resync' "
        "como administrador) e reinicie o backend. Nova tentativa a cada {s} s."),
}


class Vaga:
    """O que o firmware guarda de cada vaga (um struct no C++)."""
    def __init__(self, porta: int):
        self.porta = porta
        self.existe = False            # veio no handshake?
        self.rele = False
        self.estado = "livre"
        self.estado_do_backend = False # False = derivado do relé, não informado
        self.t_estado_ms = 0           # relógio próprio da vaga
        self.sessao_id = None
        self.energia_wh = 0.0          # acumulada na sessão (nunca delta: ADR-015)
        self.medida = {"tensao_v": 0.0, "corrente_a": 0.0, "potencia_w": 0.0}
        self.pedido_ate_ms = None      # recarga preparada no app esperando a tag
        self.pedido_de = None
        self.tela_backend = None
        self.divergente_desde_ms = None
        self.ultima_resposta = {}
        self.motivo_rele = "inicio"


class Firmware:
    def __init__(self, hal, enlace, cfg):
        self.hal, self.enlace, self.cfg = hal, enlace, cfg
        self.vagas = {p: Vaga(p) for p in (1, 2, 3, 4)}
        self.eventos: deque = deque(maxlen=200)
        self.fila_leituras: deque = deque(maxlen=K.FILA_LEITURAS_MAX)
        self.fila_fontes: deque = deque(maxlen=K.FILA_FONTES_MAX)
        self.descartadas = 0
        self.setup()

    # ===================================================================
    # setup()
    # ===================================================================

    def setup(self) -> None:
        agora = self.hal.millis()
        for v in self.vagas.values():
            self.hal.rele(v.porta, False)          # ao ligar, todo relé ABERTO
        self.hal.selecionar_fonte("rede")         # reversor da vaga 4 desligado

        self.ui, self.t_ui, self.duracao_tela = INICIANDO, agora, 0
        self.uid, self.tela = None, []

        self.link = SEM_HORA
        self.handshake_feito = False
        self.proxima_tentativa = agora
        self.espera_ms = K.RETENTATIVA_MIN_MS
        self.offline_desde = None
        self.wifi_estava_ok = True
        self.chave_recusada = False
        self.recusa, self.recusas_seguidas = None, 0   # último 401 de autenticação
        self.diagnostico = None                        # texto acionável quando bloqueia
        self.cortou_offline = False
        self.t_reconciliou = -60_000

        self.t_medicao = self.t_amostra = self.t_envio = self.t_comandos = agora
        self.comandos_ms = self.cfg.comandos_ms
        self.lote_max = K.MAX_LEITURAS_LOTE
        self.drenando = False
        self.lotes_enviados = self.lotes_descartados = 0

        self.fonte, self.t_troca, self.t_forcada = "rede", agora, None
        self.fonte_backend = None                  # "solar" | "rede" (porta solar na telemetria)
        self.queda_desde = None
        self.bateria_ok = True
        self._evento("placa ligou: reles abertos")

    # ===================================================================
    # loop()
    # ===================================================================

    def loop(self) -> None:
        agora = self.hal.millis()
        self._rede(agora)
        self._interface(agora)
        self._medir(agora)
        self._fonte_solar(agora)
        self._telemetria(agora)
        self._comandos(agora)
        self._trava_offline(agora)
        self._desenhar(agora)

    def _evento(self, texto: str) -> None:
        self.eventos.append({"t_ms": self.hal.millis(), "texto": texto})

    # ===================================================================
    # Enlace: hora -> handshake -> pronto, com nova tentativa espaçada
    # ===================================================================

    def online(self) -> bool:
        return self.link == PRONTO and self.offline_desde is None and self.hal.wifi_ok()

    def _sucesso(self) -> None:
        if self.offline_desde is not None:
            self._evento("servidor voltou a responder")
        self.offline_desde = None
        self.espera_ms = K.RETENTATIVA_MIN_MS
        self.chave_recusada = False
        if self.diagnostico:
            self._evento("servidor voltou a aceitar a placa")
        self.recusa, self.recusas_seguidas, self.diagnostico = None, 0, None

    def _esperar_mais(self, agora: int) -> None:
        self.proxima_tentativa = agora + self.espera_ms
        self.espera_ms = min(K.RETENTATIVA_MAX_MS, self.espera_ms * 2)

    def _falha(self, agora: int) -> None:
        if self.offline_desde is None:
            self.offline_desde = agora
            self._evento("sem resposta do servidor")
        self._esperar_mais(agora)

    def _recusado(self, codigo: str, agora: int) -> None:
        """401 de autenticação (ADR-021). Insistir rápido não resolve."""
        # Servidor que não aceita a placa = servidor que não acompanha a recarga:
        # a trava offline também vale aqui (D2).
        if self.offline_desde is None:
            self.offline_desde = agora
        self.recusas_seguidas = self.recusas_seguidas + 1 if codigo == self.recusa else 1
        self.recusa = codigo
        self.chave_recusada = codigo == "assinatura_invalida"
        if codigo == "fora_da_janela":
            self.link = SEM_HORA                   # o relógio da placa pode ter derivado
        if self.recusas_seguidas < K.RECUSAS_PARA_BLOQUEAR:
            self._evento(f"recusado ({codigo}): tentativa {self.recusas_seguidas}")
            self._esperar_mais(agora)
            return
        self.proxima_tentativa = agora + K.BLOQUEIO_MS
        if self.recusas_seguidas == K.RECUSAS_PARA_BLOQUEAR:
            self.diagnostico = DIAGNOSTICO[codigo].format(n=self.recusas_seguidas,
                                                          s=K.BLOQUEIO_MS // 1000)
            self._evento(f"BLOQUEADO ({codigo}): {self.diagnostico}")

    def _tratar(self, r, agora: int) -> bool:
        """Efeito colateral comum de toda resposta. True = deu 200."""
        if not r.chegou:
            self._falha(agora)
            return False
        if r.status == 401 and r.codigo in RECUSAS:
            self._recusado(r.codigo, agora)
            return False
        self._sucesso()
        if r.status == 200:
            return True
        if r.codigo == "boot_desconhecido":
            self.link = SEM_HANDSHAKE
        elif r.codigo == "replay":
            self.enlace.novo_boot()                # numeração fora de sincronia
            self.link = SEM_HANDSHAKE
            self._evento("replay: boot novo e handshake")
        return False

    def _rede(self, agora: int) -> None:
        wifi = self.hal.wifi_ok()
        if not wifi:
            if self.offline_desde is None:
                self.offline_desde = agora
                self._evento("Wi-Fi caiu")
            self.wifi_estava_ok = False
            return
        if not self.wifi_estava_ok:                # voltou agora: tenta já
            self.wifi_estava_ok = True
            self.proxima_tentativa = agora
            self.espera_ms = K.RETENTATIVA_MIN_MS
            self._evento("Wi-Fi voltou")
        if self.link == PRONTO or agora < self.proxima_tentativa:
            return

        if self.link == SEM_HORA:
            r = self.enlace.acertar_relogio()
            if not r.ok:
                self._falha(agora)
                return
            self.link = PRONTO if self.handshake_feito else SEM_HANDSHAKE
            # /hora é pública: responder não prova que o servidor aceita a placa.
            if self.link == PRONTO and self.recusa is None:
                self._sucesso()
            return

        r = self.enlace.handshake(VERSAO)
        if self._tratar(r, agora):
            self._aplicar_handshake(r.dados, agora)
            self.link, self.handshake_feito = PRONTO, True
            self.cortou_offline = False
        elif r.chegou and self.link == SEM_HANDSHAKE:
            self.proxima_tentativa = max(self.proxima_tentativa, agora + K.RETENTATIVA_MIN_MS)

    def _aplicar_handshake(self, dados: dict, agora: int) -> None:
        """Reconcilia cada vaga com o que o servidor diz que deveria estar acontecendo."""
        if dados.get("intervalo_comandos_s"):
            self.comandos_ms = int(float(dados["intervalo_comandos_s"]) * 1000)
        if dados.get("max_leituras_lote"):
            self.lote_max = min(K.MAX_LEITURAS_LOTE, int(dados["max_leituras_lote"]))
        for v in self.vagas.values():
            v.existe = False
        for p in dados.get("portas") or []:
            v = self.vagas.get(p.get("porta"))
            if not v:
                continue
            v.existe = True
            v.divergente_desde_ms = None
            ativa = p.get("sessao_ativa") or {}
            if p.get("rele_esperado"):
                self._ligar(v, ativa.get("sessao_id"), "handshake", agora,
                            energia_wh=float(ativa.get("energia_wh") or 0))
            else:
                self._desligar(v, "handshake", agora)
            if p.get("estado") in ESTADOS_DA_VAGA:
                self._estado(v, p["estado"], agora)
            self._pedido(v, p.get("pedido"), agora)
        self._evento(f"handshake ok: {len(dados.get('portas') or [])} porta(s)")

    # ===================================================================
    # Relé e estado da vaga
    # ===================================================================

    def _estado(self, v: Vaga, estado: str, agora: int, do_backend: bool = True) -> None:
        if estado != v.estado:
            v.estado, v.t_estado_ms = estado, agora
        v.estado_do_backend = do_backend
        # Só o BACKEND encerra a sessão da vaga. Um desligar pode ser pausa:
        # se a mesma sessão voltar, o contador de energia continua.
        if do_backend and estado == "livre" and not v.rele:
            v.sessao_id = None

    def _ligar(self, v: Vaga, sessao_id, origem: str, agora: int, energia_wh: float | None = None) -> None:
        nova = (sessao_id is not None and sessao_id != v.sessao_id) or \
               (sessao_id is None and v.sessao_id is None and not v.rele)
        if nova:
            v.energia_wh = 0.0                     # sessão nova: contador do zero
        if sessao_id is not None:
            v.sessao_id = sessao_id
        if energia_wh is not None:
            v.energia_wh = max(v.energia_wh, energia_wh)   # reboot: continua de onde parou
        v.pedido_ate_ms = v.pedido_de = None
        v.divergente_desde_ms = None
        if not v.rele:
            self.hal.rele(v.porta, True)
            v.rele, v.motivo_rele = True, origem
            self._evento(f"rele {v.porta} LIGADO ({origem})")
        if not v.estado_do_backend or v.estado == "livre":
            self._estado(v, "carregando", agora, do_backend=False)

    def _desligar(self, v: Vaga, origem: str, agora: int) -> None:
        if v.rele:
            self.hal.rele(v.porta, False)
            v.rele, v.motivo_rele = False, origem
            self._evento(f"rele {v.porta} DESLIGADO ({origem})")
        if not v.estado_do_backend or v.estado == "carregando":
            self._estado(v, "livre", agora, do_backend=False)

    def _pedido(self, v: Vaga, pedido: dict | None, agora: int) -> None:
        if not pedido:
            v.pedido_ate_ms = v.pedido_de = None
            return
        segundos = float(pedido.get("segundos_para_aproximar") or 120)
        v.pedido_ate_ms = agora + int(segundos * 1000)
        v.pedido_de = pedido.get("usuario")

    # ===================================================================
    # Interface: tag -> botão da vaga -> POST /v2/rfid -> tela
    # ===================================================================

    def _mostrar(self, linhas: list, agora: int, duracao_ms: int = K.TELA_MS) -> None:
        """Re-quebra em 16 colunas e pagina de 2 em 2 linhas (ADR-022 D3)."""
        self.tela = reflow(linhas)
        self.ui, self.t_ui = MOSTRA_TELA, agora
        self.duracao_tela = max(duracao_ms, paginas(self.tela) * K.PAGINA_MS)

    def _interface(self, agora: int) -> None:
        tag, botao = self.hal.tag_lida(), self.hal.botao()

        if self.ui == INICIANDO:
            if self.link != PRONTO:
                return                             # ainda sem servidor: ignora tag e botão
            self.ui, self.t_ui = AGUARDANDO_TAG, agora

        if tag:                                    # vale em qualquer tela: a pessoa não espera
            self.uid, self.ui, self.t_ui = tag, ESCOLHA_VAGA, agora
            return

        if self.ui == ESCOLHA_VAGA:
            if botao:
                self._enviar_tag(botao, agora)
            elif agora - self.t_ui >= K.TIMEOUT_ESCOLHA_MS:
                self.uid = None
                self._evento("timeout na escolha da vaga")
                self._mostrar(["Tempo esgotado", "Aproxime de novo"], agora, K.AVISO_MS)
        elif botao and self.ui == AGUARDANDO_TAG:
            self._mostrar(["Aproxime o", "cartao primeiro"], agora, K.AVISO_MS)
        elif self.ui == MOSTRA_TELA and agora - self.t_ui >= self.duracao_tela:
            self.ui, self.t_ui = AGUARDANDO_TAG, agora

    def _enviar_tag(self, porta: int, agora: int) -> None:
        uid, self.uid = self.uid, None
        v = self.vagas[porta]
        # Sem servidor NÃO guarda para depois: iniciar recarga minutos mais
        # tarde, sem ninguém na frente do totem, seria pior que recusar.
        if self.link != PRONTO or not self.hal.wifi_ok():
            self._mostrar(TELA_SEM_CONEXAO, agora)
            return
        r = self.enlace.rfid(porta, uid)
        if not self._tratar(r, agora):
            if not r.chegou:
                self._mostrar(TELA_SEM_CONEXAO, agora)
            elif r.status == 422:
                self._mostrar([f"Vaga {porta}", "indisponivel"], agora)
            else:
                self._mostrar(["Nao deu certo", "Aproxime de novo"], agora)
            return

        d = r.dados
        acao = d.get("acao")
        if acao in LIGAR:
            self._ligar(v, d.get("sessao_id"), "rfid", agora)
        elif acao in DESLIGAR:
            self._desligar(v, "rfid", agora)
        # Sem "acao" (backend de hoje): quem liga é o comando `liberar`.

        if tela_valida(d.get("tela")):
            linhas = d["tela"]
        else:
            motivo = d.get("motivo") or ("confirmada_app" if d.get("autorizado") else "")
            modelo = TELA_DO_MOTIVO.get(motivo)
            linhas = [x.format(n=porta) for x in modelo] if modelo else \
                quebrar(d.get("mensagem") or ("Liberado" if d.get("autorizado") else "Nao autorizado"))[:4]
        self._mostrar(linhas, agora)

    # ===================================================================
    # Medição: INA219 de cada vaga, energia acumulada, fila de leituras
    # ===================================================================

    def _medir(self, agora: int) -> None:
        dt_ms = agora - self.t_medicao
        if dt_ms < K.MEDICAO_MS:
            return
        self.t_medicao = agora
        for v in self.vagas.values():
            v.medida = self.hal.ler_ina(v.porta)
            if v.rele:
                v.energia_wh += v.medida["potencia_w"] * dt_ms / 3_600_000.0
            if v.pedido_ate_ms is not None and agora >= v.pedido_ate_ms:
                v.pedido_ate_ms = v.pedido_de = None

        if agora - self.t_amostra < self.cfg.amostra_ms:
            return
        self.t_amostra = agora
        for v in self.vagas.values():
            if not v.existe:
                continue
            if len(self.fila_leituras) == self.fila_leituras.maxlen:
                self.descartadas += 1              # a mais antiga sai; a energia é acumulada
            self.fila_leituras.append({
                "porta": v.porta, "t_ms": agora, "potencia_w": v.medida["potencia_w"],
                "energia_wh": round(v.energia_wh, 4), "tensao_v": v.medida["tensao_v"],
                "corrente_a": v.medida["corrente_a"], "rele_ligado": v.rele})
        if self.vagas[K.PORTA_SOLAR].existe:
            # INA219 em série com a 18650 (ADR-022 D2): COM SINAL, + descarregando,
            # - carregando. O painel não tem sensor: não vai "painel" no lote.
            m = self.hal.ler_bateria()
            self.fila_fontes.append({"fonte": "bateria", "t_ms": agora, "potencia_w": m["potencia_w"],
                                     "tensao_v": m["tensao_v"], "corrente_a": m["corrente_a"]})

    # ===================================================================
    # Vaga 4: solar OU rede, pelo relé reversor (ADR-022 D1)
    # ===================================================================

    def _virar(self, nova: str, agora: int, forcada: bool) -> None:
        if nova == self.fonte:
            return
        self.hal.selecionar_fonte(nova)            # contato reversor: nunca as duas
        self.fonte, self.t_troca, self.queda_desde = nova, agora, None
        self.t_forcada = agora if forcada else None
        self._evento(f"fonte da vaga 4 -> {nova}")

    def _fonte_solar(self, agora: int) -> None:
        if agora - self.t_troca < K.TROCA_FONTE_MS:
            return                                 # medida estabilizando
        v_bateria = self.hal.ler_bateria()["tensao_v"]
        if not self.bateria_ok and self.fonte == "rede" and v_bateria >= K.V_BATERIA_VOLTA:
            self.bateria_ok = True
            self._evento("bateria solar recuperada")
        if not self.vagas[K.PORTA_SOLAR].rele:
            self._virar("rede", agora, forcada=False)   # sem carga: o painel carrega a 18650
            return

        if self.fonte == "solar" and v_bateria < K.V_BATERIA_CORTE:
            if self.queda_desde is None:
                self.queda_desde = agora
            if agora - self.queda_desde >= K.QUEDA_MS:  # proteção local: vale offline
                self.bateria_ok = False
                self._evento("bateria solar baixa: vaga 4 para a rede")
                self._virar("rede", agora, forcada=True)
            return
        self.queda_desde = None

        if self.fonte_backend == "rede" or not self.bateria_ok:
            self._virar("rede", agora, forcada=True)
            return
        if self.fonte == "rede" and self.t_forcada is not None and \
                agora - self.t_forcada < K.FONTE_MIN_MS:
            return                                 # sem vai-e-volta no relé
        self._virar("solar", agora, forcada=False)

    # ===================================================================
    # Telemetria em lote
    # ===================================================================

    def _montar_lote(self, agora: int) -> tuple[dict, int, int]:
        n = min(len(self.fila_leituras), self.lote_max)
        m = min(len(self.fila_fontes), K.MAX_FONTES_LOTE)
        while True:
            corpo = {"t_envio_ms": agora, "leituras": [self.fila_leituras[i] for i in range(n)]}
            if m:
                corpo["fontes"] = [self.fila_fontes[i] for i in range(m)]
            if len(json.dumps(corpo, separators=(",", ":"))) <= K.CORPO_MAX_BYTES or n <= 1:
                return corpo, n, m
            n, m = max(1, n * 3 // 4), m * 3 // 4

    def _telemetria(self, agora: int) -> None:
        if not self.fila_leituras or self.link != PRONTO or not self.hal.wifi_ok():
            return
        if agora < self.proxima_tentativa:
            return
        if not self.drenando and agora - self.t_envio < self.cfg.envio_ms:
            return
        self.t_envio = agora
        corpo, n, m = self._montar_lote(agora)
        r = self.enlace.telemetria(corpo)          # reenvio = requisição nova = seq novo
        if self._tratar(r, agora):
            self._retirar(n, m)
            self.lotes_enviados += 1
            self.drenando = len(self.fila_leituras) >= self.lote_max
            for p in r.dados.get("portas") or []:
                self._resposta_da_porta(p, agora)
            return
        self.drenando = False
        if not r.chegou:
            return                                 # fica na fila para a próxima
        if r.status == 413:
            self.lote_max = max(1, self.lote_max // 2)
        elif r.status == 422:
            # Lote que o servidor nunca vai aceitar: jogar fora, senão trava a fila.
            self._retirar(n, m)
            self.lotes_descartados += 1
            self._evento(f"lote recusado ({r.codigo}): descartado")

    def _retirar(self, n: int, m: int) -> None:
        for _ in range(n):
            self.fila_leituras.popleft()
        for _ in range(m):
            self.fila_fontes.popleft()

    def _resposta_da_porta(self, p: dict, agora: int) -> None:
        v = self.vagas.get(p.get("porta"))
        if not v:
            return
        v.ultima_resposta = p
        if p.get("estado") in ESTADOS_DA_VAGA:
            self._estado(v, p["estado"], agora)
        if v.porta == K.PORTA_SOLAR and p.get("fonte") in ("solar", "rede"):
            self.fonte_backend = p["fonte"]
        if tela_valida(p.get("tela")) and p["tela"] != v.tela_backend:
            v.tela_backend = p["tela"]
            if self.ui == AGUARDANDO_TAG:
                self._mostrar(p["tela"], agora)

        deve = p.get("deve_liberar")
        if deve is False and v.rele:
            # Trava de sessão: sem sessão no servidor, o relé não fica fechado.
            self._desligar(v, "trava de sessao", agora)
        if deve is True and not v.rele:
            # O servidor acha que a vaga carrega e o relé está aberto (um comando
            # se perdeu?). Não fecha por conta própria: reconcilia pelo handshake.
            if v.divergente_desde_ms is None:
                v.divergente_desde_ms = agora
            elif agora - v.divergente_desde_ms >= 10_000 and agora - self.t_reconciliou >= 30_000:
                self.t_reconciliou, v.divergente_desde_ms = agora, None
                self.link = SEM_HANDSHAKE
                self._evento(f"vaga {v.porta} divergente do servidor: novo handshake")
        else:
            v.divergente_desde_ms = None

    # ===================================================================
    # Comandos
    # ===================================================================

    def _comandos(self, agora: int) -> None:
        if self.link != PRONTO or not self.hal.wifi_ok() or agora < self.proxima_tentativa:
            return
        if agora - self.t_comandos < self.comandos_ms:
            return
        self.t_comandos = agora
        r = self.enlace.comandos()
        if not self._tratar(r, agora):
            return
        for c in r.dados.get("comandos") or []:
            erro = self._executar(c, agora)
            self.enlace.confirmar(c.get("id"), erro is None, erro)

    def _executar(self, c: dict, agora: int) -> str | None:
        """Devolve None se executou, ou o texto do erro."""
        v = self.vagas.get(c.get("porta") or 1)
        acao = c.get("acao")
        if not v:
            return "porta_inexistente"
        if acao in LIGAR:
            self._ligar(v, c.get("sessao_id"), "comando", agora)
        elif acao in DESLIGAR:
            self._desligar(v, "comando", agora)
        elif acao == "solicitar_cartao":
            self._pedido(v, c.get("payload") or {"segundos_para_aproximar": 120}, agora)
        elif acao == "cancelar_cartao":
            self._pedido(v, None, agora)
        elif acao == "ping":
            self._evento(f"ping na vaga {v.porta}")
            if self.ui == AGUARDANDO_TAG:
                self._mostrar(["PING", f"Vaga {v.porta} ok"], agora, K.AVISO_MS)
        else:
            return "acao_desconhecida"
        return None

    # ===================================================================
    # Trava offline (ADR-020 P2)
    # ===================================================================

    def _trava_offline(self, agora: int) -> None:
        if self.offline_desde is None or self.cortou_offline:
            return
        if agora - self.offline_desde < self.cfg.offline_corte_ms:
            return
        self.cortou_offline = True
        for v in self.vagas.values():
            self._desligar(v, "trava offline", agora)
        # Na volta, o handshake diz o que o servidor ainda considera ativo.
        if self.link == PRONTO:
            self.link = SEM_HANDSHAKE
        self._evento("tempo demais sem servidor: reles abertos")

    # ===================================================================
    # LCD 20x4
    # ===================================================================

    def _rotulo(self, v: Vaga) -> str:
        """Até 5 colunas: 4 vagas cabem em 2 linhas de 16."""
        if not v.existe:
            return "--"
        if v.rele and v.estado == "carregando":
            w = v.medida["potencia_w"]
            texto = f"{w:.1f}W" if w < 9.95 else f"{w:.0f}W"
            if v.porta == K.PORTA_SOLAR:
                texto += "S" if self.fonte == "solar" else "R"
            return texto
        return ROTULO.get(v.estado, "CARGA")

    def _desenhar(self, agora: int) -> None:
        if self.ui == MOSTRA_TELA:
            linhas = pagina(self.tela, (agora - self.t_ui) // K.PAGINA_MS)
        elif self.ui == ESCOLHA_VAGA:
            resta = max(0, (K.TIMEOUT_ESCOLHA_MS - (agora - self.t_ui) + 999) // 1000)
            linhas = ["Escolha vaga 1-4", f"Tempo: {resta:>2} s"]
        elif self.ui == INICIANDO:
            passo = TELA_DA_RECUSA[self.recusa] if self.recusa else \
                "Sem Wi-Fi" if not self.hal.wifi_ok() else \
                {SEM_HORA: "Acertando hora", SEM_HANDSHAKE: "Conectando..."}.get(self.link, "")
            linhas = ["ChargeOps GoodWe", passo]
        elif (agora // K.ALTERNA_MS) % 2 == 0:
            pedido = next((v for v in self.vagas.values() if v.pedido_ate_ms is not None), None)
            aviso = TELA_DA_RECUSA[self.recusa] if self.recusa else \
                "Sem rede: espere" if not self.online() else \
                f"Vaga {pedido.porta}: aproxime" if pedido else "Aproxime cartao"
            linhas = ["ChargeOps GoodWe", aviso]
        else:
            r = {p: self._rotulo(v) for p, v in self.vagas.items()}
            linhas = [f"1:{r[1]:<5} 2:{r[2]:<5}", f"3:{r[3]:<5} 4:{r[4]:<5}"]
        self.hal.lcd_escrever(linhas)
