"""
Orquestrador do chatbot - as quatro camadas, em ordem.

    mensagem
      -> [1 ENTRADA]    limpa, limita, barra injeção           (entrada.py)
      -> [2 CONTEXTO]   identidade do token, local da allowlist (contexto.py)
      -> router         intenção (regex; LLM se o regex não decidir)
      -> dados          funções de leitura whitelisted          (dados.py)
      -> redação        LLM a partir dos fatos, ou regras
      -> [3 SAÍDA]      reprova número sem lastro/vazamento     (saida.py)
      -> [4 AUDITORIA]  grava tudo com a camada que decidiu     (auditoria.py)

O contrato do endpoint continua: `reply` e `timestamp`. Os demais campos
dizem de onde saiu a resposta - é o que o eval (evals/) confere.
"""

import time

from config import agora_iso

from . import auditoria, contexto, dados as D, entrada, llm, respostas, saida
from . import router as R


def responder(mensagem: str, usuario_id: str = None, charger_id: str = None,
              condominio_id: str = None) -> dict:
    inicio = time.perf_counter()

    # --- 1. Entrada -------------------------------------------------------
    ent = entrada.processar(mensagem)
    texto = ent["texto"]

    # --- 2. Contexto ------------------------------------------------------
    ctx = contexto.ctx_usuario(usuario_id, condominio_escolhido=condominio_id)

    if ent["bloqueado"]:
        return _fechar(texto, respostas.redigir(R.TENTATIVA_INJECAO, {}, ctx), ctx, usuario_id,
                       charger_id, inicio, intencao=R.TENTATIVA_INJECAO, camada="entrada",
                       bloqueado=True, motivo=ent["motivo"], metodo="entrada", fonte=[])

    # --- Router -----------------------------------------------------------
    rota = R.rotear(texto)
    intencao, metodo, parametros = rota["intencao"], rota["metodo"], rota["parametros"]
    if metodo == "nenhum":
        palpite = llm.classificar(texto)
        if palpite and palpite != R.FORA_DE_ESCOPO:
            intencao, metodo = palpite, "llm"
            parametros = R.extrair_parametros(R.normalizar(texto), intencao)

    if intencao in (R.TENTATIVA_INJECAO, R.FORA_DE_ESCOPO):
        return _fechar(texto, respostas.redigir(intencao, {}, ctx), ctx, usuario_id, charger_id,
                       inicio, intencao=intencao, camada="entrada" if intencao == R.TENTATIVA_INJECAO
                       else "contexto", bloqueado=True, motivo=f"router:{metodo}", metodo=metodo, fonte=[])

    # --- Dados ------------------------------------------------------------
    fatos = _buscar_fatos(intencao, ctx, usuario_id, charger_id, parametros)

    # --- Redação + 3. Saída ------------------------------------------------
    reply, camada, motivo, origem = None, "redacao_regras", None, "regras"
    if llm.llm_ligado():
        candidata = llm.redigir(texto, intencao, fatos, ctx)
        if candidata:
            ok, limpa, motivo_saida = saida.verificar(candidata, fatos)
            if ok:
                reply, camada, origem = limpa, "redacao_llm", "llm"
            else:
                camada, motivo = "saida", motivo_saida
                print(f"[CHATBOT] camada de saída reprovou o LLM ({motivo_saida}) - usando regras")
    if reply is None:
        reply = respostas.redigir(intencao, fatos, ctx)

    return _fechar(texto, reply, ctx, usuario_id, charger_id, inicio, intencao=intencao,
                   camada=camada, bloqueado=False, motivo=motivo, metodo=metodo,
                   fonte=(fatos or {}).get("fonte", []), origem=origem)


def _fechar(pergunta, reply, ctx, usuario_id, charger_id, inicio, *, intencao, camada,
            bloqueado, motivo, metodo, fonte, origem="regras") -> dict:
    latencia = round((time.perf_counter() - inicio) * 1000)
    modelo = llm.OLLAMA_MODEL if origem == "llm" else "regras"
    auditoria.registrar(usuario_id, charger_id, pergunta, reply, intencao=intencao, camada=camada,
                        bloqueado=bloqueado, motivo=motivo, modelo=modelo, latencia_ms=latencia)
    return {
        "reply": reply,
        "timestamp": agora_iso(),
        "intencao": intencao,
        "camada": camada,
        "bloqueado": bloqueado,
        "motivo": motivo,
        "fonte": fonte,
        "condominio_id": ctx.get("condominio_id"),
        "condominio_nome": ctx.get("condominio_nome"),
        "modelo": modelo,
        "roteador": metodo,
        "latencia_ms": latencia,
    }


def _buscar_fatos(intencao, ctx, usuario_id, charger_id, params):
    """Despacha para a função de leitura correta. Só o enum chega aqui."""
    if not ctx.get("encontrado") and intencao != R.AJUDA:
        return {"fonte": []}
    condominio_id = ctx.get("condominio_id")

    if intencao in (R.TEMPO_RESTANTE, R.STATUS_RECARGA, R.CUSTO_ATUAL):
        return D.sessao_ativa(usuario_id)
    if intencao == R.TARIFA:
        return D.tarifas(condominio_id)
    if intencao == R.CARREGADORES_DISPONIVEIS:
        return D.carregadores(condominio_id)
    if intencao == R.INFO_CARREGADOR:
        return D.info_carregador(condominio_id, numero=params.get("numero_carregador"),
                                 charger_id=None if params.get("numero_carregador") else charger_id)
    if intencao == R.FILA_STATUS:
        return D.fila(condominio_id, usuario_id)
    if intencao == R.MEU_SALDO:
        return D.meu_saldo(ctx)
    if intencao == R.MEUS_VEICULOS:
        return D.veiculos(usuario_id)
    if intencao == R.HISTORICO_RECENTE:
        return D.historico_recente(usuario_id, params.get("limite", 5))
    if intencao == R.SIMULAR_RECARGA:
        return D.simular_recarga(usuario_id, condominio_id, numero=params.get("numero_carregador"),
                                 charger_id=None if params.get("numero_carregador") else charger_id,
                                 alvo=params.get("alvo", 100.0), condominio=ctx.get("condominio"))
    if intencao == R.DEMANDA:
        return D.demanda(ctx.get("condominio"), usuario_id)
    if intencao == R.COBRANCA:
        return D.cobranca(usuario_id, ctx.get("condominio"))
    return {"fonte": []}
