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
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from supabase import create_client, Client

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

# ID do condomínio único usado no MVP (o mesmo do seed)
CONDOMINIO_ID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# MODELOS (payloads recebidos do frontend)
# ---------------------------------------------------------------------------

class CadastroRequest(BaseModel):
    nome: str
    tipo_usuario: str = "morador"          # "morador" | "visitante"
    bloco_apto: Optional[str] = None
    veiculo_modelo: str
    veiculo_placa: Optional[str] = None
    capacidade_bateria_kwh: float = 40
    potencia_carro_kw: float = 7.4


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


class ChatRequest(BaseModel):
    message: str
    usuario_id: Optional[str] = None
    charger_id: Optional[str] = None


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

    usuario = supabase.table("usuarios").insert({
        "nome": nome_normalizado,
        "tipo_usuario": payload.tipo_usuario,
        "condominio_id": CONDOMINIO_ID,
        "bloco_apto": payload.bloco_apto,
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


# ---------------------------------------------------------------------------
# 3. DASHBOARD (o frontend pode ler direto do Supabase, mas isso aqui
#    serve pra testar rápido pelo /docs sem precisar do frontend pronto)
# ---------------------------------------------------------------------------

@app.get("/chargers")
def list_chargers():
    result = supabase.table("carregadores").select("*").eq("condominio_id", CONDOMINIO_ID).execute()
    return result.data


# ---------------------------------------------------------------------------
# 4. FLUXO DE RECARGA
# ---------------------------------------------------------------------------

@app.post("/charge/start")
def start_charge(payload: StartChargeRequest):
    charger = supabase.table("carregadores").select("*").eq("id", payload.charger_id).execute()
    if not charger.data:
        raise HTTPException(status_code=404, detail="Carregador não encontrado")
    charger = charger.data[0]

    if charger["status"] == "em_uso":
        raise HTTPException(status_code=400, detail="Carregador já está em uso")

    veiculo = supabase.table("veiculos").select("*").eq("id", payload.veiculo_id).execute()
    if not veiculo.data:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    veiculo = veiculo.data[0]

    usuario = supabase.table("usuarios").select("*").eq("id", payload.usuario_id).execute()
    if not usuario.data:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    usuario = usuario.data[0]

    # Cálculo real (não é número aleatório): usa dados do cadastro do carro
    # (capacidade da bateria, potência que o carro aceita) + potência do
    # carregador + a % de bateria informada agora no pagamento.
    percentual_atual = payload.percentual_bateria_atual
    potencia_efetiva_kw = min(charger["potencia_maxima_kw"], veiculo["potencia_carro_kw"])
    energia_necessaria_kwh = veiculo["capacidade_bateria_kwh"] * (1 - percentual_atual / 100)
    tempo_estimado_min = round((energia_necessaria_kwh / potencia_efetiva_kw) * 60) if potencia_efetiva_kw > 0 else 0
    custo_estimado = round(energia_necessaria_kwh * charger["tarifa_kwh"], 2)

    # Pagamento RFID simulado - agora checa saldo de verdade, não aprova sozinho.
    # É AQUI que, no next, a liberação do Arduino fica condicionada à aprovação.
    if usuario["saldo"] < custo_estimado:
        raise HTTPException(
            status_code=402,
            detail=f"Saldo insuficiente. Saldo atual: R$ {usuario['saldo']:.2f}, "
                   f"custo estimado: R$ {custo_estimado:.2f}.",
        )

    novo_saldo = round(usuario["saldo"] - custo_estimado, 2)
    supabase.table("usuarios").update({"saldo": novo_saldo}).eq("id", payload.usuario_id).execute()

    sessao = supabase.table("sessoes_recarga").insert({
        "carregador_id": payload.charger_id,
        "veiculo_id": payload.veiculo_id,
        "usuario_id": payload.usuario_id,
        "status": "carregando",
        "potencia_atual_kw": potencia_efetiva_kw,
        "energia_entregue_kwh": 0,
        "percentual_bateria_inicial": percentual_atual,
        "percentual_bateria_atual": percentual_atual,
        "tempo_estimado_min": tempo_estimado_min,
        "custo_estimado": custo_estimado,
        "origem": "simulado",
        "iniciado_em": datetime.utcnow().isoformat(),
    }).execute()

    # Registra o pagamento de verdade (a tabela existia mas nunca era usada)
    supabase.table("pagamentos").insert({
        "sessao_id": sessao.data[0]["id"],
        "valor": custo_estimado,
        "metodo": "rfid_simulado",
        "status": "aprovado",
    }).execute()

    # Atualiza também o veículo com a % informada agora (fica coerente pro
    # dashboard mostrar, mesmo fora de uma sessão ativa)
    supabase.table("veiculos").update({"percentual_bateria": percentual_atual}).eq("id", payload.veiculo_id).execute()

    supabase.table("carregadores").update({"status": "em_uso"}).eq("id", payload.charger_id).execute()

    return {"success": True, "sessao": sessao.data[0], "saldo_atual": novo_saldo}


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
        "custo_final": round(sessao["energia_entregue_kwh"] * 2.10, 2),
    }).eq("id", payload.sessao_id).execute()

    supabase.table("carregadores").update({"status": "disponivel"}).eq("id", sessao["carregador_id"]).execute()

    return {"success": True}


