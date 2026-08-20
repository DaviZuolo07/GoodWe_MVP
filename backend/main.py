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

from hardware_serial import iniciar_escuta_serial, _processar_leitura_rfid

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


class VincularRfidRequest(BaseModel):
    rfid_uid: str


class PrepararRfidRequest(BaseModel):
    charger_id: str
    usuario_id: str
    veiculo_id: str
    percentual_bateria_atual: float


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


# ---------------------------------------------------------------------------
# 4. FLUXO DE RECARGA
# ---------------------------------------------------------------------------

def autorizar_e_iniciar_sessao(charger: dict, veiculo: dict, usuario: dict, percentual_atual: float, metodo: str, origem: str) -> dict:
    """
    Função central de autorização - checa saldo, deduz, cria a sessão e
    registra o pagamento. Usada tanto pelo fluxo simulado (/charge/start,
    botão no frontend) quanto pelo fluxo do cartão RFID físico (ver
    hardware_serial.py). Levanta HTTPException se algo bloquear.
    """
    estimativa = calcular_estimativa(charger, veiculo, percentual_atual)
    potencia_efetiva_kw = estimativa["potencia_agora_kw"]
    tempo_estimado_min = estimativa["tempo_estimado_min"]
    custo_estimado = estimativa["custo_estimado"]

    if usuario["saldo"] < custo_estimado:
        raise HTTPException(
            status_code=402,
            detail=f"Saldo insuficiente. Saldo atual: R$ {usuario['saldo']:.2f}, "
                   f"custo estimado: R$ {custo_estimado:.2f}.",
        )

    novo_saldo = round(usuario["saldo"] - custo_estimado, 2)
    supabase.table("usuarios").update({"saldo": novo_saldo}).eq("id", usuario["id"]).execute()

    sessao = supabase.table("sessoes_recarga").insert({
        "carregador_id": charger["id"],
        "veiculo_id": veiculo["id"],
        "usuario_id": usuario["id"],
        "status": "carregando",
        "potencia_atual_kw": potencia_efetiva_kw,
        "energia_entregue_kwh": 0,
        "percentual_bateria_inicial": percentual_atual,
        "percentual_bateria_atual": percentual_atual,
        "tempo_estimado_min": tempo_estimado_min,
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

    return {"sessao": sessao.data[0], "saldo_atual": novo_saldo}


def checar_concorrencia(veiculo_id: str):
    """Levanta erro se o veículo já tiver uma sessão ativa em outro carregador."""
    sessao_ativa = (
        supabase.table("sessoes_recarga")
        .select("id")
        .eq("veiculo_id", veiculo_id)
        .eq("status", "carregando")
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


@app.post("/charge/preparar-rfid")
def preparar_rfid(payload: PrepararRfidRequest):
    """
    Passo 1 do fluxo com hardware real: o frontend chama isso quando o
    usuário já escolheu o carregador e digitou a % de bateria, e a tela
    está mostrando 'aproxime seu cartão'. Isso NÃO inicia a recarga ainda
    - só deixa tudo pronto (calcula a estimativa) para quando o cartão for
    lido de verdade no leitor RFID físico (ver hardware_serial.py), que
    completa a autorização chamando autorizar_e_iniciar_sessao().

    Pra achar qual usuário passou o cartão, o usuário precisa ter um
    rfid_uid vinculado (ver /usuarios/{id}/vincular-rfid).
    """
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

    estimativa = calcular_estimativa(charger, veiculo, payload.percentual_bateria_atual)

    sessao = supabase.table("sessoes_recarga").insert({
        "carregador_id": payload.charger_id,
        "veiculo_id": payload.veiculo_id,
        "usuario_id": payload.usuario_id,
        "status": "aguardando_rfid",
        "percentual_bateria_inicial": payload.percentual_bateria_atual,
        "percentual_bateria_atual": payload.percentual_bateria_atual,
        "tempo_estimado_min": estimativa["tempo_estimado_min"],
        "custo_estimado": estimativa["custo_estimado"],
        "origem": "hardware",
    }).execute()

    return {"success": True, "sessao": sessao.data[0], "estimativa": estimativa}


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
        "custo_final": round(sessao["energia_entregue_kwh"] * 2.10, 2),
    }).eq("id", payload.sessao_id).execute()

    supabase.table("carregadores").update({"status": "disponivel"}).eq("id", sessao["carregador_id"]).execute()
    avisar_proximo_da_fila(sessao["carregador_id"])

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

    # O chatbot responde sobre o condomínio de quem perguntou, não sobre um
    # condomínio fixo.
    condominio_do_usuario = CONDOMINIO_PADRAO
    if payload.usuario_id:
        u = supabase.table("usuarios").select("condominio_id").eq("id", payload.usuario_id).execute()
        if u.data and u.data[0].get("condominio_id"):
            condominio_do_usuario = u.data[0]["condominio_id"]

    if ("tempo" in msg or "falta" in msg) and sessao:
        reply = f"Faltam aproximadamente {sessao['tempo_estimado_min']} minutos para concluir sua recarga."
    elif "disponível" in msg or "disponivel" in msg:
        chargers = supabase.table("carregadores").select("numero,status").eq("condominio_id", condominio_do_usuario).execute()
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
            chargers = supabase.table("carregadores").select(
                "id, status, temperatura_c, potencia_maxima_kw, tarifa_kwh"
            ).execute()

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
                        nova_energia * charger.get("tarifa_kwh", 2.10), 2
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