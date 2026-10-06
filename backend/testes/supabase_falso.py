"""
Supabase falso, em memória - só o subconjunto da API que o backend usa.

Permite rodar o fluxo completo (login -> preparar -> ESP32 pede cartão ->
cartão -> saldo -> telemetria -> encerramento -> estorno) sem rede, com o
TestClient do FastAPI. As funções RPC do 12, 14, 15 e 16 estão replicadas aqui
em Python com a mesma regra (o comportamento real é provado no Postgres pelo
db/15_verificacao.sql; aqui o que se testa é o backend em volta delas).
"""

import copy
import uuid
from datetime import datetime, timedelta, timezone

FK = {"veiculos": "veiculo_id", "usuarios": "usuario_id",
      "carregadores": "carregador_id", "sessoes_recarga": "sessao_id"}


class _Resp:
    def __init__(self, data):
        self.data = data


class ErroRPC(Exception):
    pass


class _Query:
    def __init__(self, db, tabela):
        self.db, self.tabela = db, tabela
        self.op, self.valores, self.filtros = "select", None, []
        self.cols, self._ordem, self._limite, self.on_conflict = "*", None, None, None

    # --- construção ---
    def select(self, cols="*", **_):
        self.cols = cols
        return self

    def insert(self, valores):
        self.op, self.valores = "insert", valores
        return self

    def update(self, valores):
        self.op, self.valores = "update", valores
        return self

    def upsert(self, valores, on_conflict=None):
        self.op, self.valores, self.on_conflict = "upsert", valores, on_conflict
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, c, v): self.filtros.append(lambda r: r.get(c) == v); return self
    def neq(self, c, v): self.filtros.append(lambda r: r.get(c) != v); return self
    def in_(self, c, vs): self.filtros.append(lambda r: r.get(c) in list(vs)); return self
    def lt(self, c, v): self.filtros.append(lambda r: r.get(c) is not None and _cmp(r[c]) < _cmp(v)); return self
    def gte(self, c, v): self.filtros.append(lambda r: r.get(c) is not None and _cmp(r[c]) >= _cmp(v)); return self

    def ilike(self, c, v):
        self.filtros.append(lambda r: str(r.get(c) or "").lower() == str(v).lower())
        return self

    def order(self, c, desc=False):
        self._ordem = (c, desc)
        return self

    def limit(self, n):
        self._limite = n
        return self

    def single(self):
        return self

    # --- execução ---
    def _linhas(self):
        return [r for r in self.db.t(self.tabela) if all(f(r) for f in self.filtros)]

    def execute(self):
        t = self.db.t(self.tabela)
        if self.op == "insert":
            lista = self.valores if isinstance(self.valores, list) else [self.valores]
            novas = [self.db.nova_linha(self.tabela, v) for v in lista]
            t.extend(novas)
            return _Resp(copy.deepcopy(novas))
        if self.op == "upsert":
            chaves = (self.on_conflict or "id").split(",")
            v = self.valores
            achada = [r for r in t if all(r.get(k) == v.get(k) for k in chaves)]
            if achada:
                achada[0].update(v)
                return _Resp([copy.deepcopy(achada[0])])
            nova = self.db.nova_linha(self.tabela, v)
            t.append(nova)
            return _Resp([copy.deepcopy(nova)])
        linhas = self._linhas()
        if self.op == "update":
            for r in linhas:
                r.update(copy.deepcopy(self.valores))
            return _Resp(copy.deepcopy(linhas))
        if self.op == "delete":
            for r in linhas:
                t.remove(r)
            return _Resp(copy.deepcopy(linhas))
        if self._ordem:
            c, desc = self._ordem
            linhas = sorted(linhas, key=lambda r: (_cmp(r.get(c)) is None, _cmp(r.get(c)) or 0), reverse=desc)
        if self._limite:
            linhas = linhas[: self._limite]
        return _Resp([self.db.projetar(self.tabela, r, self.cols) for r in linhas])


def _cmp(v):
    if isinstance(v, str) and len(v) >= 19 and v[4] == "-" and "T" in v:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
    return v


