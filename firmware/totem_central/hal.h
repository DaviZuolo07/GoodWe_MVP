// ============================================================================
// hal.h - O que o firmware enxerga do hardware
// ============================================================================
// Espelho da parte "HAL" de totem_virtual/bancada.py: cada função aqui tem a
// mesma no Python. firmware.cpp só fala com o hardware por estas funções.
// Nada aqui espera: cada chamada volta em microssegundos (o I2C de um INA219
// leva ~1 ms; o RFID é consultado a cada RFID_MS).
// ============================================================================
#pragma once
#include <Arduino.h>

struct Medida {
  float tensao_v = 0, corrente_a = 0, potencia_w = 0;
};

namespace hal {
  void iniciar();                      // relés abertos e reversor na rede ANTES de qualquer outra coisa
  void rele(uint8_t porta, bool ligado);
  Medida lerIna(uint8_t porta);        // vagas 1..4: corrente >= 0
  Medida lerBateria();                 // INA219 em série com a 18650: + descarregando, - carregando
  void selecionarFonte(bool solar);    // relé reversor da vaga 4 (false = rede)
  bool tagLida(char* uid, size_t tamanho);   // uma vez por aproximação, UID em hexa maiúsculo
  uint8_t botao();                     // 1..4 uma vez por aperto (com debounce), 0 = nada
  bool wifiOk();
  void lcd(const char* linha0, const char* linha1);   // só reescreve o que mudou
  void led(bool aceso);
  bool sensorOk(uint8_t porta);        // 0 = sensor da bateria
}
