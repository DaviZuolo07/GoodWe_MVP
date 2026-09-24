"""
Supabase falso, em memória - só o subconjunto da API que o backend usa.

Permite rodar o fluxo completo (login -> preparar -> ESP32 pede cartão ->
cartão -> saldo -> telemetria -> encerramento -> estorno) sem rede, com o
TestClient do FastAPI. As funções RPC do 12_produto.sql estão replicadas
aqui em Python com a mesma regra.
"""

import copy
import uuid
from datetime import datetime, timezone

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

    def t(self, nome):
        return self.tabelas.setdefault(nome, [])

    def table(self, nome):
        return _Query(self, nome)

    def nova_linha(self, tabela, v):
        linha = {"id": str(uuid.uuid4()), "criado_em": datetime.now(timezone.utc).isoformat()}
        padroes = {"sessoes_recarga": {"energia_entregue_kwh": 0, "energia_ponta_kwh": 0,
                                       "tentativas_cartao": 0, "potencia_atual_kw": 0},
                   "notificacoes": {"lida": False}}
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
    def rpc(self, nome, p):
        db = self

        class _R:
            def execute(_self):
                if nome in ("debitar_saldo", "creditar_saldo"):
                    u = next(x for x in db.t("usuarios") if x["id"] == p["p_usuario"])
                    if nome == "debitar_saldo":
                        if float(u["saldo"]) < p["p_valor"]:
                            raise ErroRPC("saldo_insuficiente")
                        u["saldo"] = round(float(u["saldo"]) - p["p_valor"], 2)
                    else:
                        u["saldo"] = round(float(u["saldo"]) + p["p_valor"], 2)
                    db.t("movimentacoes_carteira").append(db.nova_linha("movimentacoes_carteira", {
                        "usuario_id": u["id"], "sessao_id": p.get("p_sessao"), "tipo": p["p_tipo"],
                        "valor": p["p_valor"], "saldo_apos": u["saldo"], "descricao": p["p_descricao"]}))
                    return _Resp(u["saldo"])
                if nome == "registrar_consumo":
                    db.t("consumo_horario").append(dict(p))
                    return _Resp(None)
                raise ErroRPC(f"rpc desconhecida {nome}")
        return _R()
