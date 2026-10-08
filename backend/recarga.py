"""
recarga.py - Ciclo de vida de uma recarga, do "preparar" ao recibo.
===================================================================

  preparar()            morador confirma na tela -> sessão `aguardando_rfid`
                        ponto físico: enfileira `solicitar_cartao` para o ESP32
                        ponto simulado: o app é o cartão, confirma na hora
        |
  processar_cartao()    ESP32 leu um cartão -> é o dono? tem saldo?
        |                 sem saldo: a espera CONTINUA, o morador põe saldo
        |                 no app e aproxima de novo (até 3 tentativas)
  confirmar()           pré-autoriza o saldo, promove a sessão para
        |               `carregando` NO LUGAR (mesmo id: o navegador está
        |               escutando esta linha pelo Realtime), manda `liberar`
  registrar_progresso() cada leitura (sensor do ESP32 ou simulador): energia,
        |               ponta/fora-ponta, SoC, previsão de término, e as
        |               condições de parada (alvo, teto do valor reservado)
  encerrar()            custo real, ESTORNO da diferença, `bloquear`,
        |               recibo em notificação, fila avisada, potência realocada
  liberar_vaga()        ponto SIMULADO que terminou sozinho: o carro segue na
                        vaga e, depois da tolerância, corre a TAXA DE
                        OCIOSIDADE (db/21) até o morador tocar "Já retirei o carro"

TOTEM v2.1 - TAG PRIMEIRO (ADR-018)
-----------------------------------
  processar_tag()       tag + botão da vaga no totem. Vaga livre e cartão
        |               pessoal: a recarga nasce da tag, sem o app (% inicial
        |               = último conhecido do veículo, rotulado ESTIMADO).
        |               A mesma tag na vaga dela encerra. Tag alheia em vaga
        |               ocupada: recusa + evento de segurança.
  aguardando_energia    sem orçamento no alocador: saldo reservado, relé
        |               DESLIGADO, fila por ordem de chegada no condomínio
  promover_...()        quando sobra potência (fim de recarga ou laço de
                        10 s), o primeiro da fila liga por `liberar`

Todas as transições são CONDICIONAIS (`... where status = 'x'`). Se o ESP32 e
o morador encerrarem no mesmo segundo, só um UPDATE acerta a linha - e só ele
calcula o estorno. Sem isso, o estorno sairia em dobro.
"""

import math
import unicodedata
from datetime import timedelta

from fastapi import HTTPException

import cartoes
import carteira
import demanda
import dispositivos
from identidade import sessao_do_usuario, veiculo_do_usuario
from config import (MAX_TENTATIVAS_CARTAO, MODO_DEMO, RESERVA_MINIMA, SEGUNDOS_ESPERA_CARTAO,
                    agora, agora_iso, para_datetime, supabase, um)
from fisica import (calcular_estimativa, custo_da_sessao, detalhar_custo, economia_vs_so_rede,
                    em_horario_de_ponta, multiplicador_ponta, tarifa_base)

LIMIAR_BAIXA_POTENCIA_KW = 0.0005      # 0,5 W BRUTOS (domínio do sensor): o celular parou de puxar
SEGUNDOS_BAIXA_POTENCIA = 30

# Sessões vivas: ocupam a vaga e o veículo (índices únicos do db/17).
STATUS_VIVOS = ("aguardando_rfid", "carregando", "aguardando_energia")
# Tag-primeiro sem % conhecido do veículo: ponto de partida conservador, ESTIMADO.
SOC_PADRAO_TAG = 20.0


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def carregador(carregador_id: str) -> dict:
    c = um(supabase.table("carregadores").select("*").eq("id", carregador_id).execute())
    if not c:
        raise HTTPException(status_code=404, detail="Carregador não encontrado.")
    return c


def condominio_de(charger: dict) -> dict | None:
    return um(supabase.table("condominios").select("*").eq("id", charger["condominio_id"]).execute())


def veiculo(veiculo_id: str) -> dict | None:
    return um(supabase.table("veiculos").select("*").eq("id", veiculo_id).execute())


def sessao(sessao_id: str) -> dict | None:
    return um(supabase.table("sessoes_recarga").select("*").eq("id", sessao_id).execute())


def notificar(usuario_id: str, mensagem: str) -> None:
    try:
        supabase.table("notificacoes").insert(
            {"usuario_id": usuario_id, "mensagem": mensagem, "lida": False}).execute()
    except Exception as e:
        print(f"[NOTIFICACAO] falhou: {e}")


def brl(valor) -> str:
    return f"R$ {float(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def energia_legivel(kwh) -> str:
    kwh = float(kwh or 0)
    if kwh < 1:
        return f"{kwh * 1000:.1f} Wh".replace(".", ",")
    return f"{kwh:.2f} kWh".replace(".", ",")


# ---------------------------------------------------------------------------
# Validações de compatibilidade
# ---------------------------------------------------------------------------

def checar_compatibilidade(charger: dict, v: dict) -> None:
    """Carro de 40 kWh numa porta USB de 25 W levaria dias. Não deixamos."""
    if charger.get("perfil") == "bancada" and v.get("tipo") != "celular":
        raise HTTPException(status_code=400, detail=(
            "Este ponto é a bancada USB do ESP32: só aceita dispositivos do tipo "
            "celular. Cadastre um em Meus Veículos."))


def checar_concorrencia(veiculo_id: str) -> None:
    ativa = supabase.table("sessoes_recarga").select("id").eq("veiculo_id", veiculo_id) \
        .in_("status", list(STATUS_VIVOS)).execute()
    if ativa.data:
        raise HTTPException(status_code=409, detail=(
            "Esse veículo já tem uma recarga em andamento ou aguardando cartão."))


def checar_ponto_utilizavel(charger: dict) -> None:
    if charger["status"] == "em_uso":
        raise HTTPException(status_code=409, detail="Carregador já está em uso.")
    if charger["status"] == "offline" and (charger.get("origem") != "hardware" or not MODO_DEMO):
        raise HTTPException(status_code=503, detail=(
            "Este carregador está offline no momento. Tente outro ponto."))


# ---------------------------------------------------------------------------
# Prévia
# ---------------------------------------------------------------------------

def previa(usuario: dict, charger_id: str, veiculo_id: str, soc: float, alvo: float) -> dict:
    charger = carregador(charger_id)
    v = veiculo_do_usuario(veiculo_id, usuario["id"])
    checar_compatibilidade(charger, v)
    cond = condominio_de(charger)

    admissao = {"ok": True, "mensagem": None}
    alocada = None
    try:
        alocada = demanda.verificar_admissao(charger["condominio_id"], charger, v, soc)
    except HTTPException as e:
        admissao = {"ok": False, "mensagem": e.detail}

    est = calcular_estimativa(charger, v, soc, alvo, cond, potencia_alocada_kw=alocada)
    est.update({
        "saldo": usuario["saldo"],
        "saldo_suficiente": usuario["saldo"] >= est["custo_estimado"],
        # O que sai do saldo ao aproximar o cartão (a diferença volta no fim).
        "valor_reserva": valor_da_reserva(est["custo_estimado"], usuario["saldo"]),
        "admissao": admissao,
        "potencia_prevista_kw": alocada,
        "perfil_carregador": charger.get("perfil"),
        "leitor_fisico": charger.get("origem") == "hardware",
    })
    return est


def valor_da_reserva(custo_estimado: float, saldo: float) -> float:
    """
    Reserva de piso (ver config.RESERVA_MINIMA), limitada ao que a pessoa
    tem: nunca menos que a estimativa, nunca mais que o saldo acima do piso.
    """
    return round(max(float(custo_estimado), min(RESERVA_MINIMA, float(saldo or 0))), 2)


class SessaoDuplicada(Exception):
    pass


def _inserir_sessao(dados: dict) -> dict:
    try:
        return um(supabase.table("sessoes_recarga").insert(dados).execute())
    except Exception as e:
        texto = str(e)
        if "uq_sessao_viva" in texto or "23505" in texto or "duplicate key" in texto:
            raise SessaoDuplicada() from e
        raise


