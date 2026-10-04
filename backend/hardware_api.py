"""
hardware_api.py - A ponta do backend que conversa com o ESP32 por WiFi.
=======================================================================

O ESP32 é CLIENTE HTTP. Ele chama o backend; o backend nunca chama a placa.
Não precisa de IP fixo, porta aberta nem mesma sub-rede - só o SSID e a URL.

DOIS PROTOCOLOS CONVIVENDO (ADR-015)
------------------------------------
v1  /hardware/*      header X-Device-Token (o banco guarda só o SHA-256).
                     Placa de UMA porta: tudo vale para a porta 1.
                     Continua funcionando até o firmware v2 (Chat 3).

v2  /hardware/v2/*   cada requisição ASSINADA com HMAC-SHA256 e numerada:
                       X-Device-Id  uuid da placa
                       X-Boot       aleatório sorteado a cada vez que a placa liga
                       X-Seq        1, 2, 3... a cada requisição deste boot
                       X-Ts         hora unix (s); janela de ±120 s
                       X-Sig        hex(HMAC(K, MÉTODO\\ncaminho\\nboot\\nseq\\nts\\nsha256(corpo)))
                     K é derivada da DEVICE_MASTER_KEY (ver seguranca.py) e
                     nunca é gravada. Telemetria em LOTE e várias portas.

ANTI-REPLAY: timestamp E sequência. Só o timestamp deixa repetir dentro da
janela; só a sequência deixa repetir um handshake de um boot antigo. O HMAC
é conferido aqui (só o backend tem a chave-mestra); janela e sequência são
conferidas no Postgres, num UPDATE atômico (consumir_seq / registrar_lote_telemetria).

SEM DOWNGRADE: o primeiro handshake v2 aposenta o token v1 da placa (o banco
apaga o hash). Quem roubou o token v1 não volta pela porta mais fraca.

ROTAS
-----
  v1                                      v2
  POST /hardware/handshake                GET  /hardware/v2/hora          (pública)
  GET  /hardware/comandos                 POST /hardware/v2/handshake
  POST /hardware/comandos/{id}/confirmar  GET  /hardware/v2/comandos
  POST /hardware/rfid                     POST /hardware/v2/comandos/{id}/confirmar
  POST /hardware/telemetria               POST /hardware/v2/rfid          {porta, uid}
                                          POST /hardware/v2/telemetria    {t_envio_ms, leituras[]}

Erros do v2 vêm com um CÓDIGO em `detail`, para o firmware decidir sem ler texto:
  401 assinatura_invalida | fora_da_janela      (confira chave e relógio)
  409 replay | boot_desconhecido                (boot_desconhecido: refaça o handshake)
  413 corpo_grande   422 porta_inexistente | lote_invalido   503 v2_nao_configurado
"""

import time
import uuid as uuidlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import dispositivos
import recarga
from config import CORPO_MAX_V2, JANELA_REPLAY_S, MAX_LEITURAS_LOTE, agora, agora_iso, \
    para_datetime, supabase, um
from fisica import custo_da_sessao, minutos_pela_potencia_medida, soc_pela_energia
from identidade import gestor_logado
from seguranca import assinatura_v2_confere, chave_dispositivo, hash_token_dispositivo, \
    protocolo_v2_configurado

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


class LeituraV2(TelemetriaPayload):
    porta: int = Field(..., ge=1, le=8)
    # millis() da placa no instante da medição. O servidor só usa a DIFERENÇA
    # para t_envio_ms: a ordem vem do relógio do servidor, não da placa.
    t_ms: int = Field(..., ge=0)


class TelemetriaV2Payload(BaseModel):
    t_envio_ms: int = Field(..., ge=0)
    leituras: list[LeituraV2] = Field(..., min_length=1, max_length=MAX_LEITURAS_LOTE)


class RfidV2Payload(RfidPayload):
    porta: int = Field(..., ge=1, le=8)


# ---------------------------------------------------------------------------
# Peças comuns aos dois protocolos
# ---------------------------------------------------------------------------

def _resumo_sessao(s: dict | None) -> dict | None:
    if not s:
        return None
    return {
        "sessao_id": s["id"],
        "energia_wh": round(float(s.get("energia_entregue_kwh") or 0) * 1000, 3),
        "alvo": float(s.get("alvo_percentual") or 100),
        "percentual": float(s.get("percentual_bateria_atual") or 0),
    }


