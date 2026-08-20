"""
hardware_serial.py - Ponte entre o Arduino (RFID + relé) e o backend.
-----------------------------------------------------------------------
Roda em uma thread separada (leitura de serial é bloqueante, não dá pra
usar direto no asyncio do FastAPI). Fica escutando a porta serial e, toda
vez que o Arduino manda uma linha "RFID:<uid>" (o cartão foi aproximado
do leitor), tenta autorizar a recarga pendente daquele usuário.

Protocolo combinado com o Arduino (simples de propósito, texto puro):
  Arduino -> Backend:  "RFID:<uid>\n"        (cartão foi lido)
  Backend -> Arduino:  "L\n"                  (autorizado - ligar relé)
                        "N\n"                 (recusado - não ligar)

Configuração (arquivo .env do backend):
  HARDWARE_SERIAL_PORT=COM3      (Windows) ou /dev/ttyUSB0 (Linux/Mac)
  HARDWARE_SERIAL_BAUDRATE=9600  (opcional, padrão 9600)

Se HARDWARE_SERIAL_PORT não estiver definido, esse módulo simplesmente
não faz nada - assim o backend continua funcionando normalmente em PCs
do time que não têm o Arduino conectado (só quem estiver testando o
hardware físico precisa configurar isso).
"""

import os
import threading
import time

SERIAL_PORT = os.getenv("HARDWARE_SERIAL_PORT")
BAUDRATE = int(os.getenv("HARDWARE_SERIAL_BAUDRATE", "9600"))


def _processar_leitura_rfid(uid: str, supabase, autorizar_e_iniciar_sessao, HTTPException):
    """
    Chamado quando o Arduino lê um cartão. Busca o usuário dono desse UID,
    pega a sessão dele que está 'aguardando_rfid' (criada pelo endpoint
    /charge/preparar-rfid) e tenta autorizar - mesma função usada pelo
    fluxo simulado, então as regras (saldo, concorrência) são idênticas.

    Retorna "L" (ligar relé) ou "N" (negar) - é isso que volta pro Arduino.
    """
    try:
        usuario_result = supabase.table("usuarios").select("*").eq("rfid_uid", uid).execute()
        if not usuario_result.data:
            print(f"[HARDWARE] Cartão {uid} não está vinculado a nenhum usuário")
            return "N"
        usuario = usuario_result.data[0]

        sessao_result = (
            supabase.table("sessoes_recarga")
            .select("*")
            .eq("usuario_id", usuario["id"])
            .eq("status", "aguardando_rfid")
            .order("criado_em", desc=True)
            .limit(1)
            .execute()
        )
        if not sessao_result.data:
            print(f"[HARDWARE] Usuário {usuario['nome']} não tem recarga pendente aguardando cartão")
            return "N"
        sessao_pendente = sessao_result.data[0]

        charger = supabase.table("carregadores").select("*").eq("id", sessao_pendente["carregador_id"]).execute().data[0]
        veiculo = supabase.table("veiculos").select("*").eq("id", sessao_pendente["veiculo_id"]).execute().data[0]

        # A sessão "aguardando_rfid" já cumpriu seu papel (guardar a
        # estimativa) - agora descartamos ela e deixamos a função central
        # criar a sessão "carregando" de verdade, com as mesmas regras do
        # fluxo simulado (saldo, concorrência).
        supabase.table("sessoes_recarga").delete().eq("id", sessao_pendente["id"]).execute()

        autorizar_e_iniciar_sessao(
            charger, veiculo, usuario,
            sessao_pendente["percentual_bateria_atual"],
            metodo="rfid_hardware", origem="hardware",
        )
        print(f"[HARDWARE] Recarga autorizada para {usuario['nome']} no carregador {charger['numero']}")
        return "L"

    except HTTPException as e:
        print(f"[HARDWARE] Recusado: {e.detail}")
        return "N"
    except Exception as e:
        print(f"[HARDWARE] Erro inesperado ao processar RFID: {e}")
        return "N"


def _loop_serial(supabase, autorizar_e_iniciar_sessao, HTTPException):
    import serial  # pyserial - só importa se for realmente usar

    while True:
        try:
            print(f"[HARDWARE] Conectando na porta serial {SERIAL_PORT} ({BAUDRATE} baud)...")
            with serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1) as ser:
                print("[HARDWARE] Conectado. Aguardando leituras de RFID...")
                while True:
                    linha = ser.readline().decode("utf-8", errors="ignore").strip()
                    if not linha:
                        continue

                    if linha.startswith("RFID:"):
                        uid = linha.split("RFID:", 1)[1].strip()
                        resposta = _processar_leitura_rfid(uid, supabase, autorizar_e_iniciar_sessao, HTTPException)
                        ser.write(f"{resposta}\n".encode("utf-8"))
                    else:
                        print(f"[HARDWARE] Linha não reconhecida do Arduino: {linha}")

        except Exception as e:
            print(f"[HARDWARE] Erro na conexão serial ({e}). Tentando de novo em 5s...")
            time.sleep(5)


def iniciar_escuta_serial(supabase, autorizar_e_iniciar_sessao, HTTPException):
    """Chamar isso no startup do FastAPI. Não faz nada se a porta não estiver configurada."""
    if not SERIAL_PORT:
        print("[HARDWARE] HARDWARE_SERIAL_PORT não configurado - escuta serial desativada "
              "(normal se este PC não tem o Arduino conectado).")
        return

    thread = threading.Thread(
        target=_loop_serial,
        args=(supabase, autorizar_e_iniciar_sessao, HTTPException),
        daemon=True,
    )
    thread.start()