def _sair_de_todas_as_filas(usuario_id: str) -> None:
    """Começou a carregar: não faz sentido continuar na fila (de nenhum ponto)."""
    try:
        minhas = supabase.table("fila").select("carregador_id").eq("usuario_id", usuario_id).execute().data or []
        for carregador_id in {f["carregador_id"] for f in minhas}:
            supabase.table("fila").delete().eq("carregador_id", carregador_id) \
                .eq("usuario_id", usuario_id).execute()
            _renumerar_fila(carregador_id)
    except Exception as e:
        print(f"[FILA] limpeza falhou: {e}")


# ---------------------------------------------------------------------------
# Preparar
# ---------------------------------------------------------------------------

def preparar(usuario: dict, charger_id: str, veiculo_id: str, soc: float, alvo: float) -> dict:
    charger = carregador(charger_id)
    checar_ponto_utilizavel(charger)
    v = veiculo_do_usuario(veiculo_id, usuario["id"])
    checar_compatibilidade(charger, v)

    soc = max(0.0, min(99.0, float(soc)))
    alvo = max(1.0, min(100.0, float(alvo)))
    if alvo <= soc:
        raise HTTPException(status_code=400, detail="O alvo precisa ser maior que a bateria atual.")

    fisico = charger.get("origem") == "hardware"

    ja = supabase.table("sessoes_recarga").select("id, usuario_id").eq("carregador_id", charger_id) \
        .eq("status", "aguardando_rfid").execute()
    if ja.data:
        dono = ja.data[0]["usuario_id"] == usuario["id"]
        raise HTTPException(status_code=409, detail=(
            "Você já tem uma recarga aguardando cartão neste ponto." if dono
            else "Outro morador está aguardando o cartão neste ponto."))

    checar_concorrencia(veiculo_id)

    cond = condominio_de(charger)
    try:
        alocada = demanda.verificar_admissao(charger["condominio_id"], charger, v, soc)
    except HTTPException as e:
        if e.status_code == 409:
            demanda.registrar_recusa(charger["condominio_id"], usuario["id"], charger_id, "preparar")
        raise
    est = calcular_estimativa(charger, v, soc, alvo, cond, potencia_alocada_kw=alocada)

    # Ponto físico: quem decide o saldo é o CARTÃO (fluxo pedido pela banca:
    # pedido -> cartão -> verifica saldo -> sem saldo, pede para adicionar).
    # Aqui só avisamos; a tela já mostra "saldo insuficiente" com o botão de
    # adicionar. Ponto simulado confirma na hora e recusa em confirmar().
    saldo_suficiente = usuario["saldo"] >= est["custo_estimado"]

    expira = agora() + timedelta(seconds=SEGUNDOS_ESPERA_CARTAO)
    congelados = {}
    # Preço solar congelado no início, como a tarifa da rede (ADR-016 D6).
    # Só com a coluna presente: sem o 16, o insert segue igual ao de antes.
    if (cond or {}).get("preco_solar_kwh") is not None:
        congelados["tarifa_solar_kwh"] = float(cond["preco_solar_kwh"])
    try:
        nova = _inserir_sessao({
            **congelados,
            "carregador_id": charger_id,
            "veiculo_id": veiculo_id,
            "usuario_id": usuario["id"],
            "status": "aguardando_rfid",
            "percentual_bateria_inicial": soc,
            "percentual_bateria_atual": soc,
            "alvo_percentual": alvo,
            "tempo_estimado_min": est["tempo_estimado_min"],
            "custo_estimado": est["custo_estimado"],
            "tarifa_kwh": tarifa_base(charger),
            "multiplicador_ponta": multiplicador_ponta(cond),
            "origem": "hardware" if fisico else "simulado",
            "expira_em": expira.isoformat(),
        })
    except SessaoDuplicada:
        # Dois cliques (ou dois moradores) no mesmo segundo: o índice único
        # da migration 14 deixa só um passar.
        raise HTTPException(status_code=409, detail=(
            "Este ponto ou este veículo acabou de receber outra recarga. Atualize a tela."))

    if fisico:
        dispositivos.enfileirar(charger_id, "solicitar_cartao", nova["id"],
                                dispositivos.payload_pedido(nova))
        # Existe algum cartão que consiga liberar esta recarga? O pessoal
        # dela, ou o compartilhado do condomínio. Se não houver, a tela avisa
        # antes de o morador ficar dois minutos encostando plástico à toa.
        tem_cartao = bool(cartoes.do_usuario(usuario["id"])
                          or cartoes.do_condominio(charger["condominio_id"]))
        return {"sessao": nova, "estimativa": est, "aguardando_cartao": True,
                "saldo_suficiente": saldo_suficiente, "cartao_disponivel": tem_cartao,
                "segundos_para_aproximar": SEGUNDOS_ESPERA_CARTAO}

    # Ponto simulado não tem leitor: o próprio app autoriza.
    resultado = confirmar(nova, metodo="app")
    if not resultado.get("autorizado"):
        raise HTTPException(status_code=402 if resultado.get("motivo") == "saldo_insuficiente"
                            else 409, detail=resultado["mensagem"])
    return {"sessao": resultado["sessao"], "estimativa": est, "aguardando_cartao": False,
            "saldo_atual": resultado["saldo_atual"]}


# ---------------------------------------------------------------------------
# Cartão
# ---------------------------------------------------------------------------

def sessao_aguardando(carregador_id: str) -> dict | None:
    return um(supabase.table("sessoes_recarga").select("*").eq("carregador_id", carregador_id)
              .eq("status", "aguardando_rfid").order("criado_em", desc=True).limit(1).execute())


def sessao_ativa_do_carregador(carregador_id: str) -> dict | None:
    return um(supabase.table("sessoes_recarga").select("*").eq("carregador_id", carregador_id)
              .eq("status", "carregando").order("iniciado_em", desc=True).limit(1).execute())


def processar_cartao(carregador_id: str, uid: str, esperar_energia: bool = False) -> dict:
    """
    Decisão do cartão (a rota já autenticou o dispositivo).

    Ordem: existe recarga preparada aqui? o cartão está cadastrado? ele pode
    confirmar ESTA recarga? o saldo de quem preparou cobre?

    Quem paga é sempre o dono da SESSÃO - nunca o dono do cartão. Com o cartão
    compartilhado do condomínio, isso é o que faz o mesmo plástico atender
    todo mundo: quem preparou no app é quem é cobrado.
    """
    try:
        uid = cartoes.normalizar(uid)
    except HTTPException:
        return {"autorizado": False, "motivo": "uid_invalido", "continuar_aguardando": True,
                "mensagem": "Leitura do cartão veio corrompida. Aproxime de novo."}
    s = sessao_aguardando(carregador_id)
    if not s:
        return {"autorizado": False, "motivo": "sem_recarga_preparada",
                "mensagem": "Nenhuma recarga preparada aqui. Use o app primeiro.", "uid": uid}

    charger = carregador(carregador_id)
    cartao = cartoes.por_uid(uid)

    if not cartao:
        # Guarda o uid na sessão: o app mostra "cartão XXXX não cadastrado"
        # com o botão de cadastrar, sem ninguém abrir o monitor serial.
        supabase.table("sessoes_recarga").update({
            "ultimo_uid_lido": uid, "motivo_recusa": "cartao_nao_cadastrado",
        }).eq("id", s["id"]).eq("status", "aguardando_rfid").execute()
        return {"autorizado": False, "motivo": "cartao_nao_cadastrado", "continuar_aguardando": True,
                "uid": uid,
                "mensagem": f"Cartão {uid} não cadastrado. Cadastre-o pelo app e aproxime de novo."}

    pode, recusa = cartoes.autoriza(cartao, s, charger["condominio_id"])
    if not pode:
        # NÃO cancela a espera do dono e NÃO cobra o dono do cartão.
        supabase.table("sessoes_recarga").update({"ultimo_uid_lido": uid}) \
            .eq("id", s["id"]).eq("status", "aguardando_rfid").execute()
        mensagens = {
            "cartao_de_outro_usuario": "Este cartão é pessoal de outro morador.",
            "cartao_de_outro_condominio": "Este cartão pertence a outro condomínio.",
        }
        return {"autorizado": False, "motivo": recusa, "continuar_aguardando": True,
                "mensagem": mensagens.get(recusa, "Cartão não autorizado aqui.")}

    cartoes.marcar_uso(uid)
    supabase.table("sessoes_recarga").update({"ultimo_uid_lido": uid}) \
        .eq("id", s["id"]).eq("status", "aguardando_rfid").execute()
    return confirmar({**s, "ultimo_uid_lido": uid}, metodo=f"rfid_{cartao['escopo']}",
                     esperar_energia=esperar_energia)


