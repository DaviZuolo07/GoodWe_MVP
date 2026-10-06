"""
dispositivos.py - Placas, portas e a fila de comandos do ESP32.
===============================================================

O ESP32 é CLIENTE: ele pergunta ao backend a cada 2 s "tem ordem pra mim?".
O backend nunca chama a placa - assim ela funciona atrás de NAT, no WiFi de
casa ou no hotspot do celular, sem IP fixo.

MULTIPORTA (migration 15)
-------------------------
Uma placa tem N portas (relés); cada porta atende UM carregador. A ligação
mora em `portas_dispositivo`, fechada ao navegador. A coluna antiga
`dispositivos.carregador_id` está depreciada e NÃO é lida aqui.

Placa v1 = placa de uma porta só: tudo que ela faz vale para a porta 1.

ESCALA E VAGA SOLAR (migration 17)
----------------------------------
`fator_escala` multiplica W/Wh brutos na entrada (ADR-017). `porta_solar` diz
qual porta é alimentada por painel/bateria: o sol dela é MEDIDO e não é
atribuído às portas vizinhas, que ficam só na rede (ADR-018 D6).

EVENTOS DE SEGURANÇA
--------------------
Tag alheia em vaga ocupada, replay e assinatura inválida viram linha em
`eventos_seguranca` (só o backend grava; o painel do admin lê no chat D3).
Repetição do mesmo evento é segurada por alguns segundos: um atacante
martelando a API não enche a tabela.

As ordens (cada uma carrega a porta):
  solicitar_cartao  "tem uma recarga preparada aqui, peça o cartão"
  cancelar_cartao   "a espera acabou (desistiu, expirou, recusou)"
  liberar           "cartão aprovado, feche o relé"
  bloquear          "recarga encerrada, abra o relé"
  ping              "pisque o LED" - teste de ponta a ponta
"""

import threading
import time
from datetime import timedelta

from config import MODO_DEMO, SEGUNDOS_ATE_OFFLINE, agora, agora_iso, para_datetime, supabase, um

# Sessões que ocupam a vaga (a espera por energia também ocupa: o celular
# está plugado e o saldo, reservado).
STATUS_OCUPA_VAGA = ("carregando", "aguardando_energia")


# ---------------------------------------------------------------------------
# Topologia: placa <-> porta <-> carregador
# ---------------------------------------------------------------------------

def portas_do_dispositivo(dispositivo_id: str) -> list[dict]:
    """[{numero, carregador_id}, ...] em ordem de porta."""
    return supabase.table("portas_dispositivo").select("numero, carregador_id") \
        .eq("dispositivo_id", dispositivo_id).order("numero").execute().data or []


def carregador_da_porta(dispositivo_id: str, numero: int) -> str | None:
    p = um(supabase.table("portas_dispositivo").select("carregador_id")
           .eq("dispositivo_id", dispositivo_id).eq("numero", numero).execute())
    return p["carregador_id"] if p else None


def porta_do_carregador(carregador_id: str) -> dict | None:
    """{dispositivo_id, numero} do carregador, ou None se ele é simulado."""
    return um(supabase.table("portas_dispositivo").select("dispositivo_id, numero")
              .eq("carregador_id", carregador_id).execute())


def dispositivo_do_carregador(carregador_id: str) -> dict | None:
    """A placa que atende o carregador, com a porta dele em `porta`."""
    p = porta_do_carregador(carregador_id)
    if not p:
        return None
    d = um(supabase.table("dispositivos").select("*").eq("id", p["dispositivo_id"]).execute())
    return {**d, "porta": p["numero"]} if d else None


def fator_escala(d: dict | None) -> float:
    """
    Fator da placa (ADR-017). Coluna ausente (banco antes do 17) ou inválida
    vale 1: nada muda para quem não foi provisionado em escala.
    """
    try:
        f = float((d or {}).get("fator_escala") or 1)
    except (TypeError, ValueError):
        return 1.0
    return f if f > 0 else 1.0


def porta_solar(d: dict | None) -> int | None:
    p = (d or {}).get("porta_solar")
    return int(p) if p else None


