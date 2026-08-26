"""
hardware_api.py - A ponta do backend que conversa com o ESP32 por WiFi.
=======================================================================

Substitui a serial do Arduino (`hardware_serial.py`, que continua no projeto
como legado para quem ainda tiver a placa por cabo).

A DECISÃO DE ARQUITETURA
------------------------
O ESP32 é CLIENTE. Ele chama o backend; o backend nunca chama o ESP32.

Parece invertido - o servidor deveria mandar no dispositivo - mas é o que faz
isso funcionar fora do laboratório. Para o backend chamar a placa, seria
preciso IP fixo (ou mDNS), backend e placa na mesma rede e firewall liberado.
WiFi de faculdade e de condomínio costuma ter isolamento de cliente, e aí
nenhuma dessas condições existe. Com o ESP32 como cliente, funciona atrás de
NAT, em roteador doméstico ou em hotspot de celular, sem configurar nada além
do SSID e da URL.

Como o backend manda ordem para alguém que ele não pode chamar? Fila de
comandos: o backend enfileira, o dispositivo pergunta a cada 2s. O preço é
até 2s de latência entre apertar "iniciar" e o relé fechar.

OS QUATRO VERBOS DO PROTOCOLO
-----------------------------
  POST /hardware/handshake              "cheguei, quem sou eu?"
  GET  /hardware/comandos               "tem ordem pra mim?"
  POST /hardware/comandos/{id}/confirmar "executei" / "falhei"
  POST /hardware/telemetria             "estou medindo isto agora"
  POST /hardware/rfid                   "leram este cartão, pode liberar?"

Autenticação: header `X-Device-Token`. O token está na tabela `dispositivos`
e amarra a requisição a UM carregador. Um dispositivo não consegue reportar
telemetria de outro ponto nem por engano nem de propósito - mesmo princípio
usado no chatbot: o que vem do cliente é pedido, não permissão.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/hardware", tags=["hardware"])

# Sem contato por mais que isto, o ponto é considerado offline no painel.
SEGUNDOS_ATE_OFFLINE = 30

# Injetado pelo main.py no startup (mesmo padrão do módulo do chatbot: evita
# import circular e mantém uma única instância do cliente Supabase).
_CTX = {}


def configurar_hardware(supabase, autorizar_e_iniciar_sessao, calcular_estimativa,
                        tempo_de_carga_min, custo_da_sessao, eficiencia_carga,
                        avisar_proximo_da_fila, confirmar_sessao_preparada=None):
    _CTX.update({
        "supabase": supabase,
        "autorizar": autorizar_e_iniciar_sessao,
        "confirmar_preparada": confirmar_sessao_preparada,
        "estimar": calcular_estimativa,
        "tempo_de_carga_min": tempo_de_carga_min,
        "custo_da_sessao": custo_da_sessao,
        "eficiencia": eficiencia_carga,
        "avisar_fila": avisar_proximo_da_fila,
    })


def sb():
    if "supabase" not in _CTX:
        raise RuntimeError("configurar_hardware(...) não foi chamado no main.py")
    return _CTX["supabase"]


def agora():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Modelos de requisição
# ---------------------------------------------------------------------------

class HandshakePayload(BaseModel):
    mac: Optional[str] = None
    ip: Optional[str] = None
    firmware: Optional[str] = None


class TelemetriaPayload(BaseModel):
    # Potência instantânea medida pelo sensor, em watts.
    potencia_w: Optional[float] = None
    # Energia ACUMULADA na sessão atual, em watt-hora. O ESP32 integra e manda
    # o total, não o delta: se um POST se perder no WiFi, o próximo já corrige
    # sozinho. Com delta, um pacote perdido sumiria da conta para sempre.
    energia_wh: Optional[float] = None
    tensao_v: Optional[float] = None
    corrente_a: Optional[float] = None
    temperatura_c: Optional[float] = None
    rele_ligado: Optional[bool] = None


class ConfirmacaoPayload(BaseModel):
    sucesso: bool = True
    erro: Optional[str] = None


class RfidPayload(BaseModel):
    uid: str


# ---------------------------------------------------------------------------
# Autenticação e helpers
# ---------------------------------------------------------------------------

def autenticar(token: Optional[str]) -> dict:
    """Resolve o token no dispositivo e marca presença. Toda rota passa aqui."""
    if not token:
        raise HTTPException(status_code=401, detail="Header X-Device-Token ausente")

    r = sb().table("dispositivos").select("*").eq("token", token).execute()
    if not r.data:
        raise HTTPException(status_code=401, detail="Dispositivo não reconhecido")

    dispositivo = r.data[0]
    sb().table("dispositivos").update({
        "ultimo_contato": agora().isoformat(),
        "online": True,
    }).eq("id", dispositivo["id"]).execute()

    return dispositivo


def sessao_aguardando_cartao(carregador_id: str):
    """
    A sessão preparada na tela e parada esperando o cartão NESTE ponto.

    A busca é pelo CARREGADOR, não pelo usuário. É a inversão que o fluxo novo
    exige: o carregador está esperando uma pessoa específica, e o cartão
    aproximado tem que ser o dela. Buscar pelo usuário primeiro deixaria
    passar o caso de alguém preparar no ponto 01 e encostar o cartão no 02.
    """
    r = (
        sb().table("sessoes_recarga")
        .select("*")
        .eq("carregador_id", carregador_id)
        .eq("status", "aguardando_rfid")
        .order("criado_em", desc=True)
        .limit(1)
        .execute()
    )
    return r.data[0] if r.data else None


def sessao_ativa_do_carregador(carregador_id: str):
    r = (
        sb().table("sessoes_recarga")
        .select("*")
        .eq("carregador_id", carregador_id)
        .eq("status", "carregando")
        .order("iniciado_em", desc=True)
        .limit(1)
        .execute()
    )
    return r.data[0] if r.data else None


def enfileirar_comando(carregador_id: str, acao: str, sessao_id: str = None) -> Optional[dict]:
    """
    Coloca uma ordem na fila do dispositivo daquele carregador.

    Chamada pelo /charge/start e pelo /charge/stop do main.py. Se o carregador
    não tiver dispositivo cadastrado (ponto simulado), devolve None em silêncio
    - o fluxo simulado continua funcionando exatamente como antes.
    """
    d = sb().table("dispositivos").select("id").eq("carregador_id", carregador_id).execute()
    if not d.data:
        return None

    novo = sb().table("comandos_dispositivo").insert({
        "dispositivo_id": d.data[0]["id"],
        "sessao_id": sessao_id,
        "acao": acao,
        "status": "pendente",
    }).execute()

    print(f"[HARDWARE] comando '{acao}' enfileirado para o carregador {carregador_id}")
    return novo.data[0] if novo.data else None


def marcar_dispositivos_offline():
    """
    Varre dispositivos sem contato recente e derruba o ponto.

    Chamado pelo loop do simulador, que já roda a cada 10s - não vale abrir
    outra thread para isto. Um carregador físico sem dispositivo respondendo
    precisa aparecer como offline no painel: mostrar "disponível" e o morador
    chegar num ponto morto é pior que mostrar o problema.
    """
    limite = (agora() - timedelta(seconds=SEGUNDOS_ATE_OFFLINE)).isoformat()

    mortos = (
        sb().table("dispositivos")
        .select("id, carregador_id, nome, ultimo_contato")
        .eq("online", True)
        .lt("ultimo_contato", limite)
        .execute()
    )
    for d in (mortos.data or []):
        sb().table("dispositivos").update({"online": False}).eq("id", d["id"]).execute()
        sb().table("carregadores").update({"status": "offline"}).eq(
            "id", d["carregador_id"]
        ).execute()
        print(f"[HARDWARE] {d['nome']} sem contato - ponto marcado offline")


# ---------------------------------------------------------------------------
# 1. HANDSHAKE
# ---------------------------------------------------------------------------

@router.post("/handshake")
def handshake(payload: HandshakePayload, x_device_token: str = Header(None)):
    """
    Primeira chamada do ESP32 ao ligar. Ele descobre em que carregador está
    montado e com que ritmo deve reportar.

    Os intervalos vêm do banco de propósito: mudar o ritmo de telemetria vira
    um UPDATE, não uma regravação de firmware com o Gus do lado.
    """
    dispositivo = autenticar(x_device_token)

    sb().table("dispositivos").update({
        "mac": payload.mac,
        "ip": payload.ip,
        "firmware": payload.firmware,
    }).eq("id", dispositivo["id"]).execute()

    c = sb().table("carregadores").select("*").eq(
        "id", dispositivo["carregador_id"]
    ).execute().data[0]

    cond = sb().table("condominios").select("nome").eq(
        "id", c["condominio_id"]
    ).execute()

    # O ponto começa disponível assim que a placa se apresenta - a menos que
    # já exista recarga em andamento (ESP32 reiniciou no meio da sessão).
    sessao = sessao_ativa_do_carregador(c["id"])
    sb().table("carregadores").update({
        "status": "em_uso" if sessao else "disponivel"
    }).eq("id", c["id"]).execute()

    return {
        "ok": True,
        "dispositivo": {"id": dispositivo["id"], "nome": dispositivo["nome"]},
        "carregador": {
            "id": c["id"],
            "numero": c["numero"],
            "potencia_maxima_kw": c["potencia_maxima_kw"],
            "tensao_v": c.get("tensao_v"),
            "corrente_maxima_a": c.get("corrente_maxima_a"),
            "tarifa_kwh": c.get("tarifa_kwh"),
        },
        "condominio": (cond.data[0]["nome"] if cond.data else None),
        "intervalo_telemetria_s": dispositivo.get("intervalo_telemetria_s", 5),
        "intervalo_comandos_s": dispositivo.get("intervalo_comandos_s", 2),
        # Se a placa reiniciou no meio de uma recarga, ela precisa saber que o
        # relé tem que voltar a fechar - senão o carro fica parado com a
        # sessão "carregando" no banco.
        "sessao_ativa": bool(sessao),
        "rele_esperado": bool(sessao),
        "aguardando_cartao": bool(sessao_aguardando_cartao(c["id"])),
        "servidor_hora": agora().isoformat(),
    }


# ---------------------------------------------------------------------------
# 2. COMANDOS
# ---------------------------------------------------------------------------

@router.get("/comandos")
def buscar_comandos(x_device_token: str = Header(None)):
    """
    Polling do ESP32 a cada ~2s. Devolve o que estiver pendente e já marca
    como entregue.

    Marcar na entrega, e não na confirmação, evita mandar o mesmo comando
    duas vezes se o dispositivo demorar a responder. A confirmação vem depois,
    em rota própria - assim dá para distinguir "não chegou" de "chegou e o
    relé não fechou", que são problemas diferentes para o Gus depurar.
    """
    dispositivo = autenticar(x_device_token)

    r = (
        sb().table("comandos_dispositivo")
        .select("*")
        .eq("dispositivo_id", dispositivo["id"])
        .eq("status", "pendente")
        .order("criado_em")
        .limit(5)
        .execute()
    )

    comandos = []
    for c in (r.data or []):
        sb().table("comandos_dispositivo").update({
            "status": "entregue",
            "entregue_em": agora().isoformat(),
        }).eq("id", c["id"]).execute()
        comandos.append({"id": c["id"], "acao": c["acao"], "sessao_id": c.get("sessao_id")})

    return {"comandos": comandos}


@router.post("/comandos/{comando_id}/confirmar")
def confirmar_comando(comando_id: str, payload: ConfirmacaoPayload,
                      x_device_token: str = Header(None)):
    """O relé mudou de estado de verdade - ou não mudou, e queremos saber."""
    autenticar(x_device_token)

    sb().table("comandos_dispositivo").update({
        "status": "confirmado" if payload.sucesso else "falhou",
        "erro": payload.erro,
        "confirmado_em": agora().isoformat(),
    }).eq("id", comando_id).execute()

    if not payload.sucesso:
        print(f"[HARDWARE] comando {comando_id} FALHOU: {payload.erro}")

    return {"ok": True}


# ---------------------------------------------------------------------------
# 3. TELEMETRIA - o coração da coisa
# ---------------------------------------------------------------------------

@router.post("/telemetria")
def receber_telemetria(payload: TelemetriaPayload, x_device_token: str = Header(None)):
    """
    O ESP32 reporta o que o sensor está medindo. A partir daqui, a energia da
    sessão deixa de ser calculada e passa a ser MEDIDA.

    O modelo físico (potencia_no_soc, fator_termico) continua sendo usado -
    mas para ESTIMAR o tempo restante, não para inventar quanta energia
    passou. Quem sabe quanta energia passou é o medidor.

    Repare que `energia_entregue_kwh` continua sendo energia de tomada, então
    `custo_da_sessao()` funciona sem mudar uma linha: o sensor está no mesmo
    lugar onde o modelo media.
    """
    dispositivo = autenticar(x_device_token)
    carregador_id = dispositivo["carregador_id"]

    # Temperatura do ponto vem do sensor, não mais do simulador.
    if payload.temperatura_c is not None:
        sb().table("carregadores").update({
            "temperatura_c": round(float(payload.temperatura_c), 1)
        }).eq("id", carregador_id).execute()

    sessao = sessao_ativa_do_carregador(carregador_id)

    sb().table("leituras_hardware").insert({
        "dispositivo_id": dispositivo["id"],
        "sessao_id": sessao["id"] if sessao else None,
        "potencia_w": payload.potencia_w,
        "energia_wh": payload.energia_wh,
        "tensao_v": payload.tensao_v,
        "corrente_a": payload.corrente_a,
        "temperatura_c": payload.temperatura_c,
        "rele_ligado": payload.rele_ligado,
    }).execute()

    # Sem sessão ativa: o relé tem que estar aberto. Se o dispositivo diz que
    # está fechado, mandamos abrir - trava de segurança contra energia correndo
    # sem sessão registrada (ou seja, sem ninguém pagando).
    if not sessao:
        if payload.rele_ligado:
            print(f"[HARDWARE] relé fechado sem sessão no carregador "
                  f"{carregador_id} - mandando abrir")
        # `aguardando_cartao` deixa a placa sinalizar que alguém preparou a
        # recarga no app e o cartão é esperado agora. Sem isso, o morador
        # chega no ponto e não tem nenhum retorno físico de que é a vez dele.
        return {"ok": True, "sessao_ativa": False, "deve_liberar": False,
                "aguardando_cartao": bool(sessao_aguardando_cartao(carregador_id))}

    energia_kwh = _energia_monotonica(sessao, payload.energia_wh)
    update = {"energia_entregue_kwh": round(energia_kwh, 3)}

    if payload.potencia_w is not None:
        update["potencia_atual_kw"] = round(float(payload.potencia_w) / 1000.0, 2)

    soc = _soc_pela_energia(sessao, energia_kwh)
    if soc is not None:
        update["percentual_bateria_atual"] = round(soc, 1)
        update["tempo_estimado_min"] = _tempo_restante(sessao, carregador_id, soc)

    # Bateria cheia: encerra pelo mesmo caminho do simulador, para o custo e a
    # liberação da fila serem idênticos nos dois mundos.
    if soc is not None and soc >= 99.9:
        _encerrar(sessao, carregador_id, soc, update)
        return {"ok": True, "sessao_ativa": False, "deve_liberar": False,
                "motivo": "bateria_cheia"}

    sb().table("sessoes_recarga").update(update).eq("id", sessao["id"]).execute()

    # A resposta do POST já diz se o relé deve continuar fechado. Isso corta a
    # latência do "parar recarga": o dispositivo descobre no próximo pacote de
    # telemetria, sem esperar o poll de comandos.
    return {
        "ok": True,
        "sessao_ativa": True,
        "deve_liberar": True,
        "percentual": round(soc, 1) if soc is not None else None,
    }


def _energia_monotonica(sessao: dict, energia_wh) -> float:
    """
    Converte Wh acumulado do dispositivo em kWh da sessão, sem deixar andar
    para trás.

    Se o ESP32 reiniciar no meio da recarga, o contador dele volta a zero. Sem
    esta trava, a energia da sessão despencaria e o custo cairia junto - o
    morador ganharia recarga de graça por causa de um reset. Na dúvida,
    preserva o maior valor já visto.
    """
    atual = float(sessao.get("energia_entregue_kwh") or 0)
    if energia_wh is None:
        return atual
    reportada = float(energia_wh) / 1000.0
    if reportada < atual:
        print(f"[HARDWARE] energia reportada ({reportada:.3f} kWh) menor que a "
              f"registrada ({atual:.3f} kWh) - provável reset do dispositivo")
        return atual
    return reportada


def _soc_pela_energia(sessao: dict, energia_kwh: float):
    """
    SoC derivado da energia medida - não de um contador que anda sozinho.

    A conta é a inversa da do simulador: energia de tomada vezes eficiência é
    a energia que entrou na bateria; dividida pela capacidade, dá quanto por
    cento subiu desde o início.
    """
    v = sb().table("veiculos").select("capacidade_bateria_kwh").eq(
        "id", sessao["veiculo_id"]
    ).execute()
    if not v.data:
        return None

    capacidade = float(v.data[0].get("capacidade_bateria_kwh") or 0)
    if capacidade <= 0:
        return None

    inicial = float(sessao.get("percentual_bateria_inicial") or 0)
    ganho = (energia_kwh * _CTX["eficiencia"] / capacidade) * 100.0
    return min(100.0, inicial + ganho)


def _tempo_restante(sessao: dict, carregador_id: str, soc: float):
    v = sb().table("veiculos").select(
        "capacidade_bateria_kwh, potencia_carro_kw"
    ).eq("id", sessao["veiculo_id"]).execute()
    c = sb().table("carregadores").select("potencia_maxima_kw").eq(
        "id", carregador_id
    ).execute()
    if not v.data or not c.data:
        return sessao.get("tempo_estimado_min")

    teto = min(
        float(c.data[0]["potencia_maxima_kw"]),
        float(v.data[0].get("potencia_carro_kw") or c.data[0]["potencia_maxima_kw"]),
    )
    return _CTX["tempo_de_carga_min"](
        float(v.data[0]["capacidade_bateria_kwh"]), soc, 100.0, teto
    )


def _encerrar(sessao: dict, carregador_id: str, soc: float, update: dict):
    update["status"] = "finalizada"
    update["finalizado_em"] = agora().isoformat()
    update["percentual_bateria_atual"] = round(soc, 1)

    sessao_final = {**sessao, **update}
    update["custo_final"] = _CTX["custo_da_sessao"](sessao_final)

    sb().table("sessoes_recarga").update(update).eq("id", sessao["id"]).execute()
    sb().table("veiculos").update({"percentual_bateria": round(soc, 1)}).eq(
        "id", sessao["veiculo_id"]
    ).execute()
    sb().table("carregadores").update({"status": "disponivel"}).eq(
        "id", carregador_id
    ).execute()

    enfileirar_comando(carregador_id, "bloquear", sessao["id"])
    _CTX["avisar_fila"](carregador_id)
    print(f"[HARDWARE] sessão {sessao['id']} finalizada por bateria cheia")


# ---------------------------------------------------------------------------
# 4. RFID - o que a serial fazia, agora por HTTP
# ---------------------------------------------------------------------------

@router.post("/rfid")
def leitura_rfid(payload: RfidPayload, x_device_token: str = Header(None)):
    """
    Cartão aproximado do leitor - o gatilho que efetivamente inicia a recarga.

    A ordem das checagens importa e é o coração do fluxo novo:

      1. Este carregador está esperando alguém?  Se não, não há o que iniciar.
      2. O cartão é de quem preparou?            Identidade tem que bater.
      3. O saldo cobre a estimativa?             Decidido AGORA, não antes.

    Repare no que NÃO acontece aqui: a sessão não é apagada e recriada. Ela é
    promovida no lugar por `confirmar_sessao_preparada()`, preservando o id.
    O navegador do morador está inscrito nesse id pelo Realtime desde que a
    tela mostrou "aproxime seu cartão" - trocar o id deixaria ele escutando
    uma linha que não muda mais.

    E quando o saldo não cobre, a recusa é gravada na sessão antes de voltar
    para a placa. A resposta HTTP vai para o ESP32; o morador está olhando o
    celular. O canal de retorno para ele é o banco.
    """
    dispositivo = autenticar(x_device_token)
    uid = (payload.uid or "").strip()
    carregador_id = dispositivo["carregador_id"]

    sessao = sessao_aguardando_cartao(carregador_id)
    if not sessao:
        return {"autorizado": False, "motivo": "sem_recarga_preparada",
                "mensagem": "Nenhuma recarga preparada aqui. Use o aplicativo primeiro."}

    u = sb().table("usuarios").select("*").eq("rfid_uid", uid).execute()
    if not u.data:
        return {"autorizado": False, "motivo": "cartao_nao_vinculado",
                "mensagem": "Cartão não reconhecido."}
    usuario = u.data[0]

    if usuario["id"] != sessao["usuario_id"]:
        # Cartão válido, mas de outra pessoa. A sessão preparada continua
        # esperando o dono - não cancelamos por causa de um cartão errado.
        dono = sb().table("usuarios").select("nome").eq(
            "id", sessao["usuario_id"]
        ).execute()
        nome_dono = (dono.data[0]["nome"].split()[0] if dono.data else "outro morador")
        return {"autorizado": False, "motivo": "cartao_de_outro_usuario",
                "mensagem": f"Este ponto está aguardando o cartão de {nome_dono}."}

    try:
        resultado = _CTX["confirmar_preparada"](sessao, metodo="rfid_hardware")
    except HTTPException as e:
        # A recusa já foi gravada na sessão lá dentro. Aqui só devolvemos para
        # a placa poder sinalizar (LED, buzzer).
        print(f"[HARDWARE] cartão recusado para {usuario['nome']}: {e.detail}")
        return {"autorizado": False, "motivo": "saldo_insuficiente",
                "mensagem": "Saldo insuficiente para esta recarga."}

    print(f"[HARDWARE] recarga autorizada por cartão para {usuario['nome']}")
    return {
        "autorizado": True,
        "mensagem": f"Bem-vindo, {usuario['nome'].split()[0]}!",
        "sessao_id": sessao["id"],
        "usuario": usuario["nome"],
    }


# ---------------------------------------------------------------------------
# 5. Diagnóstico - para o Gus testar sem carro
# ---------------------------------------------------------------------------

@router.get("/status/{carregador_id}")
def status_dispositivo(carregador_id: str):
    """Estado do dispositivo daquele ponto. Útil no /docs durante a montagem."""
    d = sb().table("dispositivos").select("*").eq(
        "carregador_id", carregador_id
    ).execute()
    if not d.data:
        raise HTTPException(status_code=404,
                            detail="Nenhum dispositivo cadastrado neste carregador")

    dispositivo = d.data[0]
    ultimas = (
        sb().table("leituras_hardware")
        .select("potencia_w, energia_wh, temperatura_c, rele_ligado, criado_em")
        .eq("dispositivo_id", dispositivo["id"])
        .order("criado_em", desc=True)
        .limit(10)
        .execute()
    )
    pendentes = (
        sb().table("comandos_dispositivo")
        .select("id, acao, status, criado_em")
        .eq("dispositivo_id", dispositivo["id"])
        .neq("status", "confirmado")
        .order("criado_em", desc=True)
        .limit(10)
        .execute()
    )

    return {
        "dispositivo": {k: dispositivo[k] for k in
                        ("id", "nome", "online", "ultimo_contato", "ip", "firmware")},
        "ultimas_leituras": ultimas.data,
        "comandos_abertos": pendentes.data,
    }


@router.post("/ping/{carregador_id}")
def ping(carregador_id: str):
    """Enfileira um 'ping'. Se o LED da placa piscar, a ponta inteira funciona."""
    c = enfileirar_comando(carregador_id, "ping")
    if not c:
        raise HTTPException(status_code=404,
                            detail="Nenhum dispositivo cadastrado neste carregador")
    return {"ok": True, "comando_id": c["id"]}