def confirmar(s: dict, metodo: str, esperar_energia: bool = False) -> dict:
    """
    Pré-autoriza o saldo e promove a sessão para `carregando`, no lugar.

    Ordem importa: DEBITA primeiro, depois tenta promover com a condição
    `status = aguardando_rfid`. Se a promoção não pegar nenhuma linha (a
    espera expirou ou outro cartão confirmou no mesmo instante), o valor
    volta na hora. O contrário - promover e depois debitar - faria o navegador
    ver "carregando" pelo Realtime antes de sabermos se havia saldo.

    `esperar_energia` (Totem v2.1): sem orçamento no alocador, a sessão vai
    para `aguardando_energia` com o saldo reservado e o relé desligado, em vez
    de ser cancelada. O laço e o fim das outras recargas ligam depois.
    """
    charger = carregador(s["carregador_id"])
    v = veiculo(s["veiculo_id"]) or {}
    cond = condominio_de(charger)
    soc = float(s.get("percentual_bateria_inicial") or 0)
    alvo = float(s.get("alvo_percentual") or 100)

    # A demanda pode ter mudado enquanto o morador caminhava até o ponto.
    admitida = True
    try:
        alocada = demanda.verificar_admissao(charger["condominio_id"], charger, v, soc)
    except HTTPException as e:
        demanda.registrar_recusa(charger["condominio_id"], s["usuario_id"], charger["id"], "cartao")
        if not esperar_energia:
            _encerrar_espera(s, "cancelada", "limite_de_potencia")
            return {"autorizado": False, "motivo": "limite_de_potencia", "mensagem": e.detail}
        admitida, alocada = False, None
    # Quem já está na fila de energia passa na frente (ordem de chegada).
    if admitida and esperar_energia and ha_fila_de_energia(charger["condominio_id"]):
        admitida, alocada = False, None

    est = calcular_estimativa(charger, v, soc, alvo, cond, potencia_alocada_kw=alocada)
    valor = valor_da_reserva(est["custo_estimado"], carteira.saldo_de(s["usuario_id"]))

    try:
        saldo = carteira.debitar(s["usuario_id"], valor, "pre_autorizacao",
                                 f"Reserva da recarga no ponto {charger['numero']}", s["id"])
    except carteira.SaldoInsuficiente:
        return _recusar_por_saldo(s, est["custo_estimado"], metodo)

    fisico = charger.get("origem") == "hardware"
    dados = {
        "status": "carregando" if admitida else "aguardando_energia",
        "expira_em": None,
        "motivo_recusa": None,
        "ultimo_uid_lido": None,
        "uid_inicio": s.get("ultimo_uid_lido"),
        "custo_estimado": est["custo_estimado"],
        "valor_pre_autorizado": valor,
        "tempo_estimado_min": est["tempo_estimado_min"],
        "potencia_alocada_kw": alocada,
        "potencia_atual_kw": 0 if (fisico or not admitida) else est["potencia_agora_kw"],
        "energia_entregue_kwh": 0,
        "energia_ponta_kwh": 0,
    }
    if admitida:
        dados["iniciado_em"] = agora_iso()
    promovida = supabase.table("sessoes_recarga").update(dados) \
        .eq("id", s["id"]).eq("status", "aguardando_rfid").execute()

    if not promovida.data:
        carteira.creditar(s["usuario_id"], valor, "estorno", "Espera encerrada antes do cartão", s["id"])
        return {"autorizado": False, "motivo": "espera_encerrada",
                "mensagem": "A espera por este cartão já tinha terminado."}

    supabase.table("pagamentos").insert({
        "sessao_id": s["id"], "valor": valor, "metodo": metodo, "status": "pre_autorizado",
    }).execute()
    supabase.table("veiculos").update({"percentual_bateria": soc}).eq("id", s["veiculo_id"]).execute()
    supabase.table("carregadores").update({"status": "em_uso"}).eq("id", charger["id"]).execute()
    _sair_de_todas_as_filas(s["usuario_id"])

    nome = (um(supabase.table("usuarios").select("nome").eq("id", s["usuario_id"]).execute()) or {}).get("nome", "")
    primeiro = nome.split()[0] if nome else "morador"
    resposta = {
        "autorizado": True,
        "mensagem": f"Bem-vindo, {primeiro}! Recarga liberada.",
        "sessao_id": s["id"],
        "sessao": um(promovida),
        "saldo_atual": saldo,
        "valor_reservado": valor,
    }
    if admitida:
        # Ponto físico: AQUI a energia começa a correr de verdade.
        dispositivos.enfileirar(charger["id"], "liberar", s["id"])
        demanda.alocar(charger["condominio_id"])
        return resposta

    posicao = posicao_na_fila_de_energia(s["id"], charger["condominio_id"])
    resposta.update({
        "motivo": "aguardando_energia", "fila_posicao": posicao,
        "mensagem": (f"{primeiro}, o condomínio está no limite de potência agora. Sua recarga está "
                     f"reservada (posição {posicao} na fila) e liga sozinha quando houver energia."),
    })
    notificar(s["usuario_id"], resposta["mensagem"])
    return resposta


def _recusar_por_saldo(s: dict, valor: float, metodo: str) -> dict:
    """
    Sem saldo no cartão: a espera CONTINUA (prazo renovado) para o morador pôr
    saldo no app e aproximar de novo. Na terceira tentativa, recusa de vez.
    O navegador descobre pela própria linha da sessão (Realtime), porque quem
    recebe esta resposta é a placa, não o celular do morador.
    """
    tentativas = int(s.get("tentativas_cartao") or 0) + 1
    if not metodo.startswith("rfid_") or tentativas >= MAX_TENTATIVAS_CARTAO:
        _encerrar_espera(s, "recusada", "saldo_insuficiente", tentativas)
        return {"autorizado": False, "motivo": "saldo_insuficiente", "continuar_aguardando": False,
                "mensagem": f"Saldo insuficiente para reservar {brl(valor)}. Recarga recusada."}

    supabase.table("sessoes_recarga").update({
        "motivo_recusa": "saldo_insuficiente",
        "tentativas_cartao": tentativas,
        "custo_estimado": valor,
        "expira_em": (agora() + timedelta(seconds=SEGUNDOS_ESPERA_CARTAO)).isoformat(),
    }).eq("id", s["id"]).eq("status", "aguardando_rfid").execute()

    return {"autorizado": False, "motivo": "saldo_insuficiente", "continuar_aguardando": True,
            "tentativas_restantes": MAX_TENTATIVAS_CARTAO - tentativas,
            "mensagem": f"Saldo insuficiente ({brl(valor)}). Adicione saldo no app e aproxime de novo."}


def _encerrar_espera(s: dict, status: str, motivo: str, tentativas: int | None = None) -> bool:
    dados = {"status": status, "motivo_recusa": motivo, "finalizado_em": agora_iso()}
    if tentativas is not None:
        dados["tentativas_cartao"] = tentativas
    r = supabase.table("sessoes_recarga").update(dados).eq("id", s["id"]) \
        .eq("status", "aguardando_rfid").execute()
    if r.data:
        dispositivos.enfileirar(s["carregador_id"], "cancelar_cartao", s["id"], {"motivo": motivo})
    return bool(r.data)


def cancelar_espera(usuario: dict, sessao_id: str) -> dict:
    s = sessao_do_usuario(sessao_id, usuario["id"])
    if s["status"] != "aguardando_rfid":
        return {"success": True, "ja_encerrada": True}
    _encerrar_espera(s, "cancelada", "cancelado_pelo_usuario")
    return {"success": True}