# ---------------------------------------------------------------------------
# 5. CHATBOT (baseado em regras, usa os dados reais do Supabase)
# ---------------------------------------------------------------------------

@app.post("/chatbot")
def chatbot(payload: ChatRequest):
    msg = payload.message.lower()
    reply = "Posso te ajudar com informações sobre disponibilidade, tempo restante, fila e potência dos carregadores."

    sessao = None
    if payload.usuario_id:
        result = (
            supabase.table("sessoes_recarga")
            .select("*")
            .eq("usuario_id", payload.usuario_id)
            .eq("status", "carregando")
            .execute()
        )
        if result.data:
            sessao = result.data[0]

    if ("tempo" in msg or "falta" in msg) and sessao:
        reply = f"Faltam aproximadamente {sessao['tempo_estimado_min']} minutos para concluir sua recarga."
    elif "disponível" in msg or "disponivel" in msg:
        chargers = supabase.table("carregadores").select("numero,status").eq("condominio_id", CONDOMINIO_ID).execute()
        disponiveis = [c["numero"] for c in chargers.data if c["status"] == "disponivel"]
        reply = f"Carregadores disponíveis agora: {', '.join(disponiveis) if disponiveis else 'nenhum no momento'}."
    elif "potência" in msg or "potencia" in msg:
        if sessao:
            reply = f"A potência atual da sua recarga é de {sessao['potencia_atual_kw']} kW."
        else:
            reply = "Você não tem uma recarga ativa no momento."
    elif "custo" in msg or "preço" in msg or "preco" in msg:
        if sessao:
            custo = round(sessao["energia_entregue_kwh"] * 2.10, 2)
            reply = f"O custo estimado até agora é de R$ {custo}."

    # loga a conversa (opcional, mas já deixa o histórico real no banco)
    supabase.table("chat_mensagens").insert({
        "usuario_id": payload.usuario_id,
        "carregador_id": payload.charger_id,
        "remetente": "usuario",
        "mensagem": payload.message,
    }).execute()
    supabase.table("chat_mensagens").insert({
        "usuario_id": payload.usuario_id,
        "carregador_id": payload.charger_id,
        "remetente": "bot",
        "mensagem": reply,
    }).execute()

    return {"reply": reply, "timestamp": datetime.utcnow().isoformat()}


# ---------------------------------------------------------------------------
# 6. SIMULADOR - roda sozinho em background, faz as recargas "andarem"
# ---------------------------------------------------------------------------

async def simulador_loop():
    while True:
        try:
            sessoes = (
                supabase.table("sessoes_recarga")
                .select("*")
                .eq("status", "carregando")
                .execute()
            )
            for sessao in sessoes.data:
                nova_energia = sessao["energia_entregue_kwh"] + round(sessao["potencia_atual_kw"] / 360, 3)
                novo_percentual = min(100, sessao["percentual_bateria_atual"] + random.uniform(0.3, 0.8))
                novo_tempo = max(0, sessao["tempo_estimado_min"] - 1)

                update_data = {
                    "energia_entregue_kwh": round(nova_energia, 2),
                    "percentual_bateria_atual": round(novo_percentual, 1),
                    "tempo_estimado_min": novo_tempo,
                }

                # Bateria cheia ou tempo zerado -> finaliza sozinho
                if novo_percentual >= 100 or novo_tempo <= 0:
                    update_data["status"] = "finalizada"
                    update_data["finalizado_em"] = datetime.utcnow().isoformat()
                    update_data["custo_final"] = round(nova_energia * 2.10, 2)
                    supabase.table("carregadores").update({"status": "disponivel"}).eq(
                        "id", sessao["carregador_id"]
                    ).execute()

                supabase.table("sessoes_recarga").update(update_data).eq("id", sessao["id"]).execute()

        except Exception as e:
            print(f"[SIMULADOR] erro: {e}")

        await asyncio.sleep(10)  # atualiza a cada 10 segundos


@app.on_event("startup")
async def start_simulador():
    asyncio.create_task(simulador_loop())


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {"status": "ok", "service": "GoodWe ChargeOps AI Assistant API"}