"""
carteira.py - Saldo do morador, sempre por operação atômica no banco.
=====================================================================

COMO A COBRANÇA FUNCIONA (o que a banca pediu para explicar)
------------------------------------------------------------
1. PRÉ-AUTORIZAÇÃO  Ao aproximar o cartão, reservamos o custo ESTIMADO da
                    recarga (a prévia que o morador viu na tela). Se o saldo
                    não cobre, a recarga não começa.
2. MEDIÇÃO          Durante a recarga, cada kWh é contado separando o que caiu
                    fora e dentro do horário de ponta.
3. TETO             Se o custo medido alcançar o valor reservado, a recarga
                    para sozinha. O morador nunca paga mais do que autorizou.
4. ESTORNO          Ao terminar, o custo real é calculado e a diferença entre
                    o reservado e o real volta para a carteira na hora.

Tudo vira linha no extrato (`movimentacoes_carteira`): crédito, reserva e
estorno. É o que o morador vê na Carteira e o que o gestor soma no painel.

POR QUE RPC E NÃO UPDATE
------------------------
"Lê o saldo, subtrai, grava" em duas requisições tem uma janela em que outra
cobrança lê o mesmo saldo - e uma das duas some. `debitar_saldo` (ver
db/12_produto.sql) faz a conta numa instrução só, com a trava `saldo >= valor`
dentro do próprio UPDATE.
"""

from fastapi import HTTPException

from config import supabase


class SaldoInsuficiente(Exception):
    pass


def _valor_rpc(resposta) -> float:
    dados = getattr(resposta, "data", None)
    if isinstance(dados, list):
        dados = dados[0] if dados else None
    if isinstance(dados, dict):
        dados = next(iter(dados.values()), None)
    return round(float(dados or 0), 2)


def debitar(usuario_id: str, valor: float, tipo: str, descricao: str,
            sessao_id: str | None = None) -> float:
    """Devolve o saldo novo. Levanta SaldoInsuficiente se não cobrir."""
    try:
        r = supabase.rpc("debitar_saldo", {
            "p_usuario": usuario_id, "p_valor": round(float(valor), 2), "p_tipo": tipo,
            "p_descricao": descricao, "p_sessao": sessao_id,
        }).execute()
    except Exception as e:  # APIError do PostgREST carrega a mensagem do RAISE
        if "saldo_insuficiente" in str(e):
            raise SaldoInsuficiente() from e
        raise
    return _valor_rpc(r)


def creditar(usuario_id: str, valor: float, tipo: str, descricao: str,
             sessao_id: str | None = None) -> float:
    r = supabase.rpc("creditar_saldo", {
        "p_usuario": usuario_id, "p_valor": round(float(valor), 2), "p_tipo": tipo,
        "p_descricao": descricao, "p_sessao": sessao_id,
    }).execute()
    return _valor_rpc(r)


def saldo_de(usuario_id: str) -> float:
    r = supabase.table("usuarios").select("saldo").eq("id", usuario_id).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    return round(float(r.data[0]["saldo"] or 0), 2)
