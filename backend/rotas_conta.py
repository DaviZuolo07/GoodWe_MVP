"""
rotas_conta.py - Login, cadastro e tudo que é "meu" (/me/...).
==============================================================

Nenhuma rota daqui aceita `usuario_id` do cliente (Bloco 2). As antigas
`/usuarios/{id}/...` sumiram: nelas, trocar o id na URL bastava para pôr
saldo na conta de outra pessoa ou vincular o próprio cartão à conta dela -
e aí carregar pagando com o saldo alheio.
"""

import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import cartoes
import carteira
from config import CONDOMINIO_PADRAO, CREDITO_MAXIMO, supabase, um
from identidade import CAMPOS_PUBLICOS, usuario_logado
from seguranca import (SENHA_MAX, conferir_senha, emitir_token, gerar_hash_senha,
                       hash_ficticio, limitador_cadastro, limitador_por_ip,
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
    return request.client.host if request.client else "desconhecido"


def _veiculos(usuario_id: str) -> list:
    return supabase.table("veiculos").select("*").eq("usuario_id", usuario_id) \
        .order("criado_em").execute().data or []


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

@router.post("/cadastro")
def cadastro(payload: CadastroRequest, request: Request):
    limitador_cadastro.consumir(f"ip:{_ip(request)}")

    nome = payload.nome.strip()
    if not NOME_VALIDO.fullmatch(nome):
        raise HTTPException(status_code=400,
                            detail="Use só letras, números, espaço, ponto, hífen ou apóstrofo no nome.")
    validar_forca_senha(payload.senha, nome)
    _checar_capacidade(payload.veiculo_tipo, payload.capacidade_bateria_kwh, payload.potencia_carro_kw)

    if supabase.table("usuarios").select("id").ilike("nome", nome).execute().data:
        raise HTTPException(status_code=409, detail="Esse nome de usuário já está cadastrado.")

    condominio_id = payload.condominio_id or CONDOMINIO_PADRAO
    if not um(supabase.table("condominios").select("id").eq("id", condominio_id).execute()):
        raise HTTPException(status_code=400, detail="Condomínio inválido.")

    usuario = um(supabase.table("usuarios").insert({
        "nome": nome,
        "tipo_usuario": payload.tipo_usuario,
        "condominio_id": condominio_id,
        "bloco_apto": payload.bloco_apto,
    }).execute())

    # Três inserts sem transação: se credencial ou veículo falharem, o usuário
    # é apagado (o CASCADE leva o resto). Sem isso sobraria um usuário sem
    # senha, impossível de logar, com o nome ocupado para sempre.
    try:
        supabase.table("credenciais_usuario").insert({
            "usuario_id": usuario["id"], "senha_hash": gerar_hash_senha(payload.senha),
        }).execute()
        supabase.table("veiculos").insert({
            "usuario_id": usuario["id"],
            "modelo": payload.veiculo_modelo.strip(),
            "placa": _placa(payload.veiculo_placa),
            "tipo": payload.veiculo_tipo,
            "capacidade_bateria_kwh": payload.capacidade_bateria_kwh,
            "potencia_carro_kw": payload.potencia_carro_kw,
        }).execute()
        supabase.table("condominios_favoritos").insert({
            "usuario_id": usuario["id"], "condominio_id": condominio_id,
        }).execute()
    except Exception as e:
        supabase.table("usuarios").delete().eq("id", usuario["id"]).execute()
        print(f"[CADASTRO] desfeito para '{nome}': {e}")
        raise HTTPException(status_code=500, detail="Não foi possível concluir o cadastro.")

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
    return supabase.table("condominios").select("id, nome, endereco").order("nome").execute().data


def locais_do_usuario(usuario: dict) -> dict:
    favs = supabase.table("condominios_favoritos").select("condominio_id") \
        .eq("usuario_id", usuario["id"]).execute().data or []
    ids = {f["condominio_id"] for f in favs}
    if usuario.get("condominio_id"):
        ids.add(usuario["condominio_id"])
    todos = supabase.table("condominios").select("id, nome, endereco").order("nome").execute().data or []
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