def _estado_da_porta(carregador_id: str) -> dict:
    """O que a placa precisa saber de UMA porta ao ligar."""
    c = recarga.carregador(carregador_id)
    ativa = recarga.sessao_ativa_do_carregador(carregador_id)
    aguardando = recarga.sessao_aguardando(carregador_id)
    supabase.table("carregadores").update({"status": "em_uso" if ativa else "disponivel"}) \
        .eq("id", carregador_id).execute()
    return {
        "carregador": {
            "id": c["id"], "numero": c["numero"], "perfil": c.get("perfil"),
            "potencia_maxima_kw": c["potencia_maxima_kw"], "tensao_v": c.get("tensao_v"),
            "tarifa_kwh": c.get("tarifa_kwh"),
        },
        "condominio": (recarga.condominio_de(c) or {}).get("nome"),
        # Reiniciou no meio de uma recarga: o relé volta a fechar e o contador
        # de energia continua de onde parou, em vez de recomeçar do zero.
        "rele_esperado": bool(ativa),
        "sessao_ativa": _resumo_sessao(ativa),
        "pedido": dispositivos.payload_pedido(aguardando) if aguardando else None,
    }


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


def _entregar_comandos(dispositivo_id: str, so_porta: int | None = None) -> list[dict]:
    q = supabase.table("comandos_dispositivo").select("*").eq("dispositivo_id", dispositivo_id) \
        .eq("status", "pendente")
    if so_porta is not None:
        q = q.eq("porta", so_porta)
    pendentes = q.order("criado_em").limit(5).execute().data or []

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
        entregues.append({"id": cmd["id"], "acao": cmd["acao"], "porta": cmd.get("porta") or 1,
                          "sessao_id": cmd.get("sessao_id"), "payload": payload})
    return entregues


def _confirmar(dispositivo_id: str, comando_id: str, payload: ConfirmacaoPayload) -> dict:
    # Filtra pelo dispositivo: uma placa não confirma comando de outra.
    r = supabase.table("comandos_dispositivo").update({
        "status": "confirmado" if payload.sucesso else "falhou",
        "erro": payload.erro,
        "confirmado_em": agora_iso(),
    }).eq("id", comando_id).eq("dispositivo_id", dispositivo_id).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Comando não encontrado para este dispositivo")
    if not payload.sucesso:
        print(f"[HARDWARE] comando {comando_id} FALHOU: {payload.erro}")
    return {"ok": True}


def _cartao(carregador_id: str, uid_bruto: str) -> dict:
    uid = uid_bruto.replace(":", "").replace("-", "").replace(" ", "").upper()
    resposta = recarga.processar_cartao(carregador_id, uid)
    resposta.pop("sessao", None)       # a placa não precisa da linha inteira
    return resposta


def _processar_leitura(carregador_id: str, leitura: TelemetriaPayload) -> dict:
    """
    A partir daqui a energia da sessão deixa de ser calculada e passa a ser
    MEDIDA. O modelo físico só entra para derivar o SoC; o tempo restante sai
    da potência que o sensor está vendo. A leitura JÁ foi gravada por quem chamou.
    """
    if leitura.temperatura_c is not None:
        supabase.table("carregadores").update({"temperatura_c": round(leitura.temperatura_c, 1)}) \
            .eq("id", carregador_id).execute()

    s = recarga.sessao_ativa_do_carregador(carregador_id)
    if not s:
        # Sem sessão o relé tem que estar aberto: trava contra energia correndo
        # sem ninguém pagando.
        aguardando = recarga.sessao_aguardando(carregador_id)
        return {"ok": True, "sessao_ativa": False, "deve_liberar": False,
                "aguardando_cartao": bool(aguardando)}

    v = recarga.veiculo(s["veiculo_id"]) or {}
    cond = recarga.condominio_de(recarga.carregador(carregador_id))

    potencia_kw = float(leitura.potencia_w or 0) / 1000.0
    energia_kwh = max(float(s.get("energia_entregue_kwh") or 0),
                      float(leitura.energia_wh or 0) / 1000.0)

    media = s.get("potencia_media_kw")
    if leitura.rele_ligado and potencia_kw > 0:
        media = potencia_kw if media is None else float(media) * (1 - ALFA_MEDIA) + potencia_kw * ALFA_MEDIA

    soc = soc_pela_energia(s, v, energia_kwh)
    tempo = minutos_pela_potencia_medida(s, v, soc or 0, media) if soc is not None else None

    # Celular cheio para de puxar corrente. 30 s abaixo de 0,5 W com o relé
    # fechado e alguma energia já entregue = carga completa.
    fim_por_dispositivo = False
    if leitura.rele_ligado and energia_kwh > 0.0002 and potencia_kw < recarga.LIMIAR_BAIXA_POTENCIA_KW:
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


