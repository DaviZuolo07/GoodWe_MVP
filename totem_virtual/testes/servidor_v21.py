"""
servidor_v21.py - Um servidor Totem v2.1 DE REFERÊNCIA, só para teste.
======================================================================

NÃO é o backend e não substitui o trabalho do Daniel. É a leitura do Davi da
"INTERFACE CONGELADA - TOTEM v2.1" do contrato, escrita para que o lado v2.1
do totem virtual (acao, tela, estado, fontes) não entre sem teste enquanto o
servidor de verdade não chega.

O que ele NÃO faz: não confere o HMAC (isso é provado contra o backend real,
no bolso), não cobra, não tem banco. Confere boot e sequência o bastante para
exercitar a recuperação do totem.

Prazos curtos (PRAZO_S) para o roteiro rodar em segundos.
"""

import time
import uuid

from fastapi import FastAPI, Header, HTTPException, Request

from totem_virtual.fisica import CURVA_18650

PRAZO_S = 2.0
SOC_MINIMO, HISTERESE = 20.0, 5.0     # Modbus 10030 e a histerese do backend (ADR-018 D6)


def soc_pela_tensao(v: float) -> float:
    """Inversa da curva da 18650, como o backend faz (soc_pela_tensao_18650)."""
    if v <= CURVA_18650[0][1]:
        return 0.0
    for (s0, v0), (s1, v1) in zip(CURVA_18650, CURVA_18650[1:]):
        if v <= v1:
            return s0 + (s1 - s0) * (v - v0) / (v1 - v0)
    return 100.0


