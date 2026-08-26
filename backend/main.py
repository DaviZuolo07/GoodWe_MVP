"""
GoodWe ChargeOps AI Assistant - Backend MVP (conectado ao Supabase)
--------------------------------------------------------------------
Este backend NÃO guarda dados em memória. Tudo é lido e gravado
direto no Supabase (Postgres). O frontend também pode ler o Supabase
diretamente (realtime) - este backend cuida das AÇÕES:
  - cadastro / login simulado
  - iniciar / parar recarga
  - chatbot
  - simulador (faz energia/bateria/tempo andarem sozinhos)

Rodar localmente:
    pip install -r requirements.txt
    criar um arquivo .env (ver .env.example) com SUPABASE_URL e SUPABASE_KEY
    uvicorn main:app --reload

Documentação automática: http://localhost:8000/docs
"""

import os
import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from supabase import create_client, Client

from hardware_serial import iniciar_escuta_serial, _processar_leitura_rfid
from chatbot import configurar_chatbot, responder_chatbot
from hardware_api import (router as hardware_router, configurar_hardware,
                          enfileirar_comando, marcar_dispositivos_offline)

# ---------------------------------------------------------------------------
# CONEXÃO COM O SUPABASE
# ---------------------------------------------------------------------------

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_URL e SUPABASE_KEY precisam estar definidos no arquivo .env "
        "(veja .env.example)"
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="GoodWe ChargeOps AI Assistant - API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # em produção, restringir ao domínio do frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Condomínio usado quando o cliente não informa nenhum. Continua existindo
# para não quebrar chamadas antigas, mas nada mais assume que ele é o único.
CONDOMINIO_PADRAO = "11111111-1111-1111-1111-111111111111"
CONDOMINIO_ID = CONDOMINIO_PADRAO  # alias legado


# ---------------------------------------------------------------------------
# FÍSICA DA RECARGA
# ---------------------------------------------------------------------------
# Um carro não carrega em linha reta. Até ~80% ele aceita a potência cheia
# (fase de corrente constante); daí para cima a corrente cai progressivamente
# para proteger a bateria (fase de tensão constante). Além disso, parte da
# energia que sai da tomada vira calor no carregador de bordo e no cabo.
#
# Sem modelar isso, o tempo estimado mente: dá curto demais no fim da carga.

EFICIENCIA_CARGA = 0.92   # energia que chega na bateria / energia da tomada
SOC_JOELHO = 80.0         # onde começa o tapering (%)
TARIFA_PADRAO_KWH = 2.10  # só entra se o carregador não tiver tarifa cadastrada
FATOR_FINAL = 0.20        # fração da potência ao encostar em 100%


def fator_termico(temperatura_c: float) -> float:
    """Derating térmico: acima de 35 °C o carregador reduz a potência."""
    if temperatura_c is None or temperatura_c <= 35:
        return 1.0
    return max(0.7, 1 - (temperatura_c - 35) * 0.02)


def potencia_no_soc(potencia_max_kw: float, soc: float) -> float:
    """Potência realmente aceita pela bateria num dado estado de carga."""
    if soc <= SOC_JOELHO:
        return potencia_max_kw
    if soc >= 100:
        return potencia_max_kw * FATOR_FINAL
    proporcao = (soc - SOC_JOELHO) / (100 - SOC_JOELHO)
    return potencia_max_kw * (1 - proporcao * (1 - FATOR_FINAL))


def tempo_de_carga_min(capacidade_kwh: float, soc_ini: float, soc_fim: float,
                       potencia_max_kw: float) -> int:
    """
    Integra a curva de carga em passos de 1% de SoC. É o mesmo que somar
    dt = dE / P(SoC) ao longo do trecho - só que sem cálculo simbólico,
    o que mantém o código legível e o resultado estável.
    """
    if potencia_max_kw <= 0 or soc_fim <= soc_ini or capacidade_kwh <= 0:
        return 0

    energia_por_ponto = capacidade_kwh / 100.0
    horas = 0.0
    soc = float(soc_ini)

    while soc < soc_fim:
        passo = min(1.0, soc_fim - soc)
        # potência no meio do passo: aproximação do ponto médio
        p = potencia_no_soc(potencia_max_kw, soc + passo / 2)
        horas += (energia_por_ponto * passo) / (p * EFICIENCIA_CARGA)
        soc += passo

    return int(round(horas * 60))


# ---------------------------------------------------------------------------
# MODELOS (payloads recebidos do frontend)
# ---------------------------------------------------------------------------

class CadastroRequest(BaseModel):
    nome: str
    condominio_id: Optional[str] = None    # se vier vazio, cai no padrão
    tipo_usuario: str = "morador"          # "morador" | "visitante"
    bloco_apto: Optional[str] = None
    veiculo_modelo: str
    veiculo_placa: Optional[str] = None
    capacidade_bateria_kwh: float = 40
    potencia_carro_kw: float = 7.4
    rfid_uid: Optional[str] = None         # opcional - pode ser vinculado depois


class LoginRequest(BaseModel):
    nome: str
    senha: Optional[str] = None            # NÃO é validado - login simulado p/ MVP local


class StartChargeRequest(BaseModel):
    charger_id: str
    usuario_id: str
    veiculo_id: str
    percentual_bateria_atual: float  # informado na hora do pagamento RFID, não no cadastro


class StopChargeRequest(BaseModel):
    sessao_id: str


class RecarregarSaldoRequest(BaseModel):
    valor: float


class VeiculoRequest(BaseModel):
    usuario_id: str
    modelo: str
    placa: Optional[str] = None
    capacidade_bateria_kwh: float = 40
    potencia_carro_kw: float = 7.4


class ChatRequest(BaseModel):
    message: str
    usuario_id: Optional[str] = None
    charger_id: Optional[str] = None
    # Local que o usuário escolheu no seletor do chat. Campo OPCIONAL: se vier
    # nulo, o backend usa o condomínio de moradia, como sempre fez. O valor é
    # validado contra os favoritos - o frontend não decide escopo sozinho.
    condominio_id: Optional[str] = None


class FavoritoRequest(BaseModel):
    condominio_id: str


