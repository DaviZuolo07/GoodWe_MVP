"""
Redator determinístico - transforma os fatos do banco em frases em português.

Este módulo é o FALLBACK do briefing, e é também a rede de segurança do sistema
inteiro: se o Ollama estiver fora do ar no dia da gravação, o chat responde
daqui e ninguém percebe. Nenhuma frase aqui inventa número - todo valor vem do
dicionário de fatos que a camada de dados devolveu.

Formatação em padrão brasileiro: R$ 1,95 e não R$ 1.95. Parece detalhe, mas era
o que estava na tela e um jurado nota.
"""

from . import router as R


def brl(valor) -> str:
    if valor is None:
        return "—"
    return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def num(valor, casas: int = 2) -> str:
    """Número em padrão BR, sem zero à toa: 7,4 kW e não 7,40 kW."""
    if valor is None:
        return "—"
    texto = f"{float(valor):.{casas}f}"
    if "." in texto:                      # só corta zero de decimal: 7.40 -> 7.4
        texto = texto.rstrip("0").rstrip(".")   # ...mas nunca de 20 -> 2
    return (texto or "0").replace(".", ",")


def energia(kwh) -> str:
    """Celular de bancada entrega Wh, não kWh: 0,0065 kWh vira 6,5 Wh."""
    if kwh is None:
        return "—"
    kwh = float(kwh)
    return f"{num(kwh * 1000, 1)} Wh" if kwh < 1 else f"{num(kwh)} kWh"


def potencia(kw) -> str:
    if kw is None:
        return "—"
    kw = float(kw)
    return f"{num(kw * 1000, 1)} W" if kw < 1 else f"{num(kw)} kW"


def duracao(minutos) -> str:
    if minutos is None:
        return "—"
    minutos = int(minutos)
    if minutos < 60:
        return f"{minutos} min"
    h, m = divmod(minutos, 60)
    return f"{h}h{m:02d}" if m else f"{h}h"


def lista(itens) -> str:
    itens = [str(i) for i in itens if i is not None]
    if not itens:
        return ""
    if len(itens) == 1:
        return itens[0]
    return ", ".join(itens[:-1]) + f" e {itens[-1]}"


SEM_RECARGA = "Você não tem nenhuma recarga em andamento agora."


def onde(ctx: dict) -> str:
    """
    " no Portal dos Bandeirantes" - ou string vazia.

    Dizer o local em voz alta não é enfeite: o usuário acabou de escolher um
    lugar no seletor, e ver o nome de volta na resposta é o que confirma que o
    bot está falando do lugar certo. Numa banca, é a diferença entre "confio no
    número" e "de onde saiu isso".
    """
    nome = (ctx or {}).get("condominio_nome")
    return f" no {nome}" if nome else ""


