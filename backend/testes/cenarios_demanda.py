"""
cenarios_demanda.py - Os quatro cenários do critério de pronto (ADR-016 D13).
==============================================================================

Três carros iguais chegam a um quadro de 10 kW (60% na ponta, 18h-21h) com três
carregadores GoodWe HCA G2 de 7 kW. Cada carro: 50 kWh de bateria, de 20% a 80%.

  A  sem solar, controle dinâmico DESLIGADO (10025 = 0), chegada 17h30
  B  sem solar, controle dinâmico LIGADO    (10025 = 1), chegada 17h30
  C  10 kWp, modo FV + garantir mínimo      (10032 = 1, 10024 = 1), chegada 10h
  D  10 kWp, modo rápido                    (10032 = 0), chegada 10h

Relógio simulado de 1 em 1 minuto, sem banco. Usa as MESMAS funções da
operação: `item_de`, `avaliar_admissao`, `distribuir_fontes`, `limite_efetivo`
(demanda.py), `potencia_efetiva`, `teto_kw`, `detalhar_custo` (fisica.py) e a
curva solar do simulador. Única diferença: aqui o sol vem direto da curva; na
operação ele passa pela tabela `geracao_solar`.

Premissas (todas SIMULADAS e configuráveis no painel): rede R$ 1,15/kWh fora da
ponta e x1,5 na ponta; solar R$ 0,75 ao morador; custos do condomínio R$ 0,95
(rede fora), R$ 1,45 (rede ponta) e R$ 0,35 (geração solar).

Rodar (de dentro de backend/):  python testes/cenarios_demanda.py
Os números do docs/como_o_chargeops_gere_demanda_e_cobra.md saem daqui.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ambiente                                    # noqa: E402,F401  (sys.path e .env de teste)

from datetime import datetime, timedelta          # noqa: E402

import demanda                                     # noqa: E402
import simulador                                   # noqa: E402
from config import FUSO                            # noqa: E402
from fisica import (EFICIENCIA_CARGA, detalhar_custo, economia_vs_so_rede, potencia_efetiva,  # noqa: E402
                    teto_kw)

PASSO_MIN = 1
HORIZONTE_H = 40
DIA = datetime(2026, 10, 7, tzinfo=FUSO)          # quarta-feira (tem ponta)

PREMISSAS = {"custo_energia_kwh": 0.95, "custo_energia_ponta_kwh": 1.45,
             "custo_solar_kwh": 0.35, "preco_solar_kwh": 0.75}
CONDOMINIO = {"id": "cenario", "limite_potencia_kw": 10, "ponta_inicio": "18:00", "ponta_fim": "21:00",
              "ponta_fator_limite": 0.6, "ponta_multiplicador_tarifa": 1.5, **PREMISSAS}
TARIFA_REDE = 1.15
CARRO = {"capacidade_bateria_kwh": 50, "potencia_carro_kw": 7}
SOC_INICIAL, SOC_ALVO = 20.0, 80.0

CENARIOS = [
    ("A", "Sem solar, controle dinâmico desligado (10025 = 0)", (17, 30), {"controle_dinamico": False}, 0),
    ("B", "Sem solar, controle dinâmico ligado (10025 = 1)", (17, 30), {}, 0),
    ("C", "10 kWp, modo FV + garantir mínimo (10032 = 1, 10024 = 1)", (10, 0),
     {"modo_carga": 1, "garantir_minimo": True}, 10),
    ("D", "10 kWp, modo rápido (10032 = 0)", (10, 0), {}, 10),
]


def _carregador(n: int, modbus: dict) -> dict:
    return {"id": f"ch{n}", "numero": f"0{n}", "modelo": "GoodWe HCA G2 7kW", "potencia_nominal_kw": 7,
            "potencia_maxima_kw": 7, "tensao_v": 230, "tarifa_kwh": TARIFA_REDE, "perfil": "veicular",
            "origem": "simulado", "temperatura_c": 25, "controle_dinamico": True,
            "garantir_minimo": False, "modo_carga": 0, **modbus}


def rodar(codigo: str, titulo: str, hora: tuple, modbus: dict, kwp: float) -> dict:
    cond = {**CONDOMINIO, "fv_potencia_kwp": kwp}
    inicio = DIA.replace(hour=hora[0], minute=hora[1])
    carros = [{"id": f"carro{k}", "nome": f"Carro {k}", "chegada": inicio + timedelta(minutes=k - 1),
               "charger": _carregador(k, modbus), "soc": SOC_INICIAL, "estado": "a_caminho",
               "ordem": None, "inicio": None, "fim": None, "recusas": 0,
               "sessao": {"energia_entregue_kwh": 0.0, "energia_solar_kwh": 0.0, "energia_ponta_kwh": 0.0,
                          "tarifa_kwh": TARIFA_REDE, "multiplicador_ponta": cond["ponta_multiplicador_tarifa"],
                          "tarifa_solar_kwh": PREMISSAS["preco_solar_kwh"], "origem_solar": "simulado"}}
               for k in (1, 2, 3)]
    fila: list[dict] = []
    t, fim_max, dt_h = inicio, inicio + timedelta(hours=HORIZONTE_H), PASSO_MIN / 60
    proxima_ordem = 0
    met = {"pico_rede_kw": 0.0, "pico_garagem_kw": 0.0, "estouro_max_kw": 0.0, "min_estouro": 0,
           "solar_gerado_kwh": 0.0, "solar_absorvido_kwh": 0.0, "min_pausados": 0}

    def itens_ativos():
        return [demanda.item_de(c["charger"], CARRO, c["soc"], cond, c["id"], c["ordem"])
                for c in carros if c["estado"] == "carregando"]

    def admitir(c, limite) -> bool:
        nonlocal proxima_ordem
        nova = demanda.item_de(c["charger"], CARRO, c["soc"], cond, c["id"], proxima_ordem)
        _, motivo = demanda.avaliar_admissao(limite, itens_ativos(), nova)
        if motivo:
            c["recusas"] += 1
            return False
        c.update(estado="carregando", inicio=t, ordem=proxima_ordem)
        proxima_ordem += 1
        return True

    while t < fim_max and any(c["estado"] != "concluida" for c in carros):
        limite, ponta = demanda.limite_efetivo(cond, t)

        # Chegadas e fila (FIFO: quem chegou depois não fura a fila).
        for c in carros:
            if c["estado"] == "a_caminho" and c["chegada"] <= t:
                c["estado"] = "fila"
                fila.append(c)
        while fila and admitir(fila[0], limite):
            fila.pop(0)

        sol = simulador.potencia_solar_kw(kwp, t + timedelta(minutes=PASSO_MIN / 2))
        r = demanda.distribuir_fontes(limite, sol, itens_ativos())
        garagem = rede = absorvido = 0.0
        for c in [c for c in carros if c["estado"] == "carregando"]:
            x = r["itens"][c["id"]]
            met["min_pausados"] += x["pausado_motivo"] is not None
            p = potencia_efetiva(teto_kw(c["charger"], CARRO), c["soc"], x["alocado_kw"])
            do_sol = min(p, x["alocado_solar_kw"])
            s = c["sessao"]
            s["energia_entregue_kwh"] += p * dt_h
            s["energia_solar_kwh"] += do_sol * dt_h
            if ponta:
                s["energia_ponta_kwh"] += (p - do_sol) * dt_h
            c["soc"] = min(100.0, c["soc"] + p * dt_h * EFICIENCIA_CARGA / CARRO["capacidade_bateria_kwh"] * 100)
            garagem, rede, absorvido = garagem + p, rede + p - do_sol, absorvido + do_sol
            if c["soc"] >= SOC_ALVO - 1e-9:
                c.update(estado="concluida", fim=t + timedelta(minutes=PASSO_MIN))

        met["pico_rede_kw"] = max(met["pico_rede_kw"], rede)
        met["pico_garagem_kw"] = max(met["pico_garagem_kw"], garagem)
        if rede > limite + 1e-3:
            met["estouro_max_kw"] = max(met["estouro_max_kw"], rede - limite)
            met["min_estouro"] += PASSO_MIN
        met["solar_gerado_kwh"] += sol * dt_h
        met["solar_absorvido_kwh"] += absorvido * dt_h
        t += timedelta(minutes=PASSO_MIN)

    return _resultado(codigo, titulo, kwp, carros, met)


def _resultado(codigo, titulo, kwp, carros, met) -> dict:
    linhas = []
    receita = custo = economia = 0.0
    for c in carros:
        d = detalhar_custo(c["sessao"])
        custo_c = (d["energia_fora_ponta_kwh"] * PREMISSAS["custo_energia_kwh"]
                   + d["energia_ponta_kwh"] * PREMISSAS["custo_energia_ponta_kwh"]
                   + d["energia_solar_kwh"] * PREMISSAS["custo_solar_kwh"])
        receita, custo = receita + d["total"], custo + custo_c
        economia += economia_vs_so_rede(c["sessao"])
        linhas.append({"carro": c["nome"], "chegada": c["chegada"], "inicio": c["inicio"], "fim": c["fim"],
                       "espera_min": int((c["inicio"] - c["chegada"]).total_seconds() // 60) if c["inicio"] else None,
                       "recusas": c["recusas"], "detalhe": d})
    fins = [l["fim"] for l in linhas if l["fim"]]
    return {"codigo": codigo, "titulo": titulo, "fv_kwp": kwp, "carros": linhas,
            "concluidas": len(fins), "ultimo_fim": max(fins) if fins else None,
            "receita": round(receita, 2), "custo": round(custo, 2), "margem": round(receita - custo, 2),
            "economia_morador": round(economia, 2),
            **{k: round(v, 3) if isinstance(v, float) else v for k, v in met.items()}}


def todos() -> dict:
    return {c[0]: rodar(*c) for c in CENARIOS}


# ---------------------------------------------------------------------------
# Impressão em Markdown (vai para o documento do pitch)
# ---------------------------------------------------------------------------

def _n(v, casas=2) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _h(momento) -> str:
    if momento is None:
        return "—"
    dia = "" if momento.date() == DIA.date() else " (+1d)"
    return momento.strftime("%H:%M") + dia


def markdown(r: dict) -> str:
    out = [f"### Cenário {r['codigo']} — {r['titulo']}", "",
           "| Carro | Chegou | Começou | Terminou | Solar kWh | Rede fora kWh | Rede ponta kWh | Pago (R$) |",
           "|---|---|---|---|---|---|---|---|"]
    for l in r["carros"]:
        d = l["detalhe"]
        out.append(f"| {l['carro']} | {_h(l['chegada'])} | {_h(l['inicio'])} | {_h(l['fim'])} | "
                   f"{_n(d['energia_solar_kwh'])} | {_n(d['energia_fora_ponta_kwh'])} | "
                   f"{_n(d['energia_ponta_kwh'])} | {_n(d['total'])} |")
    out += ["",
            f"- Pico da rede: **{_n(r['pico_rede_kw'])} kW** (garagem: {_n(r['pico_garagem_kw'])} kW). "
            + (f"**Estouro do quadro:** até {_n(r['estouro_max_kw'])} kW por {r['min_estouro']} min — "
               "o disjuntor geral desarmaria." if r["min_estouro"] else "Quadro respeitado o tempo todo."),
            f"- Última recarga concluída: {_h(r['ultimo_fim'])}.",
            f"- Condomínio: receita R$ {_n(r['receita'])}, custo da energia R$ {_n(r['custo'])}, "
            f"margem R$ {_n(r['margem'])}.",
            ]
    if r["fv_kwp"]:
        out.append(f"- Sol: {_n(r['solar_gerado_kwh'])} kWh gerados no período, "
                   f"{_n(r['solar_absorvido_kwh'])} kWh absorvidos pela garagem; "
                   f"moradores economizaram R$ {_n(r['economia_morador'])} frente a pagar tudo pela rede.")
    return "\n".join(out)


if __name__ == "__main__":
    for res in todos().values():
        print(markdown(res))
        print()