class VincularRfidRequest(BaseModel):
    rfid_uid: str


class PrepararRfidRequest(BaseModel):
    charger_id: str
    usuario_id: str
    veiculo_id: str
    percentual_bateria_atual: float
    # Até onde carregar. Sempre existiu em calcular_estimativa(), mas ninguém
    # passava - toda estimativa ia até 100%. Agora o morador define na tela.
    alvo_percentual: float = 100.0


class CancelarRfidRequest(BaseModel):
    sessao_id: str
    usuario_id: str


# ---------------------------------------------------------------------------
# 1. CADASTRO (primeiro acesso)
# ---------------------------------------------------------------------------

@app.post("/cadastro")
def cadastro(payload: CadastroRequest):
    """Cria o usuário + veículo no Supabase. É o 'primeiro login'."""

    # Impede nomes duplicados - senão o /login (que busca por nome) poderia
    # devolver o usuário errado para quem digitou um nome já existente.
    nome_normalizado = payload.nome.strip()
    existente = (
        supabase.table("usuarios")
        .select("id")
        .ilike("nome", nome_normalizado)
        .execute()
    )
    if existente.data:
        raise HTTPException(
            status_code=409,
            detail="Esse nome de usuário já está cadastrado. Escolha outro nome.",
        )

    if payload.rfid_uid:
        rfid_existente = (
            supabase.table("usuarios").select("id").eq("rfid_uid", payload.rfid_uid).execute()
        )
        if rfid_existente.data:
            raise HTTPException(
                status_code=409,
                detail="Esse cartão RFID já está vinculado a outro usuário.",
            )

    usuario = supabase.table("usuarios").insert({
        "nome": nome_normalizado,
        "tipo_usuario": payload.tipo_usuario,
        "condominio_id": payload.condominio_id or CONDOMINIO_PADRAO,
        "bloco_apto": payload.bloco_apto,
        "rfid_uid": payload.rfid_uid,
    }).execute()

    usuario_id = usuario.data[0]["id"]

    veiculo = supabase.table("veiculos").insert({
        "usuario_id": usuario_id,
        "modelo": payload.veiculo_modelo,
        "placa": payload.veiculo_placa,
        "capacidade_bateria_kwh": payload.capacidade_bateria_kwh,
        "potencia_carro_kw": payload.potencia_carro_kw,
        # percentual_bateria NÃO é enviado aqui de propósito: é desconhecido
        # até o usuário informar na hora do pagamento (ver /charge/start).
        # A coluna no banco aceita NULL (ver 04_fix_percentual_bateria.sql).
    }).execute()

    return {
        "success": True,
        "usuario": usuario.data[0],
        "veiculo": veiculo.data[0],
    }


# ---------------------------------------------------------------------------
# 2. LOGIN SIMULADO (aceita qualquer senha - só pro MVP local)
# ---------------------------------------------------------------------------

@app.post("/login")
def login(payload: LoginRequest):
    """
    Login simulado: procura um usuário pelo nome. A senha não é checada.
    Se não achar ninguém com esse nome, retorna erro pedindo pra cadastrar.
    """
    result = supabase.table("usuarios").select("*").eq("nome", payload.nome).execute()

    if not result.data:
        raise HTTPException(
            status_code=404,
            detail="Usuário não encontrado. Faça o cadastro primeiro.",
        )

    usuario = result.data[0]

    veiculo_result = (
        supabase.table("veiculos").select("*").eq("usuario_id", usuario["id"]).execute()
    )
    veiculo = veiculo_result.data[0] if veiculo_result.data else None

    return {"success": True, "usuario": usuario, "veiculo": veiculo}


@app.post("/usuarios/{usuario_id}/vincular-rfid")
def vincular_rfid(usuario_id: str, payload: VincularRfidRequest):
    """Associa um cartão RFID físico a um usuário já cadastrado."""
    existente = (
        supabase.table("usuarios").select("id").eq("rfid_uid", payload.rfid_uid).execute()
    )
    if existente.data and existente.data[0]["id"] != usuario_id:
        raise HTTPException(status_code=409, detail="Esse cartão já está vinculado a outro usuário.")

    supabase.table("usuarios").update({"rfid_uid": payload.rfid_uid}).eq("id", usuario_id).execute()
    return {"success": True, "rfid_uid": payload.rfid_uid}


# ---------------------------------------------------------------------------
# 3. DASHBOARD (o frontend pode ler direto do Supabase, mas isso aqui
#    serve pra testar rápido pelo /docs sem precisar do frontend pronto)
# ---------------------------------------------------------------------------

@app.get("/condominios")
def listar_condominios():
    """Todos os locais atendidos. Alimenta o seletor do login e do topo."""
    result = supabase.table("condominios").select("*").order("nome").execute()
    return result.data


# --- Locais favoritos ------------------------------------------------------
# O assistente responde sobre UM local por vez. Estes três endpoints alimentam
# o seletor do chat e definem, ao mesmo tempo, a allowlist de escopo: o bot só
# aceita responder sobre um local que esteja nesta lista.

def _locais_do_usuario(usuario_id: str) -> dict:
    """Favoritos + condomínio de moradia. Usado pelo endpoint e pelo chatbot."""
    u = (
        supabase.table("usuarios")
        .select("condominio_id")
        .eq("id", usuario_id)
        .execute()
    )
    if not u.data:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    padrao_id = u.data[0].get("condominio_id")

    favs = (
        supabase.table("condominios_favoritos")
        .select("condominio_id")
        .eq("usuario_id", usuario_id)
        .execute()
    )
    ids = {f["condominio_id"] for f in (favs.data or [])}

    # O condomínio de moradia é favorito implícito: a pessoa nunca fica sem
    # nenhum local para escolher, mesmo que apague todos os favoritos.
    if padrao_id:
        ids.add(padrao_id)

    todos = supabase.table("condominios").select("*").order("nome").execute().data or []
    favoritos = [c for c in todos if c["id"] in ids]

    return {"padrao_id": padrao_id, "favoritos": favoritos, "todos": todos}