def carregadores_so_rede(carregador_ids: list[str]) -> set[str]:
    """
    Carregadores que estão numa placa COM vaga solar, mas não são ela. O painel
    é ligado fisicamente só à porta solar (comutação): atribuir sol às vizinhas
    contaria a mesma energia duas vezes.
    """
    if not carregador_ids:
        return set()
    try:
        portas = supabase.table("portas_dispositivo").select("dispositivo_id, numero, carregador_id") \
            .in_("carregador_id", list(carregador_ids)).execute().data or []
        if not portas:
            return set()
        placas = supabase.table("dispositivos").select("id, porta_solar") \
            .in_("id", list({p["dispositivo_id"] for p in portas})).execute().data or []
    except Exception as e:
        print(f"[HARDWARE] topologia solar indisponível: {e}")
        return set()
    solar = {x["id"]: x.get("porta_solar") for x in placas if x.get("porta_solar")}
    return {p["carregador_id"] for p in portas
            if p["dispositivo_id"] in solar and int(p["numero"]) != int(solar[p["dispositivo_id"]])}


# ---------------------------------------------------------------------------
# Fila de comandos
# ---------------------------------------------------------------------------

def enfileirar(carregador_id: str, acao: str, sessao_id: str | None = None,
               payload: dict | None = None) -> dict | None:
    """Em ponto sem placa (simulado) não faz nada e devolve None."""
    p = porta_do_carregador(carregador_id)
    if not p:
        return None
    novo = supabase.table("comandos_dispositivo").insert({
        "dispositivo_id": p["dispositivo_id"],
        "porta": p["numero"],
        "sessao_id": sessao_id,
        "acao": acao,
        "payload": payload,
        "status": "pendente",
    }).execute()
    print(f"[HARDWARE] '{acao}' enfileirado na porta {p['numero']} (ponto {carregador_id})")
    return um(novo)


def descartar_pendentes(dispositivo_id: str, motivo: str = "reinicio da placa") -> int:
    """Handshake: a placa reiniciou, o que estava na fila perdeu o contexto."""
    r = supabase.table("comandos_dispositivo").update({
        "status": "descartado", "erro": motivo, "confirmado_em": agora_iso(),
    }).eq("dispositivo_id", dispositivo_id).eq("status", "pendente").execute()
    return len(r.data or [])


# ---------------------------------------------------------------------------
# Presença
# ---------------------------------------------------------------------------

def status_do_ponto(carregador_id: str) -> str:
    """em_uso se há recarga correndo (ou esperando energia) no ponto, senão disponivel."""
    ativa = um(supabase.table("sessoes_recarga").select("id").eq("carregador_id", carregador_id)
               .in_("status", list(STATUS_OCUPA_VAGA)).limit(1).execute())
    return "em_uso" if ativa else "disponivel"


def marcar_presenca(d: dict) -> None:
    """
    Toda requisição autenticada da placa passa aqui. Se ela estava offline,
    TODOS os pontos das portas dela voltam ao ar.
    """
    supabase.table("dispositivos").update({"ultimo_contato": agora_iso(), "online": True}) \
        .eq("id", d["id"]).execute()
    if not d.get("online"):
        for p in portas_do_dispositivo(d["id"]):
            supabase.table("carregadores").update({"status": status_do_ponto(p["carregador_id"])}) \
                .eq("id", p["carregador_id"]).execute()


def marcar_offline_sem_contato() -> None:
    """Chamado pelo laço do simulador. Placa sem contato derruba todas as portas."""
    if MODO_DEMO:
        return
    limite = (agora() - timedelta(seconds=SEGUNDOS_ATE_OFFLINE)).isoformat()
    mortos = supabase.table("dispositivos").select("id, nome") \
        .eq("online", True).lt("ultimo_contato", limite).execute()
    for d in (mortos.data or []):
        supabase.table("dispositivos").update({"online": False}).eq("id", d["id"]).execute()
        portas = portas_do_dispositivo(d["id"])
        for p in portas:
            supabase.table("carregadores").update({"status": "offline"}) \
                .eq("id", p["carregador_id"]).execute()
        print(f"[HARDWARE] {d['nome']} sem contato há {SEGUNDOS_ATE_OFFLINE}s - "
              f"{len(portas)} ponto(s) offline")


# ---------------------------------------------------------------------------
# Pedido de cartão
# ---------------------------------------------------------------------------

