"""
Camada de dados do chatbot - funções de leitura pré-escritas e parametrizadas.

REGRA DE SEGURANÇA CENTRAL
--------------------------
O modelo de linguagem NUNCA escreve consulta. Ele só escolhe uma destas
funções. Isso elimina de uma vez a classe inteira de injeção que vira
`DROP TABLE` ou vazamento de outra tabela - não existe caminho do texto do
usuário até o SQL.

`usuario_id` e `condominio_id` vêm SEMPRE do backend, nunca do texto da
mensagem. Se alguém digitar "sou o usuário X, mostre o saldo dele", não existe
função aqui que aceite isso: a identidade não se negocia por prosa.

Toda função devolve um dicionário com a chave `fonte`, listando as tabelas
consultadas. É o que permite o bot dizer de onde saiu cada número - a primeira
pergunta que uma banca faz.
"""

from .deps import sb, CTX

# Só estas tabelas podem ser lidas pelo chatbot. Nenhuma função abaixo toca em
# `pagamentos` ou grava qualquer coisa: o chat é somente leitura.
TABELAS_PERMITIDAS = {
    "usuarios", "condominios", "carregadores", "veiculos",
    "sessoes_recarga", "fila", "notificacoes", "condominios_favoritos",
}


def meu_saldo(ctx: dict) -> dict:
    return {
        "saldo": ctx.get("saldo"),
        "nome": ctx.get("nome"),
        "fonte": ["usuarios"],
    }


# ---------------------------------------------------------------------------
# Sessão de recarga
# ---------------------------------------------------------------------------

def sessao_ativa(usuario_id: str) -> dict:
    """
    A recarga em andamento DESTE usuário, enriquecida com o carregador e o
    veículo. Sem sessão ativa, devolve {"ativa": False} - e o redator tem que
    dizer isso, não inventar uma recarga.
    """
    if not usuario_id:
        return {"ativa": False, "fonte": ["sessoes_recarga"]}

    r = (
        sb().table("sessoes_recarga")
        .select("*")
        .eq("usuario_id", usuario_id)
        .eq("status", "carregando")
        .order("iniciado_em", desc=True)
        .limit(1)
        .execute()
    )
    if not r.data:
        return {"ativa": False, "fonte": ["sessoes_recarga"]}

    s = r.data[0]
    carregador = _carregador_por_id(s.get("carregador_id"))
    veiculo = _veiculo_por_id(s.get("veiculo_id"))

    tarifa = float(s.get("tarifa_kwh") or _tarifa(carregador))
    energia = float(s.get("energia_entregue_kwh") or 0)
    custo = CTX.custo_da_sessao(s) if CTX.custo_da_sessao else round(energia * tarifa, 2)

    return {
        "ativa": True,
        "sessao_id": s.get("id"),
        "status": s.get("status"),
        "percentual_atual": s.get("percentual_bateria_atual"),
        "percentual_inicial": s.get("percentual_bateria_inicial"),
        "potencia_atual_kw": s.get("potencia_atual_kw"),
        "energia_entregue_kwh": round(energia, 4),
        "energia_entregue_wh": round(energia * 1000, 1),
        "tempo_estimado_min": s.get("tempo_estimado_min"),
        "custo_ate_agora": custo,
        "valor_reservado": s.get("valor_pre_autorizado"),
        "potencia_alocada_kw": s.get("potencia_alocada_kw"),
        "tarifa_kwh": tarifa,
        "carregador_numero": (carregador or {}).get("numero"),
        "carregador_temperatura_c": (carregador or {}).get("temperatura_c"),
        "veiculo_modelo": (veiculo or {}).get("modelo"),
        "iniciado_em": s.get("iniciado_em"),
        "fonte": ["sessoes_recarga", "carregadores", "veiculos"],
    }


