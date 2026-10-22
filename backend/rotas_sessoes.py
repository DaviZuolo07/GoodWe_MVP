"""
rotas_sessoes.py - Sessões de recarga no painel e a Sala Next.
==============================================================

Só a API ADMINISTRATIVA (main_admin.py) monta este arquivo. Tudo exige
`gestor_logado` (segundo fator incluso).

  GET   /gestor/sessoes                    lista (admin da plataforma: todos os
                                           locais; operador: só o condomínio dele)
  GET   /gestor/sessoes/{id}               o detalhe que abre ao clicar: local,
                                           usuário, veículo/celular, dados ao
                                           vivo, demanda, conta e o gráfico
  GET   /gestor/next                       Sala Next: quem se cadastrou no
                                           estande, celulares, recargas e as 4
                                           vagas do totem, em unidades REAIS (W, Wh)
  PATCH /gestor/next/demanda               limite do estande e "pico agora" (2 h de
                                           ponta), para mostrar o water-filling
  PATCH /gestor/carregadores/{id}/divisao  liga/desliga a divisão por tempo
                                           (Modbus 10025) de uma porta do totem

ESCOPO: operador nunca enxerga sessão de outro condomínio - a resposta é 404,
como se ela não existisse. Nada aqui recalcula conta: custo pelo mesmo
`detalhar_custo` do recibo, série pela mesma `leituras_sessao` do app.
"""

import re
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import demanda
import dispositivos
import serie as serie_mod
from config import FUSO, supabase, um
from fisica import EFICIENCIA_CARGA, detalhar_custo, potencia_no_soc, teto_kw
from identidade import gestor_logado
from rotas_geral import eh_admin_global

router = APIRouter(prefix="/gestor", tags=["sessões"])

UUID = re.compile(r"[0-9a-fA-F-]{36}")
LIMITE = 200
# A fonte de 5 V do totem: quanto da tomada vira energia no USB. A tomada é
# DERIVADA (não há medidor do lado de 127 V): energia no USB / eficiência.
EFICIENCIA_FONTE_5V = 0.85
ESTANDE_NEXT = "e57a4de0-0000-4000-8000-000000000000"     # preparar_totem.py


def _f(v) -> float:
    return float(v or 0)


def _escopo(gestor: dict) -> Optional[str]:
    """None = vê todos (admin da plataforma); senão, o condomínio do operador."""
    return None if eh_admin_global(gestor["id"]) else gestor.get("condominio_id")


def _carregadores(cond_id: Optional[str]) -> dict:
    q = supabase.table("carregadores").select("*")
    if cond_id:
        q = q.eq("condominio_id", cond_id)
    return {c["id"]: c for c in q.execute().data or []}


def _condominios() -> dict:
    return {c["id"]: c for c in supabase.table("condominios").select("*").execute().data or []}


# ---------------------------------------------------------------------------
# Lista
# ---------------------------------------------------------------------------

@router.get("/sessoes")
def listar(status: Optional[str] = Query(None, max_length=20),
           condominio_id: Optional[str] = Query(None, max_length=40),
           gestor: dict = Depends(gestor_logado)):
    escopo = _escopo(gestor)
    cond_filtro = escopo or condominio_id
    chargers = _carregadores(cond_filtro)
    if not chargers:
        return []
    q = supabase.table("sessoes_recarga").select(
        "id, usuario_id, veiculo_id, carregador_id, status, origem, percentual_bateria_inicial, "
        "percentual_bateria_atual, alvo_percentual, energia_entregue_kwh, potencia_atual_kw, "
        "potencia_alocada_kw, tempo_estimado_min, custo_estimado, custo_final, iniciado_em, "
        "finalizado_em, criado_em, percentual_origem"
    ).in_("carregador_id", list(chargers))
    if status:
        q = q.eq("status", status)
    lista = q.order("criado_em", desc=True).limit(LIMITE).execute().data or []
    nomes = _por_id("usuarios", [s["usuario_id"] for s in lista], "id, nome")
    veiculos = _por_id("veiculos", [s["veiculo_id"] for s in lista], "id, modelo, tipo")
    conds = _condominios()
    saida = []
    for s in lista:
        c = chargers.get(s["carregador_id"]) or {}
        v = veiculos.get(s["veiculo_id"]) or {}
        saida.append({**s, "usuario": (nomes.get(s["usuario_id"]) or {}).get("nome"),
                      "veiculo": v.get("modelo"), "veiculo_tipo": v.get("tipo"),
                      "carregador_numero": c.get("numero"), "condominio_id": c.get("condominio_id"),
                      "local": (conds.get(c.get("condominio_id")) or {}).get("nome")})
    return saida