def criar(tags: dict[str, float], portas=(1, 2, 3, 4)) -> FastAPI:
    """`tags`: uid -> saldo. Tag fora do dicionário = não cadastrada."""
    app = FastAPI()
    app.state.sessoes = {}        # porta -> {id, uid, energia_wh, baixa_desde, estado}
    app.state.comandos = []
    app.state.boot, app.state.seq = None, 0
    app.state.fontes = {}         # fonte -> última leitura
    app.state.fontes_recebidas = 0
    app.state.perder_proximo_comando = False
    app.state.garantir_minimo = False   # Modbus 10024
    app.state.modo_solar = "solar"       # solar | rede | pausada

    def numerar(boot, seq, handshake=False):
        boot, seq = int(boot), int(seq)
        if handshake and boot != app.state.boot:
            app.state.boot, app.state.seq = boot, seq
            return
        if boot != app.state.boot:
            raise HTTPException(409, "boot_desconhecido")
        if seq <= app.state.seq:
            raise HTTPException(409, "replay")
        app.state.seq = seq

    def tela(*linhas):
        return [x[:20] for x in linhas]

    @app.get("/hardware/v2/hora")
    def hora():
        return {"ts": int(time.time()), "janela_s": 120}

    @app.post("/hardware/v2/handshake")
    def handshake(x_boot: str = Header(), x_seq: str = Header()):
        numerar(x_boot, x_seq, handshake=True)
        app.state.comandos.clear()
        lista = []
        for p in portas:
            s = app.state.sessoes.get(p)
            lista.append({"porta": p, "carregador": {"id": f"ponto-{p}", "numero": f"0{p}"},
                          "rele_esperado": bool(s) and s["estado"] in ("carregando", "completa_tolerancia"),
                          "sessao_ativa": {"sessao_id": s["id"], "energia_wh": s["energia_wh"]} if s else None,
                          "estado": s["estado"] if s else "livre", "pedido": None})
        return {"ok": True, "portas": lista, "intervalo_comandos_s": 1, "max_leituras_lote": 30}

    @app.get("/hardware/v2/comandos")
    def comandos(x_boot: str = Header(), x_seq: str = Header()):
        numerar(x_boot, x_seq)
        entregues, app.state.comandos = app.state.comandos, []
        if app.state.perder_proximo_comando and entregues:
            app.state.perder_proximo_comando = False
            return {"comandos": []}                 # simula resposta perdida no caminho
        return {"comandos": entregues}

    @app.post("/hardware/v2/comandos/{cid}/confirmar")
    def confirmar(cid: str, x_boot: str = Header(), x_seq: str = Header()):
        numerar(x_boot, x_seq)
        return {"ok": True}

    @app.post("/hardware/v2/rfid")
    async def rfid(request: Request, x_boot: str = Header(), x_seq: str = Header()):
        numerar(x_boot, x_seq)
        corpo = await request.json()
        porta, uid = corpo["porta"], corpo["uid"].upper()
        sessoes = app.state.sessoes

        def resposta(autorizado, motivo, acao, linhas, sessao_id=None):
            return {"porta": porta, "autorizado": autorizado, "motivo": motivo, "acao": acao,
                    "tela": tela(*linhas), "mensagem": " ".join(linhas), "sessao_id": sessao_id,
                    "fila_posicao": None}

        if porta not in portas:
            raise HTTPException(422, "porta_inexistente")
        if uid not in tags:
            return resposta(False, "cartao_nao_cadastrado", "nenhuma", ["Tag nao cadastrada"])
        atual = sessoes.get(porta)
        if atual:
            if atual["uid"] == uid:
                del sessoes[porta]
                return resposta(True, "encerrada", "desligar", [f"Vaga {porta} encerrada", "Ate logo!"],
                                atual["id"])
            return resposta(False, "vaga_ocupada", "nenhuma", [f"Vaga {porta} ocupada"])
        if any(s["uid"] == uid for s in sessoes.values()):
            return resposta(False, "ja_carregando_em_outra_vaga", "nenhuma", ["Ja carregando", "em outra vaga"])
        if tags[uid] <= 0:
            return resposta(False, "saldo_insuficiente", "nenhuma", ["Saldo insuficiente"])
        s = {"id": str(uuid.uuid4()), "uid": uid, "energia_wh": 0.0, "baixa_desde": None,
             "estado": "carregando"}
        sessoes[porta] = s
        return resposta(True, "iniciada", "ligar", [f"Vaga {porta} liberada", "Recarga iniciada"], s["id"])

    @app.post("/hardware/v2/telemetria")
    async def telemetria(request: Request, x_boot: str = Header(), x_seq: str = Header()):
        corpo = await request.json()
        leituras, fontes = corpo.get("leituras") or [], corpo.get("fontes") or []
        if not leituras and not fontes:
            raise HTTPException(422, "lote_invalido")
        if any(l["porta"] not in portas for l in leituras):
            raise HTTPException(422, "porta_inexistente")
        numerar(x_boot, x_seq)
        for f in fontes:
            app.state.fontes[f["fonte"]] = f
        app.state.fontes_recebidas += len(fontes)
        decidir_vaga_solar()

        ultima = {}
        for l in leituras:
            if l["porta"] not in ultima or l["t_ms"] >= ultima[l["porta"]]["t_ms"]:
                ultima[l["porta"]] = l
        agora, saida = time.monotonic(), []
        for porta in sorted(ultima):
            l, s = ultima[porta], app.state.sessoes.get(porta)
            if not s:
                saida.append({"porta": porta, "estado": "livre", "deve_liberar": False,
                              "sessao_ativa": False})
                continue
            s["energia_wh"] = max(s["energia_wh"], l.get("energia_wh") or 0)
            w = l.get("potencia_w") or 0
            if porta == 4 and app.state.modo_solar == "pausada":
                s["baixa_desde"], s["estado"] = None, "pausada"
                saida.append({"porta": porta, "estado": "pausada", "deve_liberar": False,
                              "sessao_ativa": True, "fonte": "solar"})
                continue
            if not l.get("rele_ligado"):
                s["baixa_desde"] = None
            elif w >= 0.5:
                s["baixa_desde"], s["estado"] = None, "carregando"
            else:
                s["baixa_desde"] = s["baixa_desde"] or agora
                if agora - s["baixa_desde"] >= PRAZO_S:
                    if w >= 0.05:                                    # manutenção: cheio e plugado
                        s["estado"] = "completa_tolerancia"
                    else:                                            # corrente zero: saiu/sem celular
                        del app.state.sessoes[porta]
                        app.state.comandos.append({"id": str(uuid.uuid4()), "acao": "desligar",
                                                   "porta": porta, "sessao_id": s["id"]})
                        saida.append({"porta": porta, "estado": "livre", "deve_liberar": False,
                                      "sessao_ativa": False, "tela": tela(f"Vaga {porta} liberada")})
                        continue
            extra = {"fonte": "rede" if app.state.modo_solar == "rede" else "solar"} if porta == 4 else {}
            saida.append({"porta": porta, "estado": s["estado"], "deve_liberar": True,
                          "sessao_ativa": True, **extra})
        return {"ok": True, "gravadas": len(leituras), "fontes_gravadas": len(fontes), "portas": saida}

    def decidir_vaga_solar():
        """ADR-018 D6: bateria descarregando abaixo do 10030 -> pausada (ou rede com o 10024)."""
        b, s = app.state.fontes.get("bateria"), app.state.sessoes.get(4)
        if not b:
            return
        soc, antes = soc_pela_tensao(b["tensao_v"]), app.state.modo_solar
        rede_ou_pausa = "rede" if app.state.garantir_minimo else "pausada"
        if antes in ("rede", "pausada"):
            novo = "solar" if soc >= SOC_MINIMO + HISTERESE else rede_ou_pausa
        elif soc < SOC_MINIMO and b["potencia_w"] > 0.3:
            novo = rede_ou_pausa
        else:
            novo = "solar"
        app.state.modo_solar = novo
        if s and novo != antes and "pausada" in (novo, antes):
            app.state.comandos.append({"id": str(uuid.uuid4()), "porta": 4, "sessao_id": s["id"],
                                       "acao": "desligar" if novo == "pausada" else "ligar"})

    return app