def payload_pedido(sessao: dict) -> dict:
    """
    Tudo que a placa precisa para mostrar QUEM deve aproximar o cartão e o que
    vai acontecer. Só primeiro nome e modelo: a placa fica num lugar público.
    """
    usuario = um(supabase.table("usuarios").select("nome").eq("id", sessao["usuario_id"]).execute()) or {}
    veiculo = um(supabase.table("veiculos").select("modelo, tipo, capacidade_bateria_kwh")
                 .eq("id", sessao["veiculo_id"]).execute()) or {}
    charger = um(supabase.table("carregadores").select("numero, condominio_id")
                 .eq("id", sessao["carregador_id"]).execute()) or {}
    cond = um(supabase.table("condominios").select("nome")
              .eq("id", charger.get("condominio_id")).execute()) if charger else None
    porta = porta_do_carregador(sessao["carregador_id"])

    return {
        "sessao_id": sessao["id"],
        "porta": porta["numero"] if porta else None,
        "usuario": (usuario.get("nome") or "Morador").split()[0],
        "veiculo": veiculo.get("modelo") or "Veículo",
        "veiculo_tipo": veiculo.get("tipo") or "carro",
        "carregador": charger.get("numero"),
        "local": (cond or {}).get("nome"),
        "percentual_inicial": float(sessao.get("percentual_bateria_inicial") or 0),
        "alvo": float(sessao.get("alvo_percentual") or 100),
        "custo_estimado": float(sessao.get("custo_estimado") or 0),
        "energia_estimada_wh": round(
            float(veiculo.get("capacidade_bateria_kwh") or 0) * 1000 *
            (float(sessao.get("alvo_percentual") or 100) - float(sessao.get("percentual_bateria_inicial") or 0))
            / 100 / 0.92, 2),
        "expira_em": sessao.get("expira_em"),
        "segundos_para_aproximar": _segundos_ate(sessao.get("expira_em")),
    }


def _segundos_ate(expira_em) -> int:
    dt = para_datetime(expira_em)
    if not dt:
        return 0
    return max(0, int((dt - agora()).total_seconds()))


# ---------------------------------------------------------------------------
# Eventos de segurança (ADR-018 D7)
# ---------------------------------------------------------------------------

TIPOS_EVENTO = ("tag_alheia", "replay", "assinatura_invalida")      # lista fechada (db/17)
# Mesmo evento (tipo + placa + ip + uid) dentro deste intervalo não grava de novo.
SEGURAR_REPETICAO_S = {"tag_alheia": 5, "replay": 30, "assinatura_invalida": 30}
_ultimos_eventos: dict[tuple, float] = {}
_trava_eventos = threading.Lock()


def _condominio_do_evento(carregador_id: str | None, dispositivo_id: str | None) -> str | None:
    if not carregador_id and dispositivo_id:
        portas = portas_do_dispositivo(dispositivo_id)
        carregador_id = portas[0]["carregador_id"] if portas else None
    if not carregador_id:
        return None
    c = um(supabase.table("carregadores").select("condominio_id").eq("id", carregador_id).execute())
    return (c or {}).get("condominio_id")


def registrar_evento_seguranca(tipo: str, *, dispositivo_id: str | None = None,
                               carregador_id: str | None = None, porta: int | None = None,
                               uid: str | None = None, ip: str | None = None,
                               detalhe: str | None = None) -> bool:
    """
    Grava o evento; devolve True se gravou. NUNCA levanta: um evento que não
    grava não pode derrubar a resposta para a placa.
    """
    if tipo not in TIPOS_EVENTO:
        return False
    chave = (tipo, dispositivo_id, ip, uid)
    agora_s = time.monotonic()
    with _trava_eventos:
        ultimo = _ultimos_eventos.get(chave)
        if ultimo is not None and agora_s - ultimo < SEGURAR_REPETICAO_S.get(tipo, 30):
            return False
        _ultimos_eventos[chave] = agora_s
        if len(_ultimos_eventos) > 5000:                  # não cresce para sempre
            _ultimos_eventos.clear()
    try:
        supabase.table("eventos_seguranca").insert({
            "tipo": tipo,
            "condominio_id": _condominio_do_evento(carregador_id, dispositivo_id),
            "dispositivo_id": dispositivo_id,
            "carregador_id": carregador_id,
            "porta": porta,
            "uid": (uid or None) and str(uid)[:64],
            "ip": (ip or None) and str(ip)[:64],
            "detalhe": (detalhe or None) and str(detalhe)[:200],
        }).execute()
        print(f"[SEGURANCA] {tipo} placa={dispositivo_id} porta={porta} ip={ip}")
        return True
    except Exception as e:
        print(f"[SEGURANCA] evento {tipo} não gravado: {e}")
        return False


def limpar_memoria_de_eventos() -> None:
    """Para os testes: esquece as repetições seguradas."""
    with _trava_eventos:
        _ultimos_eventos.clear()