def _por_id(tabela: str, ids, cols: str) -> dict:
    ids = [i for i in {*ids} if i]
    if not ids:
        return {}
    return {r["id"]: r for r in supabase.table(tabela).select(cols).in_("id", ids).execute().data or []}


# ---------------------------------------------------------------------------
# Detalhe
# ---------------------------------------------------------------------------

def _sessao_visivel(sessao_id: str, gestor: dict) -> tuple[dict, dict]:
    nao = HTTPException(status_code=404, detail="Sessão não encontrada.")
    if not UUID.fullmatch(sessao_id):
        raise nao
    s = um(supabase.table("sessoes_recarga").select("*").eq("id", sessao_id).execute())
    if not s:
        raise nao
    c = um(supabase.table("carregadores").select("*").eq("id", s["carregador_id"]).execute()) or {}
    escopo = _escopo(gestor)
    if escopo and c.get("condominio_id") != escopo:
        raise nao                                          # 404, não 403: não confirma que existe
    return s, c


def _fonte_dos_dados(s: dict, c: dict, d: dict | None, origem_serie: str | None) -> dict:
    """De onde vem cada número da tela, sem enfeite."""
    if c.get("origem") != "hardware":
        return {"tipo": "simulado", "texto": "Eletroposto simulado: potência pela curva da bateria e "
                                              "pelo water-filling do condomínio, a cada 10 s."}
    firmware = (d or {}).get("firmware") or ""
    if firmware.startswith("totem-next") or (d or {}).get("virtual"):
        return {"tipo": "modelo", "texto": "Totem Next sem sensor de corrente: relé real, energia pelo "
                                            "MODELO DE CARGA do ESP32 (curva do celular cadastrado) e "
                                            "divisão por tempo no relé. Rotulado 'simulado'."}
    return {"tipo": origem_serie or "medido", "texto": "Placa com sensor INA219: energia medida."}


