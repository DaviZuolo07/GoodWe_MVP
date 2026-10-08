"""
rotas_geral.py - "Visão geral" do painel: todos os locais de uma vez.
======================================================================

Só a API ADMINISTRATIVA (main_admin.py) monta este arquivo.

O painel do gestor (rotas_gestor.py) responde pelo condomínio DELE. Esta
visão é de quem opera a plataforma inteira: cadastros, pagamentos, recargas,
notificações e chamados de TODOS os locais.

Quem entra: gestor (mesmas três checagens do gestor_logado) que ALÉM disso
está na tabela `admins_globais` (db/20). A lista mora no banco, fechada ao
navegador; virar ou deixar de ser admin global vale na chamada seguinte.

Nada aqui recalcula conta: valores e energia saem das colunas que o backend
já gravou (recibo, carteira, simulador).
"""

import re
from datetime import datetime, time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import FUSO, agora_iso, supabase, um
from identidade import gestor_logado

router = APIRouter(prefix="/gestor/geral", tags=["visão geral"])

LIMITE_LISTA = 200
UUID = re.compile(r"[0-9a-fA-F-]{36}")


def eh_admin_global(usuario_id: str) -> bool:
    """Tabela ausente (db/20 não rodou) = ninguém é global. Nunca abre por erro."""
    try:
        return bool(supabase.table("admins_globais").select("usuario_id")
                    .eq("usuario_id", usuario_id).execute().data)
    except Exception as e:                                   # noqa: BLE001
        print(f"[GERAL] não consegui ler admins_globais: {type(e).__name__}: {str(e)[:120]}")
        return False


def admin_global(gestor: dict = Depends(gestor_logado)) -> dict:
    if not eh_admin_global(gestor["id"]):
        raise HTTPException(status_code=403, detail="Visão geral restrita ao administrador da plataforma.")
    return gestor


# ---------------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------------

def _inicio_mes() -> str:
    hoje = datetime.now(FUSO).date().replace(day=1)
    return datetime.combine(hoje, time(0, 0), tzinfo=FUSO).isoformat()


def _inicio_dia() -> str:
    return datetime.combine(datetime.now(FUSO).date(), time(0, 0), tzinfo=FUSO).isoformat()


def _por_id(tabela: str, ids, cols: str) -> dict:
    ids = [i for i in {*ids} if i]
    if not ids:
        return {}
    return {r["id"]: r for r in supabase.table(tabela).select(cols).in_("id", ids).execute().data or []}


def _condominios() -> dict:
    return {c["id"]: c for c in supabase.table("condominios").select("id, nome").execute().data or []}


def _carregadores() -> dict:
    return {c["id"]: c for c in supabase.table("carregadores")
            .select("id, numero, condominio_id, status, perfil").execute().data or []}


def _f(v) -> float:
    return float(v or 0)


# ---------------------------------------------------------------------------
# Resumo
# ---------------------------------------------------------------------------

@router.get("/resumo")
def resumo(_: dict = Depends(admin_global)):
    """Os números da plataforma inteira, e o mesmo recorte por local."""
    conds = _condominios()
    chargers = _carregadores()
    usuarios = supabase.table("usuarios").select("id, tipo_usuario, condominio_id, criado_em") \
        .execute().data or []
    mes, dia = _inicio_mes(), _inicio_dia()
    sessoes = supabase.table("sessoes_recarga").select(
        "id, carregador_id, status, energia_entregue_kwh, energia_ponta_kwh, energia_solar_kwh, "
        "custo_final, criado_em").gte("criado_em", mes).execute().data or []
    ativas = supabase.table("sessoes_recarga").select("id, carregador_id, potencia_atual_kw") \
        .eq("status", "carregando").execute().data or []
    creditos = supabase.table("movimentacoes_carteira").select("tipo, valor") \
        .gte("criado_em", mes).execute().data or []
    try:
        abertos = len(supabase.table("chamados").select("id").neq("status", "resolvido").execute().data or [])
    except Exception:                                        # noqa: BLE001
        abertos = None

    def bloco(filtro_cond=None) -> dict:
        def do_local(cid):
            return filtro_cond is None or cid == filtro_cond
        ss = [s for s in sessoes if do_local((chargers.get(s["carregador_id"]) or {}).get("condominio_id"))]
        fin = [s for s in ss if s["status"] == "finalizada"]
        at = [s for s in ativas if do_local((chargers.get(s["carregador_id"]) or {}).get("condominio_id"))]
        cs = [c for c in chargers.values() if do_local(c["condominio_id"])]
        return {
            "usuarios": sum(1 for u in usuarios if do_local(u.get("condominio_id"))),
            "recargas_ativas": len(at),
            "potencia_agora_kw": round(sum(_f(s.get("potencia_atual_kw")) for s in at), 3),
            "recargas_mes": len(fin),
            "recargas_hoje": sum(1 for s in fin if s["criado_em"] >= dia),
            "recusadas_mes": sum(1 for s in ss if s["status"] == "recusada"),
            "energia_mes_kwh": round(sum(_f(s.get("energia_entregue_kwh")) for s in fin), 4),
            "energia_ponta_mes_kwh": round(sum(_f(s.get("energia_ponta_kwh")) for s in fin), 4),
            "energia_solar_mes_kwh": round(sum(_f(s.get("energia_solar_kwh")) for s in fin), 4),
            "faturamento_mes": round(sum(_f(s.get("custo_final")) for s in fin), 2),
            "carregadores": len(cs),
            "carregadores_por_status": {st: sum(1 for c in cs if c.get("status") == st)
                                        for st in sorted({c.get("status") for c in cs if c.get("status")})},
        }

    total = bloco()
    total["usuarios_por_tipo"] = {t: sum(1 for u in usuarios if u.get("tipo_usuario") == t)
                                  for t in ("morador", "visitante", "gestor")}
    total["novos_mes"] = sum(1 for u in usuarios if (u.get("criado_em") or "") >= mes)
    total["creditos_carteira_mes"] = round(sum(_f(m["valor"]) for m in creditos if m["tipo"] == "credito"), 2)
    total["chamados_abertos"] = abertos
    return {"total": total,
            "por_local": [{"id": cid, "nome": c["nome"], **bloco(cid)} for cid, c in conds.items()],
            "gerado_em": agora_iso()}


