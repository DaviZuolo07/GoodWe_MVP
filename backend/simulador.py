"""
simulador.py - O laço de 10 s que mantém o sistema andando sozinho.
===================================================================

A cada ciclo, nesta ordem:
  1. derruba ESP32 sem contato e expira esperas de cartão vencidas
  2. esquenta/esfria os pontos SIMULADOS (o do ESP32 manda a própria)
  3. por condomínio: roda o ALOCADOR de demanda e avança as recargas
     simuladas com a potência que ele liberou - não com o teto do carregador
  4. encerra recarga de ponto físico que ficou sem placa
  5. registra a carga total do condomínio na curva horária do gestor

Por que `asyncio.to_thread`: o cliente do Supabase é síncrono. Chamado direto
dentro do laço assíncrono, cada ciclo congelava o servidor inteiro por alguns
segundos - inclusive o GET /hardware/comandos que o ESP32 faz a cada 2 s.
"""

import asyncio
import random

import demanda
import dispositivos
import recarga
from config import supabase
from fisica import em_horario_de_ponta, potencia_no_soc, teto_kw, tempo_de_carga_min

INTERVALO_S = 10
HORAS_POR_CICLO = INTERVALO_S / 3600


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


def ciclo() -> None:
    dispositivos.marcar_offline_sem_contato()
    recarga.expirar_esperas()

    conds = supabase.table("condominios").select("*").execute().data or []
    chargers = supabase.table("carregadores").select("*").execute().data or []
    _temperaturas(chargers)
    por_id = {c["id"]: c for c in chargers}

    sessoes = supabase.table("sessoes_recarga").select(
        "*, veiculos(capacidade_bateria_kwh, potencia_carro_kw, tipo)"
    ).eq("status", "carregando").execute().data or []

    for cond in conds:
        ids = {c["id"] for c in chargers if c["condominio_id"] == cond["id"]}
        do_local = [s for s in sessoes if s["carregador_id"] in ids]
        if not do_local:
            continue

        estado = demanda.alocar(cond["id"])
        alocado = {x["id"]: x["alocado_kw"] for x in estado.get("sessoes", [])}
        carga_total = 0.0

        for s in do_local:
            c = por_id[s["carregador_id"]]
            v = s.get("veiculos") or {}

            if c.get("origem") == "hardware":
                # Energia deste ponto vem do sensor do ESP32 (hardware_api).
                # Aqui só tratamos a placa que sumiu no meio da recarga.
                if c["status"] == "offline":
                    recarga.encerrar(s, "dispositivo_offline")
                else:
                    carga_total += float(s.get("potencia_atual_kw") or 0)
                continue

            capacidade = float(v.get("capacidade_bateria_kwh") or 40)
            soc = float(s.get("percentual_bateria_atual") or 0)
            alvo = float(s.get("alvo_percentual") or 100)
            limite = min(teto_kw(c, v), float(alocado.get(s["id"], teto_kw(c, v))))

            potencia = potencia_no_soc(limite, soc)
            energia_rede = potencia * HORAS_POR_CICLO
            novo_soc = min(100.0, soc + energia_rede * 0.92 / capacidade * 100)
            nova_energia = float(s.get("energia_entregue_kwh") or 0) + energia_rede
            tempo = tempo_de_carga_min(capacidade, novo_soc, alvo, limite)

            carga_total += potencia
            recarga.registrar_progresso(s, v, cond, nova_energia, potencia, novo_soc, tempo)

        try:
            supabase.rpc("registrar_consumo", {"p_cond": cond["id"], "p_kwh": 0,
                                               "p_ponta": em_horario_de_ponta(cond),
                                               "p_carga_kw": round(carga_total, 4)}).execute()
        except Exception as e:
            print(f"[CONSUMO] falhou: {e}")


async def laco() -> None:
    while True:
        try:
            await asyncio.to_thread(ciclo)
        except Exception as e:
            print(f"[SIMULADOR] erro no ciclo: {type(e).__name__}: {e}")
        await asyncio.sleep(INTERVALO_S)
