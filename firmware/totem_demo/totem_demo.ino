/*
 * ============================================================================
 * GoodWe ChargeOps - Totem Next DEMO (ESP32) - 1 vaga, energia simulada
 * ----------------------------------------------------------------------------
 * Igual ao firmware/totem_next, com 3 mudanças (config.h, "MODO DEMONSTRAÇÃO"):
 *   - só a vaga 1 (relé GPIO 13, botão GPIO 32); vagas 2-4 do backend ignoradas;
 *   - modelo de carga acelerado (ACELERAR) e relé opcional (USAR_RELE);
 *   - monitor serial: "t <UID>" = tag, "b" = botão, "s" = status.
 * A energia sempre foi do MODELO: funciona sem corrente nenhuma na porta.
 * ============================================================================
 * 1 ESP32 comanda 4 vagas de recarga de CELULAR ao mesmo tempo: 4 relés,
 * 4 botões, 1 leitor RFID, 1 LCD 16x2, 2 USB-A + 2 USB-C. SEM INA219 e SEM
 * solar: é o hardware da banca do Next (22/10/2026).
 *
 * DUAS IDEIAS NOVAS EM RELAÇÃO AO TOTEM CENTRAL (firmware/totem_central)
 *   Modelo de carga   sem sensor, a energia de cada vaga sai da física do
 *                     celular cadastrado (curva CC-CV), integrada só com o
 *                     relé FECHADO. Vai para o backend rotulada 'simulado'.
 *                     O % real do celular (app no Chrome do Android) volta
 *                     pelo backend e corrige o modelo.
 *   Divisão por tempo o water-filling do backend vira tempo de relé fechado:
 *                     cada vaga fica ligada a fração que lhe coube, numa
 *                     janela de 30 s, em rodízio (McNaughton). No pico, o
 *                     limite do estande cai e os relés passam a revezar.
 *
 * FLUXO NO ESTANDE
 *   "Aproxime cartao" -> tag -> "Escolha vaga 1-4" (15 s) -> botão N
 *   -> POST /hardware/v2/rfid -> o backend decide (saldo, débito na carteira,
 *   fila de energia, vaga ocupada...) -> a vaga N é liberada -> o rodízio fecha
 *   o relé -> telemetria a cada 6 s -> previsão de fim no LCD e no app.
 *   A mesma tag na mesma vaga encerra (o backend estorna a diferença).
 *
 * REGRAS QUE NÃO SE NEGOCIAM
 *   - Nada de delay(): tudo com millis(). Só o HTTP bloqueia (timeout de 8 s).
 *   - Ao ligar, todo relé ABERTO. Vaga só é liberada por ordem do backend
 *     (acao "ligar", comando liberar, rele_esperado do handshake).
 *   - Corta também pelas travas: de sessão (deve_liberar false) e offline
 *     (120 s sem servidor que aceite a placa).
 *   - Tudo em unidade bruta (W, Wh, V, A). A escala 1:1000 é do backend.
 *
 * Montagem, bibliotecas e gravação: firmware/totem_next/README.md
 * Segredos: copie segredos.exemplo.h para segredos.h (não vai para o git).
 * ============================================================================
 */

#include "maquina.h"

Totem totem;

void setup() {
  Serial.begin(115200);
  totem.setup();
}

void loop() {
  totem.loop();
}
