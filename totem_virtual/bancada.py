"""
bancada.py - O "hardware" do totem, de mentira.
===============================================

Hardware alvo (ADR-022): 1 ESP32, 1 LCD 16x2, 1 leitor RFID, 4 botões,
4 vagas com relé + INA219 e 1 INA219 em série com a bateria solar. A vaga 4
é solar: um relé reversor escolhe a bateria (painel -> TP4056 -> 18650 ->
MT3608) OU a rede (barramento de 5 V). O contato nunca liga as duas.

Este arquivo tem duas faces:

  HAL    o que o FIRMWARE enxerga. Cada método tem um equivalente direto no
         ESP32 (ao lado, em comentário). firmware.py só usa esta parte.

  MUNDO  o que a PESSOA faz na bancada: encostar a tag, apertar o botão,
         plugar o celular, tapar o painel, desligar o roteador. O firmware
         não tem acesso a isto - ele só descobre medindo.

TUDO AQUI É SIMULADO.
"""

import random
import time
from collections import deque

from . import fisica
from .lcd import Lcd

PORTAS = (1, 2, 3, 4)
PORTA_SOLAR = 4
FONTES = ("rede", "solar")          # posições do relé reversor da vaga 4


class Relogio:
    """Relógio de parede. Nos testes entra o RelogioManual."""
    def agora_s(self) -> float:
        return time.monotonic()


class RelogioManual(Relogio):
    def __init__(self):
        self.t = 0.0

    def agora_s(self) -> float:
        return self.t

    def avancar(self, segundos: float) -> None:
        self.t += segundos


