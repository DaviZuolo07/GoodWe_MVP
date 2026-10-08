"""
rotas_conta.py - Login, cadastro e tudo que é "meu" (/me/...).
==============================================================

Nenhuma rota daqui aceita `usuario_id` do cliente (Bloco 2). As antigas
`/usuarios/{id}/...` sumiram: nelas, trocar o id na URL bastava para pôr
saldo na conta de outra pessoa ou vincular o próprio cartão à conta dela -
e aí carregar pagando com o saldo alheio.
"""

import hmac
import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import cartoes
import carteira
from config import (BONUS_BOAS_VINDAS, CODIGO_CADASTRO, CONDOMINIO_PADRAO, CREDITO_MAXIMO,
                    supabase, um)
from fisica import detalhar_custo
from identidade import CAMPOS_PUBLICOS, usuario_logado
from seguranca import (SENHA_MAX, conferir_senha, emitir_token, gerar_hash_senha,
                       hash_ficticio, ip_do_cliente, limitador_cadastro, limitador_por_ip,
                       limitador_por_nome, precisa_rehash, validar_forca_senha)

router = APIRouter(tags=["conta"])

NOME_VALIDO = re.compile(r"[A-Za-zÀ-ÿ0-9 .'\-]{2,60}")


# ---------------------------------------------------------------------------
# Modelos - repare: nenhum tem usuario_id
# ---------------------------------------------------------------------------

class CadastroRequest(BaseModel):
    nome: str = Field(..., min_length=2, max_length=60)
    senha: str = Field(..., min_length=1, max_length=SENHA_MAX)
    condominio_id: Optional[str] = None
    # Gestor NÃO se cadastra pela tela pública: nasce pela migration.
    tipo_usuario: Literal["morador", "visitante"] = "morador"
    bloco_apto: Optional[str] = Field(None, max_length=40)
    veiculo_modelo: str = Field(..., min_length=1, max_length=60)
    veiculo_placa: Optional[str] = Field(None, max_length=10)
    veiculo_tipo: Literal["carro", "celular"] = "carro"
    capacidade_bateria_kwh: float = Field(40, gt=0, le=250)
    potencia_carro_kw: float = Field(7.4, gt=0, le=350)
    # Só é conferido quando CODIGO_CADASTRO está definido no ambiente.
    codigo_convite: Optional[str] = Field(None, max_length=64)


class LoginRequest(BaseModel):
    nome: str = Field(..., min_length=1, max_length=60)
    senha: str = Field(..., min_length=1, max_length=SENHA_MAX)


class CreditoRequest(BaseModel):
    valor: float = Field(..., gt=0, le=CREDITO_MAXIMO)


class CartaoRequest(BaseModel):
    rfid_uid: str = Field(..., min_length=4, max_length=40)
    apelido: Optional[str] = Field(None, max_length=40)


class FavoritoRequest(BaseModel):
    condominio_id: str


class VeiculoRequest(BaseModel):
    modelo: str = Field(..., min_length=1, max_length=60)
    placa: Optional[str] = Field(None, max_length=10)
    tipo: Literal["carro", "celular"] = "carro"
    capacidade_bateria_kwh: float = Field(40, gt=0, le=250)
    potencia_carro_kw: float = Field(7.4, gt=0, le=350)


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------

def _ip(request: Request) -> str:
    # Atrás de proxy, o IP real vem do X-Forwarded-For (ver seguranca.py).
    return ip_do_cliente(request)


def _veiculos(usuario_id: str) -> list:
    return supabase.table("veiculos").select("*").eq("usuario_id", usuario_id) \
        .order("criado_em").execute().data or []


# `perfil` só existe a partir da migration 19. Se ela ainda não rodou, o
# PostgREST recusa a coluna; caímos no formato antigo e lembramos a decisão
# para não bater na mesma pedra a cada requisição.
_condominios_tem_perfil = None


def _condominios_ordenados() -> list:
    global _condominios_tem_perfil
    if _condominios_tem_perfil is not False:
        try:
            dados = supabase.table("condominios").select("id, nome, endereco, perfil") \
                .order("nome").execute().data or []
            _condominios_tem_perfil = True
            return dados
        except Exception:
            _condominios_tem_perfil = False
    return supabase.table("condominios").select("id, nome, endereco").order("nome").execute().data or []