def expirar_esperas() -> None:
    vencidas = supabase.table("sessoes_recarga").select("*").eq("status", "aguardando_rfid") \
        .lt("expira_em", agora_iso()).execute()
    for s in (vencidas.data or []):
        # Expirou DEPOIS de uma recusa por saldo: conta como recusa, não
        # desistência - é o número que interessa na análise do histórico.
        if s.get("motivo_recusa") == "saldo_insuficiente":
            _encerrar_espera(s, "recusada", "saldo_insuficiente")
        else:
            _encerrar_espera(s, "cancelada", "tempo_esgotado")
        print(f"[RECARGA] espera de cartão expirada: {s['id']}")


# ---------------------------------------------------------------------------
# Progresso (simulador e ESP32 passam pelo MESMO lugar)
# ---------------------------------------------------------------------------

def registrar_progresso(s: dict, v: dict, cond: dict | None, energia_total_kwh: float,
                        potencia_kw: float, soc: float | None, tempo_min: int | None,
                        potencia_media_kw: float | None = None, fracao_solar: float = 0.0,
                        origem_solar: str | None = None) -> str | None:
    """
    Grava uma leitura na sessão e decide se ela acabou. Devolve o motivo do
    encerramento (e encerra) ou None.

    Cada kWh novo é separado em três baldes que nunca se misturam (ADR-016):
      solar        a fração que o alocador deu do excedente FV
      rede ponta   o resto, se chegou no horário de ponta
      rede fora    o resto, fora da ponta
    Uma recarga que começa às 17h e termina às 19h paga cada kWh pelo preço
    da fonte e do horário em que ele foi entregue.
    """
    atual = float(s.get("energia_entregue_kwh") or 0)
    energia_total_kwh = max(atual, float(energia_total_kwh))     # monotônica
    delta = energia_total_kwh - atual
    ponta = em_horario_de_ponta(cond)

    fracao = min(1.0, max(0.0, float(fracao_solar or 0)))
    delta_solar = delta * fracao
    delta_rede = delta - delta_solar

    update = {
        "energia_entregue_kwh": round(energia_total_kwh, 6),
        "potencia_atual_kw": round(max(0.0, float(potencia_kw or 0)), 5),
    }
    solar_total = float(s.get("energia_solar_kwh") or 0)
    if delta_solar > 0:
        solar_total = min(energia_total_kwh, solar_total + delta_solar)
        update["energia_solar_kwh"] = round(solar_total, 6)
        update["origem_solar"] = origem_solar or s.get("origem_solar") or "simulado"
        if s.get("tarifa_solar_kwh") is None and (cond or {}).get("preco_solar_kwh") is not None:
            update["tarifa_solar_kwh"] = float(cond["preco_solar_kwh"])
    if ponta and delta_rede > 0:
        # Ponta conta só REDE, e a soma das fontes nunca passa do total.
        ponta_total = float(s.get("energia_ponta_kwh") or 0) + delta_rede
        update["energia_ponta_kwh"] = round(max(0.0, min(ponta_total, energia_total_kwh - solar_total)), 6)
    if soc is not None:
        update["percentual_bateria_atual"] = round(soc, 1)
    if tempo_min is not None:
        update["tempo_estimado_min"] = int(tempo_min)
    if potencia_media_kw is not None:
        update["potencia_media_kw"] = round(potencia_media_kw, 5)

    if delta > 0 and cond:
        demanda.registrar_consumo(cond["id"], delta, ponta, 0, solar_kwh=delta_solar)

    supabase.table("sessoes_recarga").update(update).eq("id", s["id"]) \
        .eq("status", "carregando").execute()

    merged = {**s, **update}
    alvo = float(s.get("alvo_percentual") or 100)
    reservado = float(s.get("valor_pre_autorizado") or 0)

    motivo = None
    # % ESTIMADO (tag-primeiro) não encerra recarga: quem diz que acabou é a
    # medição (D2), a tag ou o teto do valor reservado.
    estimado = s.get("percentual_origem") == "estimado"
    if soc is not None and not estimado and soc >= alvo - 0.05:
        motivo = "alvo_atingido" if alvo < 100 else "bateria_cheia"
    elif reservado > 0 and custo_da_sessao(merged) >= reservado:
        motivo = "limite_pre_autorizado"

    if motivo:
        encerrar(merged, motivo)
    return motivo


def resumo_por_fonte(sessao: dict) -> str:
    """'3,20 kWh solar (simulado) a R$ 0,75 + 4,10 kWh rede a R$ 1,15' - para notificação."""
    partes = []
    for it in detalhar_custo(sessao)["itens"]:
        if it["origem"].startswith("solar_"):
            nome = f"solar ({it['origem'].removeprefix('solar_')})"
        else:
            nome = "rede na ponta" if it["faixa"] == "ponta" else "rede"
        partes.append(f"{energia_legivel(it['energia_kwh'])} {nome} a {brl(it['tarifa_kwh'])}/kWh")
    return " + ".join(partes)


# ---------------------------------------------------------------------------
# Encerrar
# ---------------------------------------------------------------------------

MENSAGEM_MOTIVO = {
    "usuario": "encerrada por você",
    "alvo_atingido": "alvo de carga atingido",
    "bateria_cheia": "bateria cheia",
    "dispositivo_carregado": "o dispositivo parou de puxar energia (carga completa)",
    "limite_pre_autorizado": "valor reservado atingido",
    "dispositivo_offline": "o ponto perdeu a conexão",
    "tag": "encerrada pela sua tag no totem",
    "sistema": "encerrada pelo sistema",
}


def encerrar(s: dict, motivo: str) -> dict:
    """Idempotente: a segunda chamada para a mesma sessão não faz nada."""
    atual = sessao(s["id"]) or s
    if atual.get("status") != "carregando":
        return {"success": True, "ja_encerrada": True}

    reservado = float(atual.get("valor_pre_autorizado") or 0)
    custo = custo_da_sessao(atual)
    if reservado > 0:
        custo = min(custo, reservado)

    fechada = supabase.table("sessoes_recarga").update({
        "status": "finalizada",
        "finalizado_em": agora_iso(),
        "custo_final": custo,
        "encerrado_por": motivo,
        "potencia_atual_kw": 0,
        "tempo_estimado_min": 0,
    }).eq("id", atual["id"]).eq("status", "carregando").execute()
    if not fechada.data:
        return {"success": True, "ja_encerrada": True}

    estorno = round(max(0.0, reservado - custo), 2)
    if estorno > 0:
        carteira.creditar(atual["usuario_id"], estorno, "estorno",
                          "Devolução da diferença entre o reservado e o consumido", atual["id"])
    supabase.table("sessoes_recarga").update({"valor_estornado": estorno}).eq("id", atual["id"]).execute()
    supabase.table("pagamentos").update({"valor": custo, "status": "capturado"}) \
        .eq("sessao_id", atual["id"]).execute()

    charger = carregador(atual["carregador_id"])
    # Terminou sozinha num ponto simulado: o carro continua plugado. A vaga
    # só libera quando o morador avisa (liberar_vaga) - até lá corre a taxa.
    fica_na_vaga = (motivo in MOTIVOS_CARRO_FICA and charger.get("origem") != "hardware"
                    and _tem_ociosidade())
    if fica_na_vaga:
        supabase.table("sessoes_recarga").update({"vaga_ocupada_desde": agora_iso()}) \
            .eq("id", atual["id"]).execute()
    elif charger["status"] != "offline":
        supabase.table("carregadores").update({"status": "disponivel"}).eq("id", charger["id"]).execute()
    if atual.get("percentual_bateria_atual") is not None:
        supabase.table("veiculos").update({"percentual_bateria": atual["percentual_bateria_atual"]}) \
            .eq("id", atual["veiculo_id"]).execute()

    dispositivos.enfileirar(charger["id"], "bloquear", atual["id"])

    fontes = resumo_por_fonte(atual)
    notificar(atual["usuario_id"], (
        f"Recarga no ponto {charger['numero']} finalizada ({MENSAGEM_MOTIVO.get(motivo, motivo)}): "
        f"{fontes or energia_legivel(atual.get('energia_entregue_kwh'))}, custo {brl(custo)}"
        + (f", estorno de {brl(estorno)} já na sua carteira." if estorno > 0 else ".")))

    if fica_na_vaga:
        p = politica_ociosidade(condominio_de(charger))
        notificar(atual["usuario_id"], (
            f"Retire o carro do ponto {charger['numero']}: a vaga fica sem custo por "
            f"{p['tolerancia_min']} min. Depois disso, taxa de ociosidade de "
            f"{brl(p['taxa_por_min'])}/min (máximo {brl(p['teto'])}). "
            "Toque em \"Já retirei o carro\" no app."))
    else:
        avisar_proximo_da_fila(charger["id"])
    demanda.alocar(charger["condominio_id"])
    _promover_sem_derrubar(charger["condominio_id"])
    print(f"[RECARGA] {atual['id']} encerrada ({motivo}) custo={custo} estorno={estorno}")
    return {"success": True, "custo_final": custo, "estorno": estorno, "motivo": motivo}


