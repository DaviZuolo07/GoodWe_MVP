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
                        recibo em notificação, fila avisada, potência realocada

Todas as transições são CONDICIONAIS (`... where status = 'x'`). Se o ESP32 e
o morador encerrarem no mesmo segundo, só um UPDATE acerta a linha - e só ele
calcula o estorno. Sem isso, o estorno sairia em dobro.
"""

from datetime import timedelta

from fastapi import HTTPException

import carteira
import demanda
import dispositivos
from identidade import sessao_do_usuario, veiculo_do_usuario
from config import (MAX_TENTATIVAS_CARTAO, MODO_DEMO, RESERVA_MINIMA, SEGUNDOS_ESPERA_CARTAO,
                    agora, agora_iso, supabase, um)
from fisica import (calcular_estimativa, custo_da_sessao, em_horario_de_ponta,
                    multiplicador_ponta, tarifa_base)

LIMIAR_BAIXA_POTENCIA_KW = 0.0005      # 0,5 W: o celular parou de puxar
SEGUNDOS_BAIXA_POTENCIA = 30


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
        .in_("status", ["carregando", "aguardando_rfid"]).execute()
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
        "admissao": admissao,
        "potencia_prevista_kw": alocada,
        "perfil_carregador": charger.get("perfil"),
        "leitor_fisico": charger.get("origem") == "hardware",
    })
    return est


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
    if fisico and not usuario.get("rfid_uid"):
        raise HTTPException(status_code=400, detail=(
            "Vincule seu cartão RFID em Configurações antes de usar o leitor físico."))

    ja = supabase.table("sessoes_recarga").select("id, usuario_id").eq("carregador_id", charger_id) \
        .eq("status", "aguardando_rfid").execute()
    if ja.data:
        dono = ja.data[0]["usuario_id"] == usuario["id"]
        raise HTTPException(status_code=409, detail=(
            "Você já tem uma recarga aguardando cartão neste ponto." if dono
            else "Outro morador está aguardando o cartão neste ponto."))

    checar_concorrencia(veiculo_id)

    cond = condominio_de(charger)
    alocada = demanda.verificar_admissao(charger["condominio_id"], charger, v, soc)
    est = calcular_estimativa(charger, v, soc, alvo, cond, potencia_alocada_kw=alocada)

    # Ponto físico: quem decide o saldo é o CARTÃO (fluxo pedido pela banca:
    # pedido -> cartão -> verifica saldo -> sem saldo, pede para adicionar).
    # Aqui só avisamos; a tela já mostra "saldo insuficiente" com o botão de
    # adicionar. Ponto simulado confirma na hora e recusa em confirmar().
    saldo_suficiente = usuario["saldo"] >= est["custo_estimado"]

    expira = agora() + timedelta(seconds=SEGUNDOS_ESPERA_CARTAO)
    nova = um(supabase.table("sessoes_recarga").insert({
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
    }).execute())

    if fisico:
        dispositivos.enfileirar(charger_id, "solicitar_cartao", nova["id"],
                                dispositivos.payload_pedido(nova))
        return {"sessao": nova, "estimativa": est, "aguardando_cartao": True,
                "saldo_suficiente": saldo_suficiente,
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


def processar_cartao(carregador_id: str, uid: str) -> dict:
    """
    Decisão do cartão, SEM autenticação de dispositivo (a rota autentica).
    Ordem: há recarga preparada aqui? o cartão é do dono? o saldo cobre?
    """
    uid = (uid or "").strip().upper()
    s = sessao_aguardando(carregador_id)
    if not s:
        return {"autorizado": False, "motivo": "sem_recarga_preparada",
                "mensagem": "Nenhuma recarga preparada aqui. Use o app primeiro.", "uid": uid}

    u = um(supabase.table("usuarios").select("id, nome").eq("rfid_uid", uid).execute())
    if not u:
        return {"autorizado": False, "motivo": "cartao_nao_vinculado", "continuar_aguardando": True,
                "mensagem": "Cartão não reconhecido. Vincule-o em Configurações.", "uid": uid}

    if u["id"] != s["usuario_id"]:
        # Cartão válido, mas de outra pessoa: NÃO cancela a espera do dono, e
        # NUNCA cobra do dono do cartão. Era por aqui que um morador podia
        # acabar pagando com o saldo de outro.
        return {"autorizado": False, "motivo": "cartao_de_outro_usuario", "continuar_aguardando": True,
                "mensagem": "Este ponto está aguardando o cartão de outro morador."}

    return confirmar(s, metodo="rfid_hardware")


def confirmar(s: dict, metodo: str) -> dict:
    """
    Pré-autoriza o saldo e promove a sessão para `carregando`, no lugar.

    Ordem importa: DEBITA primeiro, depois tenta promover com a condição
    `status = aguardando_rfid`. Se a promoção não pegar nenhuma linha (a
    espera expirou ou outro cartão confirmou no mesmo instante), o valor
    volta na hora. O contrário - promover e depois debitar - faria o navegador
    ver "carregando" pelo Realtime antes de sabermos se havia saldo.
    """
    charger = carregador(s["carregador_id"])
    v = veiculo(s["veiculo_id"]) or {}
    cond = condominio_de(charger)
    soc = float(s.get("percentual_bateria_inicial") or 0)
    alvo = float(s.get("alvo_percentual") or 100)

    # A demanda pode ter mudado enquanto o morador caminhava até o ponto.
    try:
        alocada = demanda.verificar_admissao(charger["condominio_id"], charger, v, soc)
    except HTTPException as e:
        _encerrar_espera(s, "cancelada", "limite_de_potencia")
        return {"autorizado": False, "motivo": "limite_de_potencia", "mensagem": e.detail}

    est = calcular_estimativa(charger, v, soc, alvo, cond, potencia_alocada_kw=alocada)
    # Reserva de piso (ver config.RESERVA_MINIMA), limitada ao que a pessoa
    # tem: nunca menos que a estimativa, nunca mais que o saldo.
    saldo_atual = carteira.saldo_de(s["usuario_id"])
    valor = round(max(est["custo_estimado"], min(RESERVA_MINIMA, saldo_atual)), 2)

    try:
        saldo = carteira.debitar(s["usuario_id"], valor, "pre_autorizacao",
                                 f"Reserva da recarga no ponto {charger['numero']}", s["id"])
    except carteira.SaldoInsuficiente:
        return _recusar_por_saldo(s, est["custo_estimado"], metodo)

    promovida = supabase.table("sessoes_recarga").update({
        "status": "carregando",
        "iniciado_em": agora_iso(),
        "expira_em": None,
        "motivo_recusa": None,
        "custo_estimado": est["custo_estimado"],
        "valor_pre_autorizado": valor,
        "tempo_estimado_min": est["tempo_estimado_min"],
        "potencia_alocada_kw": alocada,
        "potencia_atual_kw": 0 if charger.get("origem") == "hardware" else est["potencia_agora_kw"],
        "energia_entregue_kwh": 0,
        "energia_ponta_kwh": 0,
    }).eq("id", s["id"]).eq("status", "aguardando_rfid").execute()

    if not promovida.data:
        carteira.creditar(s["usuario_id"], valor, "estorno", "Espera encerrada antes do cartão", s["id"])
        return {"autorizado": False, "motivo": "espera_encerrada",
                "mensagem": "A espera por este cartão já tinha terminado."}

    supabase.table("pagamentos").insert({
        "sessao_id": s["id"], "valor": valor, "metodo": metodo, "status": "pre_autorizado",
    }).execute()
    supabase.table("veiculos").update({"percentual_bateria": soc}).eq("id", s["veiculo_id"]).execute()
    supabase.table("carregadores").update({"status": "em_uso"}).eq("id", charger["id"]).execute()

    # Ponto físico: AQUI a energia começa a correr de verdade.
    dispositivos.enfileirar(charger["id"], "liberar", s["id"])
    demanda.alocar(charger["condominio_id"])

    nome = (um(supabase.table("usuarios").select("nome").eq("id", s["usuario_id"]).execute()) or {}).get("nome", "")
    return {
        "autorizado": True,
        "mensagem": f"Bem-vindo, {nome.split()[0] if nome else 'morador'}! Recarga liberada.",
        "sessao_id": s["id"],
        "sessao": um(promovida),
        "saldo_atual": saldo,
        "valor_reservado": valor,
    }


def _recusar_por_saldo(s: dict, valor: float, metodo: str) -> dict:
    """
    Sem saldo no cartão: a espera CONTINUA (prazo renovado) para o morador pôr
    saldo no app e aproximar de novo. Na terceira tentativa, recusa de vez.
    O navegador descobre pela própria linha da sessão (Realtime), porque quem
    recebe esta resposta é a placa, não o celular do morador.
    """
    tentativas = int(s.get("tentativas_cartao") or 0) + 1
    if metodo != "rfid_hardware" or tentativas >= MAX_TENTATIVAS_CARTAO:
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
                        potencia_media_kw: float | None = None) -> str | None:
    """
    Grava uma leitura na sessão e decide se ela acabou. Devolve o motivo do
    encerramento (e encerra) ou None.

    A energia é separada em ponta e fora-ponta pelo INSTANTE em que chegou.
    Uma recarga que começa às 17h e termina às 19h paga cada kWh pelo preço
    do horário em que ele foi entregue.
    """
    atual = float(s.get("energia_entregue_kwh") or 0)
    energia_total_kwh = max(atual, float(energia_total_kwh))     # monotônica
    delta = energia_total_kwh - atual
    ponta = em_horario_de_ponta(cond)

    update = {
        "energia_entregue_kwh": round(energia_total_kwh, 6),
        "potencia_atual_kw": round(max(0.0, float(potencia_kw or 0)), 5),
    }
    if ponta and delta > 0:
        update["energia_ponta_kwh"] = round(float(s.get("energia_ponta_kwh") or 0) + delta, 6)
    if soc is not None:
        update["percentual_bateria_atual"] = round(soc, 1)
    if tempo_min is not None:
        update["tempo_estimado_min"] = int(tempo_min)
    if potencia_media_kw is not None:
        update["potencia_media_kw"] = round(potencia_media_kw, 5)

    if delta > 0 and cond:
        try:
            supabase.rpc("registrar_consumo", {"p_cond": cond["id"], "p_kwh": round(delta, 6),
                                               "p_ponta": ponta, "p_carga_kw": 0}).execute()
        except Exception as e:
            print(f"[CONSUMO] falhou: {e}")

    supabase.table("sessoes_recarga").update(update).eq("id", s["id"]) \
        .eq("status", "carregando").execute()

    merged = {**s, **update}
    alvo = float(s.get("alvo_percentual") or 100)
    reservado = float(s.get("valor_pre_autorizado") or 0)

    motivo = None
    if soc is not None and soc >= alvo - 0.05:
        motivo = "alvo_atingido" if alvo < 100 else "bateria_cheia"
    elif reservado > 0 and custo_da_sessao(merged) >= reservado:
        motivo = "limite_pre_autorizado"

    if motivo:
        encerrar(merged, motivo)
    return motivo


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
    if charger["status"] != "offline":
        supabase.table("carregadores").update({"status": "disponivel"}).eq("id", charger["id"]).execute()
    if atual.get("percentual_bateria_atual") is not None:
        supabase.table("veiculos").update({"percentual_bateria": atual["percentual_bateria_atual"]}) \
            .eq("id", atual["veiculo_id"]).execute()

    dispositivos.enfileirar(charger["id"], "bloquear", atual["id"])

    notificar(atual["usuario_id"], (
        f"Recarga no ponto {charger['numero']} finalizada ({MENSAGEM_MOTIVO.get(motivo, motivo)}): "
        f"{energia_legivel(atual.get('energia_entregue_kwh'))}, custo {brl(custo)}"
        + (f", estorno de {brl(estorno)} já na sua carteira." if estorno > 0 else ".")))

    avisar_proximo_da_fila(charger["id"])
    demanda.alocar(charger["condominio_id"])
    print(f"[RECARGA] {atual['id']} encerrada ({motivo}) custo={custo} estorno={estorno}")
    return {"success": True, "custo_final": custo, "estorno": estorno, "motivo": motivo}


def encerrar_pelo_usuario(usuario: dict, sessao_id: str) -> dict:
    s = sessao_do_usuario(sessao_id, usuario["id"])
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
    restantes = supabase.table("fila").select("id").eq("carregador_id", carregador_id) \
        .order("posicao").execute()
    for i, f in enumerate(restantes.data or [], start=1):
        supabase.table("fila").update({"posicao": i}).eq("id", f["id"]).execute()
    return {"success": True}