class FakeSupabase:
    def __init__(self):
        self.tabelas = {}

    def limpar(self):
        """Zera o banco em memória (cada teste começa do zero)."""
        self.tabelas.clear()

    def t(self, nome):
        return self.tabelas.setdefault(nome, [])

    def table(self, nome):
        return _Query(self, nome)

    def nova_linha(self, tabela, v):
        linha = {"id": str(uuid.uuid4()), "criado_em": datetime.now(timezone.utc).isoformat()}
        padroes = {"sessoes_recarga": {"energia_entregue_kwh": 0, "energia_ponta_kwh": 0,
                                       "tentativas_cartao": 0, "potencia_atual_kw": 0},
                   "notificacoes": {"lida": False},
                   "usuarios": {"saldo": 0},
                   "dispositivos": {"protocolo": 1, "chave_versao": 1, "boot_atual": None,
                                    "seq_atual": 0, "online": False},
                   "comandos_dispositivo": {"porta": 1},
                   "leituras_hardware": {"porta": 1, "origem": "medido"},
                   "geracao_solar": {"origem": "simulado"}}
        linha.update(padroes.get(tabela, {}))
        linha.update(copy.deepcopy(v))
        return linha

    def projetar(self, tabela, r, cols):
        out = copy.deepcopy(r)
        for parte in [p.strip() for p in cols.split(",") if "(" in p]:
            pass
        # joins "nome(col, col)"
        import re
        for nome, sub in re.findall(r"(\w+)\(([^)]*)\)", cols):
            fk = FK.get(nome)
            alvo = next((x for x in self.t(nome) if x["id"] == r.get(fk)), None)
            out[nome] = {c.strip(): alvo.get(c.strip()) for c in sub.split(",")} if alvo else None
        return out

    # --- RPC com a mesma regra do SQL ---
    SINAL = {"credito": 1, "bonus": 1, "estorno": 1, "ajuste": 1,
             "pre_autorizacao": -1, "ajuste_debito": -1}

    def _usuario(self, uid):
        u = next((x for x in self.t("usuarios") if x["id"] == uid), None)
        if not u:
            raise ErroRPC("usuario_inexistente")
        return u

    def _mover(self, uid, valor, tipo, descricao, sessao=None, sinal=1):
        if valor < 0:
            raise ErroRPC("valor_negativo")
        if self.SINAL.get(tipo) != sinal:
            raise ErroRPC("tipo_invalido")
        u = self._usuario(uid)
        if sinal < 0 and float(u["saldo"]) < valor:
            raise ErroRPC("saldo_insuficiente")
        u["saldo"] = round(float(u["saldo"]) + sinal * valor, 2)
        self.t("movimentacoes_carteira").append(self.nova_linha("movimentacoes_carteira", {
            "usuario_id": uid, "sessao_id": sessao, "tipo": tipo, "valor": valor,
            "saldo_apos": u["saldo"], "descricao": descricao}))
        return u["saldo"]

    def conferir_carteira(self):
        out = []
        for u in self.t("usuarios"):
            soma = sum(self.SINAL[m["tipo"]] * float(m["valor"])
                       for m in self.t("movimentacoes_carteira") if m["usuario_id"] == u["id"])
            if round(float(u.get("saldo") or 0) - soma, 2) != 0:
                out.append({"usuario_id": u["id"], "saldo": u["saldo"], "soma_extrato": soma})
        return out

    def _consumir_seq(self, p, handshake):
        ts = datetime.fromisoformat(str(p["p_ts"]).replace("Z", "+00:00"))
        if abs((datetime.now(timezone.utc) - ts).total_seconds()) > p.get("p_janela_s", 120):
            raise ErroRPC("fora_da_janela")
        if p.get("p_boot") is None or p.get("p_seq") is None or p["p_seq"] < 1:
            raise ErroRPC("seq_invalido")
        d = next((x for x in self.t("dispositivos") if x["id"] == p["p_dispositivo"]), None)
        if not d:
            raise ErroRPC("dispositivo_inexistente")
        boots = self.t("dispositivo_boots")
        if handshake:
            if not any(b["dispositivo_id"] == d["id"] and b["boot"] == p["p_boot"] for b in boots):
                boots.append({"dispositivo_id": d["id"], "boot": p["p_boot"]})
                d.update({"boot_atual": p["p_boot"], "seq_atual": p["p_seq"],
                          "protocolo": 2, "token_hash": None})
                return
            if d.get("boot_atual") == p["p_boot"] and d["seq_atual"] < p["p_seq"]:
                d["seq_atual"] = p["p_seq"]
                return
            raise ErroRPC("replay")
        if d.get("boot_atual") == p["p_boot"] and d["seq_atual"] < p["p_seq"]:
            d["seq_atual"] = p["p_seq"]
            return
        if d.get("boot_atual") != p["p_boot"]:
            raise ErroRPC("boot_desconhecido")
        raise ErroRPC("replay")

    def _registrar_lote(self, p):
        lote = p.get("p_leituras")
        if not isinstance(lote, list) or not 1 <= len(lote) <= 30:
            raise ErroRPC("lote_invalido")
        estado = copy.deepcopy(self.t("dispositivos"))
        self._consumir_seq(p, False)
        portas = {x["numero"]: x["carregador_id"] for x in self.t("portas_dispositivo")
                  if x["dispositivo_id"] == p["p_dispositivo"]}
        if any(l.get("porta") not in portas for l in lote):
            self.tabelas["dispositivos"] = estado          # a transação inteira volta
            raise ErroRPC("porta_inexistente")
        agora = datetime.now(timezone.utc)
        for l in lote:
            s = next((x for x in self.t("sessoes_recarga")
                      if x["carregador_id"] == portas[l["porta"]] and x["status"] == "carregando"), None)
            atraso = max(0, min(600000, p["p_t_envio_ms"] - (l.get("t_ms") or p["p_t_envio_ms"])))
            self.t("leituras_hardware").append(self.nova_linha("leituras_hardware", {
                "dispositivo_id": p["p_dispositivo"], "porta": l["porta"],
                "sessao_id": s["id"] if s else None,
                **{k: l.get(k) for k in ("potencia_w", "energia_wh", "tensao_v", "corrente_a",
                                         "temperatura_c", "rele_ligado")},
                "medido_em": (agora - timedelta(milliseconds=atraso)).isoformat(),
                "origem": "medido"}))
        return len(lote)

    def _cadastrar(self, p):
        if p["p_tipo"] not in ("morador", "visitante"):
            raise ErroRPC("tipo_invalido")
        if not str(p.get("p_senha_hash") or "").startswith("$argon2"):
            raise ErroRPC("hash_invalido")
        if not any(c["id"] == p["p_condominio"] for c in self.t("condominios")):
            raise ErroRPC("condominio_invalido")
        v = p.get("p_veiculo") or {}
        if not str(v.get("modelo") or "").strip():
            raise ErroRPC("veiculo_invalido")
        nome = p["p_nome"].strip()
        if any(str(u["nome"]).lower() == nome.lower() for u in self.t("usuarios")):
            raise ErroRPC("nome_em_uso")
        u = self.nova_linha("usuarios", {"nome": nome, "tipo_usuario": p["p_tipo"],
                                         "condominio_id": p["p_condominio"], "bloco_apto": p.get("p_bloco"),
                                         "papel": "Morador", "saldo": 0})
        self.t("usuarios").append(u)
        self.t("credenciais_usuario").append({"usuario_id": u["id"], "senha_hash": p["p_senha_hash"]})
        self.t("veiculos").append(self.nova_linha("veiculos", {
            "usuario_id": u["id"], "modelo": v["modelo"].strip(), "placa": v.get("placa") or None,
            "tipo": v.get("tipo") or "carro",
            "capacidade_bateria_kwh": v.get("capacidade_bateria_kwh") or 40,
            "potencia_carro_kw": v.get("potencia_carro_kw") or 7.4}))
        self.t("condominios_favoritos").append(self.nova_linha("condominios_favoritos", {
            "usuario_id": u["id"], "condominio_id": p["p_condominio"]}))
        if p.get("p_bonus", 100) > 0:
            self._mover(u["id"], p.get("p_bonus", 100), "bonus", "Crédito de boas-vindas (simulado)")
        return u["id"]

    def _registrar_consumo(self, p):
        """Mesma regra do db/16: soma energia (total, ponta só da rede, solar) e guarda os picos."""
        hora = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()
        kwh = max(0.0, float(p["p_kwh"]))
        solar = min(kwh, max(0.0, float(p.get("p_solar_kwh") or 0)))
        carga = max(0.0, float(p["p_carga_kw"]))
        rede = p.get("p_rede_kw")
        rede = max(0.0, float(carga if rede is None else rede))
        linha = next((x for x in self.t("consumo_horario")
                      if x["condominio_id"] == p["p_cond"] and x["hora"] == hora), None)
        if not linha:
            linha = {"condominio_id": p["p_cond"], "hora": hora, "energia_kwh": 0.0, "energia_ponta_kwh": 0.0,
                     "energia_solar_kwh": 0.0, "pico_kw": 0.0, "demanda_kw": 0.0, "pico_rede_kw": 0.0}
            self.t("consumo_horario").append(linha)
        linha["energia_kwh"] += kwh
        linha["energia_solar_kwh"] += solar
        if p["p_ponta"]:
            linha["energia_ponta_kwh"] += kwh - solar
        linha["pico_kw"] = max(linha["pico_kw"], carga)
        linha["demanda_kw"] = max(linha["demanda_kw"], float(p.get("p_demanda_kw") or 0), carga)
        linha["pico_rede_kw"] = max(linha["pico_rede_kw"], rede)

    def _somar_geracao(self, p):
        desde = _cmp(p["p_desde"])
        por = {}
        for g in self.t("geracao_solar"):
            if g["condominio_id"] == p["p_cond"] and _cmp(g["momento"]) >= desde:
                o = por.setdefault(g["origem"], {"origem": g["origem"], "energia_kwh": 0.0, "pico_kw": 0.0})
                o["energia_kwh"] += float(g["energia_kwh"])
                o["pico_kw"] = max(o["pico_kw"], float(g["potencia_kw"]))
        return list(por.values())

    def rpc(self, nome, p):
        db = self

        class _R:
            def execute(_self):
                if nome == "debitar_saldo":
                    return _Resp(db._mover(p["p_usuario"], p["p_valor"], p["p_tipo"], p["p_descricao"],
                                           p.get("p_sessao"), -1))
                if nome == "creditar_saldo":
                    return _Resp(db._mover(p["p_usuario"], p["p_valor"], p["p_tipo"], p["p_descricao"],
                                           p.get("p_sessao"), 1))
                if nome == "ajustar_saldo":
                    dif = round(p["p_saldo_alvo"] - float(db._usuario(p["p_usuario"])["saldo"]), 2)
                    if dif > 0:
                        return _Resp(db._mover(p["p_usuario"], dif, "ajuste", p["p_descricao"]))
                    if dif < 0:
                        return _Resp(db._mover(p["p_usuario"], -dif, "ajuste_debito", p["p_descricao"], sinal=-1))
                    return _Resp(db._usuario(p["p_usuario"])["saldo"])
                if nome == "conferir_carteira":
                    return _Resp(db.conferir_carteira())
                if nome == "cadastrar_usuario":
                    return _Resp(db._cadastrar(p))
                if nome == "consumir_seq":
                    db._consumir_seq(p, p.get("p_handshake", False))
                    return _Resp(None)
                if nome == "registrar_lote_telemetria":
                    return _Resp(db._registrar_lote(p))
                if nome == "registrar_consumo":
                    db._registrar_consumo(p)
                    return _Resp(None)
                if nome == "somar_geracao_solar":
                    return _Resp(db._somar_geracao(p))
                raise ErroRPC(f"rpc desconhecida {nome}")
        return _R()