# ---------------------------------------------------------------------------
# Cadastros
# ---------------------------------------------------------------------------

@router.get("/usuarios")
def usuarios(busca: Optional[str] = Query(None, max_length=60),
             condominio_id: Optional[str] = Query(None, max_length=40),
             _: dict = Depends(admin_global)):
    q = supabase.table("usuarios").select("id, nome, tipo_usuario, condominio_id, bloco_apto, saldo, criado_em")
    if condominio_id:
        q = q.eq("condominio_id", condominio_id)
    lista = q.order("criado_em", desc=True).limit(LIMITE_LISTA).execute().data or []
    if busca:
        b = busca.strip().lower()
        lista = [u for u in lista if b in (u.get("nome") or "").lower()]
    ids = [u["id"] for u in lista]
    veiculos, recargas = {}, {}
    if ids:
        for v in supabase.table("veiculos").select("usuario_id, modelo, tipo").in_("usuario_id", ids).execute().data or []:
            veiculos.setdefault(v["usuario_id"], []).append(f"{v.get('modelo')} ({v.get('tipo') or 'carro'})")
        for s in supabase.table("sessoes_recarga").select("usuario_id, status").in_("usuario_id", ids).execute().data or []:
            if s["status"] == "finalizada":
                recargas[s["usuario_id"]] = recargas.get(s["usuario_id"], 0) + 1
    conds = _condominios()
    return [{**u, "saldo": round(_f(u.get("saldo")), 2),
             "local": (conds.get(u.get("condominio_id")) or {}).get("nome"),
             "veiculos": veiculos.get(u["id"], []), "recargas": recargas.get(u["id"], 0)} for u in lista]


# ---------------------------------------------------------------------------
# Pagamentos (carteira) e recargas
# ---------------------------------------------------------------------------

@router.get("/pagamentos")
def pagamentos(_: dict = Depends(admin_global)):
    """Todo movimento de carteira: crédito, pré-autorização, estorno, bônus."""
    movs = supabase.table("movimentacoes_carteira").select("*").order("criado_em", desc=True) \
        .limit(LIMITE_LISTA).execute().data or []
    nomes = _por_id("usuarios", [m["usuario_id"] for m in movs], "id, nome")
    return [{**m, "valor": round(_f(m.get("valor")), 2), "saldo_apos": round(_f(m.get("saldo_apos")), 2),
             "usuario": (nomes.get(m["usuario_id"]) or {}).get("nome")} for m in movs]


@router.get("/recargas")
def recargas(status: Optional[str] = Query(None, max_length=20), _: dict = Depends(admin_global)):
    q = supabase.table("sessoes_recarga").select(
        "id, usuario_id, carregador_id, status, origem, percentual_bateria_inicial, "
        "percentual_bateria_atual, alvo_percentual, energia_entregue_kwh, energia_ponta_kwh, "
        "energia_solar_kwh, potencia_atual_kw, custo_estimado, custo_final, valor_estornado, "
        "motivo_recusa, encerrado_por, iniciado_em, finalizado_em, criado_em")
    if status:
        q = q.eq("status", status)
    lista = q.order("criado_em", desc=True).limit(LIMITE_LISTA).execute().data or []
    nomes = _por_id("usuarios", [s["usuario_id"] for s in lista], "id, nome")
    chargers, conds = _carregadores(), _condominios()
    saida = []
    for s in lista:
        c = chargers.get(s["carregador_id"]) or {}
        saida.append({**s, "usuario": (nomes.get(s["usuario_id"]) or {}).get("nome"),
                      "carregador_numero": c.get("numero"),
                      "local": (conds.get(c.get("condominio_id")) or {}).get("nome")})
    return saida