def _resposta_autenticada(usuario: dict) -> dict:
    vs = _veiculos(usuario["id"])
    usuario = {k: usuario.get(k) for k in CAMPOS_PUBLICOS.replace(" ", "").split(",")}
    usuario["saldo"] = round(float(usuario.get("saldo") or 0), 2)
    return {"success": True, "usuario": usuario, "veiculo": vs[0] if vs else None,
            "veiculos": vs, "cartoes": cartoes.do_usuario(usuario["id"]),
            **emitir_token(usuario["id"])}


def _placa(bruta: Optional[str]) -> Optional[str]:
    """Só letras e números: a placa entra num ILIKE, e '%' seria curinga."""
    return re.sub(r"[^A-Z0-9]", "", (bruta or "").upper()) or None


def _checar_capacidade(tipo: str, capacidade: float, potencia: float) -> None:
    # Um "celular" de 40 kWh passaria na bancada USB e levaria dias.
    if tipo == "celular" and (capacidade > 0.2 or potencia > 0.2):
        raise HTTPException(status_code=400, detail=(
            "Celular: capacidade até 0,2 kWh (ex.: 0,015 = 15 Wh) e potência até 0,2 kW."))


# ---------------------------------------------------------------------------
# Login e cadastro
# ---------------------------------------------------------------------------

@router.get("/config-publica")
def config_publica():
    """O que a tela de cadastro precisa saber antes do login. Nada sensível."""
    return {"cadastro_exige_codigo": bool(CODIGO_CADASTRO)}