@app.get("/usuarios/{usuario_id}/locais")
def listar_locais(usuario_id: str):
    """
    Tudo que o seletor do chat precisa, numa chamada só:
    os favoritos (que ele mostra), todos os locais (para adicionar) e qual é
    o condomínio de moradia (que não pode ser desfavoritado).
    """
    return _locais_do_usuario(usuario_id)


@app.post("/usuarios/{usuario_id}/favoritos")
def favoritar_local(usuario_id: str, payload: FavoritoRequest):
    """Idempotente: favoritar de novo não duplica nem dá erro."""
    existe = (
        supabase.table("condominios")
        .select("id")
        .eq("id", payload.condominio_id)
        .execute()
    )
    if not existe.data:
        raise HTTPException(status_code=404, detail="Condomínio não encontrado")

    ja = (
        supabase.table("condominios_favoritos")
        .select("id")
        .eq("usuario_id", usuario_id)
        .eq("condominio_id", payload.condominio_id)
        .execute()
    )
    if not ja.data:
        supabase.table("condominios_favoritos").insert({
            "usuario_id": usuario_id,
            "condominio_id": payload.condominio_id,
        }).execute()

    return _locais_do_usuario(usuario_id)


@app.delete("/usuarios/{usuario_id}/favoritos/{condominio_id}")
def desfavoritar_local(usuario_id: str, condominio_id: str):
    """
    Remove o favorito - menos o condomínio de moradia.

    Se deixássemos remover, o usuário conseguiria zerar a própria allowlist e
    o chat ficaria sem nenhum local para responder.
    """
    u = supabase.table("usuarios").select("condominio_id").eq("id", usuario_id).execute()
    if u.data and u.data[0].get("condominio_id") == condominio_id:
        raise HTTPException(
            status_code=400,
            detail="O condomínio onde você mora não pode ser removido dos favoritos.",
        )

    (
        supabase.table("condominios_favoritos")
        .delete()
        .eq("usuario_id", usuario_id)
        .eq("condominio_id", condominio_id)
        .execute()
    )
    return _locais_do_usuario(usuario_id)


@app.get("/chargers")
def list_chargers(condominio_id: Optional[str] = None):
    result = (
        supabase.table("carregadores")
        .select("*")
        .eq("condominio_id", condominio_id or CONDOMINIO_PADRAO)
        .order("numero")
        .execute()
    )
    return result.data


# ---------------------------------------------------------------------------
# CÁLCULO DE ESTIMATIVA (compartilhado entre o fluxo simulado e o RFID real)
# ---------------------------------------------------------------------------

def calcular_estimativa(charger: dict, veiculo: dict, percentual_atual: float, alvo: float = 100.0) -> dict:
    """
    Estimativa de energia, tempo e custo para levar o veículo de
    `percentual_atual` até `alvo`.

    Três coisas entram na conta, e todas mudam o resultado:
      1. Derating térmico  - carregador quente entrega menos potência.
      2. Curva de carga    - acima de 80% a bateria aceita cada vez menos.
      3. Eficiência        - parte da energia da tomada vira calor.

    O custo é cobrado sobre a energia que sai da tomada (energia_rede), não
    sobre a que entra na bateria. É assim que a conta de luz funciona.
    """
    temperatura_c = charger.get("temperatura_c", 25) or 25
    ft = fator_termico(temperatura_c)

    potencia_nominal_kw = min(charger["potencia_maxima_kw"], veiculo["potencia_carro_kw"])
    potencia_efetiva_kw = round(potencia_nominal_kw * ft, 2)

    capacidade = veiculo["capacidade_bateria_kwh"]
    soc = max(0.0, min(100.0, float(percentual_atual)))

    energia_bateria_kwh = capacidade * (alvo - soc) / 100.0
    energia_rede_kwh = round(energia_bateria_kwh / EFICIENCIA_CARGA, 3)

    tempo_estimado_min = tempo_de_carga_min(capacidade, soc, alvo, potencia_efetiva_kw)
    custo_estimado = round(energia_rede_kwh * charger["tarifa_kwh"], 2)

    # Potência instantânea neste exato SoC - é o número que o card mostra.
    potencia_agora_kw = round(potencia_no_soc(potencia_efetiva_kw, soc), 2)

    return {
        "potencia_efetiva_kw": potencia_efetiva_kw,
        "potencia_agora_kw": potencia_agora_kw,
        "energia_necessaria_kwh": energia_rede_kwh,
        "energia_bateria_kwh": round(energia_bateria_kwh, 3),
        "tempo_estimado_min": tempo_estimado_min,
        "custo_estimado": custo_estimado,
        "fator_termico": round(ft, 3),
        "temperatura_c": temperatura_c,
        "eficiencia": EFICIENCIA_CARGA,
    }


def custo_da_sessao(sessao: dict) -> float:
    """
    Custo real de uma sessão, sempre pela tarifa do carregador daquele
    condomínio - nunca por um valor fixo no código.

    `energia_entregue_kwh` já é energia de tomada (o simulador acumula
    energia_rede, não energia_bateria), então ela entra direto na conta. Não
    dividir de novo por EFICIENCIA_CARGA aqui, senão a perda é cobrada duas
    vezes.
    """
    energia_rede_kwh = float(sessao.get("energia_entregue_kwh") or 0)

    tarifa = TARIFA_PADRAO_KWH
    charger = (
        supabase.table("carregadores")
        .select("tarifa_kwh")
        .eq("id", sessao["carregador_id"])
        .execute()
    )
    if charger.data and charger.data[0].get("tarifa_kwh") is not None:
        tarifa = float(charger.data[0]["tarifa_kwh"])

    return round(energia_rede_kwh * tarifa, 2)


# ---------------------------------------------------------------------------
# 4. FLUXO DE RECARGA
# ---------------------------------------------------------------------------