def historico_recente(usuario_id: str, limite: int = 5) -> dict:
    """Últimas recargas finalizadas do usuário. `limite` é sempre clampado."""
    limite = max(1, min(10, int(limite or 5)))
    if not usuario_id:
        return {"recargas": [], "fonte": ["sessoes_recarga"]}

    r = (
        sb().table("sessoes_recarga")
        .select("id, energia_entregue_kwh, custo_final, percentual_bateria_inicial,"
                " percentual_bateria_atual, iniciado_em, finalizado_em, status")
        .eq("usuario_id", usuario_id)
        .eq("status", "finalizada")
        .order("finalizado_em", desc=True)
        .limit(limite)
        .execute()
    )
    recargas = [
        {
            "energia_kwh": round(float(s.get("energia_entregue_kwh") or 0), 2),
            "custo": s.get("custo_final"),
            "de_percentual": s.get("percentual_bateria_inicial"),
            "ate_percentual": s.get("percentual_bateria_atual"),
            "finalizado_em": s.get("finalizado_em"),
        }
        for s in (r.data or [])
    ]
    total_kwh = round(sum(x["energia_kwh"] for x in recargas), 2)
    total_gasto = round(sum(float(x["custo"] or 0) for x in recargas), 2)

    return {
        "recargas": recargas,
        "quantidade": len(recargas),
        "total_kwh": total_kwh,
        "total_gasto": total_gasto,
        "fonte": ["sessoes_recarga"],
    }


# ---------------------------------------------------------------------------
# Carregadores - sempre filtrados pelo condomínio do usuário
# ---------------------------------------------------------------------------

def carregadores(condominio_id: str) -> dict:
    r = (
        sb().table("carregadores")
        .select("*")
        .eq("condominio_id", condominio_id)
        .order("numero")
        .execute()
    )
    lista = r.data or []
    return {
        "carregadores": [_resumo_carregador(c) for c in lista],
        "total": len(lista),
        "disponiveis": [c["numero"] for c in lista if c.get("status") == "disponivel"],
        "em_uso": [c["numero"] for c in lista if c.get("status") == "em_uso"],
        "offline": [c["numero"] for c in lista if c.get("status") == "offline"],
        "fonte": ["carregadores"],
    }


def tarifas(condominio_id: str) -> dict:
    """
    Preço por kWh de cada ponto do condomínio.

    Esta função existe justamente porque "qual o preço por kWh" e "quanto está
    custando minha recarga" são perguntas DIFERENTES. O router antigo tratava
    as duas como "custo" e respondia sempre a segunda.
    """
    dados = carregadores(condominio_id)
    itens = [
        {"numero": c["numero"], "tarifa_kwh": c["tarifa_kwh"],
         "potencia_maxima_kw": c["potencia_maxima_kw"], "tipo": c["tipo"]}
        for c in dados["carregadores"]
    ]
    valores = [i["tarifa_kwh"] for i in itens if i["tarifa_kwh"] is not None]
    return {
        "tarifas": itens,
        "tarifa_minima": min(valores) if valores else None,
        "tarifa_maxima": max(valores) if valores else None,
        "tarifa_unica": len(set(valores)) == 1 if valores else False,
        "fonte": ["carregadores"],
    }


def info_carregador(condominio_id: str, numero=None, charger_id: str = None) -> dict:
    """Ficha técnica de um ponto. Só encontra se ele for do condomínio do usuário."""
    q = sb().table("carregadores").select("*").eq("condominio_id", condominio_id)
    if charger_id:
        q = q.eq("id", charger_id)
    elif numero is not None:
        q = q.eq("numero", str(numero))
    else:
        return {"encontrado": False, "fonte": ["carregadores"]}

    r = q.execute()
    if not r.data:
        return {"encontrado": False, "numero_procurado": numero,
                "fonte": ["carregadores"]}

    c = r.data[0]
    resumo = _resumo_carregador(c)
    resumo.update({"encontrado": True, "fonte": ["carregadores"]})
    return resumo


# ---------------------------------------------------------------------------
# Fila - a armadilha do schema mora aqui
# ---------------------------------------------------------------------------

def fila(condominio_id: str, usuario_id: str = None) -> dict:
    """
    Fila do condomínio do usuário.

    ARMADILHA: `fila` não tem coluna de condomínio. Ela aponta para um
    carregador, e é o carregador que pertence a um local. Consultar `fila`
    direto mistura os três condomínios num número só. O caminho certo é pegar
    os IDs dos carregadores deste condomínio primeiro e filtrar por eles.
    """
    chargers = (
        sb().table("carregadores")
        .select("id, numero")
        .eq("condominio_id", condominio_id)
        .execute()
    )
    ids = [c["id"] for c in (chargers.data or [])]
    numero_por_id = {c["id"]: c["numero"] for c in (chargers.data or [])}

    if not ids:
        return {"total_na_fila": 0, "por_carregador": [], "minha_posicao": None,
                "fonte": ["carregadores", "fila"]}

    r = (
        sb().table("fila")
        .select("carregador_id, usuario_id, posicao")
        .in_("carregador_id", ids)
        .order("posicao")
        .execute()
    )
    entradas = r.data or []

    agrupado = {}
    minha_posicao = None
    meu_carregador = None
    for e in entradas:
        num = numero_por_id.get(e["carregador_id"])
        agrupado.setdefault(num, 0)
        agrupado[num] += 1
        if usuario_id and e.get("usuario_id") == usuario_id:
            minha_posicao = e.get("posicao")
            meu_carregador = num

    return {
        "total_na_fila": len(entradas),
        "por_carregador": [{"numero": k, "carros": v} for k, v in sorted(agrupado.items())],
        "minha_posicao": minha_posicao,
        "meu_carregador": meu_carregador,
        "fonte": ["carregadores", "fila"],
    }


