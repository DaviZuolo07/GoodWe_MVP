"""
Orquestrador do chatbot - o fluxo inteiro em um lugar só.

    mensagem
       -> sanitização
       -> router (regex; LLM só se o regex não decidir)
       -> camada de dados (funções whitelisted, escopo do backend)
       -> redação (LLM, com verificação; senão determinística)
       -> log em chat_mensagens
       -> {reply, timestamp, intencao, fonte, modelo, latencia_ms}

O contrato do endpoint é sagrado: `reply` e `timestamp` continuam exatamente
como estavam. Os outros campos são aditivos - o frontend ignora o que não usa,
e eles respondem a pergunta que a banca faz: de onde saiu esse número.
"""

import time
from datetime import datetime

from . import dados as D
from . import router as R
from . import respostas
from . import llm
from . import verificador
from .contexto import sb


def responder(mensagem: str, usuario_id: str = None, charger_id: str = None,
              condominio_id: str = None) -> dict:
    """
    `condominio_id` é o local escolhido no seletor do chat. Ele é um PEDIDO,
    não uma permissão: quem decide o escopo final é `ctx_usuario`, validando
    contra a allowlist de favoritos. Se o local não estiver liberado, a
    resposta sai sobre o condomínio de moradia e ninguém vaza dado de lugar
    nenhum.
    """
    inicio = time.perf_counter()

    mensagem = (mensagem or "").strip()[:R.LIMITE_CARACTERES]
    ctx = D.ctx_usuario(usuario_id, condominio_escolhido=condominio_id)
    condominio_id = ctx.get("condominio_id")   # já validado

    # --- 1. Router -------------------------------------------------------
    rota = R.rotear(mensagem)
    intencao = rota["intencao"]
    metodo = rota["metodo"]
    parametros = rota["parametros"]

    if metodo == "nenhum":
        palpite = llm.classificar(mensagem)
        if palpite and palpite != R.FORA_DE_ESCOPO:
            intencao = palpite
            metodo = "llm"
            parametros = R.extrair_parametros(R.normalizar(mensagem), intencao)

    # --- 2. Dados --------------------------------------------------------
    fatos = _buscar_fatos(intencao, ctx, usuario_id, condominio_id,
                          charger_id, parametros)

    # --- 3. Redação ------------------------------------------------------
    reply = None
    origem_resposta = "regras"

    intencoes_sem_llm = {R.TENTATIVA_INJECAO, R.FORA_DE_ESCOPO}
    if llm.llm_ligado() and intencao not in intencoes_sem_llm:
        candidata = llm.redigir(mensagem, intencao, fatos, ctx)
        if candidata:
            ok, motivo = verificador.aprovado(candidata, fatos)
            if ok:
                reply = candidata
                origem_resposta = "llm"
            else:
                print(f"[CHATBOT] resposta do LLM reprovada ({motivo}) - usando regras")

    if reply is None:
        reply = respostas.redigir(intencao, fatos, ctx)

    # --- 4. Log ----------------------------------------------------------
    _registrar(usuario_id, charger_id, mensagem, reply)

    return {
        "reply": reply,
        "timestamp": datetime.utcnow().isoformat(),
        # campos aditivos - não quebram o contrato
        "intencao": intencao,
        "fonte": (fatos or {}).get("fonte", []),
        "condominio_id": condominio_id,
        "condominio_nome": ctx.get("condominio_nome"),
        "modelo": llm.OLLAMA_MODEL if origem_resposta == "llm" else "regras",
        "roteador": metodo,
        "latencia_ms": round((time.perf_counter() - inicio) * 1000),
    }


def _buscar_fatos(intencao, ctx, usuario_id, condominio_id, charger_id, params):
    """Despacha para a função de leitura correta. Só o enum chega até aqui."""
    if not ctx.get("encontrado") and intencao not in (R.AJUDA, R.FORA_DE_ESCOPO,
                                                      R.TENTATIVA_INJECAO):
        return {"fonte": []}

    if intencao in (R.TEMPO_RESTANTE, R.STATUS_RECARGA, R.CUSTO_ATUAL):
        return D.sessao_ativa(usuario_id)

    if intencao == R.TARIFA:
        return D.tarifas(condominio_id)

    if intencao == R.CARREGADORES_DISPONIVEIS:
        return D.carregadores(condominio_id)

    if intencao == R.INFO_CARREGADOR:
        # `info_carregador` filtra por condomínio, então um charger_id de outro
        # local simplesmente não é encontrado. É o comportamento certo: o
        # escopo do chat é o local escolhido, não a tela anterior.
        return D.info_carregador(
            condominio_id,
            numero=params.get("numero_carregador"),
            charger_id=None if params.get("numero_carregador") else charger_id,
        )

    if intencao == R.FILA_STATUS:
        return D.fila(condominio_id, usuario_id)

    if intencao == R.MEU_SALDO:
        return D.meu_saldo(ctx)

    if intencao == R.MEUS_VEICULOS:
        return D.veiculos(usuario_id)

    if intencao == R.HISTORICO_RECENTE:
        return D.historico_recente(usuario_id, params.get("limite", 5))

    if intencao == R.SIMULAR_RECARGA:
        return D.simular_recarga(
            usuario_id, condominio_id,
            numero=params.get("numero_carregador"),
            charger_id=None if params.get("numero_carregador") else charger_id,
            alvo=params.get("alvo", 100.0),
        )

    return {"fonte": []}


def _registrar(usuario_id, charger_id, pergunta, reply):
    """
    Grava as duas pontas em chat_mensagens (auditoria).

    Falha de log NUNCA pode derrubar a resposta: se o insert quebrar, o
    usuário ainda recebe o que perguntou.
    """
    try:
        sb().table("chat_mensagens").insert({
            "usuario_id": usuario_id, "carregador_id": charger_id,
            "remetente": "usuario", "mensagem": pergunta,
        }).execute()
        sb().table("chat_mensagens").insert({
            "usuario_id": usuario_id, "carregador_id": charger_id,
            "remetente": "bot", "mensagem": reply,
        }).execute()
    except Exception as e:
        print(f"[CHATBOT] falha ao gravar histórico: {e}")