@router.get("/sessoes/{sessao_id}")
def detalhe(sessao_id: str, gestor: dict = Depends(gestor_logado)):
    s, c = _sessao_visivel(sessao_id, gestor)
    cond = um(supabase.table("condominios").select("*").eq("id", c.get("condominio_id")).execute()) or {}
    u = um(supabase.table("usuarios").select("id, nome, tipo_usuario, bloco_apto, criado_em")
           .eq("id", s["usuario_id"]).execute()) or {}
    v = um(supabase.table("veiculos").select("modelo, tipo, capacidade_bateria_kwh, potencia_carro_kw")
           .eq("id", s["veiculo_id"]).execute()) or {}
    d = dispositivos.dispositivo_do_carregador(c["id"]) if c.get("origem") == "hardware" else None
    fator = dispositivos.fator_escala(d) if d else 1.0
    s_serie = serie_mod.serie_da_sessao(s)
    try:
        custo = detalhar_custo(s)
    except Exception:                                        # noqa: BLE001
        custo = None

    energia = _f(s.get("energia_entregue_kwh"))
    alocado = s.get("potencia_alocada_kw")
    # Fração de tempo do relé (totem) ou fração da potência (simulado): o
    # mesmo número - quanto do que a bateria pede o water-filling liberou.
    pedida = potencia_no_soc(teto_kw(c, v), _f(s.get("percentual_bateria_atual"))) if v else 0.0
    fracao = demanda.fracao_de_tempo(alocado, pedida)
    limite, ponta = demanda.limite_efetivo(cond) if cond else (0.0, False)
    return {
        "sessao": {k: s.get(k) for k in (
            "id", "status", "origem", "percentual_bateria_inicial", "percentual_bateria_atual",
            "alvo_percentual", "percentual_origem", "energia_entregue_kwh", "energia_ponta_kwh",
            "energia_solar_kwh", "potencia_atual_kw", "potencia_media_kw", "potencia_alocada_kw",
            "tempo_estimado_min", "custo_estimado", "custo_final", "valor_pre_autorizado",
            "valor_estornado", "motivo_recusa", "encerrado_por", "iniciado_em", "finalizado_em",
            "criado_em", "uid_inicio")},
        "local": {"id": cond.get("id"), "nome": cond.get("nome"), "endereco": cond.get("endereco"),
                  "perfil": cond.get("perfil")},
        "usuario": {"id": u.get("id"), "nome": u.get("nome"), "tipo": u.get("tipo_usuario"),
                    "bloco_apto": u.get("bloco_apto"), "desde": u.get("criado_em")},
        "veiculo": v,
        "carregador": {"id": c.get("id"), "numero": c.get("numero"), "modelo": c.get("modelo"),
                       "perfil": c.get("perfil"), "origem": c.get("origem"), "status": c.get("status"),
                       "potencia_maxima_kw": c.get("potencia_maxima_kw"),
                       "temperatura_c": c.get("temperatura_c") if c.get("origem") != "hardware" else None,
                       "temperatura_texto": None if c.get("origem") != "hardware"
                       else "sem sensor de temperatura no totem",
                       "divisao_por_tempo": demanda.por_tempo(c)},
        "demanda": {"limite_kw": limite, "limite_nominal_kw": _f(cond.get("limite_potencia_kw")),
                    "em_ponta": ponta, "pedida_kw": round(pedida, 4),
                    "alocado_kw": alocado, "fracao": fracao},
        "energia": {
            "entregue_kwh": round(energia, 6),
            # Na bateria (perde ~8% no celular/carro) e na tomada (fonte de 5 V do totem).
            "na_bateria_kwh": round(energia * EFICIENCIA_CARGA, 6),
            "da_tomada_kwh": round(energia / EFICIENCIA_FONTE_5V, 6) if c.get("perfil") == "bancada" else None,
            "fator_escala": fator,
            "real_wh": round(energia * 1000 / fator, 3) if fator != 1 else None,
        },
        "fonte_dos_dados": _fonte_dos_dados(s, c, d, s_serie.get("origem")),
        "custo": custo,
        "serie": s_serie,
    }


# ---------------------------------------------------------------------------
# Sala Next
# ---------------------------------------------------------------------------

def _estandes() -> list[dict]:
    """O estande do Next (preparar_totem.py) - e qualquer outro local de perfil bancada."""
    conds = supabase.table("condominios").select("*").execute().data or []
    return [c for c in conds if c["id"] == ESTANDE_NEXT or c.get("perfil") == "bancada"]


