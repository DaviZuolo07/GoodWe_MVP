"""
simular_esp32.py - Um ESP32 de mentira, para testar sem a placa.
================================================================

Fala o MESMO protocolo HTTP do firmware (`firmware/chargeops_esp32`), contra
o backend de verdade: handshake, polling de comandos a cada 2 s, leitura de
cartão e telemetria com energia integrada.

Serve para três coisas:
  1. Você testar o fluxo físico inteiro antes de a placa do Gus existir.
  2. O Gus comparar: se aqui funciona e na placa dele não, o problema é de
     WiFi, token ou fiação - não do backend.
  3. Gravar a demonstração mesmo se a placa falhar no dia.

Uso (com o backend rodando em outro terminal):

    python testes/simular_esp32.py --token gw_dev_o_token_da_placa

    # tapear o cartão automaticamente assim que o pedido chegar:
    python testes/simular_esp32.py --token gw_dev_... --uid A1B2C3D4 --auto

Durante a execução, digite um UID e tecle Enter para "encostar o cartão".
Ctrl+C encerra (e abre o relé, como a placa faria).
"""

import argparse
import os
import sys
import threading
import time

import httpx

ESTADOS = ("OCIOSO", "AGUARDANDO_CARTAO", "AUTORIZADO", "CARREGANDO")


