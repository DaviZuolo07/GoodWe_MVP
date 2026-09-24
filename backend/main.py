"""
GoodWe ChargeOps AI Assistant - API
===================================

Este arquivo só MONTA a aplicação. A regra de negócio mora em módulos com
um dono cada:

  config.py         ambiente, cliente do Supabase, constantes
  seguranca.py      senha (Argon2id), JWT, token do ESP32, rate limit
  identidade.py     "quem está chamando" - sempre do token (Bloco 2)
  fisica.py         curva de carga, derating, tarifa de ponta (funções puras)
  demanda.py        alocador único de potência do condomínio (Bloco 3)
  carteira.py       débito/crédito atômicos, pré-autorização e estorno
  recarga.py        ciclo de vida da recarga, do preparar ao recibo
  dispositivos.py   fila de comandos do ESP32
  hardware_api.py   protocolo HTTP do ESP32 (Bloco 5)
  simulador.py      laço de 10 s: demanda, pontos simulados, expirações
  chatbot/          assistente em camadas: entrada, contexto, saída, auditoria (Bloco 4)

Rodar (de dentro de backend/):
    uvicorn main:app --reload --host 0.0.0.0
Documentação: http://localhost:8000/docs
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import simulador
from chatbot import configurar_chatbot, responder_chatbot
from config import CONDOMINIO_PADRAO, FRONTEND_ORIGIN_REGEX, FRONTEND_ORIGINS, MODO_DEMO, supabase
from fisica import calcular_estimativa, custo_da_sessao
from hardware_api import router as hardware_router
from identidade import usuario_logado
from rotas_conta import locais_do_usuario, router as conta_router
from rotas_gestor import router as gestor_router
from rotas_recarga import router as recarga_router
from seguranca import limitador_chat


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    tarefa = asyncio.create_task(simulador.laco())
    if MODO_DEMO:
        print("[AVISO] MODO_DEMO=1: rotas /debug ativas e varredura de ESP32 suspensa. "
              "Desligue antes de conectar a placa.")
    yield
    tarefa.cancel()


app = FastAPI(title="GoodWe ChargeOps AI Assistant - API", lifespan=ciclo_de_vida)

# CORS restrito à origem do frontend (Bloco 2). Sem cookies: a identidade vai
# no header Authorization, então allow_credentials fica desligado.
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_origin_regex=FRONTEND_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(conta_router)
app.include_router(recarga_router)
app.include_router(gestor_router)
app.include_router(hardware_router)

if MODO_DEMO:
    from rotas_debug import router as debug_router
    app.include_router(debug_router)

configurar_chatbot(
    supabase=supabase,
    calcular_estimativa=calcular_estimativa,
    custo_da_sessao=custo_da_sessao,
    condominio_padrao=CONDOMINIO_PADRAO,
    locais_do_usuario=locais_do_usuario,
)


class ChatRequest(BaseModel):
    message: str = Field(..., max_length=2000)
    charger_id: Optional[str] = None
    # Local escolhido no seletor: é PEDIDO. O chatbot valida contra os favoritos.
    condominio_id: Optional[str] = None


@app.post("/chatbot", tags=["chatbot"])
def chatbot(payload: ChatRequest, usuario: dict = Depends(usuario_logado)):
    limitador_chat.consumir(f"usuario:{usuario['id']}")
    return responder_chatbot(
        mensagem=payload.message,
        usuario_id=usuario["id"],          # do token, nunca do corpo
        charger_id=payload.charger_id,
        condominio_id=payload.condominio_id,
    )


@app.get("/", tags=["saúde"])
def raiz():
    return {"status": "ok", "service": "GoodWe ChargeOps AI Assistant API", "modo_demo": MODO_DEMO}