@router.post("/cadastro")
def cadastro(payload: CadastroRequest, request: Request):
    limitador_cadastro.consumir(f"ip:{_ip(request)}")

    # Código do evento (se configurado). Comparação em tempo constante, e o
    # limitador acima já freia quem tenta adivinhar.
    if CODIGO_CADASTRO and not hmac.compare_digest(
            (payload.codigo_convite or "").strip().encode("utf-8"),
            CODIGO_CADASTRO.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Código de convite inválido.")

    nome = payload.nome.strip()
    if not NOME_VALIDO.fullmatch(nome):
        raise HTTPException(status_code=400,
                            detail="Use só letras, números, espaço, ponto, hífen ou apóstrofo no nome.")
    validar_forca_senha(payload.senha, nome)
    _checar_capacidade(payload.veiculo_tipo, payload.capacidade_bateria_kwh, payload.potencia_carro_kw)

    condominio_id = payload.condominio_id or CONDOMINIO_PADRAO

    # Uma chamada, uma transação (db/15): usuário, senha, veículo, favorito e
    # o bônus de boas-vindas no extrato. Falhou qualquer parte, não sobra
    # nada - nem usuário sem senha, nem nome ocupado para sempre. O nome
    # repetido é barrado por índice único (sem a corrida do "checa e insere").
    try:
        r = supabase.rpc("cadastrar_usuario", {
            "p_nome": nome,
            "p_senha_hash": gerar_hash_senha(payload.senha),
            "p_condominio": condominio_id,
            "p_tipo": payload.tipo_usuario,
            "p_bloco": payload.bloco_apto,
            "p_veiculo": {
                "modelo": payload.veiculo_modelo.strip(),
                "placa": _placa(payload.veiculo_placa),
                "tipo": payload.veiculo_tipo,
                "capacidade_bateria_kwh": payload.capacidade_bateria_kwh,
                "potencia_carro_kw": payload.potencia_carro_kw,
            },
            "p_bonus": BONUS_BOAS_VINDAS,
        }).execute()
    except Exception as e:
        texto = str(e)
        if "nome_em_uso" in texto:
            raise HTTPException(status_code=409, detail="Esse nome de usuário já está cadastrado.")
        if "condominio_invalido" in texto:
            raise HTTPException(status_code=400, detail="Condomínio inválido.")
        print(f"[CADASTRO] falhou para '{nome}': {type(e).__name__}: {texto[:200]}")
        raise HTTPException(status_code=500, detail="Não foi possível concluir o cadastro.")

    usuario_id = r.data[0] if isinstance(r.data, list) else r.data
    usuario = um(supabase.table("usuarios").select(CAMPOS_PUBLICOS).eq("id", usuario_id).execute())
    return _resposta_autenticada(usuario)


@router.post("/login")
def login(payload: LoginRequest, request: Request):
    """
    Nome inexistente e senha errada dão a MESMA resposta, no MESMO tempo
    (o Argon2 roda contra um hash fictício). Responder "usuário não
    encontrado" ensinaria quais nomes existem.
    """
    nome = payload.nome.strip()
    chave_nome, chave_ip = f"nome:{nome.lower()}", f"ip:{_ip(request)}"
    limitador_por_nome.verificar(chave_nome)
    limitador_por_ip.verificar(chave_ip)

    # ILIKE para o login não depender de maiúscula. O nome passa pela mesma
    # regex do cadastro ANTES: sem isso, digitar "%" casaria com o primeiro
    # usuário do banco (curinga do ILIKE).
    usuario = None
    if NOME_VALIDO.fullmatch(nome):
        usuario = um(supabase.table("usuarios").select(CAMPOS_PUBLICOS).ilike("nome", nome).execute())
    credencial = None
    if usuario:
        credencial = um(supabase.table("credenciais_usuario").select("senha_hash")
                        .eq("usuario_id", usuario["id"]).execute())

    hash_salvo = credencial["senha_hash"] if credencial else hash_ficticio()
    if not (usuario and credencial and conferir_senha(hash_salvo, payload.senha)):
        limitador_por_nome.registrar_falha(chave_nome)
        limitador_por_ip.registrar_falha(chave_ip)
        raise HTTPException(status_code=401, detail="Nome de usuário ou senha incorretos.")

    # Conta de gestor NÃO entra pelo app do morador (ADR-023): o painel tem
    # endereço, login e segundo fator próprios. A resposta é a mesma da senha
    # errada, para esta tela não servir de teste de senha de gestor nem
    # revelar quais nomes administram o condomínio.
    if usuario.get("tipo_usuario") == "gestor":
        limitador_por_nome.registrar_falha(chave_nome)
        limitador_por_ip.registrar_falha(chave_ip)
        raise HTTPException(status_code=401, detail="Nome de usuário ou senha incorretos.")

    limitador_por_nome.limpar(chave_nome)
    if precisa_rehash(credencial["senha_hash"]):
        supabase.table("credenciais_usuario").update(
            {"senha_hash": gerar_hash_senha(payload.senha)}).eq("usuario_id", usuario["id"]).execute()

    return _resposta_autenticada(usuario)


@router.get("/me")
def eu(usuario: dict = Depends(usuario_logado)):
    """O frontend relê daqui o saldo depois de cada movimento da carteira."""
    vs = _veiculos(usuario["id"])
    return {
        "usuario": usuario,
        "veiculo": vs[0] if vs else None,
        "veiculos": vs,
        "cartoes": cartoes.do_usuario(usuario["id"]),
        "cartoes_compartilhados": (cartoes.do_condominio(usuario["condominio_id"])
                                   if usuario.get("condominio_id") else []),
    }


# ---------------------------------------------------------------------------
# Carteira, cartão e veículos
# ---------------------------------------------------------------------------

@router.post("/me/carteira/creditar")
def creditar(payload: CreditoRequest, usuario: dict = Depends(usuario_logado)):
    """Crédito simulado (sem gateway). Vai para o extrato como qualquer movimento."""
    saldo = carteira.creditar(usuario["id"], payload.valor, "credito", "Crédito adicionado pelo app")
    return {"success": True, "saldo_atual": saldo}


@router.get("/me/extrato")
def extrato(limite: int = 100, usuario: dict = Depends(usuario_logado)):
    """
    O extrato da carteira com a energia de cada recarga POR FONTE (ADR-016 D8).
    O dinheiro continua reserva -> estorno (saldo = soma do extrato); cada
    movimento ligado a uma recarga traz as linhas do recibo dela: energia,
    origem (rede | solar_simulado | solar_medido) e preço de cada uma.
    """
    limite = max(1, min(200, int(limite)))
    movimentos = supabase.table("movimentacoes_carteira").select(
        "tipo, valor, saldo_apos, descricao, sessao_id, criado_em"
    ).eq("usuario_id", usuario["id"]).order("criado_em", desc=True).limit(limite).execute().data or []
    ids = list({m["sessao_id"] for m in movimentos if m.get("sessao_id")})
    sessoes = {}
    if ids:
        for s in supabase.table("sessoes_recarga").select("*").in_("id", ids) \
                .eq("usuario_id", usuario["id"]).execute().data or []:
            sessoes[s["id"]] = s
    for m in movimentos:
        s = sessoes.get(m.get("sessao_id"))
        m["energia_por_fonte"] = detalhar_custo(s)["itens"] if s and s.get("status") == "finalizada" else None
    return {"saldo": carteira.saldo_de(usuario["id"]), "movimentos": movimentos}


@router.get("/me/cartoes")
def meus_cartoes(usuario: dict = Depends(usuario_logado)):
    """Os meus cartões pessoais + os compartilhados do condomínio onde moro."""
    return {
        "pessoais": cartoes.do_usuario(usuario["id"]),
        "compartilhados": cartoes.do_condominio(usuario["condominio_id"]) if usuario.get("condominio_id") else [],
    }


@router.post("/me/cartao")
def vincular_cartao(payload: CartaoRequest, usuario: dict = Depends(usuario_logado)):
    """
    Cadastra um cartão PESSOAL. A partir daí ele autoriza só as recargas
    desta conta. Não é obrigatório: onde há cartão compartilhado do
    condomínio, ele já atende (ver cartoes.py).
    """
    cartao = cartoes.registrar_pessoal(usuario["id"], payload.rfid_uid, payload.apelido)
    return {"success": True, "cartao": cartao, "rfid_uid": cartao["uid"]}


@router.delete("/me/cartao/{uid}")
def remover_cartao(uid: str, usuario: dict = Depends(usuario_logado)):
    if not cartoes.remover(uid, usuario_id=usuario["id"]):
        raise HTTPException(status_code=404, detail="Cartão não encontrado nos seus cartões.")
    return {"success": True}


@router.get("/me/veiculos")
def listar_veiculos(usuario: dict = Depends(usuario_logado)):
    return _veiculos(usuario["id"])


@router.post("/me/veiculos")
def adicionar_veiculo(payload: VeiculoRequest, usuario: dict = Depends(usuario_logado)):
    _checar_capacidade(payload.tipo, payload.capacidade_bateria_kwh, payload.potencia_carro_kw)
    placa = _placa(payload.placa)
    if placa and supabase.table("veiculos").select("id").ilike("placa", placa).execute().data:
        raise HTTPException(status_code=409, detail="Já existe um veículo com essa placa.")
    v = um(supabase.table("veiculos").insert({
        "usuario_id": usuario["id"], "modelo": payload.modelo.strip(), "placa": placa,
        "tipo": payload.tipo, "capacidade_bateria_kwh": payload.capacidade_bateria_kwh,
        "potencia_carro_kw": payload.potencia_carro_kw,
    }).execute())
    return {"success": True, "veiculo": v}


# ---------------------------------------------------------------------------
# Locais: catálogo público e favoritos (allowlist do chatbot)
# ---------------------------------------------------------------------------

@router.get("/condominios")
def listar_condominios():
    """Público: alimenta o cadastro. Nome e endereço não são dado pessoal."""
    return _condominios_ordenados()


def locais_do_usuario(usuario: dict) -> dict:
    favs = supabase.table("condominios_favoritos").select("condominio_id") \
        .eq("usuario_id", usuario["id"]).execute().data or []
    ids = {f["condominio_id"] for f in favs}
    if usuario.get("condominio_id"):
        ids.add(usuario["condominio_id"])
    todos = _condominios_ordenados()
    return {"padrao_id": usuario.get("condominio_id"),
            "favoritos": [c for c in todos if c["id"] in ids], "todos": todos}


@router.get("/me/locais")
def meus_locais(usuario: dict = Depends(usuario_logado)):
    return locais_do_usuario(usuario)


@router.post("/me/favoritos")
def favoritar(payload: FavoritoRequest, usuario: dict = Depends(usuario_logado)):
    if not um(supabase.table("condominios").select("id").eq("id", payload.condominio_id).execute()):
        raise HTTPException(status_code=404, detail="Condomínio não encontrado.")
    supabase.table("condominios_favoritos").upsert(
        {"usuario_id": usuario["id"], "condominio_id": payload.condominio_id},
        on_conflict="usuario_id,condominio_id").execute()
    return locais_do_usuario(usuario)


@router.delete("/me/favoritos/{condominio_id}")
def desfavoritar(condominio_id: str, usuario: dict = Depends(usuario_logado)):
    if usuario.get("condominio_id") == condominio_id:
        raise HTTPException(status_code=400,
                            detail="O condomínio onde você mora não pode sair dos favoritos.")
    supabase.table("condominios_favoritos").delete().eq("usuario_id", usuario["id"]) \
        .eq("condominio_id", condominio_id).execute()
    return locais_do_usuario(usuario)


@router.get("/chargers")
def listar_carregadores(condominio_id: Optional[str] = None,
                        usuario: dict = Depends(usuario_logado)):
    alvo = condominio_id or usuario.get("condominio_id") or CONDOMINIO_PADRAO
    return supabase.table("carregadores").select("*").eq("condominio_id", alvo) \
        .order("numero").execute().data
