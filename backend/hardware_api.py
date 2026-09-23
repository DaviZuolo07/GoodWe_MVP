"""
hardware_api.py - A ponta do backend que conversa com o ESP32 por WiFi.
=======================================================================

O ESP32 é CLIENTE HTTP. Ele chama o backend; o backend nunca chama a placa.
Não precisa de IP fixo, porta aberta nem mesma sub-rede - só o SSID e a URL.
(O `hardware_serial.py` do Arduino por cabo USB foi removido: com o ESP32
por WiFi ele não tem mais papel nenhum e implementava o fluxo antigo.)

O PROTOCOLO
-----------
  POST /hardware/handshake                "liguei: quem sou eu, o que estava acontecendo?"
  GET  /hardware/comandos                 a cada 2 s: "tem ordem pra mim?"
  POST /hardware/comandos/{id}/confirmar  "executei" / "falhei"
  POST /hardware/rfid                     "aproximaram este cartão"
  POST /hardware/telemetria               "estou medindo isto agora"

O FLUXO COMPLETO (Bloco 5)
--------------------------
  app: morador prepara a recarga
    -> backend enfileira `solicitar_cartao` com sessão, morador, veículo,
       local, alvo e estimativa
  ESP32 (poll de 2 s): recebe, pisca rápido, mostra "aproxime o cartão"
  ESP32: cartão lido -> POST /rfid
    -> backend: é o dono? tem saldo? (sem saldo: pede saldo no app, espera)
    -> aprovado: pré-autoriza o saldo e enfileira `liberar`
  ESP32: fecha o relé e manda telemetria a cada 2 s (W, V, A, Wh, °C)
    -> backend: energia, SoC, previsão de término PELA POTÊNCIA MEDIDA, custo
    -> alvo atingido / celular parou de puxar / valor reservado atingido:
       encerra, estorna a diferença e responde `deve_liberar: false`

Autenticação: header `X-Device-Token`. O banco guarda só o SHA-256 dele
(ver 11_seguranca.sql e `provisionar.py token-esp`). O token amarra a placa a
UM carregador: ela não reporta nem confirma nada de outro ponto.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

import dispositivos
import recarga
from config import agora, agora_iso, para_datetime, supabase, um
from fisica import custo_da_sessao, minutos_pela_potencia_medida, soc_pela_energia
from identidade import gestor_logado
from seguranca import hash_token_dispositivo

router = APIRouter(prefix="/hardware", tags=["hardware"])

# Média móvel exponencial da potência medida: 30% da leitura nova, 70% do
# histórico. Suaviza o ruído do sensor sem demorar a reagir.
ALFA_MEDIA = 0.3


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

class HandshakePayload(BaseModel):
    mac: Optional[str] = Field(None, max_length=32)
    ip: Optional[str] = Field(None, max_length=64)
    firmware: Optional[str] = Field(None, max_length=32)


class TelemetriaPayload(BaseModel):
    potencia_w: Optional[float] = Field(None, ge=0, le=100000)
    # ACUMULADA na sessão, não delta: um POST perdido no WiFi se corrige no
    # próximo. Com delta, o pacote perdido sumiria da conta para sempre.
    energia_wh: Optional[float] = Field(None, ge=0)
    tensao_v: Optional[float] = None
    corrente_a: Optional[float] = None
    temperatura_c: Optional[float] = None
    rele_ligado: Optional[bool] = None


class ConfirmacaoPayload(BaseModel):
    sucesso: bool = True
    erro: Optional[str] = Field(None, max_length=200)


class RfidPayload(BaseModel):
    uid: str = Field(..., min_length=4, max_length=32, pattern=r"^[0-9A-Fa-f:\- ]+$")


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------

def autenticar(token: Optional[str]) -> dict:
    """Resolve o token no dispositivo e marca presença. Toda rota passa aqui."""
    if not token:
        raise HTTPException(status_code=401, detail="Header X-Device-Token ausente")
    d = um(supabase.table("dispositivos").select("*")
           .eq("token_hash", hash_token_dispositivo(token)).execute())
    if not d:
        raise HTTPException(status_code=401, detail="Dispositivo não reconhecido")

    supabase.table("dispositivos").update({"ultimo_contato": agora_iso(), "online": True}) \
        .eq("id", d["id"]).execute()

    # Ponto que estava offline volta ao ar assim que a placa fala qualquer coisa.
    if not d.get("online"):
        ativa = recarga.sessao_ativa_do_carregador(d["carregador_id"])
        supabase.table("carregadores").update({"status": "em_uso" if ativa else "disponivel"}) \
            .eq("id", d["carregador_id"]).execute()
    return d


def _resumo_sessao(s: dict | None) -> dict | None:
    if not s:
        return None
    return {
        "sessao_id": s["id"],
        "energia_wh": round(float(s.get("energia_entregue_kwh") or 0) * 1000, 3),
        "alvo": float(s.get("alvo_percentual") or 100),
        "percentual": float(s.get("percentual_bateria_atual") or 0),
    }


# ---------------------------------------------------------------------------
# 1. Handshake
# ---------------------------------------------------------------------------

@router.post("/handshake")
def handshake(payload: HandshakePayload, x_device_token: str = Header(None)):
    d = autenticar(x_device_token)
    supabase.table("dispositivos").update(
        {"mac": payload.mac, "ip": payload.ip, "firmware": payload.firmware}
    ).eq("id", d["id"]).execute()

    # A placa acabou de ligar: o que estava na fila foi pensado para a vida
    # anterior dela. O estado real vai nesta resposta.
    descartados = dispositivos.descartar_pendentes(d["id"])

    c = recarga.carregador(d["carregador_id"])
    cond = recarga.condominio_de(c) or {}
    ativa = recarga.sessao_ativa_do_carregador(c["id"])
    aguardando = recarga.sessao_aguardando(c["id"])

    supabase.table("carregadores").update({"status": "em_uso" if ativa else "disponivel"}) \
        .eq("id", c["id"]).execute()

    return {
        "ok": True,
        "dispositivo": {"id": d["id"], "nome": d["nome"]},
        "carregador": {
            "id": c["id"], "numero": c["numero"], "perfil": c.get("perfil"),
            "potencia_maxima_kw": c["potencia_maxima_kw"], "tensao_v": c.get("tensao_v"),
            "tarifa_kwh": c.get("tarifa_kwh"),
        },
        "condominio": cond.get("nome"),
        "intervalo_telemetria_s": d.get("intervalo_telemetria_s") or 2,
        "intervalo_comandos_s": d.get("intervalo_comandos_s") or 2,
        # Reiniciou no meio de uma recarga: o relé volta a fechar e o contador
        # de energia continua de onde parou, em vez de recomeçar do zero.
        "rele_esperado": bool(ativa),
        "sessao_ativa": _resumo_sessao(ativa),
        "pedido": dispositivos.payload_pedido(aguardando) if aguardando else None,
        "comandos_descartados": descartados,
        "servidor_hora": agora_iso(),
    }


# ---------------------------------------------------------------------------
# 2. Comandos
# ---------------------------------------------------------------------------

def _ainda_vale(cmd: dict) -> bool:
    """Comando que perdeu o sentido enquanto esperava não é entregue."""
    if cmd["acao"] not in ("solicitar_cartao", "liberar") or not cmd.get("sessao_id"):
        return True
    s = recarga.sessao(cmd["sessao_id"])
    if not s:
        return False
    if cmd["acao"] == "solicitar_cartao":
        expira = para_datetime(s.get("expira_em"))
        return s["status"] == "aguardando_rfid" and (not expira or expira > agora())
    return s["status"] == "carregando"


@router.get("/comandos")
def buscar_comandos(x_device_token: str = Header(None)):
    d = autenticar(x_device_token)
    pendentes = supabase.table("comandos_dispositivo").select("*").eq("dispositivo_id", d["id"]) \
        .eq("status", "pendente").order("criado_em").limit(5).execute().data or []

    entregues = []
    for cmd in pendentes:
        if not _ainda_vale(cmd):
            supabase.table("comandos_dispositivo").update(
                {"status": "descartado", "erro": "perdeu a validade antes da entrega",
                 "confirmado_em": agora_iso()}).eq("id", cmd["id"]).execute()
            continue

        payload = cmd.get("payload")
        if cmd["acao"] == "solicitar_cartao":
            payload = dispositivos.payload_pedido(recarga.sessao(cmd["sessao_id"]))  # prazo de agora

        supabase.table("comandos_dispositivo").update(
            {"status": "entregue", "entregue_em": agora_iso()}).eq("id", cmd["id"]).execute()
        entregues.append({"id": cmd["id"], "acao": cmd["acao"],
                          "sessao_id": cmd.get("sessao_id"), "payload": payload})
    return {"comandos": entregues}


@router.post("/comandos/{comando_id}/confirmar")
def confirmar_comando(comando_id: str, payload: ConfirmacaoPayload,
                      x_device_token: str = Header(None)):
    d = autenticar(x_device_token)
    # Filtra pelo dispositivo: uma placa não confirma comando de outra.
    r = supabase.table("comandos_dispositivo").update({
        "status": "confirmado" if payload.sucesso else "falhou",
        "erro": payload.erro,
        "confirmado_em": agora_iso(),
    }).eq("id", comando_id).eq("dispositivo_id", d["id"]).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Comando não encontrado para este dispositivo")
    if not payload.sucesso:
        print(f"[HARDWARE] comando {comando_id} FALHOU: {payload.erro}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# 3. Cartão
# ---------------------------------------------------------------------------

@router.post("/rfid")
def leitura_rfid(payload: RfidPayload, x_device_token: str = Header(None)):
    d = autenticar(x_device_token)
    uid = payload.uid.replace(":", "").replace("-", "").replace(" ", "").upper()
    resposta = recarga.processar_cartao(d["carregador_id"], uid)
    resposta.pop("sessao", None)       # a placa não precisa da linha inteira
    return resposta


# ---------------------------------------------------------------------------
# 4. Telemetria
# ---------------------------------------------------------------------------

@router.post("/telemetria")
def receber_telemetria(payload: TelemetriaPayload, x_device_token: str = Header(None)):
    """
    A partir daqui a energia da sessão deixa de ser calculada e passa a ser
    MEDIDA. O modelo físico só entra para derivar o SoC; o tempo restante sai
    da potência que o sensor está vendo.
    """
    d = autenticar(x_device_token)
    carregador_id = d["carregador_id"]

    if payload.temperatura_c is not None:
        supabase.table("carregadores").update({"temperatura_c": round(payload.temperatura_c, 1)}) \
            .eq("id", carregador_id).execute()

    s = recarga.sessao_ativa_do_carregador(carregador_id)

    supabase.table("leituras_hardware").insert({
        "dispositivo_id": d["id"],
        "sessao_id": s["id"] if s else None,
        "potencia_w": payload.potencia_w,
        "energia_wh": payload.energia_wh,
        "tensao_v": payload.tensao_v,
        "corrente_a": payload.corrente_a,
        "temperatura_c": payload.temperatura_c,
        "rele_ligado": payload.rele_ligado,
    }).execute()

    if not s:
        # Sem sessão o relé tem que estar aberto: trava contra energia correndo
        # sem ninguém pagando.
        aguardando = recarga.sessao_aguardando(carregador_id)
        return {"ok": True, "sessao_ativa": False, "deve_liberar": False,
                "aguardando_cartao": bool(aguardando)}

    v = recarga.veiculo(s["veiculo_id"]) or {}
    charger = recarga.carregador(carregador_id)
    cond = recarga.condominio_de(charger)

    potencia_kw = float(payload.potencia_w or 0) / 1000.0
    energia_kwh = max(float(s.get("energia_entregue_kwh") or 0),
                      float(payload.energia_wh or 0) / 1000.0)

    media = s.get("potencia_media_kw")
    if payload.rele_ligado and potencia_kw > 0:
        media = potencia_kw if media is None else float(media) * (1 - ALFA_MEDIA) + potencia_kw * ALFA_MEDIA

    soc = soc_pela_energia(s, v, energia_kwh)
    tempo = minutos_pela_potencia_medida(s, v, soc or 0, media) if soc is not None else None

    # Celular cheio para de puxar corrente. 30 s abaixo de 0,5 W com o relé
    # fechado e alguma energia já entregue = carga completa.
    fim_por_dispositivo = False
    if payload.rele_ligado and energia_kwh > 0.0002 and potencia_kw < recarga.LIMIAR_BAIXA_POTENCIA_KW:
        desde = para_datetime(s.get("baixa_potencia_desde"))
        if not desde:
            supabase.table("sessoes_recarga").update({"baixa_potencia_desde": agora_iso()}) \
                .eq("id", s["id"]).execute()
        elif (agora() - desde).total_seconds() >= recarga.SEGUNDOS_BAIXA_POTENCIA:
            fim_por_dispositivo = True
    elif s.get("baixa_potencia_desde"):
        supabase.table("sessoes_recarga").update({"baixa_potencia_desde": None}).eq("id", s["id"]).execute()

    motivo = recarga.registrar_progresso(s, v, cond, energia_kwh, potencia_kw, soc, tempo, media)
    if not motivo and fim_por_dispositivo:
        motivo = "dispositivo_carregado"
        recarga.encerrar(recarga.sessao(s["id"]) or s, motivo)

    atual = recarga.sessao(s["id"]) or s
    return {
        "ok": True,
        "sessao_ativa": motivo is None,
        "deve_liberar": motivo is None,
        "motivo": motivo,
        "percentual": round(soc, 1) if soc is not None else None,
        "tempo_restante_min": tempo,
        "energia_wh": round(energia_kwh * 1000, 3),
        "custo_ate_agora": custo_da_sessao(atual),
        "valor_reservado": float(atual.get("valor_pre_autorizado") or 0),
        "potencia_media_w": round((media or 0) * 1000, 2),
    }


# ---------------------------------------------------------------------------
# 5. Diagnóstico (só gestor)
# ---------------------------------------------------------------------------

@router.get("/status/{carregador_id}")
def status_dispositivo(carregador_id: str, _gestor: dict = Depends(gestor_logado)):
    d = dispositivos.dispositivo_do_carregador(carregador_id)
    if not d:
        raise HTTPException(status_code=404, detail="Nenhum dispositivo neste carregador")
    ultimas = supabase.table("leituras_hardware").select(
        "potencia_w, energia_wh, tensao_v, corrente_a, temperatura_c, rele_ligado, criado_em"
    ).eq("dispositivo_id", d["id"]).order("criado_em", desc=True).limit(10).execute()
    comandos = supabase.table("comandos_dispositivo").select("id, acao, status, erro, criado_em") \
        .eq("dispositivo_id", d["id"]).order("criado_em", desc=True).limit(10).execute()
    return {
        "dispositivo": {k: d.get(k) for k in ("id", "nome", "online", "ultimo_contato", "ip", "firmware")},
        "ultimas_leituras": ultimas.data,
        "ultimos_comandos": comandos.data,
    }


@router.post("/ping/{carregador_id}")
def ping(carregador_id: str, _gestor: dict = Depends(gestor_logado)):
    """Se o LED da placa piscar 3 vezes, a ponta inteira funciona."""
    if not dispositivos.enfileirar(carregador_id, "ping"):
        raise HTTPException(status_code=404, detail="Nenhum dispositivo neste carregador")
    return {"ok": True}