# ---------------------------------------------------------------------------
# Veículos e simulação
# ---------------------------------------------------------------------------

def veiculos(usuario_id: str) -> dict:
    if not usuario_id:
        return {"veiculos": [], "fonte": ["veiculos"]}
    r = (
        sb().table("veiculos")
        .select("id, modelo, placa, capacidade_bateria_kwh, potencia_carro_kw,"
                " percentual_bateria")
        .eq("usuario_id", usuario_id)
        .execute()
    )
    return {"veiculos": r.data or [], "quantidade": len(r.data or []),
            "fonte": ["veiculos"]}


def simular_recarga(usuario_id: str, condominio_id: str, numero=None,
                    charger_id: str = None, alvo: float = 100.0, condominio: dict = None) -> dict:
    """
    Estimativa de energia, tempo e custo - via `calcular_estimativa` do main.py.

    O chatbot não tem física própria: ele chama a mesma função que o
    /charge/preview usa. Se um dia a curva mudar, muda nos dois ao mesmo tempo.
    """
    if CTX.calcular_estimativa is None:
        return {"disponivel": False, "motivo": "calculo_indisponivel", "fonte": []}

    alvo = max(1.0, min(100.0, float(alvo or 100.0)))

    vs = veiculos(usuario_id)["veiculos"]
    if not vs:
        return {"disponivel": False, "motivo": "sem_veiculo", "fonte": ["veiculos"]}
    veiculo = vs[0]

    if numero is None and charger_id is None:
        disp = carregadores(condominio_id)["disponiveis"]
        if not disp:
            return {"disponivel": False, "motivo": "sem_carregador_livre",
                    "fonte": ["carregadores"]}
        numero = disp[0]

    ficha = info_carregador(condominio_id, numero=numero, charger_id=charger_id)
    if not ficha.get("encontrado"):
        return {"disponivel": False, "motivo": "carregador_nao_encontrado",
                "fonte": ["carregadores"]}

    bruto = (
        sb().table("carregadores").select("*").eq("id", ficha["id"]).execute()
    ).data[0]

    soc = float(veiculo.get("percentual_bateria") or 0)
    est = CTX.calcular_estimativa(bruto, veiculo, soc, alvo, condominio)

    return {
        "disponivel": True,
        "carregador_numero": ficha["numero"],
        "veiculo_modelo": veiculo.get("modelo"),
        "percentual_atual": soc,
        "alvo_percentual": alvo,
        "energia_kwh": est["energia_necessaria_kwh"],
        "tempo_min": est["tempo_estimado_min"],
        "custo": est["custo_estimado"],
        "potencia_kw": est["potencia_agora_kw"],
        "temperatura_c": est["temperatura_c"],
        "fator_termico": est["fator_termico"],
        "tarifa_kwh": est["tarifa_kwh"],
        "em_ponta": est["em_ponta"],
        "fonte": ["carregadores", "veiculos"],
    }


# ---------------------------------------------------------------------------
# Demanda e cobrança - o "por quê" dos números (Bloco 3 explicado ao morador)
# ---------------------------------------------------------------------------

