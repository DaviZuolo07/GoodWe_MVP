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
                "carregadores disponíveis, fila, seu saldo, seus veículos e seu "
                "histórico de recargas.")

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
                f"{num(f['energia_entregue_kwh'])} kWh, o que dá "
                f"{brl(f['custo_ate_agora'])} até agora "
                f"(tarifa de {brl(f['tarifa_kwh'])} por kWh).")

    if intencao == R.TEMPO_RESTANTE:
        if not f.get("ativa"):
            return SEM_RECARGA
        return (f"Faltam cerca de {duracao(f['tempo_estimado_min'])} para completar. "
                f"A bateria está em {num(f['percentual_atual'], 1)}% e o carregador "
                f"está entregando {num(f['potencia_atual_kw'])} kW agora.")

    if intencao == R.STATUS_RECARGA:
        if not f.get("ativa"):
            return SEM_RECARGA
        return (f"Recarga do {f.get('veiculo_modelo') or 'seu veículo'} no carregador "
                f"{f['carregador_numero']}: bateria em {num(f['percentual_atual'], 1)}%, "
                f"potência de {num(f['potencia_atual_kw'])} kW, "
                f"{num(f['energia_entregue_kwh'])} kWh entregues e "
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
        return (f"Seu saldo é de {brl(f.get('saldo'))}. Ele é debitado no início da "
                "recarga pela estimativa até 100%.")

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
                f"cerca de {num(f['energia_kwh'])} kWh, {duracao(f['tempo_min'])} e "
                f"{brl(f['custo'])} pela tarifa de {brl(f['tarifa_kwh'])}/kWh. "
                f"A {num(f['temperatura_c'], 0)} °C o ponto entrega "
                f"{num(f['potencia_kw'])} kW.")

    if intencao == R.HISTORICO_RECENTE:
        recargas = f.get("recargas") or []
        if not recargas:
            return "Não encontrei recargas finalizadas no seu histórico ainda."
        return (f"Suas últimas {f['quantidade']} recargas somam "
                f"{num(f['total_kwh'])} kWh e {brl(f['total_gasto'])}. "
                f"A mais recente entregou {num(recargas[0]['energia_kwh'])} kWh "
                f"por {brl(recargas[0]['custo'])}.")

    return ("Posso ajudar com sua recarga, carregadores, fila, tarifas, saldo e "
            "veículos. O que você quer saber?")