class ESP32Virtual:
    def __init__(self, base: str, token: str, uid: str = "", auto: bool = False,
                 potencia_w: float = 9.0):
        self.base = base.rstrip("/")
        self.http = httpx.Client(headers={"X-Device-Token": token}, timeout=10)
        self.uid, self.auto = uid.upper(), auto
        self.potencia_nominal = potencia_w

        self.estado = "OCIOSO"
        self.rele = False
        self.energia_wh = 0.0
        self.ultima_medicao = time.monotonic()
        self.intervalo_comandos = 2.0
        self.intervalo_telemetria = 2.0
        self.percentual = 0.0
        self.pedido = None
        self.rodando = True

    # -- HTTP ---------------------------------------------------------------
    def _post(self, caminho, corpo=None):
        try:
            r = self.http.post(f"{self.base}/hardware{caminho}", json=corpo or {})
            if r.status_code >= 400:
                print(f"[HTTP] POST {caminho} -> {r.status_code}: {r.text[:160]}")
                return None
            return r.json()
        except Exception as e:
            print(f"[HTTP] POST {caminho} falhou: {type(e).__name__}: {e}")
            return None

    def _get(self, caminho):
        try:
            r = self.http.get(f"{self.base}/hardware{caminho}")
            if r.status_code >= 400:
                print(f"[HTTP] GET {caminho} -> {r.status_code}: {r.text[:160]}")
                return None
            return r.json()
        except Exception as e:
            print(f"[HTTP] GET {caminho} falhou: {type(e).__name__}: {e}")
            return None

    # -- Ciclo de vida ------------------------------------------------------
    def handshake(self) -> bool:
        r = self._post("/handshake", {"mac": "AA:BB:CC:DD:EE:FF", "ip": "127.0.0.1",
                                      "firmware": "simulador-2.0.0"})
        if not r or not r.get("ok"):
            print("Handshake recusado. Confira o token (provisionar.py token-esp).")
            return False

        c = r["carregador"]
        print(f"\n[HANDSHAKE] ponto {c['numero']} em {r.get('condominio')} "
              f"(até {float(c['potencia_maxima_kw']) * 1000:.0f} W)")
        self.intervalo_comandos = r.get("intervalo_comandos_s", 2)
        self.intervalo_telemetria = r.get("intervalo_telemetria_s", 2)

        if r.get("rele_esperado"):
            self.energia_wh = float((r.get("sessao_ativa") or {}).get("energia_wh") or 0)
            self.aplicar_rele(True, zerar=False)
            self.estado = "CARREGANDO"
            print(f"[HANDSHAKE] retomando sessão com {self.energia_wh:.2f} Wh já entregues")
        if r.get("pedido"):
            self.mostrar_pedido(r["pedido"])
        return True

    def aplicar_rele(self, ligar: bool, zerar: bool = True):
        self.rele = ligar
        if ligar and zerar:
            self.energia_wh = 0.0
        self.ultima_medicao = time.monotonic()
        print(f"[RELE] {'FECHADO - energia liberada' if ligar else 'ABERTO'}")

    def mostrar_pedido(self, p):
        self.pedido = p
        self.estado = "AGUARDANDO_CARTAO"
        if self.auto and self.uid:
            # Vale tanto para o pedido que chega por comando quanto para o que
            # vem no handshake (placa que ligou com a espera já em curso).
            threading.Timer(1.5, self.enviar_cartao, [self.uid]).start()
        print("\n" + "-" * 54)
        print("  APROXIME O CARTAO NO LEITOR")
        print(f"  Morador ...: {p.get('usuario')}")
        print(f"  Dispositivo: {p.get('veiculo')}")
        print(f"  Local .....: {p.get('local')} - ponto {p.get('carregador')}")
        print(f"  Carga .....: {p.get('percentual_inicial'):.0f}% -> {p.get('alvo'):.0f}%"
              f"  (~{p.get('energia_estimada_wh'):.1f} Wh)")
        print(f"  Estimativa : R$ {p.get('custo_estimado'):.2f}")
        print(f"  Prazo .....: {p.get('segundos_para_aproximar')} s")
        print("-" * 54)
        if self.uid:
            print(f"  (digite um UID + Enter, ou espere: --auto usa {self.uid})")

    # -- Comandos -----------------------------------------------------------
    def buscar_comandos(self):
        r = self._get("/comandos")
        for cmd in (r or {}).get("comandos", []):
            acao = cmd["acao"]
            print(f"[COMANDO] {acao}")
            if acao == "solicitar_cartao":
                self.mostrar_pedido(cmd["payload"])
            elif acao == "cancelar_cartao":
                self.estado, self.pedido = "OCIOSO", None
                print("[FLUXO] espera cancelada pelo backend")
            elif acao == "liberar":
                self.aplicar_rele(True)
                self.estado = "CARREGANDO"
                print("[FLUXO] recarga iniciada")
            elif acao == "bloquear":
                if self.rele:
                    print(f"[FLUXO] recarga encerrada - {self.energia_wh:.2f} Wh entregues")
                self.aplicar_rele(False)
                self.estado = "OCIOSO"
            elif acao == "ping":
                print("[PING] LED piscaria 3 vezes")
            self._post(f"/comandos/{cmd['id']}/confirmar", {"sucesso": True})

    # -- Cartão -------------------------------------------------------------
    def enviar_cartao(self, uid: str):
        uid = uid.strip().upper()
        if len(uid) < 4:
            return
        print(f"[CARTAO] {uid}")
        r = self._post("/rfid", {"uid": uid})
        if not r:
            return
        if r.get("autorizado"):
            print(f"[CARTAO] APROVADO - {r.get('mensagem')} "
                  f"(reservado R$ {float(r.get('valor_reservado') or 0):.2f})")
            self.estado = "AUTORIZADO"
            self.buscar_comandos()          # o `liberar` costuma já estar na fila
        else:
            print(f"[CARTAO] NEGADO - {r.get('mensagem')}")
            if not r.get("continuar_aguardando") and self.estado == "AGUARDANDO_CARTAO":
                self.estado = "OCIOSO"

    # -- Medição e telemetria ----------------------------------------------
    def medir(self):
        agora = time.monotonic()
        horas = (agora - self.ultima_medicao) / 3600
        self.ultima_medicao = agora
        if not self.rele:
            return 0.0, 5.05, 0.0
        # Mesma curva do firmware: cai perto do fim da carga.
        fator = 1.0 if self.percentual < 80 else max(0.12, 1 - (self.percentual - 80) * 0.03)
        potencia = self.potencia_nominal * fator
        tensao = 5.05
        self.energia_wh += potencia * horas
        return potencia, tensao, potencia / tensao

    def telemetria(self):
        potencia, tensao, corrente = self.medir()
        r = self._post("/telemetria", {
            "potencia_w": round(potencia, 3), "energia_wh": round(self.energia_wh, 4),
            "tensao_v": tensao, "corrente_a": round(corrente, 3),
            "temperatura_c": 31.2, "rele_ligado": self.rele,
        })
        if not r:
            return
        self.percentual = float(r.get("percentual") or 0)
        if self.rele and not r.get("deve_liberar"):
            print(f"[FIM] {r.get('motivo')} - {self.energia_wh:.2f} Wh entregues, "
                  f"R$ {float(r.get('custo_ate_agora') or 0):.2f}")
            self.aplicar_rele(False)
            self.estado = "OCIOSO"
        elif self.rele:
            print(f"[MEDINDO] {potencia:5.2f} W | {tensao:.2f} V | {corrente:.3f} A | "
                  f"{self.energia_wh:6.2f} Wh | bateria {self.percentual:5.1f}% | "
                  f"faltam {r.get('tempo_restante_min')} min | "
                  f"R$ {float(r.get('custo_ate_agora') or 0):.2f} de "
                  f"R$ {float(r.get('valor_reservado') or 0):.2f} reservados")

    # -- Laço principal -----------------------------------------------------
    def laco(self):
        proximo_cmd = proximo_tel = 0.0
        while self.rodando:
            agora = time.monotonic()
            if agora >= proximo_cmd:
                proximo_cmd = agora + self.intervalo_comandos
                self.buscar_comandos()
            ritmo = self.intervalo_telemetria if self.estado == "CARREGANDO" else 10
            if agora >= proximo_tel:
                proximo_tel = agora + ritmo
                self.telemetria()
            time.sleep(0.2)