def redigir(intencao: str, fatos: dict, ctx: dict) -> str:
    """Ponto de entrada: intenção + fatos -> frase pronta."""
    f = fatos or {}

    if intencao == R.TENTATIVA_INJECAO:
        return ("Só consigo responder sobre a sua conta e o seu condomínio, com os "
                "dados que o sistema me entrega. Não consigo assumir outra identidade "
                "nem consultar dados de outro morador. Posso ajudar com sua recarga, "
                "os carregadores, a fila ou seu saldo.")

    if intencao == R.FORA_DE_ESCOPO:
        return ("Isso está fora do que eu cubro. Sou o assistente de recarga do "
                "ChargeOps: falo sobre carregadores, sua recarga, fila, tarifas, "
                "veículos e saldo. Sobre o que posso ajudar?")

    if intencao == R.AJUDA:
        nome = (ctx or {}).get("nome") or ""
        saudacao = f"Olá, {nome.split()[0]}! " if nome else "Olá! "
        local = (ctx or {}).get("condominio_nome")
        if local:
            saudacao += f"Você está vendo o {local}. "
        return (saudacao + "Posso responder sobre: tempo restante e status da sua "
                "recarga, quanto ela está custando, tarifa por kWh de cada ponto, "
                "carregadores disponíveis, fila, seu saldo, seus veículos, seu "
                "histórico, a potência do condomínio e como a cobrança funciona.")

    if intencao == R.TARIFA:
        itens = f.get("tarifas") or []
        if not itens:
            return "Não encontrei carregadores cadastrados no seu condomínio."
        if f.get("tarifa_unica"):
            return (f"A tarifa{onde(ctx)} é de {brl(itens[0]['tarifa_kwh'])} por kWh "
                    f"em todos os {len(itens)} pontos.")
        partes = [f"o {i['numero']} cobra {brl(i['tarifa_kwh'])}/kWh" for i in itens]
        return (f"As tarifas variam por ponto{onde(ctx)}: " + lista(partes) + ".")

    if intencao == R.CUSTO_ATUAL:
        if not f.get("ativa"):
            return SEM_RECARGA + " Se quiser, posso te dizer a tarifa por kWh de cada ponto."
        return (f"Sua recarga no carregador {f['carregador_numero']} já consumiu "
                f"{energia(f['energia_entregue_kwh'])}, o que dá "
                f"{brl(f['custo_ate_agora'])} até agora "
                f"(tarifa de {brl(f['tarifa_kwh'])} por kWh"
                + (f"; o teto reservado é {brl(f['valor_reservado'])}" if f.get('valor_reservado') else "")
                + ").")

    if intencao == R.TEMPO_RESTANTE:
        if not f.get("ativa"):
            return SEM_RECARGA
        return (f"Faltam cerca de {duracao(f['tempo_estimado_min'])} para completar. "
                f"A bateria está em {num(f['percentual_atual'], 1)}% e o carregador "
                f"está entregando {potencia(f['potencia_atual_kw'])} agora.")

    if intencao == R.STATUS_RECARGA:
        if not f.get("ativa"):
            return SEM_RECARGA
        return (f"Recarga do {f.get('veiculo_modelo') or 'seu veículo'} no carregador "
                f"{f['carregador_numero']}: bateria em {num(f['percentual_atual'], 1)}%, "
                f"potência de {potencia(f['potencia_atual_kw'])}, "
                f"{energia(f['energia_entregue_kwh'])} entregues e "
                f"{duracao(f['tempo_estimado_min'])} restantes.")

    if intencao == R.CARREGADORES_DISPONIVEIS:
        disp = f.get("disponiveis") or []
        total = f.get("total") or 0
        if not disp:
            em_uso = len(f.get("em_uso") or [])
            return (f"Nenhum carregador livre{onde(ctx)} agora — {em_uso} de {total} "
                    "estão em uso. Posso te colocar na fila pelo painel.")
        return (f"Estão livres agora{onde(ctx)}: {lista(disp)} "
                f"({len(disp)} de {total} pontos).")

    if intencao == R.INFO_CARREGADOR:
        if not f.get("encontrado"):
            return ("Não encontrei esse carregador no seu condomínio. "
                    "Confere o número no painel?")
        return (f"Carregador {f['numero']} ({f.get('modelo') or 'modelo não informado'}): "
                f"{f.get('tipo') or '—'}, até {num(f['potencia_maxima_kw'])} kW, "
                f"conector {f.get('conector') or '—'}, tarifa {brl(f['tarifa_kwh'])}/kWh. "
                f"Status: {f.get('status')}. Temperatura: {num(f.get('temperatura_c'), 1)} °C.")

    if intencao == R.FILA_STATUS:
        total = f.get("total_na_fila") or 0
        if f.get("minha_posicao"):
            return (f"Você está na posição {f['minha_posicao']} da fila do carregador "
                    f"{f.get('meu_carregador')}. Ao todo há {total} "
                    f"{'carro' if total == 1 else 'carros'} aguardando no condomínio.")
        if total == 0:
            return (f"Não há ninguém na fila{onde(ctx)} agora — os pontos livres são "
                    "de entrada direta.")
        partes = [f"{p['carros']} no {p['numero']}" for p in f.get("por_carregador", [])]
        return f"Há {total} na fila do condomínio: {lista(partes)}. Você não está na fila."

    if intencao == R.MEU_SALDO:
        return (f"Seu saldo é de {brl(f.get('saldo'))}. Ao aproximar o cartão, o valor "
                "estimado da recarga fica reservado; no fim, a diferença para o consumo "
                "real volta para a carteira.")

    if intencao == R.MEUS_VEICULOS:
        vs = f.get("veiculos") or []
        if not vs:
            return "Você ainda não tem veículo cadastrado. Dá para adicionar em Meus Veículos."
        partes = [
            f"{v.get('modelo')} ({v.get('placa')}), bateria de "
            f"{num(v.get('capacidade_bateria_kwh'), 1)} kWh em "
            f"{num(v.get('percentual_bateria'), 0)}%"
            for v in vs
        ]
        return "Seus veículos: " + lista(partes) + "."

    if intencao == R.SIMULAR_RECARGA:
        if not f.get("disponivel"):
            motivos = {
                "sem_veiculo": "Você precisa cadastrar um veículo antes de eu simular.",
                "sem_carregador_livre": "Não há carregador livre agora para simular.",
                "carregador_nao_encontrado": "Não achei esse carregador no seu condomínio.",
                "calculo_indisponivel": "O cálculo de estimativa não está disponível agora.",
            }
            return motivos.get(f.get("motivo"), "Não consegui montar a simulação agora.")
        return (f"Levar o {f['veiculo_modelo']} de {num(f['percentual_atual'], 0)}% até "
                f"{num(f['alvo_percentual'], 0)}% no carregador {f['carregador_numero']}: "
                f"cerca de {energia(f['energia_kwh'])}, {duracao(f['tempo_min'])} e "
                f"{brl(f['custo'])} pela tarifa de {brl(f['tarifa_kwh'])}/kWh. "
                f"A {num(f['temperatura_c'], 0)} °C o ponto entrega "
                f"{potencia(f['potencia_kw'])}"
                + (" (horário de ponta: tarifa maior agora)." if f.get("em_ponta") else "."))

    if intencao == R.HISTORICO_RECENTE:
        recargas = f.get("recargas") or []
        if not recargas:
            return "Não encontrei recargas finalizadas no seu histórico ainda."
        return (f"Suas últimas {f['quantidade']} recargas somam "
                f"{num(f['total_kwh'])} kWh e {brl(f['total_gasto'])}. "
                f"A mais recente entregou {num(recargas[0]['energia_kwh'])} kWh "
                f"por {brl(recargas[0]['custo'])}.")

    if intencao == R.DEMANDA:
        if not f.get("encontrado"):
            return "Não encontrei os dados de potência deste condomínio."
        ponta = (f"Agora é horário de ponta ({f['ponta_inicio']} às {f['ponta_fim']}): o limite "
                 f"para recarga cai para {f['ponta_percentual_limite']}% e a tarifa fica "
                 f"{num(f['ponta_multiplicador'], 2)}x maior."
                 if f.get("em_ponta") else
                 f"O horário de ponta é das {f['ponta_inicio']} às {f['ponta_fim']} em dias "
                 "úteis; nele o limite cai e a tarifa sobe.")
        geral = (f"O condomínio{onde(ctx)} libera até {potencia(f['limite_agora_kw'])} para recarga e "
                 f"tem {potencia(f['carga_agora_kw'])} reservados para {f['recargas_ativas']} recarga(s) em andamento. "
                 "O sistema divide essa potência entre os carros para nunca passar do limite do quadro.")
        m = f.get("minha")
        if not m:
            return f"{geral} {ponta}"
        if m.get("limitada"):
            sua = (f"Sua recarga no ponto {m['carregador_numero']} está recebendo "
                   f"{potencia(m['potencia_alocada_kw'])} de {potencia(m['potencia_maxima_kw'])} possíveis, "
                   f"porque os carros ligados pediriam {potencia(f['demanda_agora_kw'])}. Quando alguém "
                   "terminar, a sua sobe sozinha.")
        elif m.get("fixa"):
            sua = (f"Sua recarga no ponto {m['carregador_numero']} não é limitada pelo condomínio: a "
                   f"potência é a que o aparelho puxa, {potencia(m['potencia_atual_kw'])} agora, medida pelo sensor.")
        elif float(m.get("percentual_atual") or 0) > 80:
            sua = (f"Sua recarga no ponto {m['carregador_numero']} não é limitada pelo condomínio. Ela "
                   f"desacelerou porque a bateria passou de 80% e aceita menos potência.")
        else:
            sua = (f"Sua recarga no ponto {m['carregador_numero']} não é limitada pelo condomínio: "
                   f"está puxando {potencia(m['potencia_atual_kw'])}.")
        return f"{sua} {geral} {ponta}"

    if intencao == R.COBRANCA:
        base = ("Funciona como pré-autorização: ao aproximar o cartão, reservamos o custo "
                "estimado; cada kWh é cobrado pela tarifa do horário em que foi entregue "
                f"(na ponta, {f['ponta_inicio']} às {f['ponta_fim']}, fica "
                f"{num(f['ponta_multiplicador'], 2)}x); ao terminar, a diferença volta na hora.")
        u = f.get("ultima")
        if u and u.get("reservado") is not None:
            base += (f" Na sua última recarga: reservado {brl(u['reservado'])}, custo real "
                     f"{brl(u['custo_final'])}, estorno de {brl(u.get('estornado') or 0)}.")
        return base

    return ("Posso ajudar com sua recarga, carregadores, fila, tarifas, saldo e "
            "veículos. O que você quer saber?")