# ---------------------------------------------------------------------------
# Taxa de ociosidade (db/21) - só pontos SIMULADOS
# ---------------------------------------------------------------------------
# Encerrar pelo app ("usuario") conta como "estou no carro": a vaga libera na
# hora. Só quem deixa a recarga terminar sozinha pode ter esquecido o carro.
MOTIVOS_CARRO_FICA = ("bateria_cheia", "alvo_atingido", "limite_pre_autorizado")
# Carro "esquecido" para sempre travaria o ponto simulado: o sistema libera
# sozinho depois disto, cobrando a taxa (que já parou no teto).
HORAS_LIBERACAO_AUTOMATICA = 6
_ociosidade_no_banco = None


def _tem_ociosidade() -> bool:
    """O db/21 já rodou? Sem ele, a vaga libera na hora, como antes."""
    global _ociosidade_no_banco
    if _ociosidade_no_banco is None:
        try:
            supabase.table("sessoes_recarga").select("vaga_ocupada_desde").limit(1).execute()
            _ociosidade_no_banco = True
        except Exception:
            _ociosidade_no_banco = False
    return _ociosidade_no_banco


def politica_ociosidade(cond: dict | None) -> dict:
    c = cond or {}

    def campo(nome, padrao):
        return padrao if c.get(nome) is None else c[nome]
    return {"tolerancia_min": int(campo("tolerancia_ociosidade_min", 15)),
            "taxa_por_min": round(float(campo("taxa_ociosidade_min", 0.50)), 2),
            "teto": round(float(campo("teto_ociosidade", 60.00)), 2)}


def calcular_ociosidade(s: dict, cond: dict | None, ate=None) -> dict:
    """Minuto COMEÇADO depois da tolerância conta inteiro (como Tesla e EA)."""
    p = politica_ociosidade(cond)
    desde = para_datetime(s.get("vaga_ocupada_desde"))
    if not desde:
        return {**p, "minutos_parado": 0, "minutos_cobrados": 0, "valor": 0.0, "cobra_a_partir_de": None}
    fim = ate or para_datetime(s.get("vaga_liberada_em")) or agora()
    parado = max(0.0, (fim - desde).total_seconds() / 60)
    cobrados = max(0, math.ceil(parado - p["tolerancia_min"] - 1e-9))
    return {**p, "minutos_parado": round(parado, 1), "minutos_cobrados": cobrados,
            "valor": round(min(p["teto"], cobrados * p["taxa_por_min"]), 2),
            "cobra_a_partir_de": (desde + timedelta(minutes=p["tolerancia_min"])).isoformat()}


def _ociosas(usuario_id: str | None = None) -> list[dict]:
    if not _tem_ociosidade():
        return []
    q = supabase.table("sessoes_recarga").select("*").not_.is_("vaga_ocupada_desde", "null") \
        .is_("vaga_liberada_em", "null")
    if usuario_id:
        q = q.eq("usuario_id", usuario_id)
    return q.execute().data or []


def vaga_ocupada_do_usuario(usuario_id: str) -> dict | None:
    """A recarga que terminou e cujo carro ainda está na vaga, com a taxa ao vivo."""
    s = next(iter(_ociosas(usuario_id)), None)
    if not s:
        return None
    charger = carregador(s["carregador_id"])
    return {"sessao_id": s["id"], "carregador_id": charger["id"], "carregador": charger.get("numero"),
            "finalizado_em": s.get("finalizado_em"), "vaga_ocupada_desde": s["vaga_ocupada_desde"],
            **calcular_ociosidade(s, condominio_de(charger))}


def _fechar_vaga(s: dict, por: str) -> dict:
    """Uma vez só por sessão (UPDATE condicional), como o encerrar()."""
    momento = agora()
    marcada = supabase.table("sessoes_recarga").update({"vaga_liberada_em": momento.isoformat()}) \
        .eq("id", s["id"]).is_("vaga_liberada_em", "null").execute()
    if not marcada.data:
        return {"success": True, "ja_liberada": True}

    charger = carregador(s["carregador_id"])
    conta = calcular_ociosidade(s, condominio_de(charger), ate=momento)
    valor, cobrado = conta["valor"], 0.0
    if valor > 0:
        descricao = (f"Taxa de ociosidade - ponto {charger['numero']}, "
                     f"{conta['minutos_cobrados']} min após a tolerância")
        try:
            carteira.debitar(s["usuario_id"], valor, "taxa_ociosidade", descricao, s["id"])
            cobrado = valor
        except carteira.SaldoInsuficiente:
            # Cobra o que houver; o resto fica registrado como pendente.
            disponivel = carteira.saldo_de(s["usuario_id"])
            if disponivel > 0:
                carteira.debitar(s["usuario_id"], disponivel, "taxa_ociosidade",
                                 descricao + " (parcial)", s["id"])
                cobrado = disponivel
    supabase.table("sessoes_recarga").update({"taxa_ociosidade": valor,
                                              "taxa_ociosidade_cobrada": round(cobrado, 2)}) \
        .eq("id", s["id"]).execute()

    if charger["status"] == "em_uso" and not sessao_viva_na_vaga(charger["id"]):
        supabase.table("carregadores").update({"status": "disponivel"}).eq("id", charger["id"]).execute()
    pendente = round(valor - cobrado, 2)
    quem = "pelo sistema" if por == "sistema" else "por você"
    notificar(s["usuario_id"], (
        f"Vaga do ponto {charger['numero']} liberada {quem} após {conta['minutos_parado']:.0f} min. "
        + (f"Taxa de ociosidade: {brl(cobrado)}." if valor > 0 else "Sem taxa de ociosidade.")
        + (f" {brl(pendente)} ficaram pendentes por falta de saldo." if pendente > 0 else "")))
    avisar_proximo_da_fila(charger["id"])
    demanda.alocar(charger["condominio_id"])
    print(f"[OCIOSIDADE] {s['id']} vaga liberada ({por}) taxa={valor} cobrado={cobrado}")
    return {"success": True, "taxa": valor, "cobrado": round(cobrado, 2), "pendente": pendente,
            "minutos_parado": conta["minutos_parado"]}


def liberar_vaga(usuario: dict, sessao_id: str) -> dict:
    s = sessao_do_usuario(sessao_id, usuario["id"])
    if not s.get("vaga_ocupada_desde") or s.get("vaga_liberada_em"):
        return {"success": True, "ja_liberada": True}
    return _fechar_vaga(s, "usuario")


