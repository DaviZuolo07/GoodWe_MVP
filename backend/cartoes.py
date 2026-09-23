"""
cartoes.py - Cartões RFID: pessoais e compartilhados.
=====================================================

REGRA CENTRAL
-------------
O cartão NÃO é a identidade do pagamento. Quem paga é quem preparou a recarga
no aplicativo - essa pessoa está logada, escolheu o ponto, o veículo e o alvo,
e viu o custo estimado. O cartão responde outra pergunta: "tem alguém aqui,
na frente do carregador, mandando começar?".

Dois tipos:

  pessoal        Amarrado a um morador. Só autoriza a recarga DELE. É o modelo
                 de produção: cada um com o seu crachá.

  compartilhado  Amarrado ao CONDOMÍNIO. Não identifica ninguém. Autoriza a
                 recarga preparada naquele ponto, seja de quem for, e a
                 cobrança sai de quem preparou.

É o segundo que faz UM cartão físico atender a demonstração inteira: Joaquim
prepara e encosta -> debita do Joaquim; Marcos prepara e encosta o MESMO
cartão -> debita do Marcos. A placa não guarda nem aprende nada sobre eles -
ela só manda o uid e recebe sim ou não.

O QUE O COMPARTILHADO NÃO FAZ
-----------------------------
Não prova identidade. Quem estiver com ele pode confirmar a recarga que já
estiver preparada ali. Como a recarga nasce de alguém logado e a cobrança é
dessa pessoa, o pior caso é "iniciar a recarga que o vizinho acabou de pedir".
Quem quiser a trava forte cadastra um cartão pessoal - ele passa a valer para
essa pessoa, e o compartilhado segue atendendo os demais.
"""

import re

from fastapi import HTTPException

from config import agora_iso, supabase, um

UID_VALIDO = re.compile(r"^[0-9A-F]{4,32}$")


def normalizar(uid: str) -> str:
    """Leitores escrevem o mesmo cartão de formas diferentes: A1:B2 c3-d4."""
    limpo = re.sub(r"[\s:\-]", "", (uid or "")).upper()
    if not UID_VALIDO.fullmatch(limpo):
        raise HTTPException(status_code=400,
                            detail="UID inválido: use só hexadecimal (ex.: A1B2C3D4).")
    return limpo


def por_uid(uid: str) -> dict | None:
    return um(supabase.table("cartoes_rfid").select("*").eq("uid", uid).eq("ativo", True).execute())


def do_usuario(usuario_id: str) -> list[dict]:
    return supabase.table("cartoes_rfid").select("*").eq("usuario_id", usuario_id) \
        .order("criado_em").execute().data or []


def do_condominio(condominio_id: str) -> list[dict]:
    return supabase.table("cartoes_rfid").select("*").eq("condominio_id", condominio_id) \
        .eq("escopo", "compartilhado").order("criado_em").execute().data or []


def registrar_pessoal(usuario_id: str, uid: str, apelido: str | None = None) -> dict:
    uid = normalizar(uid)
    existente = um(supabase.table("cartoes_rfid").select("*").eq("uid", uid).execute())
    if existente:
        if existente["escopo"] == "compartilhado":
            raise HTTPException(status_code=409, detail=(
                "Este cartão é o cartão compartilhado do condomínio e não pode virar pessoal."))
        if existente["usuario_id"] != usuario_id:
            raise HTTPException(status_code=409, detail="Esse cartão já pertence a outro morador.")
        return existente
    return um(supabase.table("cartoes_rfid").insert({
        "uid": uid, "escopo": "pessoal", "usuario_id": usuario_id,
        "apelido": apelido or "Cartão pessoal",
    }).execute())


def registrar_compartilhado(condominio_id: str, uid: str, apelido: str | None = None) -> dict:
    uid = normalizar(uid)
    existente = um(supabase.table("cartoes_rfid").select("*").eq("uid", uid).execute())
    if existente:
        if existente["escopo"] == "pessoal":
            raise HTTPException(status_code=409, detail=(
                "Este cartão é pessoal de um morador. Peça para ele removê-lo antes."))
        if existente["condominio_id"] != condominio_id:
            raise HTTPException(status_code=409, detail="Esse cartão já é de outro condomínio.")
        return existente
    return um(supabase.table("cartoes_rfid").insert({
        "uid": uid, "escopo": "compartilhado", "condominio_id": condominio_id,
        "apelido": apelido or "Cartão do condomínio",
    }).execute())


def remover(uid: str, *, usuario_id: str | None = None, condominio_id: str | None = None) -> bool:
    """Remove só o que pertence a quem pediu - nunca por uid solto."""
    q = supabase.table("cartoes_rfid").delete().eq("uid", normalizar(uid))
    if usuario_id:
        q = q.eq("usuario_id", usuario_id).eq("escopo", "pessoal")
    elif condominio_id:
        q = q.eq("condominio_id", condominio_id).eq("escopo", "compartilhado")
    else:
        raise ValueError("remover() exige usuario_id ou condominio_id")
    return bool(q.execute().data)


def marcar_uso(uid: str) -> None:
    supabase.table("cartoes_rfid").update({"ultimo_uso": agora_iso()}).eq("uid", uid).execute()


def autoriza(cartao: dict, sessao: dict, condominio_id: str) -> tuple[bool, str | None]:
    """
    O cartão pode confirmar ESTA sessão? Devolve (pode, motivo_da_recusa).

    Pessoal: só a recarga do dono. Era exatamente aqui que, no modelo antigo,
    dava para pendurar o próprio cartão na conta de outro e carregar com o
    saldo dele - por isso a comparação é com o dono da SESSÃO, e o débito
    nunca sai do dono do cartão.

    Compartilhado: qualquer recarga preparada num ponto do mesmo condomínio.
    """
    if cartao["escopo"] == "pessoal":
        if cartao["usuario_id"] != sessao["usuario_id"]:
            return False, "cartao_de_outro_usuario"
        return True, None

    if cartao.get("condominio_id") != condominio_id:
        return False, "cartao_de_outro_condominio"
    return True, None