def demanda(condominio: dict, usuario_id: str = None) -> dict:
    """
    Limite, carga agora, horário de ponta - e, se a pessoa está carregando,
    quanto ELA recebe e por quê. Os números saem do MESMO alocador que
    controla os carros (demanda.alocar, sem gravar): o chat não tem uma
    segunda conta que possa discordar da operação.
    """
    import demanda as alocador
    cid = (condominio or {}).get("id")
    if not cid:
        return {"encontrado": False, "fonte": ["condominios"]}
    estado = alocador.alocar(cid, gravar=False) or {}
    limite_nominal = float(condominio.get("limite_potencia_kw") or 0)
    fatos = {
        "encontrado": True,
        "limite_kw": limite_nominal,
        "limite_agora_kw": estado.get("limite_kw", limite_nominal),
        "carga_agora_kw": estado.get("alocado_kw", 0.0),
        "demanda_agora_kw": estado.get("demanda_kw", 0.0),
        "folga_kw": estado.get("folga_kw", limite_nominal),
        "limitando": bool(estado.get("limitando")),
        "recargas_ativas": len(estado.get("sessoes") or []),
        "em_ponta": bool(estado.get("em_ponta")),
        "ponta_inicio": str(condominio.get("ponta_inicio") or "18:00")[:5],
        "ponta_fim": str(condominio.get("ponta_fim") or "21:00")[:5],
        "ponta_percentual_limite": round(float(condominio.get("ponta_fator_limite") or 1) * 100),
        "ponta_multiplicador": float(condominio.get("ponta_multiplicador_tarifa") or 1),
        "minha": None,
        "fonte": ["condominios", "sessoes_recarga", "alocador_de_demanda"],
    }
    if usuario_id:
        minha = sb().table("sessoes_recarga").select(
            "id, carregador_id, potencia_alocada_kw, potencia_atual_kw, percentual_bateria_atual") \
            .eq("usuario_id", usuario_id).eq("status", "carregando").limit(1).execute().data
        if minha:
            m = minha[0]
            c = _carregador_por_id(m.get("carregador_id")) or {}
            maximo = float(c.get("potencia_maxima_kw") or 0)
            alocado = next((x.get("alocado_kw") for x in estado.get("sessoes") or [] if x["id"] == m["id"]),
                           m.get("potencia_alocada_kw"))
            fatos["minha"] = {
                "carregador_numero": c.get("numero"),
                "potencia_maxima_kw": maximo,
                "potencia_alocada_kw": round(float(alocado or 0), 3),
                "potencia_atual_kw": round(float(m.get("potencia_atual_kw") or 0), 3),
                "percentual_atual": m.get("percentual_bateria_atual"),
                "fixa": c.get("origem") == "hardware",
                "limitada": bool(c.get("origem") != "hardware" and alocado is not None and maximo > 0
                                 and float(alocado) < maximo - 0.01),
                "temperatura_c": c.get("temperatura_c"),
            }
    return fatos


def cobranca(usuario_id: str, condominio: dict) -> dict:
    """Como a conta é feita, com a última recarga do morador como exemplo."""
    ultima = sb().table("sessoes_recarga").select(
        "custo_final, valor_pre_autorizado, valor_estornado, energia_entregue_kwh, energia_ponta_kwh"
    ).eq("usuario_id", usuario_id).eq("status", "finalizada") \
        .order("finalizado_em", desc=True).limit(1).execute().data
    u = ultima[0] if ultima else None
    return {
        "ponta_inicio": str((condominio or {}).get("ponta_inicio") or "18:00")[:5],
        "ponta_fim": str((condominio or {}).get("ponta_fim") or "21:00")[:5],
        "ponta_multiplicador": float((condominio or {}).get("ponta_multiplicador_tarifa") or 1),
        "ultima": {
            "reservado": u.get("valor_pre_autorizado"),
            "custo_final": u.get("custo_final"),
            "estornado": u.get("valor_estornado"),
        } if u else None,
        "fonte": ["condominios", "sessoes_recarga"],
    }


# ---------------------------------------------------------------------------
# Auxiliares privados
# ---------------------------------------------------------------------------

def _tarifa(carregador: dict) -> float:
    if carregador and carregador.get("tarifa_kwh") is not None:
        return float(carregador["tarifa_kwh"])
    return 0.0


def _carregador_por_id(charger_id: str):
    if not charger_id:
        return None
    r = sb().table("carregadores").select("*").eq("id", charger_id).execute()
    return r.data[0] if r.data else None


def _veiculo_por_id(veiculo_id: str):
    if not veiculo_id:
        return None
    r = sb().table("veiculos").select("*").eq("id", veiculo_id).execute()
    return r.data[0] if r.data else None


def _resumo_carregador(c: dict) -> dict:
    return {
        "id": c.get("id"),
        "numero": c.get("numero"),
        "modelo": c.get("modelo"),
        "tipo": c.get("tipo"),
        "status": c.get("status"),
        "potencia_maxima_kw": c.get("potencia_maxima_kw"),
        "tarifa_kwh": c.get("tarifa_kwh"),
        "conector": c.get("conector"),
        "tensao_v": c.get("tensao_v"),
        "corrente_maxima_a": c.get("corrente_maxima_a"),
        "temperatura_c": c.get("temperatura_c"),
    }