def atualizar_ociosas() -> None:
    """Laço de 10 s: taxa ao vivo na sessão, aviso quando a tolerância acaba."""
    for s in _ociosas():
        charger = carregador(s["carregador_id"])
        conta = calcular_ociosidade(s, condominio_de(charger))
        if conta["minutos_parado"] >= HORAS_LIBERACAO_AUTOMATICA * 60:
            _fechar_vaga(s, "sistema")
            continue
        anterior = float(s.get("taxa_ociosidade") or 0)
        if conta["valor"] != anterior:
            supabase.table("sessoes_recarga").update({"taxa_ociosidade": conta["valor"]}) \
                .eq("id", s["id"]).is_("vaga_liberada_em", "null").execute()
        if anterior == 0 and conta["valor"] > 0:
            notificar(s["usuario_id"], (
                f"A tolerância do ponto {charger['numero']} acabou: a taxa de ociosidade "
                f"({brl(conta['taxa_por_min'])}/min) começou a contar. Retire o carro."))



def encerrar_pelo_usuario(usuario: dict, sessao_id: str) -> dict:
    s = sessao_do_usuario(sessao_id, usuario["id"])
    if s.get("status") == "aguardando_energia":
        return cancelar_aguardando_energia(s, "cancelado_pelo_usuario")
    return encerrar(s, "usuario")


# ---------------------------------------------------------------------------
# Fila
# ---------------------------------------------------------------------------

def avisar_proximo_da_fila(carregador_id: str) -> None:
    primeiro = um(supabase.table("fila").select("*").eq("carregador_id", carregador_id)
                  .order("posicao").limit(1).execute())
    if not primeiro:
        return
    c = um(supabase.table("carregadores").select("numero").eq("id", carregador_id).execute()) or {}
    notificar(primeiro["usuario_id"],
              f"O carregador {c.get('numero', '?')} liberou. É a sua vez na fila.")


def entrar_fila(usuario: dict, carregador_id: str) -> dict:
    carregador(carregador_id)
    ja = supabase.table("fila").select("id").eq("carregador_id", carregador_id) \
        .eq("usuario_id", usuario["id"]).execute()
    if ja.data:
        raise HTTPException(status_code=409, detail="Você já está nessa fila.")
    atual = supabase.table("fila").select("posicao").eq("carregador_id", carregador_id).execute()
    posicao = max([f["posicao"] for f in (atual.data or [])], default=0) + 1
    supabase.table("fila").insert({"carregador_id": carregador_id, "usuario_id": usuario["id"],
                                   "posicao": posicao}).execute()
    return {"success": True, "posicao": posicao}


def sair_fila(usuario: dict, carregador_id: str) -> dict:
    supabase.table("fila").delete().eq("carregador_id", carregador_id) \
        .eq("usuario_id", usuario["id"]).execute()
    _renumerar_fila(carregador_id)
    return {"success": True}


def _renumerar_fila(carregador_id: str) -> None:
    restantes = supabase.table("fila").select("id").eq("carregador_id", carregador_id) \
        .order("posicao").execute()
    for i, f in enumerate(restantes.data or [], start=1):
        supabase.table("fila").update({"posicao": i}).eq("id", f["id"]).execute()


# ---------------------------------------------------------------------------
# Recibo - "como a cobrança funciona", com os números da recarga da pessoa
# ---------------------------------------------------------------------------

def recibo(usuario: dict, sessao_id: str) -> dict:
    """
    A conta linha a linha: energia fora e dentro da ponta, tarifa de cada
    uma, subtotal, reservado, cobrado, devolvido - e as movimentações da
    carteira que provam cada passo. É a resposta concreta para "como vocês
    cobram?".
    """
    s = sessao_do_usuario(sessao_id, usuario["id"])
    charger = carregador(s["carregador_id"])
    linhas = detalhar_custo(s)
    reservado = float(s.get("valor_pre_autorizado") or 0)
    finalizada = s.get("status") == "finalizada"
    cobrado = float(s.get("custo_final") or 0) if finalizada else min(linhas["total"], reservado or linhas["total"])
    movimentos = supabase.table("movimentacoes_carteira").select(
        "tipo, valor, saldo_apos, descricao, criado_em"
    ).eq("sessao_id", sessao_id).eq("usuario_id", usuario["id"]).order("criado_em").execute().data or []

    inicio, fim = para_datetime(s.get("iniciado_em")), para_datetime(s.get("finalizado_em"))
    duracao = round((fim - inicio).total_seconds() / 60, 1) if inicio and fim else None
    energia = linhas["energia_kwh"]
    return {
        "sessao_id": sessao_id,
        "status": s.get("status"),
        "carregador": charger.get("numero"),
        "iniciado_em": s.get("iniciado_em"),
        "finalizado_em": s.get("finalizado_em"),
        "duracao_min": duracao,
        "encerrado_por": s.get("encerrado_por"),
        "motivo_legivel": MENSAGEM_MOTIVO.get(s.get("encerrado_por"), s.get("encerrado_por")),
        "percentual_inicial": s.get("percentual_bateria_inicial"),
        "percentual_final": s.get("percentual_bateria_atual"),
        "linhas": linhas,
        "custo_estimado": s.get("custo_estimado"),
        "valor_reservado": round(reservado, 2),
        "valor_cobrado": round(cobrado, 2),
        "valor_estornado": round(float(s.get("valor_estornado") or 0), 2) if finalizada
                           else round(max(0.0, reservado - cobrado), 2),
        "limitado_pela_reserva": finalizada and reservado > 0 and linhas["total"] > reservado + 1e-9,
        "preco_medio_kwh": round(cobrado / energia, 4) if energia > 0 else None,
        # Uma linha por fonte, cada uma com origem e preço próprio (ADR-016).
        "itens": linhas["itens"],
        "economia_vs_so_rede": {"valor": economia_vs_so_rede(s), "origem": "estimado",
                                "explicacao": "kWh solar comparado com a tarifa da rede fora da ponta "
                                              "congelada nesta recarga."},
        "movimentacoes": movimentos,
        "ociosidade": (calcular_ociosidade(s, condominio_de(charger))
                       if s.get("vaga_ocupada_desde") else None),
    }


# ===========================================================================
# TOTEM v2.1 - tag primeiro, fila de energia (ADR-018)
# ===========================================================================

def sessao_viva_na_vaga(carregador_id: str) -> dict | None:
    """Quem ocupa a vaga: carregando ou esperando energia (o celular está plugado)."""
    return um(supabase.table("sessoes_recarga").select("*").eq("carregador_id", carregador_id)
              .in_("status", ["carregando", "aguardando_energia"])
              .order("criado_em", desc=True).limit(1).execute())


def sessao_viva_do_usuario(usuario_id: str) -> dict | None:
    return um(supabase.table("sessoes_recarga").select("id, carregador_id, status")
              .eq("usuario_id", usuario_id).in_("status", list(STATUS_VIVOS)).limit(1).execute())


def sessao_aguardando_energia(carregador_id: str) -> dict | None:
    return um(supabase.table("sessoes_recarga").select("*").eq("carregador_id", carregador_id)
              .eq("status", "aguardando_energia").limit(1).execute())


def _fila_de_energia(condominio_id: str) -> list[dict]:
    ids = [c["id"] for c in (supabase.table("carregadores").select("id")
                             .eq("condominio_id", condominio_id).execute().data or [])]
    if not ids:
        return []
    return supabase.table("sessoes_recarga").select("*").eq("status", "aguardando_energia") \
        .in_("carregador_id", ids).order("criado_em").execute().data or []


def ha_fila_de_energia(condominio_id: str) -> bool:
    return bool(_fila_de_energia(condominio_id))


def posicao_na_fila_de_energia(sessao_id: str, condominio_id: str) -> int | None:
    for i, s in enumerate(_fila_de_energia(condominio_id), start=1):
        if s["id"] == sessao_id:
            return i
    return None


def _ligar_sessao_em_espera(s: dict, alocada: float | None) -> bool:
    """aguardando_energia -> carregando (condicional) e manda `liberar` à placa."""
    charger = carregador(s["carregador_id"])
    r = supabase.table("sessoes_recarga").update({
        "status": "carregando",
        "iniciado_em": agora_iso(),
        "potencia_alocada_kw": alocada,
        "potencia_atual_kw": 0,
        "baixa_potencia_desde": None,
    }).eq("id", s["id"]).eq("status", "aguardando_energia").execute()
    if not r.data:
        return False
    supabase.table("carregadores").update({"status": "em_uso"}).eq("id", charger["id"]).execute()
    dispositivos.enfileirar(charger["id"], "liberar", s["id"])
    demanda.alocar(charger["condominio_id"])
    return True


