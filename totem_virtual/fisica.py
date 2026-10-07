"""
fisica.py - O mundo físico de mentira: celular, sensor, painel e bateria.
=========================================================================

TUDO AQUI É SIMULADO. Nenhum número deste arquivo é medição.

Celular: física de referência do contrato (seção C):
  ~7,5 W até 80% da carga; cai em linha reta até ~0,5 W em 100%; depois
  manutenção de ~0,1 W. Desplugar = corrente zero imediata, com o relé
  fechado. Ruído de ±2%.

Solar (ADR-022): painel 5 V 1 W -> TP4056 -> 18650 2000 mAh -> MT3608 (5 V),
dedicado à vaga 4 por um relé reversor (solar OU rede). Modelo simplificado:
serve para exercitar a comutação e a telemetria; os limiares de verdade saem
da bancada real.

Funções puras e classes pequenas, sem relógio próprio: quem chama diz quanto
tempo passou.
"""

from dataclasses import dataclass

P_CHEIA_W = 7.5
P_FIM_W = 0.5
P_MANUTENCAO_W = 0.1
SOC_JOELHO = 80.0
RUIDO = 0.02
EFICIENCIA_CARGA = 0.92          # mesma premissa do backend (fisica.EFICIENCIA_CARGA)
V_USB = 5.05                     # barramento sem carga
R_CABO = 0.04                    # ohms: a tensão cede um pouco com a corrente


def potencia_do_celular(soc: float) -> float:
    """Quanto o celular PEDE, em W, para um dado % de carga."""
    if soc >= 100.0:
        return P_MANUTENCAO_W
    if soc <= SOC_JOELHO:
        return P_CHEIA_W
    fracao = (soc - SOC_JOELHO) / (100.0 - SOC_JOELHO)
    return P_CHEIA_W + (P_FIM_W - P_CHEIA_W) * fracao


@dataclass
class CelularVirtual:
    capacidade_wh: float = 15.0
    soc: float = 20.0                # %
    plugado: bool = True

    def pede_w(self) -> float:
        return potencia_do_celular(self.soc) if self.plugado else 0.0

    def absorver(self, potencia_w: float, dt_s: float) -> None:
        if not self.plugado or potencia_w <= 0 or self.soc >= 100.0:
            return
        ganho_wh = potencia_w * EFICIENCIA_CARGA * dt_s / 3600.0
        self.soc = min(100.0, self.soc + 100.0 * ganho_wh / self.capacidade_wh)


# ---------------------------------------------------------------------------
# INA219: o que o sensor entrega depois de quantizar
# ---------------------------------------------------------------------------

LSB_TENSAO_V = 0.004
LSB_CORRENTE_A = 0.0001


def ina219(tensao_v: float, corrente_a: float, assinado: bool = False) -> dict:
    """`assinado`: o sensor em série com a bateria mede nos dois sentidos (ADR-022 D2)."""
    v = round(max(0.0, tensao_v) / LSB_TENSAO_V) * LSB_TENSAO_V
    i = round((corrente_a if assinado else max(0.0, corrente_a)) / LSB_CORRENTE_A) * LSB_CORRENTE_A
    return {"tensao_v": round(v, 3), "corrente_a": round(i, 4), "potencia_w": round(v * i, 3)}


# ---------------------------------------------------------------------------
# Painel e bateria da vaga 4
# ---------------------------------------------------------------------------

P_PAINEL_MAX_W = 1.0             # painel 5 V 1 W da bancada
V_PAINEL_ABERTO = 6.0
P_CARGA_BATERIA_MAX_W = 4.0      # TP4056: 1 A a ~4 V (o painel limita antes)
P_SAIDA_BATERIA_MAX_W = 7.5      # MT3608 a 5 V: ~1,5 A na prática
EFICIENCIA_CONVERSOR = 0.90
R_BATERIA = 0.06                 # ohms

# SOC (%) -> tensão em circuito aberto de uma 18650 (curva típica de Li-íon)
CURVA_18650 = [(0, 3.00), (5, 3.30), (10, 3.45), (20, 3.60), (30, 3.68), (40, 3.74),
               (50, 3.80), (60, 3.87), (70, 3.95), (80, 4.02), (90, 4.10), (100, 4.20)]


def tensao_aberta_18650(soc: float) -> float:
    soc = max(0.0, min(100.0, soc))
    for (s0, v0), (s1, v1) in zip(CURVA_18650, CURVA_18650[1:]):
        if soc <= s1:
            return v0 + (v1 - v0) * (soc - s0) / (s1 - s0)
    return CURVA_18650[-1][1]


@dataclass
class PainelVirtual:
    luz: float = 1.0                 # 0 (escuro) a 1 (sol pleno)

    def disponivel_w(self) -> float:
        return P_PAINEL_MAX_W * max(0.0, min(1.0, self.luz))

    def tensao_v(self, pedido_w: float = 0.0) -> float:
        """Em aberto a tensão sobe com a luz; pedindo mais do que há, ela desaba."""
        if self.luz <= 0.01:
            return 0.0
        aberta = V_PAINEL_ABERTO * (0.7 + 0.3 * min(1.0, self.luz))
        disponivel = self.disponivel_w()
        if pedido_w <= disponivel:
            return aberta
        return aberta * disponivel / pedido_w


@dataclass
class Bateria18650:
    capacidade_wh: float = 7.4       # 2000 mAh x 3,7 V
    soc: float = 60.0

    def tensao_v(self, saida_w: float = 0.0, entrada_w: float = 0.0) -> float:
        aberta = tensao_aberta_18650(self.soc)
        corrente = (saida_w - entrada_w) / aberta        # > 0 descarregando
        return aberta - corrente * R_BATERIA

    def descarregar(self, potencia_w: float, dt_s: float) -> None:
        self.soc = max(0.0, self.soc - 100.0 * potencia_w * dt_s / 3600.0 / self.capacidade_wh)

    def carregar(self, potencia_w: float, dt_s: float) -> None:
        self.soc = min(100.0, self.soc + 100.0 * potencia_w * 0.95 * dt_s / 3600.0 / self.capacidade_wh)
