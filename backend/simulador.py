"""
simulador.py - O laço de 10 s que mantém o sistema andando sozinho.
===================================================================

A cada ciclo, nesta ordem:
  1. derruba ESP32 sem contato e expira esperas de cartão vencidas
  2. esquenta/esfria os pontos SIMULADOS (o do ESP32 manda a própria)
  3. por condomínio com FV: grava a geração SOLAR SIMULADA (ADR-016 D9)
  4. por condomínio: roda o ALOCADOR de demanda e avança as recargas
     simuladas com a potência que ele liberou - e de qual fonte
  5. encerra recarga de ponto físico cuja placa sumiu há mais de
     SEGUNDOS_OFFLINE_ENCERRA (o totem corta sozinho aos 120 s; ADR-018)
  5b. liga quem espera energia (fila por ordem de chegada, ADR-018)
  6. registra a carga total do condomínio (e quanto veio da rede) na curva
     horária do gestor
  7. taxa de ociosidade: carro que ficou na vaga depois da carga (db/21)

SOLAR SIMULADO
--------------
Curva de céu limpo, determinística (ver config.py). O simulador é o ÚNICO
lugar que conhece a curva: o alocador lê `geracao_solar`, a mesma tabela que
um inversor de verdade vai preencher com origem 'medido'. Quando houver
leitura medida recente - ou qualquer linha gravada por uma placa (painel do
totem, real ou virtual) -, o simulador para de gravar naquele condomínio:
ele é o fallback rotulado.

Por que `asyncio.to_thread`: o cliente do Supabase é síncrono. Chamado direto
dentro do laço assíncrono, cada ciclo congelava o servidor inteiro por alguns
segundos - inclusive o GET /hardware/comandos que o ESP32 faz a cada 2 s.
"""

import asyncio
import math
import random
import time
from datetime import datetime, timedelta, timezone

import demanda
import dispositivos
import recarga
from config import (FUSO, SOLAR_BALDE_MIN, SOLAR_FATOR_PICO, SOLAR_NASCER_H, SOLAR_POR_H,
                    SOLAR_VALIDADE_MIN, agora, para_datetime, supabase)
from fisica import EFICIENCIA_CARGA, em_horario_de_ponta, potencia_efetiva, teto_kw, tempo_de_carga_min

INTERVALO_S = 10
# O ciclo não dura 10 s cravados: dorme 10 s DEPOIS de fazer as consultas.
# A energia simulada usa o tempo real decorrido (com teto, para um servidor
# que ficou parado não despejar horas de energia de uma vez).
MAX_DT_S = 30
# A placa marca offline aos 30 s (config.SEGUNDOS_ATE_OFFLINE), mas a recarga
# só é encerrada depois disto: o totem segue carregando até a trava offline
# dele (120 s, ADR-020 P2) e reconcilia pelo handshake se a rede voltar antes.
SEGUNDOS_OFFLINE_ENCERRA = 150
_ultimo_ciclo = None


def _horas_decorridas() -> float:
    global _ultimo_ciclo
    agora = time.monotonic()
    dt = INTERVALO_S if _ultimo_ciclo is None else agora - _ultimo_ciclo
    _ultimo_ciclo = agora
    return max(0.0, min(float(MAX_DT_S), dt)) / 3600


def _temperaturas(chargers: list[dict]) -> None:
    for c in chargers:
        if c.get("origem") != "simulado":
            continue
        atual = float(c.get("temperatura_c") or 25)
        alvo = 45 if c["status"] == "em_uso" else 24
        nova = max(18, min(60, atual + (alvo - atual) * 0.15 + random.uniform(-0.4, 0.4)))
        # Só grava mudança perceptível: cada UPDATE vira evento de Realtime
        # e faz todos os painéis abertos recarregarem.
        if abs(nova - atual) >= 0.3:
            supabase.table("carregadores").update({"temperatura_c": round(nova, 1)}) \
                .eq("id", c["id"]).execute()
            c["temperatura_c"] = round(nova, 1)


# ---------------------------------------------------------------------------
# Solar simulado (funções puras + gravação)
# ---------------------------------------------------------------------------