def main():
    p = argparse.ArgumentParser(description="ESP32 virtual do ChargeOps")
    p.add_argument("--base", default=os.getenv("ESP_BASE", "http://localhost:8000"))
    p.add_argument("--token", default=os.getenv("DEVICE_TOKEN"),
                   help="token do dispositivo (provisionar.py token-esp)")
    p.add_argument("--uid", default="", help="UID do cartão a usar quando pedirem")
    p.add_argument("--auto", action="store_true",
                   help="encosta o cartão sozinho assim que o pedido chegar")
    p.add_argument("--potencia-w", type=float, default=9.0, dest="potencia_w",
                   help="potência simulada (padrão 9 W, um carregador de celular)")
    args = p.parse_args()

    if not args.token:
        sys.exit("Informe --token (ou a variável DEVICE_TOKEN).")

    esp = ESP32Virtual(args.base, args.token, args.uid, args.auto, args.potencia_w)
    print(f"ESP32 virtual -> {args.base}")
    if not esp.handshake():
        return 1

    laco = threading.Thread(target=esp.laco, daemon=True)
    laco.start()

    interativo = sys.stdin is not None and sys.stdin.isatty()
    if interativo:
        print("Digite um UID e tecle Enter para encostar o cartão. Ctrl+C encerra.\n")
    else:
        # Sem terminal (script, CI, nohup): não morre na primeira leitura de
        # stdin - fica rodando como a placa faria.
        print("Sem terminal interativo: rodando em modo automático. Ctrl+C encerra.\n")
    try:
        if interativo:
            for linha in sys.stdin:
                if linha.strip():
                    esp.enviar_cartao(linha)
            while esp.rodando:          # stdin fechou, mas a placa continua
                time.sleep(0.5)
        else:
            while esp.rodando:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        esp.rodando = False
        if esp.rele:
            esp.aplicar_rele(False)
            esp.telemetria()
        print("\nESP32 virtual encerrado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