def promover_aguardando_energia(condominio_id: str) -> int:
    """
    Liga quem espera energia, por ORDEM DE CHEGADA, enquanto o alocador
    aceitar. Para no primeiro que não cabe: ninguém fura a fila. Devolve
    quantas sessões ligaram.
    """
    ligadas = 0
    for s in _fila_de_energia(condominio_id):
        charger = carregador(s["carregador_id"])
        v = veiculo(s["veiculo_id"]) or {}
        try:
            alocada = demanda.verificar_admissao(condominio_id, charger, v,
                                                 float(s.get("percentual_bateria_atual") or 0))
        except HTTPException:
            break
        if _ligar_sessao_em_espera(s, alocada):
            ligadas += 1
            notificar(s["usuario_id"], f"Energia liberada: sua recarga no ponto {charger['numero']} começou.")
            print(f"[DEMANDA] sessão {s['id']} saiu da fila de energia")
    return ligadas


def _promover_sem_derrubar(condominio_id: str) -> None:
    try:
        promover_aguardando_energia(condominio_id)
    except Exception as e:
        print(f"[DEMANDA] promoção da fila de energia falhou: {e}")


def cancelar_aguardando_energia(s: dict, motivo: str) -> dict:
    """Desiste da espera: devolve a reserva INTEIRA (não houve energia)."""
    atual = sessao(s["id"]) or s
    r = supabase.table("sessoes_recarga").update({
        "status": "cancelada", "motivo_recusa": motivo, "finalizado_em": agora_iso(),
        "custo_final": 0, "potencia_atual_kw": 0,
    }).eq("id", s["id"]).eq("status", "aguardando_energia").execute()
    if not r.data:
        return {"success": True, "ja_encerrada": True}

    reservado = round(float(atual.get("valor_pre_autorizado") or 0), 2)
    if reservado > 0:
        carteira.creditar(atual["usuario_id"], reservado, "estorno",
                          "Espera por energia cancelada: reserva devolvida", atual["id"])
    supabase.table("sessoes_recarga").update({"valor_estornado": reservado}).eq("id", atual["id"]).execute()
    supabase.table("pagamentos").update({"valor": 0, "status": "estornado"}) \
        .eq("sessao_id", atual["id"]).execute()

    charger = carregador(atual["carregador_id"])
    if charger["status"] != "offline":
        supabase.table("carregadores").update({"status": "disponivel"}).eq("id", charger["id"]).execute()
    dispositivos.enfileirar(charger["id"], "bloquear", atual["id"])     # idempotente: o relé já está aberto
    notificar(atual["usuario_id"], f"Espera por energia no ponto {charger['numero']} cancelada. "
                                   f"Reserva de {brl(reservado)} devolvida à sua carteira.")
    _promover_sem_derrubar(charger["condominio_id"])
    return {"success": True, "custo_final": 0.0, "estorno": reservado, "motivo": motivo}


# ---------------------------------------------------------------------------
# Tela do totem: até 4 linhas, até 20 caracteres, ASCII sem acento
# ---------------------------------------------------------------------------

def _ascii(texto) -> str:
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()


def _reais(valor) -> str:
    return f"R$ {float(valor or 0):.2f}".replace(".", ",")


def tela_do_motivo(motivo: str, porta: int, nome: str | None = None, custo=None,
                   fila: int | None = None, valor=None) -> list[str]:
    n = porta
    telas = {
        "iniciada": [f"Vaga {n} liberada", f"Boa recarga, {nome}!" if nome else "Boa recarga!"],
        "encerrada": [f"Vaga {n} encerrada", f"Custo {_reais(custo)}" if custo is not None else "",
                      "Retire o celular"],
        "confirmada_app": [f"Vaga {n} liberada", "Recarga do app"],
        "aguardando_energia": [f"Vaga {n} na espera", "Sem energia agora",
                               f"Fila: {fila}" if fila else "", "Liga sozinha depois"],
        "vaga_ocupada": [f"Vaga {n} ocupada", "Escolha outra vaga"],
        "ja_carregando_em_outra_vaga": ["Voce ja esta", "carregando em", "outra vaga"],
        "saldo_insuficiente": ["Saldo insuficiente", f"Precisa {_reais(valor)}" if valor else "",
                               "Recarregue no app"],
        "taxa_pendente": ["Taxa pendente", "Quite no app"],
        "cartao_nao_cadastrado": ["Tag nao cadastrada", "Cadastre no app"],
        "cartao_de_outro_usuario": ["Tag de outro", "morador"],
        "cartao_de_outro_condominio": ["Tag de outro", "condominio"],
        "sem_veiculo": ["Sem veiculo", "compativel", "Cadastre no app"],
        "uid_invalido": ["Leitura falhou", "Aproxime de novo"],
        "sem_recarga_preparada": [f"Vaga {n}: sem recarga", "preparada", "Use o app primeiro"],
        "espera_encerrada": ["Espera encerrada", "Prepare de novo"],
    }
    linhas = telas.get(motivo, ["Nao deu certo", "Veja o app"])
    return [_ascii(x)[:20] for x in linhas if x][:4]


def _resposta(porta: int, autorizado: bool, motivo: str, acao: str, mensagem: str, *,
              sessao_id: str | None = None, fila_posicao: int | None = None,
              tela: dict | None = None, legado: dict | None = None) -> dict:
    """
    Formato da interface congelada (ADR-018). `legado` traz os campos que a
    resposta do /v2/rfid já tinha (continuar_aguardando, uid, saldo_atual...):
    mudança só aditiva, nada some.
    """
    r = {k: v for k, v in (legado or {}).items() if k != "sessao"}
    r.update({
        "autorizado": bool(autorizado),
        "motivo": motivo,
        "acao": acao,
        "tela": tela_do_motivo(motivo, porta, **(tela or {})),
        "mensagem": mensagem,
        "sessao_id": sessao_id,
        "fila_posicao": fila_posicao,
    })
    return r


def _do_app(r: dict, porta: int) -> dict:
    """Recarga preparada no app + tag: traduz a resposta de processar_cartao."""
    if r.get("autorizado") and r.get("motivo") == "aguardando_energia":
        return _resposta(porta, True, "aguardando_energia", "nenhuma", r["mensagem"],
                         sessao_id=r.get("sessao_id"), fila_posicao=r.get("fila_posicao"),
                         tela={"fila": r.get("fila_posicao")}, legado=r)
    if r.get("autorizado"):
        return _resposta(porta, True, "confirmada_app", "ligar", r["mensagem"],
                         sessao_id=r.get("sessao_id"), legado=r)
    return _resposta(porta, False, r.get("motivo") or "sem_recarga_preparada", "nenhuma",
                     r.get("mensagem") or "Cartão não autorizado aqui.", legado=r)


def _encerrar_pela_tag(s: dict, porta: int) -> dict:
    if s["status"] == "carregando":
        res = encerrar(s, "tag")
        custo = res.get("custo_final")
        if custo is None:
            custo = float((sessao(s["id"]) or {}).get("custo_final") or 0)
    else:
        res = cancelar_aguardando_energia(s, "cancelado_pela_tag")
        custo = 0.0
    return _resposta(porta, True, "encerrada", "desligar",
                     f"Recarga na vaga {porta} encerrada. Custo {brl(custo)}.",
                     sessao_id=s["id"], tela={"custo": custo},
                     legado={"custo_final": custo, "estorno": res.get("estorno")})


def _veiculo_para_tag(usuario_id: str, charger: dict) -> dict | None:
    """Primeiro veículo compatível do morador (bancada só aceita celular)."""
    for v in supabase.table("veiculos").select("*").eq("usuario_id", usuario_id) \
            .order("criado_em").execute().data or []:
        if charger.get("perfil") == "bancada" and v.get("tipo") != "celular":
            continue
        return v
    return None


