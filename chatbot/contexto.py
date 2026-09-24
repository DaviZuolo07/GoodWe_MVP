"""
Camada 2 - CONTEXTO.
====================

Monta o que o assistente pode saber sobre QUEM pergunta e sobre QUAL LOCAL.

  - Identidade: vem do token (main.py passa `usuario_id` resolvido pelo JWT).
    Não existe caminho do texto da mensagem até a identidade: "sou o
    usuário X" é só texto.
  - Local: o escolhido no seletor do chat é PEDIDO. Só vale se estiver na
    allowlist (favoritos + moradia). Fora dela, cai na moradia em silêncio.
  - Para o modelo vai o MÍNIMO: primeiro nome e nome do local. Nenhum id,
    nenhum saldo que a pergunta não pediu.
"""

from .deps import CTX, sb


def locais_permitidos(usuario_id: str, condominio_moradia: str = None) -> set:
    permitidos = {condominio_moradia} if condominio_moradia else set()
    if not usuario_id:
        return permitidos
    try:
        r = sb().table("condominios_favoritos").select("condominio_id") \
            .eq("usuario_id", usuario_id).execute()
        permitidos.update(f["condominio_id"] for f in (r.data or []))
    except Exception as e:
        print(f"[CHATBOT] favoritos indisponíveis ({e}) - usando só a moradia")
    return permitidos


def ctx_usuario(usuario_id: str, condominio_escolhido: str = None) -> dict:
    vazio = {"encontrado": False, "fonte": ["usuarios"]}
    if not usuario_id:
        return vazio

    r = sb().table("usuarios").select(
        "id, nome, tipo_usuario, condominio_id, bloco_apto, saldo"
    ).eq("id", usuario_id).execute()
    if not r.data:
        return vazio
    u = r.data[0]

    moradia_id = u.get("condominio_id") or CTX.condominio_padrao
    condominio_id, local_ajustado = moradia_id, False
    if condominio_escolhido and condominio_escolhido != moradia_id:
        if condominio_escolhido in locais_permitidos(usuario_id, moradia_id):
            condominio_id = condominio_escolhido
        else:
            local_ajustado = True
            print(f"[CHATBOT] local fora da allowlist ({condominio_escolhido}) - usando a moradia")

    cond = {}
    if condominio_id:
        c = sb().table("condominios").select("*").eq("id", condominio_id).execute()
        cond = c.data[0] if c.data else {}

    return {
        "encontrado": True,
        "usuario_id": u["id"],
        "nome": u.get("nome"),
        "tipo_usuario": u.get("tipo_usuario"),
        "bloco_apto": u.get("bloco_apto"),
        "saldo": u.get("saldo"),
        "condominio_id": condominio_id,
        "condominio_nome": cond.get("nome"),
        "condominio": cond,
        "condominio_moradia_id": moradia_id,
        "local_ajustado": local_ajustado,
        "fonte": ["usuarios", "condominios"],
    }


def contexto_para_modelo(ctx: dict) -> dict:
    """O que o LLM enxerga do usuário: primeiro nome e local. Mais nada."""
    nome = (ctx or {}).get("nome") or ""
    return {"nome": nome.split()[0] if nome else None,
            "condominio": (ctx or {}).get("condominio_nome")}