def estimar_e_validar_saldo(charger: dict, veiculo: dict, usuario: dict,
                            percentual_atual: float, alvo: float = 100.0) -> dict:
    """
    Calcula a estimativa e confere se o saldo cobre o custo.

    Extraída porque agora a mesma checagem roda em TRÊS momentos diferentes do
    fluxo do cartão: ao preparar na tela (para recusar cedo, antes do morador
    caminhar até o carregador), ao aproximar o cartão (o saldo pode ter mudado
    no meio do caminho) e no fluxo direto pelo app. Três cópias da mesma regra
    seriam três lugares para ela divergir.

    Levanta HTTPException 402 se o saldo não cobrir.
    """
    estimativa = calcular_estimativa(charger, veiculo, percentual_atual, alvo)
    custo_estimado = estimativa["custo_estimado"]

    if usuario["saldo"] < custo_estimado:
        raise HTTPException(
            status_code=402,
            detail=f"Saldo insuficiente. Saldo atual: R$ {usuario['saldo']:.2f}, "
                   f"custo estimado: R$ {custo_estimado:.2f}.",
        )

    return estimativa


def autorizar_e_iniciar_sessao(charger: dict, veiculo: dict, usuario: dict,
                               percentual_atual: float, metodo: str, origem: str,
                               alvo: float = 100.0) -> dict:
    """
    Função central de autorização do fluxo DIRETO (app): valida saldo, deduz,
    cria a sessão e registra o pagamento.

    O fluxo do cartão RFID não passa por aqui - ele usa
    `confirmar_sessao_preparada()`, porque lá a linha da sessão já existe
    desde o "aguardando cartão" e precisa ser promovida no lugar, não
    recriada. Recriar geraria um id novo, e o navegador está escutando o id
    antigo pelo Realtime.
    """
    estimativa = estimar_e_validar_saldo(charger, veiculo, usuario, percentual_atual, alvo)

    custo_estimado = estimativa["custo_estimado"]
    novo_saldo = round(usuario["saldo"] - custo_estimado, 2)
    supabase.table("usuarios").update({"saldo": novo_saldo}).eq("id", usuario["id"]).execute()

    sessao = supabase.table("sessoes_recarga").insert({
        "carregador_id": charger["id"],
        "veiculo_id": veiculo["id"],
        "usuario_id": usuario["id"],
        "status": "carregando",
        "potencia_atual_kw": estimativa["potencia_agora_kw"],
        "energia_entregue_kwh": 0,
        "percentual_bateria_inicial": percentual_atual,
        "percentual_bateria_atual": percentual_atual,
        "alvo_percentual": alvo,
        "tempo_estimado_min": estimativa["tempo_estimado_min"],
        "custo_estimado": custo_estimado,
        "origem": origem,
        "iniciado_em": datetime.utcnow().isoformat(),
    }).execute()

    supabase.table("pagamentos").insert({
        "sessao_id": sessao.data[0]["id"],
        "valor": custo_estimado,
        "metodo": metodo,
        "status": "aprovado",
    }).execute()

    supabase.table("veiculos").update({"percentual_bateria": percentual_atual}).eq("id", veiculo["id"]).execute()
    supabase.table("carregadores").update({"status": "em_uso"}).eq("id", charger["id"]).execute()

    # Ponto físico: manda o ESP32 fechar o relé. É AQUI que a energia começa a
    # correr de verdade. Em ponto simulado a função devolve None e nada muda.
    enfileirar_comando(charger["id"], "liberar", sessao.data[0]["id"])

    return {"sessao": sessao.data[0], "saldo_atual": novo_saldo}


def confirmar_sessao_preparada(sessao: dict, metodo: str = "rfid_hardware") -> dict:
    """
    Promove uma sessão `aguardando_rfid` para `carregando` - ou a recusa.

    Chamada pelo ESP32 quando o cartão é aproximado. A linha NÃO é recriada:
    ela é atualizada no lugar, preservando o id. Isso é essencial porque o
    navegador do morador está inscrito no Realtime justamente desse id desde
    que a tela mostrou "aproxime seu cartão". Recriar a linha significaria o
    navegador nunca receber a notícia.

    Em caso de saldo insuficiente, a recusa é GRAVADA na sessão
    (status=recusada + motivo_recusa) antes de propagar o erro. O morador está
    olhando o celular, não a resposta HTTP que vai para a placa - então o
    canal de retorno tem que ser o banco.
    """
    charger = supabase.table("carregadores").select("*").eq(
        "id", sessao["carregador_id"]
    ).execute().data[0]
    veiculo = supabase.table("veiculos").select("*").eq(
        "id", sessao["veiculo_id"]
    ).execute().data[0]
    usuario = supabase.table("usuarios").select("*").eq(
        "id", sessao["usuario_id"]
    ).execute().data[0]

    percentual = float(sessao.get("percentual_bateria_inicial") or 0)
    alvo = float(sessao.get("alvo_percentual") or 100)

    try:
        estimativa = estimar_e_validar_saldo(charger, veiculo, usuario, percentual, alvo)
    except HTTPException as e:
        supabase.table("sessoes_recarga").update({
            "status": "recusada",
            "motivo_recusa": e.detail,
            "finalizado_em": datetime.utcnow().isoformat(),
        }).eq("id", sessao["id"]).execute()
        raise

    custo_estimado = estimativa["custo_estimado"]
    novo_saldo = round(usuario["saldo"] - custo_estimado, 2)
    supabase.table("usuarios").update({"saldo": novo_saldo}).eq("id", usuario["id"]).execute()

    atualizada = supabase.table("sessoes_recarga").update({
        "status": "carregando",
        "potencia_atual_kw": estimativa["potencia_agora_kw"],
        "energia_entregue_kwh": 0,
        "tempo_estimado_min": estimativa["tempo_estimado_min"],
        "custo_estimado": custo_estimado,
        "expira_em": None,
        "iniciado_em": datetime.utcnow().isoformat(),
    }).eq("id", sessao["id"]).execute()

    supabase.table("pagamentos").insert({
        "sessao_id": sessao["id"],
        "valor": custo_estimado,
        "metodo": metodo,
        "status": "aprovado",
    }).execute()

    supabase.table("veiculos").update({"percentual_bateria": percentual}).eq(
        "id", veiculo["id"]
    ).execute()
    supabase.table("carregadores").update({"status": "em_uso"}).eq(
        "id", charger["id"]
    ).execute()

    enfileirar_comando(charger["id"], "liberar", sessao["id"])

    return {
        "sessao": atualizada.data[0] if atualizada.data else sessao,
        "saldo_atual": novo_saldo,
        "usuario": usuario,
    }