# ---------------------------------------------------------------------------
# Notificações
# ---------------------------------------------------------------------------

class NovaNotificacao(BaseModel):
    mensagem: str = Field(..., min_length=3, max_length=300)
    destino: Literal["todos", "local", "usuario"]
    condominio_id: Optional[str] = Field(None, max_length=40)
    usuario_id: Optional[str] = Field(None, max_length=40)


@router.get("/notificacoes")
def notificacoes(_: dict = Depends(admin_global)):
    lista = supabase.table("notificacoes").select("*").order("criado_em", desc=True) \
        .limit(LIMITE_LISTA).execute().data or []
    nomes = _por_id("usuarios", [n["usuario_id"] for n in lista], "id, nome")
    return [{**n, "usuario": (nomes.get(n["usuario_id"]) or {}).get("nome")} for n in lista]


@router.post("/notificacoes")
def enviar_notificacao(payload: NovaNotificacao, _: dict = Depends(admin_global)):
    """Chega no sino do app na hora (a tabela está no Realtime desde o 01)."""
    q = supabase.table("usuarios").select("id").neq("tipo_usuario", "gestor")
    if payload.destino == "local":
        if not payload.condominio_id:
            raise HTTPException(status_code=422, detail="Escolha o local.")
        q = q.eq("condominio_id", payload.condominio_id)
    elif payload.destino == "usuario":
        if not payload.usuario_id:
            raise HTTPException(status_code=422, detail="Escolha o usuário.")
        q = q.eq("id", payload.usuario_id)
    ids = [u["id"] for u in q.execute().data or []]
    if not ids:
        raise HTTPException(status_code=404, detail="Nenhum destinatário encontrado.")
    texto = payload.mensagem.strip()
    supabase.table("notificacoes").insert([{"usuario_id": i, "mensagem": texto} for i in ids]).execute()
    return {"success": True, "enviadas": len(ids)}


# ---------------------------------------------------------------------------
# Chamados
# ---------------------------------------------------------------------------

class RespostaChamado(BaseModel):
    status: Optional[Literal["aberto", "em_andamento", "resolvido"]] = None
    resposta: Optional[str] = Field(None, min_length=2, max_length=2000)


SEM_CHAMADOS = HTTPException(status_code=503, detail="Chamados indisponíveis: rode o db/20.")


@router.get("/chamados")
def listar_chamados(status: Optional[str] = Query(None, max_length=20), _: dict = Depends(admin_global)):
    try:
        q = supabase.table("chamados").select("*")
        if status:
            q = q.eq("status", status)
        lista = q.order("criado_em", desc=True).limit(LIMITE_LISTA).execute().data or []
    except Exception:                                        # noqa: BLE001
        raise SEM_CHAMADOS
    nomes = _por_id("usuarios", [c["usuario_id"] for c in lista], "id, nome, bloco_apto")
    conds = _condominios()
    return [{**c, "usuario": (nomes.get(c["usuario_id"]) or {}).get("nome"),
             "bloco_apto": (nomes.get(c["usuario_id"]) or {}).get("bloco_apto"),
             "local": (conds.get(c.get("condominio_id")) or {}).get("nome")} for c in lista]


@router.patch("/chamados/{chamado_id}")
def responder_chamado(chamado_id: str, payload: RespostaChamado, gestor: dict = Depends(admin_global)):
    if payload.status is None and payload.resposta is None:
        raise HTTPException(status_code=400, detail="Nada para alterar.")
    if not UUID.fullmatch(chamado_id):
        raise HTTPException(status_code=404, detail="Chamado não encontrado.")
    try:
        c = um(supabase.table("chamados").select("*").eq("id", chamado_id).execute())
    except Exception:                                        # noqa: BLE001
        raise SEM_CHAMADOS
    if not c:
        raise HTTPException(status_code=404, detail="Chamado não encontrado.")
    dados = {"atualizado_em": agora_iso()}
    if payload.resposta is not None:
        dados.update({"resposta": payload.resposta.strip(), "respondido_por": gestor["id"],
                      "respondido_em": agora_iso(),
                      "status": payload.status or ("resolvido" if c["status"] != "resolvido" else c["status"])})
    elif payload.status:
        dados["status"] = payload.status
    supabase.table("chamados").update(dados).eq("id", chamado_id).execute()
    if payload.resposta is not None:
        # A resposta aparece no sino do app e na tela de Suporte.
        supabase.table("notificacoes").insert({
            "usuario_id": c["usuario_id"],
            "mensagem": f"Seu chamado \"{c['assunto'][:60]}\" foi respondido. Veja em Suporte.",
        }).execute()
    return {"success": True, "chamado": {**c, **dados}}
