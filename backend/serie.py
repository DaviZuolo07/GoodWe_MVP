"""
serie.py - O gráfico de uma recarga e o % lido do próprio celular.
==================================================================

UMA série para todo tipo de recarga (db/23, `leituras_sessao`), gravada por
`recarga.registrar_progresso` - o mesmo ponto por onde passam o simulador
(eletroposto de carro, a cada 10 s) e o totem (a cada lote de telemetria).
O app do morador e o painel do gestor leem daqui; nenhum dos dois recalcula.

Sem o db/23, a recarga do totem cai para `leituras_hardware` (a série crua
da placa) e a simulada fica sem gráfico - nada quebra.

% DO CELULAR (Modelo + % real)
------------------------------
O totem Next não tem sensor: a energia sai do MODELO DE CARGA do ESP32. Se o
app estiver aberto no próprio celular que carrega (Chrome do Android tem a
Battery Status API), ele manda o % real da bateria. Aqui ele vira a âncora
do modelo: o % de partida é recalculado para que "% de partida + energia"
dê exatamente o % lido. A energia e a cobrança NÃO mudam (são o que a vaga
entregou); muda o % e, com ele, a previsão de término e o fim pelo alvo.
O valor vem do navegador, então só serve para a própria recarga de quem
manda, e só dentro de uma faixa plausível.
"""

import time

from fastapi import HTTPException

import dispositivos
from config import supabase, um
from fisica import EFICIENCIA_CARGA

LIMITE_PONTOS = 720                 # 2 h de recarga simulada (10 s por ponto)
INTERVALO_BATERIA_S = 20            # o app manda o % no máximo a cada 20 s
SALTO_MAXIMO = 40.0                 # pontos de diferença aceitos entre o lido e o modelo

_ultimo_envio: dict[str, float] = {}


def fator_da_sessao(s: dict) -> float:
    d = dispositivos.dispositivo_do_carregador(s["carregador_id"])
    return dispositivos.fator_escala(d) if d else 1.0


def serie_da_sessao(s: dict) -> dict:
    """{fator_escala, origem, pontos: [...]} em unidades de PRODUTO (kW, kWh)."""
    pontos, origem = [], None
    try:
        linhas = supabase.table("leituras_sessao").select(
            "momento, potencia_kw, energia_kwh, percentual, alocado_kw, tempo_restante_min, origem"
        ).eq("sessao_id", s["id"]).order("momento").limit(LIMITE_PONTOS).execute().data or []
        pontos = [{"t": x["momento"], "potencia_kw": float(x["potencia_kw"] or 0),
                   "energia_kwh": float(x["energia_kwh"] or 0),
                   "percentual": None if x["percentual"] is None else float(x["percentual"]),
                   "alocado_kw": None if x["alocado_kw"] is None else float(x["alocado_kw"]),
                   "tempo_restante_min": x["tempo_restante_min"]} for x in linhas]
        origem = linhas[-1]["origem"] if linhas else None
    except Exception as e:                                   # noqa: BLE001
        print(f"[SERIE] leituras_sessao ilegível (db/23?): {type(e).__name__}: {str(e)[:100]}")

    fator = fator_da_sessao(s)
    if not pontos and s.get("origem") == "hardware":
        linhas = supabase.table("leituras_hardware").select(
            "potencia_w, energia_wh, rele_ligado, origem, criado_em"
        ).eq("sessao_id", s["id"]).order("criado_em").limit(LIMITE_PONTOS).execute().data or []
        pontos = [{"t": x["criado_em"], "potencia_kw": float(x["potencia_w"] or 0) * fator / 1000,
                   "energia_kwh": float(x["energia_wh"] or 0) * fator / 1000, "percentual": None,
                   "alocado_kw": None, "tempo_restante_min": None} for x in linhas]
        origem = linhas[-1].get("origem") if linhas else None
    return {"fator_escala": fator, "origem": origem or ("simulado" if s.get("origem") != "hardware" else None),
            "pontos": pontos}


def percentual_do_celular(usuario: dict, sessao_id: str, percentual: float) -> dict:
    """O app manda o % real da bateria do celular que está carregando."""
    from identidade import sessao_do_usuario
    s = sessao_do_usuario(sessao_id, usuario["id"])
    if s["status"] != "carregando":
        raise HTTPException(status_code=409, detail="Esta recarga não está em andamento.")
    v = um(supabase.table("veiculos").select("tipo, capacidade_bateria_kwh")
           .eq("id", s["veiculo_id"]).execute()) or {}
    if v.get("tipo") != "celular":
        raise HTTPException(status_code=422, detail="Só a bateria de celular é lida pelo app.")
    agora = time.monotonic()
    if agora - _ultimo_envio.get(s["id"], -1e9) < INTERVALO_BATERIA_S:
        return {"aceito": False, "motivo": "cedo_demais"}
    _ultimo_envio[s["id"]] = agora

    capacidade = float(v.get("capacidade_bateria_kwh") or 0)
    atual = float(s.get("percentual_bateria_atual") or 0)
    if capacidade <= 0 or abs(percentual - atual) > SALTO_MAXIMO:
        # Muito longe do modelo: outro aparelho, aba velha... não ancora.
        return {"aceito": False, "motivo": "fora_da_faixa"}
    ganho = float(s.get("energia_entregue_kwh") or 0) * EFICIENCIA_CARGA / capacidade * 100.0
    inicial = max(0.0, min(100.0, percentual - ganho))
    try:
        supabase.table("sessoes_recarga").update({
            "percentual_bateria_inicial": round(inicial, 2),
            "percentual_bateria_atual": round(percentual, 1),
            "percentual_origem": "celular",
        }).eq("id", s["id"]).eq("status", "carregando").execute()
    except Exception as e:                                   # noqa: BLE001
        # Sem o db/23 o banco recusa 'celular': mantém o modelo, sem erro para o app.
        print(f"[SERIE] % do celular não gravado (db/23?): {type(e).__name__}: {str(e)[:100]}")
        return {"aceito": False, "motivo": "indisponivel"}
    return {"aceito": True, "percentual": round(percentual, 1)}