def checar_concorrencia(veiculo_id: str):
    """Levanta erro se o veículo já tiver uma sessão ativa em outro carregador."""
    sessao_ativa = (
        supabase.table("sessoes_recarga")
        .select("id")
        .eq("veiculo_id", veiculo_id)
        # aguardando_rfid entra junto: um veículo com recarga preparada em um
        # ponto não pode ser preparado em outro. Sem isso, o morador prepara
        # em dois carregadores, aproxima o cartão num, e a sessão órfã do
        # outro segura o ponto até expirar.
        .in_("status", ["carregando", "aguardando_rfid"])
        .execute()
    )
    if sessao_ativa.data:
        raise HTTPException(
            status_code=400,
            detail="Esse veículo já está carregando em outro carregador. Encerre a recarga atual primeiro.",
        )


@app.post("/charge/start")
def start_charge(payload: StartChargeRequest):
    charger = supabase.table("carregadores").select("*").eq("id", payload.charger_id).execute()
    if not charger.data:
        raise HTTPException(status_code=404, detail="Carregador não encontrado")
    charger = charger.data[0]

    if charger["status"] == "em_uso":
        raise HTTPException(status_code=400, detail="Carregador já está em uso")

    # Ponto físico offline: o comando "liberar" ficaria pendente para sempre,
    # porque não existe ESP32 buscando comandos. O saldo seria debitado, a tela
    # diria "carregando" e o carro ficaria parado. Falha silenciosa é a pior
    # espécie - recusa explicitamente.
    if charger.get("origem") == "hardware" and charger["status"] == "offline":
        raise HTTPException(
            status_code=503,
            detail="Este carregador está offline no momento. Tente outro ponto.",
        )

    veiculo = supabase.table("veiculos").select("*").eq("id", payload.veiculo_id).execute()
    if not veiculo.data:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    veiculo = veiculo.data[0]

    checar_concorrencia(payload.veiculo_id)

    usuario = supabase.table("usuarios").select("*").eq("id", payload.usuario_id).execute()
    if not usuario.data:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    usuario = usuario.data[0]

    resultado = autorizar_e_iniciar_sessao(
        charger, veiculo, usuario, payload.percentual_bateria_atual,
        metodo="rfid_simulado", origem="simulado",
    )
    return {"success": True, **resultado}


# Prazo para aproximar o cartão. Curto o bastante para o ponto não ficar
# travado se alguém desistir, longo o bastante para caminhar até o carregador.
SEGUNDOS_ESPERA_CARTAO = 120


@app.post("/charge/preparar-rfid")
def preparar_rfid(payload: PrepararRfidRequest):
    """
    Passo 1 do fluxo com cartão físico.

    O morador escolheu o carregador, informou a bateria atual e o alvo, e
    confirmou na tela. Isto NÃO inicia a recarga: cria uma sessão parada em
    `aguardando_rfid` e devolve o id dela, para o navegador ficar escutando
    essa linha no Realtime enquanto mostra "aproxime seu cartão".

    Quem inicia de fato é a aproximação do cartão no ESP32
    (POST /hardware/rfid -> confirmar_sessao_preparada).

    O saldo é conferido AQUI TAMBÉM, mesmo sabendo que será conferido de novo
    no cartão. Recusar cedo evita que a pessoa caminhe até o carregador para
    descobrir lá que não dava. A checagem no cartão continua sendo a que vale
    - o saldo pode mudar no meio do caminho.
    """
    charger = supabase.table("carregadores").select("*").eq("id", payload.charger_id).execute()
    if not charger.data:
        raise HTTPException(status_code=404, detail="Carregador não encontrado")
    charger = charger.data[0]

    if charger["status"] == "em_uso":
        raise HTTPException(status_code=400, detail="Carregador já está em uso")

    # Ponto físico offline = ESP32 desligado ou sem rede. Não adianta preparar:
    # o cartão seria lido por uma placa que não está conversando com o backend,
    # ou nem seria lido. Melhor recusar agora com uma mensagem clara do que
    # deixar o morador esperando por um evento que não vem.
    if charger.get("origem") == "hardware" and charger["status"] == "offline":
        raise HTTPException(
            status_code=503,
            detail="O leitor deste carregador está offline. Tente outro ponto.",
        )

    # Uma preparação por carregador. Sem isto, dois moradores ficam esperando
    # no mesmo ponto e o cartão do primeiro a chegar decide - com o segundo
    # sem entender por que a tela dele não mudou.
    ja_aguardando = (
        supabase.table("sessoes_recarga")
        .select("id, usuario_id")
        .eq("carregador_id", payload.charger_id)
        .eq("status", "aguardando_rfid")
        .execute()
    )
    if ja_aguardando.data:
        if ja_aguardando.data[0]["usuario_id"] == payload.usuario_id:
            raise HTTPException(
                status_code=409,
                detail="Você já tem uma recarga aguardando cartão neste carregador.",
            )
        raise HTTPException(
            status_code=409,
            detail="Outro morador já está aguardando o cartão neste carregador.",
        )

    veiculo = supabase.table("veiculos").select("*").eq("id", payload.veiculo_id).execute()
    if not veiculo.data:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    veiculo = veiculo.data[0]

    checar_concorrencia(payload.veiculo_id)

    usuario = supabase.table("usuarios").select("*").eq("id", payload.usuario_id).execute()
    if not usuario.data:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    usuario = usuario.data[0]

    if not usuario.get("rfid_uid"):
        raise HTTPException(
            status_code=400,
            detail="Esse usuário não tem cartão RFID vinculado. Vincule antes de usar o leitor físico.",
        )

    alvo = max(1.0, min(100.0, float(payload.alvo_percentual or 100)))
    if alvo <= payload.percentual_bateria_atual:
        raise HTTPException(
            status_code=400,
            detail="O alvo precisa ser maior que a bateria atual.",
        )

    # Recusa cedo por saldo - levanta 402 e o modal já mostra na tela.
    estimativa = estimar_e_validar_saldo(
        charger, veiculo, usuario, payload.percentual_bateria_atual, alvo
    )

    expira_em = datetime.utcnow() + timedelta(seconds=SEGUNDOS_ESPERA_CARTAO)

    sessao = supabase.table("sessoes_recarga").insert({
        "carregador_id": payload.charger_id,
        "veiculo_id": payload.veiculo_id,
        "usuario_id": payload.usuario_id,
        "status": "aguardando_rfid",
        "percentual_bateria_inicial": payload.percentual_bateria_atual,
        "percentual_bateria_atual": payload.percentual_bateria_atual,
        "alvo_percentual": alvo,
        "tempo_estimado_min": estimativa["tempo_estimado_min"],
        "custo_estimado": estimativa["custo_estimado"],
        "origem": "hardware",
        "expira_em": expira_em.isoformat(),
    }).execute()

    return {
        "success": True,
        "sessao": sessao.data[0],
        "estimativa": estimativa,
        "expira_em": expira_em.isoformat(),
        "segundos_para_aproximar": SEGUNDOS_ESPERA_CARTAO,
    }


