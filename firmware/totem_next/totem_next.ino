/*
 * ============================================================================
 * GoodWe ChargeOps - Totem Next (ESP32) - protocolo v2 + Totem v2.1
 * ============================================================================
 * 1 ESP32 comanda PORTAS vagas de recarga de CELULAR ao mesmo tempo (config.h;
 * 2 na banca de 24/10): um relé, um botão e uma porta USB por vaga, 1 leitor
 * RFID, 1 LCD 16x2 (opcional). SEM INA219 e SEM solar.
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
 *   "Aproxime cartao" -> tag -> "Escolha vaga 1-2" (15 s) -> botão N
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
