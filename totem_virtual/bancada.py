"""
bancada.py - O "hardware" do totem, de mentira.
===============================================

Hardware alvo (contrato): 1 ESP32, 1 LCD 20x4, 1 leitor RFID, 4 botões e
4 vagas com relé + INA219. A vaga 4 é solar: painel OU bateria 18650, com
uma chave de fonte que nunca liga as duas ao mesmo tempo.

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
FONTES = ("painel", "bateria", "nenhuma")


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
        self._fontes = {"painel": (0.0, 0.0), "bateria": (0.0, 0.0)}
        self._fonte = "nenhuma"
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

    def ler_fonte(self, nome: str) -> dict:                    # INA219 do painel / da bateria
        return fisica.ina219(*self._fontes[nome])

    def selecionar_fonte(self, nome: str) -> None:             # 2 relés intertravados: nunca os dois
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
        self._fonte = "nenhuma"
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

        # Vaga 4: painel OU bateria.
        pedido = self._pedido(PORTA_SOLAR)
        disponivel = self.painel.disponivel_w()
        sai_painel = sai_bateria = entra_bateria = 0.0
        entregue, barra = 0.0, 0.0

        if self._fonte == "painel":
            if pedido <= disponivel:
                entregue = sai_painel = pedido
                barra = fisica.V_USB - fisica.R_CABO * (pedido / fisica.V_USB) if disponivel > 0 else 0.0
            else:                                   # painel fraco: o barramento afunda
                sai_painel = disponivel
                entregue = disponivel * 0.9
                barra = fisica.V_USB * disponivel / pedido
        elif self._fonte == "bateria" and self.bateria.soc > 0:
            entregue = min(pedido, fisica.P_SAIDA_BATERIA_MAX_W)
            sai_bateria = entregue / fisica.EFICIENCIA_CONVERSOR
            barra = fisica.V_USB - fisica.R_CABO * (entregue / fisica.V_USB)
            self.bateria.descarregar(sai_bateria, dt_s)
        else:
            # Ninguém alimenta a vaga: o painel aproveita para carregar a bateria.
            if self.bateria.soc < 100.0:
                entra_bateria = sai_painel = min(disponivel, fisica.P_CARGA_BATERIA_MAX_W)
                self.bateria.carregar(entra_bateria, dt_s)

        if self._reles[PORTA_SOLAR]:
            self._entregar(PORTA_SOLAR, entregue, barra, dt_s)
        else:
            self._medidas[PORTA_SOLAR] = (0.0, 0.0)

        v_painel = self.painel.tensao_v(pedido if self._fonte == "painel" else sai_painel)
        self._fontes["painel"] = (v_painel, sai_painel / v_painel if v_painel > 0.1 else 0.0)
        v_bateria = self.bateria.tensao_v(saida_w=sai_bateria, entrada_w=entra_bateria)
        self._fontes["bateria"] = (v_bateria, sai_bateria / v_bateria if v_bateria > 0.1 else 0.0)
