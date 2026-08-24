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

from .contexto import sb, CTX

# Só estas tabelas podem ser lidas pelo chatbot. Nenhuma função abaixo toca em
# `pagamentos` ou grava qualquer coisa: o chat é somente leitura.
TABELAS_PERMITIDAS = {
    "usuarios", "condominios", "carregadores", "veiculos",
    "sessoes_recarga", "fila", "notificacoes", "condominios_favoritos",
}


# ---------------------------------------------------------------------------
# Contexto do usuário - a origem única da identidade
# ---------------------------------------------------------------------------

def locais_permitidos(usuario_id: str, condominio_moradia: str = None) -> set:
    """
    Allowlist de locais deste usuário: favoritos + o condomínio onde ele mora.

    ESTA FUNÇÃO É A TRAVA DE ESCOPO. A partir do momento em que o frontend
    passou a mandar qual local o usuário escolheu, o `condominio_id` deixou de
    ser um dado confiável - virou entrada. Sem validar contra esta lista,
    bastaria alterar o corpo da requisição para ler carregadores, tarifas e
    fila de um condomínio onde a pessoa não tem vínculo nenhum.

    Mesmo princípio do briefing aplicado ao local, não só à identidade: o que
    vem do cliente é pedido, não permissão.
    """
    permitidos = set()
    if condominio_moradia:
        permitidos.add(condominio_moradia)

    if not usuario_id:
        return permitidos

    try:
        r = (
            sb().table("condominios_favoritos")
            .select("condominio_id")
            .eq("usuario_id", usuario_id)
            .execute()
        )
        permitidos.update(f["condominio_id"] for f in (r.data or []))
    except Exception as e:
        # Tabela ainda não criada (migration 08 não rodou): degrada para o
        # comportamento antigo em vez de derrubar o chat.
        print(f"[CHATBOT] favoritos indisponíveis ({e}) - usando só a moradia")

    return permitidos


def ctx_usuario(usuario_id: str, condominio_escolhido: str = None) -> dict:
    """
    Resolve quem é o usuário e sobre QUAL LOCAL ele está perguntando.

    Duas coisas diferentes moram aqui:
      - identidade  -> sempre do banco, nunca negociável;
      - local ativo -> o escolhido no seletor do chat, SE estiver na allowlist;
                       caso contrário cai para o condomínio de moradia.

    Repare que os dados pessoais (saldo, veículos, sessão ativa) continuam
    seguindo o usuário, não o local. Só carregadores, tarifas e fila mudam
    quando ele troca de lugar - que é exatamente como funciona na vida real.
    """
    vazio = {"encontrado": False, "fonte": ["usuarios"]}
    if not usuario_id:
        return vazio

    r = (
        sb().table("usuarios")
        .select("id, nome, tipo_usuario, condominio_id, bloco_apto, saldo")
        .eq("id", usuario_id)
        .execute()
    )
    if not r.data:
        return vazio

    u = r.data[0]
    moradia_id = u.get("condominio_id") or CTX.condominio_padrao

    condominio_id = moradia_id
    local_ajustado = False
    if condominio_escolhido and condominio_escolhido != moradia_id:
        if condominio_escolhido in locais_permitidos(usuario_id, moradia_id):
            condominio_id = condominio_escolhido
        else:
            # Pedido recusado em silêncio: responde sobre a moradia e sinaliza
            # para quem chamou. Não é erro de usuário, é escopo negado.
            local_ajustado = True
            print(f"[CHATBOT] local fora da allowlist ({condominio_escolhido}) "
                  f"- respondendo sobre {moradia_id}")

    nome_condominio = None
    limite_kw = None
    if condominio_id:
        c = (
            sb().table("condominios")
            .select("nome, limite_energia_kw")
            .eq("id", condominio_id)
            .execute()
        )
        if c.data:
            nome_condominio = c.data[0].get("nome")
            limite_kw = c.data[0].get("limite_energia_kw")

    return {
        "encontrado": True,
        "usuario_id": u["id"],
        "nome": u.get("nome"),
        "tipo_usuario": u.get("tipo_usuario"),
        "bloco_apto": u.get("bloco_apto"),
        "saldo": u.get("saldo"),
        "condominio_id": condominio_id,
        "condominio_nome": nome_condominio,
        "condominio_moradia_id": moradia_id,
        "local_ajustado": local_ajustado,
        "limite_energia_kw": limite_kw,
        "fonte": ["usuarios", "condominios"],
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

    tarifa = _tarifa(carregador)
    energia = float(s.get("energia_entregue_kwh") or 0)

    return {
        "ativa": True,
        "sessao_id": s.get("id"),
        "status": s.get("status"),
        "percentual_atual": s.get("percentual_bateria_atual"),
        "percentual_inicial": s.get("percentual_bateria_inicial"),
        "potencia_atual_kw": s.get("potencia_atual_kw"),
        "energia_entregue_kwh": round(energia, 2),
        "tempo_estimado_min": s.get("tempo_estimado_min"),
        "custo_ate_agora": round(energia * tarifa, 2),
        "custo_estimado_total": s.get("custo_estimado"),
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
                    charger_id: str = None, alvo: float = 100.0) -> dict:
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
    est = CTX.calcular_estimativa(bruto, veiculo, soc, alvo)

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
        "tarifa_kwh": bruto.get("tarifa_kwh"),
        "fonte": ["carregadores", "veiculos"],
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