def _iniciar_pela_tag(charger: dict, cartao: dict, uid: str, porta: int) -> dict:
    """Vaga livre + cartão pessoal: a recarga nasce da tag (sem passar pelo app)."""
    usuario_id = cartao["usuario_id"]
    u = um(supabase.table("usuarios").select("id, nome, condominio_id").eq("id", usuario_id).execute())
    if not u:
        return _resposta(porta, False, "cartao_nao_cadastrado", "nenhuma",
                         f"Cartão {uid} sem morador ativo.", legado={"uid": uid})
    if u.get("condominio_id") != charger["condominio_id"]:
        return _resposta(porta, False, "cartao_de_outro_condominio", "nenhuma",
                         "Este cartão pertence a outro condomínio.")
    if sessao_viva_do_usuario(usuario_id):
        return _resposta(porta, False, "ja_carregando_em_outra_vaga", "nenhuma",
                         "Você já tem uma recarga em andamento em outra vaga.")
    v = _veiculo_para_tag(usuario_id, charger)
    if not v:
        return _resposta(porta, False, "sem_veiculo", "nenhuma",
                         "Nenhum veículo compatível com este ponto. Cadastre um no app.")

    cond = condominio_de(charger)
    conhecido = v.get("percentual_bateria")
    soc = max(0.0, min(99.0, float(conhecido if conhecido is not None else SOC_PADRAO_TAG)))
    alvo = 100.0

    admitida = True
    try:
        alocada = demanda.verificar_admissao(charger["condominio_id"], charger, v, soc)
    except HTTPException:
        admitida, alocada = False, None
    if admitida and ha_fila_de_energia(charger["condominio_id"]):
        admitida, alocada = False, None           # quem chegou antes liga antes

    est = calcular_estimativa(charger, v, soc, alvo, cond, potencia_alocada_kw=alocada)
    # A reserva assume a bateria VAZIA: o % é só estimado e, se o celular
    # estiver mais descarregado que o último registro, a recarga não para no
    # meio pelo teto. A diferença volta inteira no fim (estorno).
    pior_caso = calcular_estimativa(charger, v, 0.0, alvo, cond, potencia_alocada_kw=alocada)
    saldo = carteira.saldo_de(usuario_id)
    valor = valor_da_reserva(pior_caso["custo_estimado"], saldo)
    if saldo < valor:
        return _resposta(porta, False, "saldo_insuficiente", "nenhuma",
                         f"Saldo insuficiente: a recarga reserva {brl(valor)}. Adicione saldo no app.",
                         tela={"valor": valor})

    congelados = {}
    if (cond or {}).get("preco_solar_kwh") is not None:
        congelados["tarifa_solar_kwh"] = float(cond["preco_solar_kwh"])
    try:
        nova = _inserir_sessao({
            **congelados,
            "carregador_id": charger["id"], "veiculo_id": v["id"], "usuario_id": usuario_id,
            "status": "aguardando_energia",
            "percentual_bateria_inicial": soc, "percentual_bateria_atual": soc,
            "percentual_origem": "estimado", "alvo_percentual": alvo,
            "tempo_estimado_min": est["tempo_estimado_min"], "custo_estimado": est["custo_estimado"],
            "tarifa_kwh": tarifa_base(charger), "multiplicador_ponta": multiplicador_ponta(cond),
            "origem": "hardware", "uid_inicio": uid, "potencia_atual_kw": 0,
        })
    except SessaoDuplicada:
        return _resposta(porta, False, "vaga_ocupada", "nenhuma",
                         f"A vaga {porta} acabou de ser ocupada. Escolha outra vaga.")

    try:
        saldo = carteira.debitar(usuario_id, valor, "pre_autorizacao",
                                 f"Reserva da recarga no ponto {charger['numero']} (tag)", nova["id"])
    except carteira.SaldoInsuficiente:
        supabase.table("sessoes_recarga").update({
            "status": "recusada", "motivo_recusa": "saldo_insuficiente", "finalizado_em": agora_iso(),
        }).eq("id", nova["id"]).eq("status", "aguardando_energia").execute()
        return _resposta(porta, False, "saldo_insuficiente", "nenhuma",
                         f"Saldo insuficiente: a recarga reserva {brl(valor)}.", tela={"valor": valor})

    supabase.table("sessoes_recarga").update({"valor_pre_autorizado": valor}).eq("id", nova["id"]).execute()
    supabase.table("pagamentos").insert({
        "sessao_id": nova["id"], "valor": valor, "metodo": "rfid_pessoal", "status": "pre_autorizado",
    }).execute()
    cartoes.marcar_uso(uid)
    supabase.table("carregadores").update({"status": "em_uso"}).eq("id", charger["id"]).execute()
    _sair_de_todas_as_filas(usuario_id)

    primeiro = (u.get("nome") or "").split()[0] if u.get("nome") else None
    legado = {"saldo_atual": saldo, "valor_reservado": valor, "percentual_inicial": soc,
              "percentual_origem": "estimado"}
    if admitida and _ligar_sessao_em_espera(nova, alocada):
        return _resposta(porta, True, "iniciada", "ligar",
                         f"Recarga iniciada na vaga {porta}. Reserva de {brl(valor)}; "
                         f"a diferença volta no fim.", sessao_id=nova["id"],
                         tela={"nome": primeiro}, legado=legado)

    demanda.registrar_recusa(charger["condominio_id"], usuario_id, charger["id"], "cartao")
    posicao = posicao_na_fila_de_energia(nova["id"], charger["condominio_id"])
    mensagem = (f"O condomínio está no limite de potência agora. Sua recarga na vaga {porta} está "
                f"reservada (posição {posicao} na fila) e liga sozinha quando houver energia.")
    notificar(usuario_id, mensagem)
    return _resposta(porta, True, "aguardando_energia", "nenhuma", mensagem, sessao_id=nova["id"],
                     fila_posicao=posicao, tela={"fila": posicao}, legado=legado)


def processar_tag(carregador_id: str, uid_bruto: str, porta: int, dispositivo_id: str | None = None,
                  ip: str | None = None) -> dict:
    """
    Decisão do Totem v2.1 para tag + botão da vaga (a rota já autenticou a
    placa e resolveu a porta). Ordem:
      1. vaga ocupada?   mesma tag -> encerra | outra -> vaga_ocupada + evento
      2. recarga do app esperando a tag nesta vaga? -> fluxo do app
      3. vaga livre      cartão pessoal -> tag-primeiro
    """
    try:
        uid = cartoes.normalizar(uid_bruto)
    except HTTPException:
        return _resposta(porta, False, "uid_invalido", "nenhuma",
                         "Leitura da tag veio corrompida. Aproxime de novo.",
                         legado={"continuar_aguardando": True})

    charger = carregador(carregador_id)
    cartao = cartoes.por_uid(uid)

    viva = sessao_viva_na_vaga(carregador_id)
    if viva:
        if cartoes.mesma_tag(viva, uid, cartao):
            return _encerrar_pela_tag(viva, porta)
        dispositivos.registrar_evento_seguranca(
            "tag_alheia", dispositivo_id=dispositivo_id, carregador_id=carregador_id, porta=porta,
            uid=uid, ip=ip, detalhe=f"vaga ocupada pela sessao {viva['id']}")
        return _resposta(porta, False, "vaga_ocupada", "nenhuma",
                         f"A vaga {porta} está ocupada. Escolha outra vaga.")

    if sessao_aguardando(carregador_id):
        return _do_app(processar_cartao(carregador_id, uid, esperar_energia=True), porta)

    if not cartao:
        return _resposta(porta, False, "cartao_nao_cadastrado", "nenhuma",
                         f"Cartão {uid} não cadastrado. Cadastre-o pelo app.", legado={"uid": uid})
    if not cartoes.pagador_da_tag(cartao):
        if cartao.get("condominio_id") != charger["condominio_id"]:
            return _resposta(porta, False, "cartao_de_outro_condominio", "nenhuma",
                             "Este cartão pertence a outro condomínio.")
        return _resposta(porta, False, "sem_recarga_preparada", "nenhuma",
                         "O cartão do condomínio só confirma recarga preparada no app.", legado={"uid": uid})
    return _iniciar_pela_tag(charger, cartao, uid, porta)