@app.post("/charge/cancelar-rfid")
def cancelar_rfid(payload: CancelarRfidRequest):
    """
    Morador desistiu enquanto a tela dizia "aproxime seu cartão".

    Sem este endpoint a única saída seria esperar os 120s do prazo, com o
    carregador travado. O `usuario_id` é conferido para ninguém cancelar a
    espera de outro morador.
    """
    r = (
        supabase.table("sessoes_recarga")
        .select("*")
        .eq("id", payload.sessao_id)
        .eq("status", "aguardando_rfid")
        .execute()
    )
    if not r.data:
        return {"success": True, "ja_encerrada": True}

    if r.data[0]["usuario_id"] != payload.usuario_id:
        raise HTTPException(status_code=403, detail="Essa espera não é sua.")

    supabase.table("sessoes_recarga").update({
        "status": "cancelada",
        "motivo_recusa": "cancelado_pelo_usuario",
        "finalizado_em": datetime.utcnow().isoformat(),
    }).eq("id", payload.sessao_id).execute()

    return {"success": True}


class PreviewRequest(BaseModel):
    charger_id: str
    veiculo_id: str
    percentual_bateria_atual: float


@app.post("/charge/preview")
def preview_recarga(payload: PreviewRequest):
    """
    Mesma conta que a autorização faz, sem gravar nada.

    Existe para que a tela de confirmação mostre exatamente o número que vai
    ser cobrado. Antes o frontend calculava por conta própria e divergia do
    backend assim que a curva de carga e a temperatura entraram na conta.
    """
    charger = supabase.table("carregadores").select("*").eq("id", payload.charger_id).execute()
    if not charger.data:
        raise HTTPException(status_code=404, detail="Carregador não encontrado")

    veiculo = supabase.table("veiculos").select("*").eq("id", payload.veiculo_id).execute()
    if not veiculo.data:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")

    return calcular_estimativa(charger.data[0], veiculo.data[0], payload.percentual_bateria_atual)


# ---------------------------------------------------------------------------
# FILA DE ESPERA
# ---------------------------------------------------------------------------

class FilaRequest(BaseModel):
    charger_id: str
    usuario_id: str


@app.get("/fila/{charger_id}")
def ver_fila(charger_id: str):
    """
    Estado da espera: quem está carregando agora (com quanto falta) e quem
    já está na fila, em ordem.
    """
    fila = (
        supabase.table("fila")
        .select("*, usuarios(nome)")
        .eq("carregador_id", charger_id)
        .order("posicao")
        .execute()
    )

    sessao = (
        supabase.table("sessoes_recarga")
        .select("*, veiculos(modelo, placa)")
        .eq("carregador_id", charger_id)
        .eq("status", "carregando")
        .execute()
    )

    atual = sessao.data[0] if sessao.data else None

    return {
        "em_recarga": atual,
        "fila": fila.data,
        "tamanho": len(fila.data),
        # Só a recarga em andamento é previsível. O tempo de quem está na
        # fila depende do carro que ainda nem plugou - por isso não inventamos
        # um número para as posições seguintes.
        "liberacao_estimada_min": atual["tempo_estimado_min"] if atual else 0,
    }


@app.post("/fila/entrar")
def entrar_fila(payload: FilaRequest):
    ja_esta = (
        supabase.table("fila")
        .select("id")
        .eq("carregador_id", payload.charger_id)
        .eq("usuario_id", payload.usuario_id)
        .execute()
    )
    if ja_esta.data:
        raise HTTPException(status_code=409, detail="Você já está nessa fila.")

    atual = supabase.table("fila").select("posicao").eq("carregador_id", payload.charger_id).execute()
    posicao = max([f["posicao"] for f in atual.data], default=0) + 1

    registro = supabase.table("fila").insert({
        "carregador_id": payload.charger_id,
        "usuario_id": payload.usuario_id,
        "posicao": posicao,
    }).execute()

    return {"success": True, "posicao": posicao, "fila": registro.data[0]}


@app.post("/fila/sair")
def sair_fila(payload: FilaRequest):
    supabase.table("fila").delete().eq("carregador_id", payload.charger_id).eq(
        "usuario_id", payload.usuario_id
    ).execute()

    # Reordena quem ficou, para não abrir buracos na numeração.
    restantes = (
        supabase.table("fila")
        .select("id")
        .eq("carregador_id", payload.charger_id)
        .order("posicao")
        .execute()
    )
    for i, f in enumerate(restantes.data, start=1):
        supabase.table("fila").update({"posicao": i}).eq("id", f["id"]).execute()

    return {"success": True}


def avisar_proximo_da_fila(carregador_id: str):
    """Quando um carregador libera, quem é o primeiro da fila recebe aviso."""
    fila = (
        supabase.table("fila")
        .select("*")
        .eq("carregador_id", carregador_id)
        .order("posicao")
        .limit(1)
        .execute()
    )
    if not fila.data:
        return

    carregador = supabase.table("carregadores").select("numero").eq("id", carregador_id).execute()
    numero = carregador.data[0]["numero"] if carregador.data else "?"

    supabase.table("notificacoes").insert({
        "usuario_id": fila.data[0]["usuario_id"],
        "mensagem": f"O carregador {numero} liberou. É a sua vez - você tem prioridade na fila.",
        "lida": False,
    }).execute()