@router.get("/next")
def sala_next(gestor: dict = Depends(gestor_logado)):
    estandes = _estandes()
    escopo = _escopo(gestor)
    if escopo:
        estandes = [c for c in estandes if c["id"] == escopo]
    if not estandes:
        raise HTTPException(status_code=404, detail="Nenhum estande do Next visível para esta conta.")
    ids_cond = [c["id"] for c in estandes]
    chargers = {c["id"]: c for c in supabase.table("carregadores").select("*")
                .in_("condominio_id", ids_cond).order("numero").execute().data or []}
    d = None
    for cid in chargers:
        d = dispositivos.dispositivo_do_carregador(cid)
        if d:
            break
    fator = dispositivos.fator_escala(d) if d else 1000.0

    def wh(kwh) -> float:
        return round(_f(kwh) * 1000 / fator, 3)                   # kWh de produto -> Wh reais

    usuarios = supabase.table("usuarios").select("id, nome, tipo_usuario, saldo, criado_em, condominio_id") \
        .in_("condominio_id", ids_cond).neq("tipo_usuario", "gestor").order("criado_em", desc=True) \
        .limit(LIMITE).execute().data or []
    uids = [u["id"] for u in usuarios]
    celulares, tags = {}, {}
    if uids:
        for v in supabase.table("veiculos").select("usuario_id, modelo, tipo, capacidade_bateria_kwh, "
                                                   "potencia_carro_kw").in_("usuario_id", uids).execute().data or []:
            celulares.setdefault(v["usuario_id"], []).append(
                {"modelo": v.get("modelo"), "tipo": v.get("tipo"),
                 "bateria_wh": wh(v.get("capacidade_bateria_kwh")),
                 "potencia_w": round(_f(v.get("potencia_carro_kw")) * 1000 / fator, 2)})
        for t in supabase.table("cartoes_rfid").select("usuario_id, ativo").in_("usuario_id", uids) \
                .execute().data or []:
            tags[t["usuario_id"]] = tags.get(t["usuario_id"], 0) + (1 if t.get("ativo") else 0)

    sessoes = supabase.table("sessoes_recarga").select(
        "id, usuario_id, carregador_id, status, percentual_bateria_inicial, percentual_bateria_atual, "
        "percentual_origem, alvo_percentual, energia_entregue_kwh, potencia_atual_kw, potencia_alocada_kw, "
        "tempo_estimado_min, custo_final, custo_estimado, iniciado_em, finalizado_em, criado_em, encerrado_por"
    ).in_("carregador_id", list(chargers) or ["-"]).order("criado_em", desc=True).limit(LIMITE).execute().data or []
    nomes = {u["id"]: u["nome"] for u in usuarios}
    por_usuario = {}
    for s in sessoes:
        if s["status"] == "finalizada":
            p = por_usuario.setdefault(s["usuario_id"], {"recargas": 0, "energia_wh": 0.0, "gasto": 0.0})
            p["recargas"] += 1
            p["energia_wh"] = round(p["energia_wh"] + wh(s.get("energia_entregue_kwh")), 3)
            p["gasto"] = round(p["gasto"] + _f(s.get("custo_final")), 2)

    ativas = {s["carregador_id"]: s for s in sessoes if s["status"] == "carregando"}
    estado = {x["carregador_id"]: x for cid in ids_cond
              for x in demanda.alocar(cid, gravar=False).get("sessoes", [])}
    vagas = []
    for c in chargers.values():
        s = ativas.get(c["id"])
        x = estado.get(c["id"]) or {}
        vagas.append({
            "carregador_id": c["id"], "numero": c["numero"], "status": c["status"],
            "divisao_por_tempo": demanda.por_tempo(c),
            "sessao_id": s["id"] if s else None,
            "usuario": nomes.get(s["usuario_id"]) if s else None,
            "percentual": s.get("percentual_bateria_atual") if s else None,
            "percentual_origem": s.get("percentual_origem") if s else None,
            "potencia_w": round(_f(s.get("potencia_atual_kw")) * 1000 / fator, 3) if s else 0.0,
            "liberado_w": round(_f(x.get("alocado_kw")) * 1000 / fator, 3) if s else 0.0,
            "fracao": demanda.fracao_de_tempo(x.get("alocado_kw"), _f(x.get("demanda_kw"))) if s else None,
            "energia_wh": wh(s.get("energia_entregue_kwh")) if s else 0.0,
            "tempo_min": s.get("tempo_estimado_min") if s else None,
        })
    limite, ponta = demanda.limite_efetivo(estandes[0])
    return {
        "estande": {"id": estandes[0]["id"], "nome": estandes[0]["nome"],
                    "limite_w": round(limite * 1000 / fator, 2), "limite_kw": limite, "em_ponta": ponta,
                    "ponta_inicio": estandes[0].get("ponta_inicio"), "ponta_fim": estandes[0].get("ponta_fim")},
        "fator_escala": fator,
        "placa": {k: (d or {}).get(k) for k in ("id", "nome", "online", "ultimo_contato", "firmware", "ip")},
        "vagas": vagas,
        "cadastros": [{
            "id": u["id"], "nome": u["nome"], "tipo": u["tipo_usuario"], "saldo": round(_f(u.get("saldo")), 2),
            "desde": u["criado_em"], "celulares": celulares.get(u["id"], []), "tags": tags.get(u["id"], 0),
            **por_usuario.get(u["id"], {"recargas": 0, "energia_wh": 0.0, "gasto": 0.0}),
        } for u in usuarios],
        "recargas": [{
            "id": s["id"], "usuario": nomes.get(s["usuario_id"]),
            "vaga": (chargers.get(s["carregador_id"]) or {}).get("numero"), "status": s["status"],
            "percentual_inicial": s.get("percentual_bateria_inicial"),
            "percentual": s.get("percentual_bateria_atual"), "percentual_origem": s.get("percentual_origem"),
            "alvo": s.get("alvo_percentual"), "energia_wh": wh(s.get("energia_entregue_kwh")),
            "valor": s.get("custo_final") if s.get("custo_final") is not None else s.get("custo_estimado"),
            "encerrado_por": s.get("encerrado_por"), "inicio": s.get("iniciado_em") or s.get("criado_em"),
            "fim": s.get("finalizado_em"),
        } for s in sessoes],
        "totais": {
            "cadastros": len(usuarios),
            "recargas": sum(1 for s in sessoes if s["status"] == "finalizada"),
            "ativas": len(ativas),
            "energia_wh": round(sum(wh(s.get("energia_entregue_kwh")) for s in sessoes), 3),
            "faturamento": round(sum(_f(s.get("custo_final")) for s in sessoes), 2),
        },
    }