# ===========================================================================
# PROTOCOLO v1 - inalterado para a placa (porta 1 implícita)
# ===========================================================================

def autenticar(token: Optional[str]) -> dict:
    """
    Resolve o token na placa, marca presença e devolve a placa com
    `carregador_id` = o carregador da PORTA 1. Toda rota v1 passa aqui.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Header X-Device-Token ausente")
    d = um(supabase.table("dispositivos").select("*")
           .eq("token_hash", hash_token_dispositivo(token)).execute())
    # protocolo 2: o handshake v2 já apagou o hash, mas a checagem explícita
    # não depende disso - placa promovida não volta para o v1.
    if not d or d.get("protocolo") == 2:
        raise HTTPException(status_code=401, detail="Dispositivo não reconhecido")

    carregador_id = dispositivos.carregador_da_porta(d["id"], 1)
    if not carregador_id:
        raise HTTPException(status_code=409, detail="Placa sem porta 1 cadastrada")

    dispositivos.marcar_presenca(d)
    return {**d, "carregador_id": carregador_id}


@router.post("/handshake")
def handshake(payload: HandshakePayload, x_device_token: str = Header(None)):
    d = autenticar(x_device_token)
    supabase.table("dispositivos").update(
        {"mac": payload.mac, "ip": payload.ip, "firmware": payload.firmware}
    ).eq("id", d["id"]).execute()

    # A placa acabou de ligar: o que estava na fila foi pensado para a vida
    # anterior dela. O estado real vai nesta resposta.
    descartados = dispositivos.descartar_pendentes(d["id"])
    porta = _estado_da_porta(d["carregador_id"])

    return {
        "ok": True,
        "dispositivo": {"id": d["id"], "nome": d["nome"]},
        **porta,
        "intervalo_telemetria_s": d.get("intervalo_telemetria_s") or 2,
        "intervalo_comandos_s": d.get("intervalo_comandos_s") or 2,
        "comandos_descartados": descartados,
        "servidor_hora": agora_iso(),
    }


@router.get("/comandos")
def buscar_comandos(x_device_token: str = Header(None)):
    d = autenticar(x_device_token)
    return {"comandos": _entregar_comandos(d["id"], so_porta=1)}


@router.post("/comandos/{comando_id}/confirmar")
def confirmar_comando(comando_id: str, payload: ConfirmacaoPayload,
                      x_device_token: str = Header(None)):
    d = autenticar(x_device_token)
    return _confirmar(d["id"], comando_id, payload)


@router.post("/rfid")
def leitura_rfid(payload: RfidPayload, x_device_token: str = Header(None)):
    d = autenticar(x_device_token)
    return _cartao(d["carregador_id"], payload.uid)


@router.post("/telemetria")
def receber_telemetria(payload: TelemetriaPayload, x_device_token: str = Header(None)):
    d = autenticar(x_device_token)
    s = recarga.sessao_ativa_do_carregador(d["carregador_id"])
    supabase.table("leituras_hardware").insert({
        "dispositivo_id": d["id"],
        "porta": 1,
        "sessao_id": s["id"] if s else None,
        "potencia_w": payload.potencia_w,
        "energia_wh": payload.energia_wh,
        "tensao_v": payload.tensao_v,
        "corrente_a": payload.corrente_a,
        "temperatura_c": payload.temperatura_c,
        "rele_ligado": payload.rele_ligado,
    }).execute()
    return _processar_leitura(d["carregador_id"], payload)


# ===========================================================================
# PROTOCOLO v2 - assinado, numerado, multiporta, telemetria em lote
# ===========================================================================

# Erros que o banco levanta -> (status HTTP, código para o firmware).
_ERROS_BANCO = {
    "fora_da_janela": 401, "replay": 409, "boot_desconhecido": 409,
    "dispositivo_inexistente": 401, "seq_invalido": 400,
    "porta_inexistente": 422, "lote_invalido": 422,
}


def _erro_do_banco(e: Exception) -> HTTPException:
    texto = str(e)
    for codigo, status in _ERROS_BANCO.items():
        if codigo in texto:
            # dispositivo_inexistente vira o mesmo 401 de assinatura errada:
            # a resposta não ensina quais ids existem.
            if codigo == "dispositivo_inexistente":
                codigo = "assinatura_invalida"
            return HTTPException(status_code=status, detail=codigo)
    raise e


def _rpc(nome: str, params: dict):
    try:
        return supabase.rpc(nome, params).execute()
    except Exception as e:
        raise _erro_do_banco(e)


def _cabecalho_int(valor: Optional[str]) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="assinatura_invalida")
    if n < 0 or n > 2 ** 63 - 1:
        raise HTTPException(status_code=401, detail="assinatura_invalida")
    return n


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _conferir_assinatura(request_info: dict) -> dict:
    """Parte síncrona: busca a placa, deriva a chave e confere o HMAC."""
    try:
        uuidlib.UUID(request_info["id"] or "")
    except ValueError:
        raise HTTPException(status_code=401, detail="assinatura_invalida")
    d = um(supabase.table("dispositivos").select("*").eq("id", request_info["id"]).execute())
    # Placa inexistente e assinatura errada dão a MESMA resposta.
    chave = chave_dispositivo(d["id"], d.get("chave_versao") or 1) if d else b"\0" * 32
    ok = assinatura_v2_confere(chave, request_info["sig"], request_info["metodo"],
                               request_info["caminho"], request_info["boot"],
                               request_info["seq"], request_info["ts"], request_info["corpo"])
    if not (d and ok):
        raise HTTPException(status_code=401, detail="assinatura_invalida")
    return d


def _assinada(consumir: bool, handshake: bool = False):
    """
    Fábrica de dependência. `consumir=False` só na telemetria, onde a RPC do
    lote consome o seq na MESMA transação em que grava as leituras.
    """
    async def dependencia(request: Request,
                          x_device_id: Optional[str] = Header(None),
                          x_boot: Optional[str] = Header(None),
                          x_seq: Optional[str] = Header(None),
                          x_ts: Optional[str] = Header(None),
                          x_sig: Optional[str] = Header(None)) -> dict:
        if not protocolo_v2_configurado():
            raise HTTPException(status_code=503, detail="v2_nao_configurado")
        corpo = await request.body()
        if len(corpo) > CORPO_MAX_V2:
            raise HTTPException(status_code=413, detail="corpo_grande")
        info = {"id": x_device_id, "sig": x_sig, "metodo": request.method,
                "caminho": request.url.path, "boot": _cabecalho_int(x_boot),
                "seq": _cabecalho_int(x_seq), "ts": _cabecalho_int(x_ts),
                "corpo": corpo}

        def sincrono() -> dict:
            d = _conferir_assinatura(info)
            if consumir:
                _rpc("consumir_seq", {"p_dispositivo": d["id"], "p_boot": info["boot"],
                                      "p_seq": info["seq"], "p_ts": _iso(info["ts"]),
                                      "p_handshake": handshake, "p_janela_s": JANELA_REPLAY_S})
                dispositivos.marcar_presenca(d)
            return {**d, "_boot": info["boot"], "_seq": info["seq"], "_ts": info["ts"]}

        return await run_in_threadpool(sincrono)
    return dependencia


@router.get("/v2/hora")
def hora_v2():
    """Pública: a placa acerta o relógio antes do primeiro handshake. Hora não é segredo."""
    return {"ts": int(time.time()), "iso": agora_iso(), "janela_s": JANELA_REPLAY_S}


@router.post("/v2/handshake")
def handshake_v2(payload: HandshakePayload, d: dict = Depends(_assinada(consumir=True, handshake=True))):
    supabase.table("dispositivos").update(
        {"mac": payload.mac, "ip": payload.ip, "firmware": payload.firmware}
    ).eq("id", d["id"]).execute()
    descartados = dispositivos.descartar_pendentes(d["id"])
    portas = [{"porta": p["numero"], **_estado_da_porta(p["carregador_id"])}
              for p in dispositivos.portas_do_dispositivo(d["id"])]
    return {
        "ok": True,
        "dispositivo": {"id": d["id"], "nome": d["nome"]},
        "portas": portas,
        "intervalo_telemetria_s": d.get("intervalo_telemetria_s") or 2,
        "intervalo_comandos_s": d.get("intervalo_comandos_s") or 2,
        "comandos_descartados": descartados,
        "max_leituras_lote": MAX_LEITURAS_LOTE,
        "janela_s": JANELA_REPLAY_S,
        "servidor_ts": int(time.time()),
    }


@router.get("/v2/comandos")
def buscar_comandos_v2(d: dict = Depends(_assinada(consumir=True))):
    return {"comandos": _entregar_comandos(d["id"])}


@router.post("/v2/comandos/{comando_id}/confirmar")
def confirmar_comando_v2(comando_id: str, payload: ConfirmacaoPayload,
                         d: dict = Depends(_assinada(consumir=True))):
    return _confirmar(d["id"], comando_id, payload)


@router.post("/v2/rfid")
def leitura_rfid_v2(payload: RfidV2Payload, d: dict = Depends(_assinada(consumir=True))):
    carregador_id = dispositivos.carregador_da_porta(d["id"], payload.porta)
    if not carregador_id:
        raise HTTPException(status_code=422, detail="porta_inexistente")
    return {"porta": payload.porta, **_cartao(carregador_id, payload.uid)}


@router.post("/v2/telemetria")
def receber_telemetria_v2(payload: TelemetriaV2Payload, d: dict = Depends(_assinada(consumir=False))):
    """
    Uma RPC consome o seq E grava o lote na mesma transação: leitura repetida
    não entra, e leitura recusada não gasta o seq. Depois, a regra de negócio
    roda UMA vez por porta, com a leitura mais recente dela (energia é
    acumulada, então a última basta).
    """
    leituras = [x.model_dump() for x in payload.leituras]
    _rpc("registrar_lote_telemetria", {
        "p_dispositivo": d["id"], "p_boot": d["_boot"], "p_seq": d["_seq"], "p_ts": _iso(d["_ts"]),
        "p_t_envio_ms": payload.t_envio_ms, "p_leituras": leituras, "p_janela_s": JANELA_REPLAY_S,
    })
    dispositivos.marcar_presenca(d)

    ultima: dict[int, LeituraV2] = {}
    for x in payload.leituras:
        if x.porta not in ultima or x.t_ms >= ultima[x.porta].t_ms:
            ultima[x.porta] = x

    respostas = []
    for porta in sorted(ultima):
        carregador_id = dispositivos.carregador_da_porta(d["id"], porta)
        respostas.append({"porta": porta, **_processar_leitura(carregador_id, ultima[porta])})
    return {"ok": True, "gravadas": len(leituras), "portas": respostas}


# ---------------------------------------------------------------------------
# Diagnóstico (só gestor)
# ---------------------------------------------------------------------------

def _ponto_do_gestor(carregador_id: str, gestor: dict) -> dict:
    """Gestor só enxerga (e cutuca) equipamento do PRÓPRIO condomínio."""
    c = recarga.carregador(carregador_id)
    if c["condominio_id"] != gestor.get("condominio_id"):
        raise HTTPException(status_code=404, detail="Carregador não encontrado.")
    return c


@router.get("/status/{carregador_id}")
def status_dispositivo(carregador_id: str, gestor: dict = Depends(gestor_logado)):
    _ponto_do_gestor(carregador_id, gestor)
    d = dispositivos.dispositivo_do_carregador(carregador_id)
    if not d:
        raise HTTPException(status_code=404, detail="Nenhum dispositivo neste carregador")
    ultimas = supabase.table("leituras_hardware").select(
        "porta, potencia_w, energia_wh, tensao_v, corrente_a, temperatura_c, rele_ligado, medido_em"
    ).eq("dispositivo_id", d["id"]).eq("porta", d["porta"]) \
        .order("medido_em", desc=True).limit(10).execute()
    comandos = supabase.table("comandos_dispositivo").select("id, porta, acao, status, erro, criado_em") \
        .eq("dispositivo_id", d["id"]).eq("porta", d["porta"]) \
        .order("criado_em", desc=True).limit(10).execute()
    return {
        "dispositivo": {k: d.get(k) for k in ("id", "nome", "online", "ultimo_contato", "ip",
                                               "firmware", "protocolo", "porta")},
        "ultimas_leituras": ultimas.data,
        "ultimos_comandos": comandos.data,
    }


@router.post("/ping/{carregador_id}")
def ping(carregador_id: str, gestor: dict = Depends(gestor_logado)):
    """Se o LED da porta piscar 3 vezes, a ponta inteira funciona."""
    _ponto_do_gestor(carregador_id, gestor)
    if not dispositivos.enfileirar(carregador_id, "ping"):
        raise HTTPException(status_code=404, detail="Nenhum dispositivo neste carregador")
    return {"ok": True}