@app.get("/usuarios/{usuario_id}/veiculos")
def listar_veiculos(usuario_id: str):
    result = supabase.table("veiculos").select("*").eq("usuario_id", usuario_id).execute()
    return result.data


@app.post("/veiculos")
def adicionar_veiculo(payload: VeiculoRequest):
    """Cadastra um veículo adicional para um usuário que já existe."""

    # Impede que a mesma placa seja cadastrada duas vezes - se isso
    # acontecesse, o mesmo carro físico viraria dois veiculo_id diferentes,
    # e a trava de "não pode carregar em dois lugares ao mesmo tempo"
    # (que checa por veiculo_id) não pegaria o caso.
    if payload.placa:
        existente = (
            supabase.table("veiculos")
            .select("id")
            .ilike("placa", payload.placa.strip())
            .execute()
        )
        if existente.data:
            raise HTTPException(
                status_code=409,
                detail="Já existe um veículo cadastrado com essa placa.",
            )

    veiculo = supabase.table("veiculos").insert({
        "usuario_id": payload.usuario_id,
        "modelo": payload.modelo,
        "placa": payload.placa,
        "capacidade_bateria_kwh": payload.capacidade_bateria_kwh,
        "potencia_carro_kw": payload.potencia_carro_kw,
    }).execute()
    return {"success": True, "veiculo": veiculo.data[0]}


@app.post("/usuarios/{usuario_id}/recarregar-saldo")
def recarregar_saldo(usuario_id: str, payload: RecarregarSaldoRequest):
    """
    Adiciona crédito ao saldo do usuário. No MVP isso é só um botão que
    credita na hora (não tem gateway de pagamento real por trás) - serve
    pra não travar a demo caso o saldo acabe durante os testes/vídeo.
    """
    if payload.valor <= 0:
        raise HTTPException(status_code=400, detail="Valor precisa ser maior que zero")

    usuario = supabase.table("usuarios").select("saldo").eq("id", usuario_id).execute()
    if not usuario.data:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    novo_saldo = round(usuario.data[0]["saldo"] + payload.valor, 2)
    supabase.table("usuarios").update({"saldo": novo_saldo}).eq("id", usuario_id).execute()

    return {"success": True, "saldo_atual": novo_saldo}


@app.post("/charge/stop")
def stop_charge(payload: StopChargeRequest):
    sessao = supabase.table("sessoes_recarga").select("*").eq("id", payload.sessao_id).execute()
    if not sessao.data:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    sessao = sessao.data[0]

    supabase.table("sessoes_recarga").update({
        "status": "finalizada",
        "finalizado_em": datetime.utcnow().isoformat(),
        "custo_final": custo_da_sessao(sessao),
    }).eq("id", payload.sessao_id).execute()

    supabase.table("carregadores").update({"status": "disponivel"}).eq("id", sessao["carregador_id"]).execute()

    # Ponto físico: abre o relé. Sem isto o carro continuaria carregando de
    # graça depois do "parar" na tela.
    enfileirar_comando(sessao["carregador_id"], "bloquear", sessao["id"])

    avisar_proximo_da_fila(sessao["carregador_id"])

    return {"success": True}


# ---------------------------------------------------------------------------
# 5. CHATBOT
# ---------------------------------------------------------------------------
# A lógica vive em backend/chatbot/ - router de intenção, camada de dados
# whitelisted, prompts versionados, verificação anti-alucinação e fallback por
# regras. Aqui fica só a casca HTTP.
#
# O contrato do endpoint não mudou: `reply` e `timestamp` continuam iguais. Os
# outros campos são aditivos (o frontend ignora o que não usa).

# --- Hardware ESP32 por WiFi ------------------------------------------------
# O ESP32 é cliente: ele chama estas rotas, o backend nunca chama a placa.
# Ver hardware_api.py para o porquê dessa inversão.
app.include_router(hardware_router)

configurar_hardware(
    supabase=supabase,
    autorizar_e_iniciar_sessao=autorizar_e_iniciar_sessao,
    calcular_estimativa=calcular_estimativa,
    tempo_de_carga_min=tempo_de_carga_min,
    custo_da_sessao=custo_da_sessao,
    eficiencia_carga=EFICIENCIA_CARGA,
    avisar_proximo_da_fila=avisar_proximo_da_fila,
    confirmar_sessao_preparada=confirmar_sessao_preparada,
)

configurar_chatbot(
    supabase=supabase,
    calcular_estimativa=calcular_estimativa,
    custo_da_sessao=custo_da_sessao,
    condominio_padrao=CONDOMINIO_PADRAO,
)


@app.post("/chatbot")
def chatbot(payload: ChatRequest):
    return responder_chatbot(
        mensagem=payload.message,
        usuario_id=payload.usuario_id,
        charger_id=payload.charger_id,
        condominio_id=payload.condominio_id,
    )


# ---------------------------------------------------------------------------
# 6. SIMULADOR - roda sozinho em background, faz as recargas "andarem"
# ---------------------------------------------------------------------------

def expirar_esperas_de_cartao():
    """
    Cancela sessões que ficaram esperando cartão além do prazo.

    Sem isto, quem prepara a recarga e fecha o navegador deixa o carregador
    travado indefinidamente - ninguém consegue preparar nele de novo. Como o
    UPDATE vai para o Realtime, um navegador que ainda esteja aberto recebe a
    notícia e mostra "tempo esgotado" em vez de girar para sempre.
    """
    agora_iso = datetime.utcnow().isoformat()
    try:
        vencidas = (
            supabase.table("sessoes_recarga")
            .select("id, carregador_id")
            .eq("status", "aguardando_rfid")
            .lt("expira_em", agora_iso)
            .execute()
        )
        for sessao in (vencidas.data or []):
            supabase.table("sessoes_recarga").update({
                "status": "cancelada",
                "motivo_recusa": "tempo_esgotado",
                "finalizado_em": agora_iso,
            }).eq("id", sessao["id"]).execute()
            print(f"[RFID] espera de cartão expirada na sessão {sessao['id']}")
    except Exception as e:
        print(f"[RFID] falha ao expirar esperas: {e}")