class Bancada:
    def __init__(self, relogio: Relogio | None = None, rng: random.Random | None = None):
        self.relogio = relogio or Relogio()
        self.rng = rng or random.Random()
        self._ligou_em = self.relogio.agora_s()
        self._reles = {p: False for p in PORTAS}
        self._medidas = {p: (0.0, 0.0) for p in PORTAS}              # (V, A) reais
        self._bateria_vi = (0.0, 0.0)                               # (V, A com sinal)
        self._painel_vi = (0.0, 0.0)                                # só para a página
        self._fonte = "rede"
        self._tags, self._botoes = deque(maxlen=4), deque(maxlen=8)
        self.celulares: dict[int, fisica.CelularVirtual | None] = {p: None for p in PORTAS}
        self.painel = fisica.PainelVirtual(luz=1.0)
        self.bateria = fisica.Bateria18650()
        self.lcd = Lcd()
        self.wifi = True
        self.avancar(0.0)

    # ===================================================================
    # HAL - o que o firmware enxerga
    # ===================================================================

    def millis(self) -> int:                                   # millis()
        return int((self.relogio.agora_s() - self._ligou_em) * 1000)

    def rele(self, porta: int, ligado: bool) -> None:          # digitalWrite(PINO_RELE[p], ...)
        self._reles[porta] = bool(ligado)

    def rele_ligado(self, porta: int) -> bool:                 # digitalRead(PINO_RELE[p])
        return self._reles[porta]

    def ler_ina(self, porta: int) -> dict:                     # ina[p].getBusVoltage_V() / getCurrent_mA()
        return fisica.ina219(*self._medidas[porta])

    def ler_bateria(self) -> dict:                             # inaSolar (Wire1): em série com a 18650
        return fisica.ina219(*self._bateria_vi, assinado=True)  # + descarregando, - carregando

    def selecionar_fonte(self, nome: str) -> None:             # digitalWrite(PINO_REVERSOR, nome == solar)
        if nome not in FONTES:
            raise ValueError(nome)
        self._fonte = nome

    def fonte_selecionada(self) -> str:
        return self._fonte

    def tag_lida(self) -> str | None:                          # mfrc522.PICC_ReadCardSerial()
        return self._tags.popleft() if self._tags else None

    def botao(self) -> int | None:                             # botão com debounce: devolve 1..4 uma vez
        return self._botoes.popleft() if self._botoes else None

    def wifi_ok(self) -> bool:                                 # WiFi.status() == WL_CONNECTED
        return self.wifi

    def lcd_escrever(self, linhas) -> None:                    # lcd.setCursor() + lcd.print()
        self.lcd.escrever(linhas)

    # ===================================================================
    # MUNDO - o que a pessoa faz na bancada
    # ===================================================================

    def aproximar_tag(self, uid: str) -> None:
        self._tags.append(str(uid).strip())

    def apertar_botao(self, porta: int) -> None:
        if porta in PORTAS:
            self._botoes.append(porta)

    def plugar(self, porta: int, capacidade_wh: float = 15.0, soc: float = 20.0) -> None:
        self.celulares[porta] = fisica.CelularVirtual(
            capacidade_wh=max(0.05, float(capacidade_wh)), soc=max(0.0, min(100.0, float(soc))))

    def desplugar(self, porta: int) -> None:
        self.celulares[porta] = None

    def reiniciar(self) -> None:
        """Faltou energia na placa: relés caem, RAM some. Celular e bateria continuam onde estavam."""
        self._ligou_em = self.relogio.agora_s()
        self._reles = {p: False for p in PORTAS}
        self._fonte = "rede"                        # bobina do reversor desligada
        self._tags.clear()
        self._botoes.clear()
        self.lcd.apagar()
        self.avancar(0.0)

    # ===================================================================
    # Física: avança o mundo `dt_s` segundos
    # ===================================================================

    def _pedido(self, porta: int) -> float:
        cel = self.celulares[porta]
        if not (self._reles[porta] and cel and cel.plugado):
            return 0.0
        return cel.pede_w() * (1.0 + self.rng.uniform(-fisica.RUIDO, fisica.RUIDO))

    def _entregar(self, porta: int, potencia_w: float, tensao_v: float, dt_s: float) -> None:
        corrente = potencia_w / tensao_v if tensao_v > 0.1 else 0.0
        self._medidas[porta] = (tensao_v, corrente)
        if potencia_w > 0 and self.celulares[porta]:
            self.celulares[porta].absorver(potencia_w, dt_s)

    def avancar(self, dt_s: float) -> None:
        # Vagas 1 a 3: barramento USB comum.
        for porta in (1, 2, 3):
            if not self._reles[porta]:
                self._medidas[porta] = (0.0, 0.0)
                continue
            pedido = self._pedido(porta)
            tensao = fisica.V_USB - fisica.R_CABO * (pedido / fisica.V_USB)
            self._entregar(porta, pedido, tensao, dt_s)

        # Vaga 4: bateria solar (MT3608) OU rede, pelo reversor.
        pedido = self._pedido(PORTA_SOLAR)
        bateria = self.bateria
        # TP4056: com sol, o painel carrega a 18650 o tempo todo (com ou sem carga).
        carga_painel = (min(self.painel.disponivel_w(), fisica.P_CARGA_BATERIA_MAX_W)
                        if bateria.soc < 100.0 else 0.0)
        tem_fonte = self._fonte == "rede" or bateria.soc > 0    # MT3608 sem bateria = 0 V
        entregue = 0.0
        if tem_fonte:
            entregue = pedido if self._fonte == "rede" else min(pedido, fisica.P_SAIDA_BATERIA_MAX_W)
        sai_bateria = entregue / fisica.EFICIENCIA_CONVERSOR if self._fonte == "solar" else 0.0
        liquido = sai_bateria - carga_painel                    # > 0: a bateria descarrega
        if liquido > 0:
            bateria.descarregar(liquido, dt_s)
        else:
            bateria.carregar(-liquido, dt_s)

        if self._reles[PORTA_SOLAR] and tem_fonte:
            barra = fisica.V_USB - fisica.R_CABO * (entregue / fisica.V_USB)
            self._entregar(PORTA_SOLAR, entregue, barra, dt_s)
        else:
            self._medidas[PORTA_SOLAR] = (0.0, 0.0)

        v_bateria = bateria.tensao_v(saida_w=sai_bateria, entrada_w=carga_painel)
        self._bateria_vi = (v_bateria, liquido / v_bateria if v_bateria > 0.1 else 0.0)
        v_painel = self.painel.tensao_v(carga_painel)
        self._painel_vi = (v_painel, carga_painel / v_painel if v_painel > 0.1 else 0.0)

    def painel_visto(self) -> dict:
        """MUNDO, só para a página: o painel não tem sensor no totem (ADR-022 D2)."""
        return fisica.ina219(*self._painel_vi)