def _hora_local(momento: datetime) -> float:
    m = momento.astimezone(FUSO)
    return m.hour + m.minute / 60 + m.second / 3600 + m.microsecond / 3.6e9


def potencia_solar_kw(kwp: float, momento: datetime) -> float:
    """Potência FV de céu limpo no instante (0 à noite)."""
    h = _hora_local(momento)
    if kwp <= 0 or not SOLAR_NASCER_H < h < SOLAR_POR_H:
        return 0.0
    u = math.pi * (h - SOLAR_NASCER_H) / (SOLAR_POR_H - SOLAR_NASCER_H)
    return kwp * SOLAR_FATOR_PICO * math.sin(u) ** 2


def energia_solar_kwh(kwp: float, inicio: datetime, fim: datetime) -> float:
    """
    Integral exata da curva entre dois instantes do MESMO dia local:
    integral de sen²(u) = u/2 - sen(2u)/4.
    """
    if kwp <= 0 or fim <= inicio:
        return 0.0
    dia = SOLAR_POR_H - SOLAR_NASCER_H
    h1 = min(max(_hora_local(inicio), SOLAR_NASCER_H), SOLAR_POR_H)
    h2 = min(max(_hora_local(fim), SOLAR_NASCER_H), SOLAR_POR_H)
    if h2 <= h1:
        return 0.0

    def primitiva(h):
        u = math.pi * (h - SOLAR_NASCER_H) / dia
        return u / 2 - math.sin(2 * u) / 4

    return kwp * SOLAR_FATOR_PICO * dia / math.pi * (primitiva(h2) - primitiva(h1))


def inicio_do_balde(momento: datetime) -> datetime:
    m = momento.astimezone(timezone.utc)
    return m.replace(minute=m.minute - m.minute % SOLAR_BALDE_MIN, second=0, microsecond=0)


def balde_solar(kwp: float, momento: datetime) -> dict | None:
    """A linha de `geracao_solar` do balde que contém `momento` (None à noite)."""
    inicio = inicio_do_balde(momento)
    energia = energia_solar_kwh(kwp, inicio, inicio + timedelta(minutes=SOLAR_BALDE_MIN))
    if energia <= 0:
        return None
    return {"momento": inicio.isoformat(), "energia_kwh": round(energia, 6),
            "potencia_kw": round(energia / (SOLAR_BALDE_MIN / 60), 4), "origem": "simulado"}


def gravar_geracao_solar(cond: dict, momento: datetime | None = None) -> None:
    """
    Upsert idempotente do balde atual: reescrever dá o mesmo valor, então não
    precisa de RPC. Não sobrescreve leitura MEDIDA recente (inversor real).
    """
    kwp = float(cond.get("fv_potencia_kwp") or 0)
    if kwp <= 0:
        return
    momento = momento or agora()
    linha = balde_solar(kwp, momento)
    if not linha:
        return
    try:
        desde = (momento - timedelta(minutes=SOLAR_VALIDADE_MIN)).isoformat()
        recentes = supabase.table("geracao_solar").select("origem, dispositivo_id") \
            .eq("condominio_id", cond["id"]).gte("momento", desde).limit(20).execute().data or []
        if any(r.get("origem") == "medido" or r.get("dispositivo_id") for r in recentes):
            return
        supabase.table("geracao_solar").upsert({"condominio_id": cond["id"], **linha},
                                               on_conflict="condominio_id,momento").execute()
    except Exception as e:
        print(f"[SOLAR] geração não gravada: {e}")


# ---------------------------------------------------------------------------
# Ciclo
# ---------------------------------------------------------------------------

def _offline_ha_muito(carregador_id: str) -> bool:
    d = dispositivos.dispositivo_do_carregador(carregador_id)
    ultimo = para_datetime((d or {}).get("ultimo_contato"))
    return not ultimo or (agora() - ultimo).total_seconds() >= SEGUNDOS_OFFLINE_ENCERRA


