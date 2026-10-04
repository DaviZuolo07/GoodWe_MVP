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

As ordens (cada uma carrega a porta):
  solicitar_cartao  "tem uma recarga preparada aqui, peça o cartão"
  cancelar_cartao   "a espera acabou (desistiu, expirou, recusou)"
  liberar           "cartão aprovado, feche o relé"
  bloquear          "recarga encerrada, abra o relé"
  ping              "pisque o LED" - teste de ponta a ponta
"""

from datetime import timedelta

from config import MODO_DEMO, SEGUNDOS_ATE_OFFLINE, agora, agora_iso, para_datetime, supabase, um


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
    """em_uso se há recarga correndo no ponto, senão disponivel."""
    ativa = um(supabase.table("sessoes_recarga").select("id").eq("carregador_id", carregador_id)
               .eq("status", "carregando").limit(1).execute())
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
