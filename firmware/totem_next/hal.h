// ============================================================================
// hal.h - O que o firmware enxerga do hardware do Totem Next
// ============================================================================
// Relés, botões, leitor de tag, LCD, LED e Wi-Fi. NÃO há sensor de corrente:
// a energia de cada vaga sai do modelo de carga (carga.h), nunca daqui.
// Nada aqui espera: cada chamada volta em microssegundos (o RFID é consultado
// a cada RFID_MS).
// ============================================================================
#pragma once
#include <Arduino.h>

namespace hal {
  void iniciar();                      // relés abertos ANTES de qualquer outra coisa
  uint8_t lcdEndereco();               // 0x27/0x3F = LCD achado no boot; 0 = sem LCD
  void rele(uint8_t porta, bool ligado);
  bool tagLida(char* uid, size_t tamanho);   // uma vez por aproximação, UID em hexa maiúsculo
  uint8_t botao();                     // 1..PORTAS uma vez por aperto (com debounce), 0 = nada
  bool wifiOk();
  void lcd(const char* linha0, const char* linha1);   // só reescreve o que mudou
  void led(bool aceso);
}