# ---------------------------------------------------------------------------
# Demanda do estande, ao vivo (a demonstração do pico)
# ---------------------------------------------------------------------------

class DemandaEstande(BaseModel):
    limite_potencia_kw: Optional[float] = Field(None, gt=0, le=2000)
    ponta_fator_limite: Optional[float] = Field(None, gt=0, le=1)
    # "pico_agora": abre a janela de ponta AGORA por 2 h; "sem_pico": fecha.
    pico: Optional[Literal["pico_agora", "sem_pico"]] = None


@router.patch("/next/demanda")
def demanda_do_estande(payload: DemandaEstande, gestor: dict = Depends(gestor_logado)):
    """
    O admin da plataforma tem o condomínio-base dele (a aba Operação mostra
    esse); o estande se controla daqui. O alocador relê no ciclo seguinte
    (<= 10 s): as frações mudam e o ESP32 refaz o rodízio dos relés.
    """
    escopo = _escopo(gestor)
    estandes = [c for c in _estandes() if not escopo or c["id"] == escopo]
    if not estandes:
        raise HTTPException(status_code=404, detail="Nenhum estande do Next visível para esta conta.")
    dados = {k: v for k, v in payload.model_dump().items() if v is not None and k != "pico"}
    if payload.pico == "pico_agora":
        agora_local = datetime.now(FUSO)
        dados["ponta_inicio"] = agora_local.strftime("%H:%M")
        dados["ponta_fim"] = (agora_local + timedelta(hours=2)).strftime("%H:%M")
    elif payload.pico == "sem_pico":
        dados["ponta_inicio"] = dados["ponta_fim"] = "00:00"
    if not dados:
        raise HTTPException(status_code=400, detail="Nada para alterar.")
    supabase.table("condominios").update(dados).eq("id", estandes[0]["id"]).execute()
    cond = um(supabase.table("condominios").select("*").eq("id", estandes[0]["id"]).execute())
    limite, ponta = demanda.limite_efetivo(cond)
    return {"success": True, "limite_kw": limite, "em_ponta": ponta}


# ---------------------------------------------------------------------------
# Divisão por tempo (Modbus 10025) numa porta do totem
# ---------------------------------------------------------------------------

class Divisao(BaseModel):
    ligada: bool


@router.patch("/carregadores/{carregador_id}/divisao")
def divisao(carregador_id: str, payload: Divisao, gestor: dict = Depends(gestor_logado)):
    if not UUID.fullmatch(carregador_id):
        raise HTTPException(status_code=404, detail="Carregador não encontrado.")
    c = um(supabase.table("carregadores").select("id, condominio_id, origem").eq("id", carregador_id).execute())
    escopo = _escopo(gestor)
    if not c or (escopo and c["condominio_id"] != escopo):
        raise HTTPException(status_code=404, detail="Carregador não encontrado.")
    if c.get("origem") != "hardware":
        raise HTTPException(status_code=422, detail="Divisão por tempo é só para porta de relé (totem).")
    supabase.table("carregadores").update({"controle_dinamico": payload.ligada}).eq("id", c["id"]).execute()
    return {"success": True, "divisao_por_tempo": payload.ligada}