def _promover_filas_de_energia(chargers_por_id: dict) -> None:
    """Fim da ponta, sol que voltou, limite que subiu: quem espera energia liga."""
    espera = supabase.table("sessoes_recarga").select("carregador_id") \
        .eq("status", "aguardando_energia").execute().data or []
    for cond_id in {chargers_por_id[s["carregador_id"]]["condominio_id"]
                    for s in espera if s["carregador_id"] in chargers_por_id}:
        try:
            recarga.promover_aguardando_energia(cond_id)
        except Exception as e:
            print(f"[SIMULADOR] fila de energia de {cond_id} não andou: {e}")


def ciclo() -> None:
    horas = _horas_decorridas()
    dispositivos.marcar_offline_sem_contato()
    recarga.expirar_esperas()

    conds = supabase.table("condominios").select("*").execute().data or []
    chargers = supabase.table("carregadores").select("*").execute().data or []
    _temperaturas(chargers)
    por_id = {c["id"]: c for c in chargers}
    _promover_filas_de_energia(por_id)

    sessoes = supabase.table("sessoes_recarga").select(
        "*, veiculos(capacidade_bateria_kwh, potencia_carro_kw, tipo)"
    ).eq("status", "carregando").execute().data or []

    for cond in conds:
        gravar_geracao_solar(cond)

        ids = {c["id"] for c in chargers if c["condominio_id"] == cond["id"]}
        do_local = [s for s in sessoes if s["carregador_id"] in ids]
        if not do_local:
            continue

        estado = demanda.alocar(cond["id"])
        por_sessao = {x["id"]: x for x in estado.get("sessoes", [])}
        origem_solar = (estado.get("origem_solar") or "solar_simulado").removeprefix("solar_")
        carga_total = solar_total = 0.0

        for s in do_local:
            c = por_id[s["carregador_id"]]
            v = s.get("veiculos") or {}
            x = por_sessao.get(s["id"], {})

            if c.get("origem") == "hardware":
                # Energia deste ponto vem do sensor do ESP32 (hardware_api).
                # Aqui só tratamos a placa que sumiu no meio da recarga.
                if c["status"] == "offline":
                    if _offline_ha_muito(c["id"]):
                        recarga.encerrar(s, "dispositivo_offline")
                else:
                    medida = float(s.get("potencia_atual_kw") or 0)
                    carga_total += medida
                    solar_total += min(medida, float(x.get("alocado_solar_kw") or 0))
                continue

            capacidade = float(v.get("capacidade_bateria_kwh") or 40)
            soc = float(s.get("percentual_bateria_atual") or 0)
            alvo = float(s.get("alvo_percentual") or 100)
            teto = teto_kw(c, v)
            liberado = x.get("alocado_kw", s.get("potencia_alocada_kw"))

            # O carro puxa o MENOR entre a curva da bateria e o que o alocador
            # liberou; dessa potência, o sol alocado vem primeiro.
            potencia = potencia_efetiva(teto, soc, liberado)
            do_sol = min(potencia, float(x.get("alocado_solar_kw") or 0))
            fracao = do_sol / potencia if potencia > 0 else 0.0

            energia_rede = potencia * horas            # energia que sai da tomada
            novo_soc = min(100.0, soc + energia_rede * EFICIENCIA_CARGA / capacidade * 100)
            nova_energia = float(s.get("energia_entregue_kwh") or 0) + energia_rede
            tempo = tempo_de_carga_min(capacidade, novo_soc, alvo, teto, liberado)

            carga_total += potencia
            solar_total += do_sol
            recarga.registrar_progresso(s, v, cond, nova_energia, potencia, novo_soc, tempo,
                                        fracao_solar=fracao, origem_solar=origem_solar)

        demanda.registrar_consumo(cond["id"], 0, em_horario_de_ponta(cond), carga_total,
                                  demanda_kw=estado.get("demanda_kw", carga_total),
                                  rede_kw=max(0.0, carga_total - solar_total))

    recarga.atualizar_ociosas()

async def laco() -> None:
    while True:
        try:
            await asyncio.to_thread(ciclo)
        except Exception as e:
            print(f"[SIMULADOR] erro no ciclo: {type(e).__name__}: {e}")
        await asyncio.sleep(INTERVALO_S)
