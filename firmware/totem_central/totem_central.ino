/*
 * ============================================================================
 * GoodWe ChargeOps - Totem Central (ESP32) - protocolo v2 + Totem v2.1
 * ============================================================================
 * 1 ESP32 comanda 4 vagas de recarga USB ao mesmo tempo: 4 relés, 4 INA219,
 * 4 botões, 1 leitor RFID, 1 LCD 16x2. A vaga 4 é solar: um relé reversor
 * escolhe a bateria 18650 (painel -> TP4056 -> 18650 -> MT3608) ou a rede
 * (fonte de 5 V), nunca as duas. Um 5º INA219 mede a bateria com sinal.
 *
 * NÃO É UMA REINVENÇÃO. É a tradução de totem_virtual/firmware.py, que é a
 * implementação testada de docs/contratos/maquina_de_estados_totem.md.
 * Mudança de comportamento: contrato -> totem virtual -> aqui, nesta ordem.
 * Decisões: ADR-015 (protocolo), ADR-018 (v2.1), ADR-020 (totem virtual),
 * ADR-021 (recusa de autenticação), ADR-022 (este hardware).
 *
 * FLUXO NO ESTANDE
 *   "Aproxime cartao" -> tag -> "Escolha vaga 1-4" (15 s) -> botão N
 *   -> POST /hardware/v2/rfid -> o backend decide (iniciada, fila de energia,
 *   vaga ocupada, sem saldo...) -> só o canal N do relé muda -> a tela volta
 *   sozinha. A mesma tag na mesma vaga encerra. Cada vaga tem o seu relógio.
 *
 * REGRAS QUE NÃO SE NEGOCIAM
 *   - Nada de delay(): tudo com millis(). Só o HTTP bloqueia (timeout de 3 s).
 *   - Ao ligar, todo relé ABERTO. Relé só fecha por ordem do backend
 *     (acao "ligar", comando liberar, rele_esperado do handshake).
 *   - Abre também pelas travas: de sessão (deve_liberar false) e offline
 *     (120 s sem servidor que aceite a placa).
 *   - Tudo em unidade bruta (W, Wh, V, A). A escala 1:1000 é do backend.
 *
 * Bibliotecas e montagem: firmware/totem_central/README.md
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
