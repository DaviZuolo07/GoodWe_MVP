"""
dispositivos.py - Fila de comandos para o ESP32.
================================================

O ESP32 é CLIENTE: ele pergunta ao backend a cada 2 s "tem ordem pra mim?"
(GET /hardware/comandos). O backend nunca chama a placa - assim ela funciona
atrás de NAT, no WiFi de casa ou no hotspot do celular, sem IP fixo.

As ordens:
  solicitar_cartao  "tem uma recarga preparada aqui, peça o cartão"
                    (payload: sessão, morador, veículo, local, alvo, estimativa)
  cancelar_cartao   "a espera acabou (desistiu, expirou, recusou)"
  liberar           "cartão aprovado, feche o relé"
  bloquear          "recarga encerrada, abra o relé"
  ping              "pisque o LED" - teste de ponta a ponta
"""

from datetime import timedelta

from config import MODO_DEMO, SEGUNDOS_ATE_OFFLINE, agora, agora_iso, para_datetime, supabase, um


def dispositivo_do_carregador(carregador_id: str) -> dict | None:
    return um(supabase.table("dispositivos").select("*")
              .eq("carregador_id", carregador_id).execute())


def enfileirar(carregador_id: str, acao: str, sessao_id: str | None = None,
               payload: dict | None = None) -> dict | None:
    """Em ponto sem dispositivo (simulado) não faz nada e devolve None."""
    d = dispositivo_do_carregador(carregador_id)
    if not d:
        return None
    novo = supabase.table("comandos_dispositivo").insert({
        "dispositivo_id": d["id"],
        "sessao_id": sessao_id,
        "acao": acao,
        "payload": payload,
        "status": "pendente",
    }).execute()
    print(f"[HARDWARE] '{acao}' enfileirado no ponto {carregador_id}")
    return um(novo)


def descartar_pendentes(dispositivo_id: str, motivo: str = "reinicio da placa") -> int:
    """Handshake: a placa reiniciou, o que estava na fila perdeu o contexto."""
    r = supabase.table("comandos_dispositivo").update({
        "status": "descartado", "erro": motivo, "confirmado_em": agora_iso(),
    }).eq("dispositivo_id", dispositivo_id).eq("status", "pendente").execute()
    return len(r.data or [])


def marcar_offline_sem_contato() -> None:
    """Chamado pelo laço do simulador. Ponto físico sem contato cai para offline."""
    if MODO_DEMO:
        return
    limite = (agora() - timedelta(seconds=SEGUNDOS_ATE_OFFLINE)).isoformat()
    mortos = supabase.table("dispositivos").select("id, carregador_id, nome") \
        .eq("online", True).lt("ultimo_contato", limite).execute()
    for d in (mortos.data or []):
        supabase.table("dispositivos").update({"online": False}).eq("id", d["id"]).execute()
        supabase.table("carregadores").update({"status": "offline"}).eq("id", d["carregador_id"]).execute()
        print(f"[HARDWARE] {d['nome']} sem contato há {SEGUNDOS_ATE_OFFLINE}s - ponto offline")


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

    return {
        "sessao_id": sessao["id"],
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