async def simulador_loop():
    """
    Faz as recargas andarem sozinhas - mas com física, não com random.

    A cada ciclo de 10s, para cada sessão ativa:
      1. descobre a potência que a bateria aceita NESTE estado de carga
      2. aplica o derating térmico do carregador
      3. converte energia da tomada em energia na bateria (eficiência)
      4. avança o SoC pela energia que realmente entrou
      5. recalcula o tempo restante pela curva, não por subtração fixa

    O resultado é que a barra desacelera perto dos 100%, exatamente como um
    carro de verdade - e o tempo restante para de mentir no fim da carga.
    """
    INTERVALO_S = 10
    horas_por_ciclo = INTERVALO_S / 3600

    while True:
        try:
            # --- Temperatura dos carregadores ---
            # Persegue um alvo (quente em uso, ambiente se livre) com passo
            # pequeno e ruído, para parecer curva e não degrau.
            # Só pontos SIMULADOS. Carregador com origem='hardware' tem um
            # ESP32 escrevendo temperatura e energia a partir do sensor - se o
            # simulador também escrevesse, os dois brigariam pela mesma linha
            # a cada 10s e o valor na tela ficaria pulando entre o medido e o
            # modelado. Um dono por linha.
            chargers = supabase.table("carregadores").select(
                "id, status, temperatura_c, potencia_maxima_kw, tarifa_kwh"
            ).eq("origem", "simulado").execute()

            # Dispositivos sem contato recente derrubam o ponto. Aproveita
            # este loop em vez de abrir outra thread.
            marcar_dispositivos_offline()
            expirar_esperas_de_cartao()

            por_id = {}
            for c in chargers.data:
                temp_atual = c.get("temperatura_c", 25) or 25
                alvo = 45 if c["status"] == "em_uso" else 24
                nova_temp = temp_atual + (alvo - temp_atual) * 0.15 + random.uniform(-0.4, 0.4)
                nova_temp = max(18, min(60, nova_temp))
                supabase.table("carregadores").update(
                    {"temperatura_c": round(nova_temp, 1)}
                ).eq("id", c["id"]).execute()

                c["temperatura_c"] = nova_temp
                por_id[c["id"]] = c

            # --- Sessões de recarga ativas ---
            sessoes = (
                supabase.table("sessoes_recarga")
                .select("*, veiculos(capacidade_bateria_kwh, potencia_carro_kw)")
                .eq("status", "carregando")
                .execute()
            )

            for sessao in sessoes.data:
                veiculo = sessao.get("veiculos") or {}
                capacidade = veiculo.get("capacidade_bateria_kwh") or 40
                potencia_carro = veiculo.get("potencia_carro_kw") or 7.4
                charger = por_id.get(sessao["carregador_id"])
                if not charger:
                    # `por_id` só tem pontos simulados. Sessão rodando em
                    # carregador físico cai aqui e é ignorada de propósito:
                    # quem avança energia e SoC nela é o ESP32, via
                    # POST /hardware/telemetria. NÃO remova este guard.
                    continue

                soc = float(sessao["percentual_bateria_atual"] or 0)

                # Teto de potência agora: menor entre carregador e carro,
                # penalizado pela temperatura do equipamento.
                teto_kw = min(charger["potencia_maxima_kw"], potencia_carro)
                teto_kw *= fator_termico(charger["temperatura_c"])

                # Potência que a bateria aceita neste SoC (curva CC/CV).
                potencia_agora = potencia_no_soc(teto_kw, soc)

                # Energia da tomada neste ciclo, e quanto dela chega na bateria.
                energia_rede = potencia_agora * horas_por_ciclo
                energia_bateria = energia_rede * EFICIENCIA_CARGA

                novo_soc = min(100.0, soc + (energia_bateria / capacidade) * 100)
                nova_energia = float(sessao["energia_entregue_kwh"] or 0) + energia_rede
                novo_tempo = tempo_de_carga_min(capacidade, novo_soc, 100.0, teto_kw)

                update_data = {
                    "energia_entregue_kwh": round(nova_energia, 3),
                    "percentual_bateria_atual": round(novo_soc, 1),
                    "potencia_atual_kw": round(potencia_agora, 2),
                    "tempo_estimado_min": novo_tempo,
                }

                # Bateria cheia -> encerra e libera o ponto.
                if novo_soc >= 99.9:
                    update_data["status"] = "finalizada"
                    update_data["finalizado_em"] = datetime.utcnow().isoformat()
                    update_data["custo_final"] = round(
                        nova_energia * (charger.get("tarifa_kwh") or TARIFA_PADRAO_KWH), 2
                    )
                    supabase.table("carregadores").update({"status": "disponivel"}).eq(
                        "id", sessao["carregador_id"]
                    ).execute()
                    supabase.table("veiculos").update(
                        {"percentual_bateria": round(novo_soc, 1)}
                    ).eq("id", sessao["veiculo_id"]).execute()
                    avisar_proximo_da_fila(sessao["carregador_id"])

                supabase.table("sessoes_recarga").update(update_data).eq(
                    "id", sessao["id"]
                ).execute()

        except Exception as e:
            print(f"[SIMULADOR] erro: {e}")

        await asyncio.sleep(INTERVALO_S)


@app.on_event("startup")
async def start_simulador():
    asyncio.create_task(simulador_loop())
    iniciar_escuta_serial(supabase, autorizar_e_iniciar_sessao, HTTPException)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.post("/debug/simular-rfid")
def debug_simular_rfid(payload: VincularRfidRequest):
    """
    SÓ PARA TESTES - simula exatamente o que acontece quando o Arduino lê
    um cartão de verdade (chama a mesma função interna). Útil pra testar
    o fluxo /charge/preparar-rfid → autorização sem ter o hardware físico
    conectado ainda. Pode remover esse endpoint quando o Arduino estiver
    pronto e testado de verdade.
    """
    resultado = _processar_leitura_rfid(payload.rfid_uid, supabase, autorizar_e_iniciar_sessao, HTTPException)
    return {"resultado": "autorizado" if resultado == "L" else "negado", "codigo": resultado}


@app.get("/")
def root():
    return {"status": "ok", "service": "GoodWe ChargeOps AI Assistant API"}