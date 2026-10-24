#include "hal.h"

#include <LiquidCrystal_I2C.h>
#include <MFRC522.h>
#include <SPI.h>
#include <WiFi.h>
#include <Wire.h>

#include "config.h"

namespace {
  // O LCD é criado no boot, no endereço que RESPONDEU (0x27 ou 0x3F). Sem
  // LCD fica nullptr e hal::lcd não faz nada: escrever num I2C vazio enche o
  // monitor serial de "nack" do core 3.x a cada troca de tela.
  LiquidCrystal_I2C* tela = nullptr;
  uint8_t enderecoLcd = 0;
  char sombra[LINHAS][COLUNAS + 1];                      // o que está no vidro agora

  MFRC522 rfid(PINO_RFID_SS, PINO_RFID_RST);
  uint32_t tRfid = 0, tUltimaTag = 0;
  char ultimaTag[33] = "";

  bool botaoEstavel[5], botaoLido[5];
  uint32_t botaoMudou[5];

  inline uint8_t nivel(bool ligado, bool ativoEmLow) { return (ligado != ativoEmLow) ? HIGH : LOW; }
}

namespace hal {

void iniciar() {
  // 1) Segurança primeiro: todo relé ABERTO. O digitalWrite vem ANTES do
  //    pinMode: o pino já nasce no nível "desligado" quando vira saída.
  for (uint8_t p = 1; p <= PORTAS && USAR_RELE; p++) {
    digitalWrite(PINO_RELE[p], nivel(false, RELE_ATIVO_EM_LOW));
    pinMode(PINO_RELE[p], OUTPUT);
    digitalWrite(PINO_RELE[p], nivel(false, RELE_ATIVO_EM_LOW));
  }
  pinMode(PINO_LED, OUTPUT);
  digitalWrite(PINO_LED, LOW);

  for (uint8_t p = 1; p <= PORTAS; p++) {
    pinMode(PINO_BOTAO[p], PINO_BOTAO[p] >= 34 ? INPUT : INPUT_PULLUP);   // 34..39 sem pull-up
    botaoEstavel[p] = botaoLido[p] = digitalRead(PINO_BOTAO[p]);
    botaoMudou[p] = 0;
  }

  Wire.begin(PINO_SDA, PINO_SCL);
  const uint8_t candidatos[2] = {ENDERECO_LCD, (uint8_t)(ENDERECO_LCD == 0x27 ? 0x3F : 0x27)};
  for (uint8_t e : candidatos) {
    Wire.beginTransmission(e);
    if (Wire.endTransmission() == 0) { enderecoLcd = e; break; }
  }
  if (enderecoLcd) {
    tela = new LiquidCrystal_I2C(enderecoLcd, COLUNAS, LINHAS);
    tela->init();
    tela->backlight();
    tela->clear();
  }
  for (uint8_t l = 0; l < LINHAS; l++) { memset(sombra[l], ' ', COLUNAS); sombra[l][COLUNAS] = '\0'; }

  SPI.begin();
  rfid.PCD_Init();

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
}

uint8_t lcdEndereco() { return enderecoLcd; }

void rele(uint8_t porta, bool ligado) {
  if (!USAR_RELE) return;                      // bancada sem módulo de relé
  if (porta >= 1 && porta <= PORTAS) digitalWrite(PINO_RELE[porta], nivel(ligado, RELE_ATIVO_EM_LOW));
}

bool tagLida(char* uid, size_t tamanho) {
  uint32_t agora = millis();
  if (agora - tRfid < RFID_MS) return false;
  tRfid = agora;
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return false;
  char lido[33];
  size_t j = 0;
  for (byte i = 0; i < rfid.uid.size && j + 2 < sizeof(lido); i++) j += snprintf(lido + j, 3, "%02X", rfid.uid.uidByte[i]);
  lido[j] = '\0';
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  // A mesma tag parada no leitor acorda de novo depois do HaltA em alguns cartões.
  if (strcmp(lido, ultimaTag) == 0 && agora - tUltimaTag < MESMA_TAG_MS) { tUltimaTag = agora; return false; }
  strncpy(ultimaTag, lido, sizeof(ultimaTag));
  tUltimaTag = agora;
  strncpy(uid, lido, tamanho);
  uid[tamanho - 1] = '\0';
  return true;
}

uint8_t botao() {
  uint32_t agora = millis();
  uint8_t apertado = 0;
  for (uint8_t p = 1; p <= PORTAS; p++) {
    bool lido = digitalRead(PINO_BOTAO[p]);
    if (lido != botaoLido[p]) { botaoLido[p] = lido; botaoMudou[p] = agora; }
    if (agora - botaoMudou[p] >= DEBOUNCE_MS && lido != botaoEstavel[p]) {
      botaoEstavel[p] = lido;
      if (lido == LOW && !apertado) apertado = p;       // borda de descida = aperto
    }
  }
  return apertado;
}

bool wifiOk() { return WiFi.status() == WL_CONNECTED; }

void lcd(const char* l0, const char* l1) {
  if (!tela) return;                           // sem LCD: o serial é a tela
  const char* linhas[LINHAS] = {l0, l1};
  for (uint8_t l = 0; l < LINHAS; l++) {
    char nova[COLUNAS + 1];
    snprintf(nova, sizeof(nova), "%-16.16s", linhas[l] ? linhas[l] : "");
    if (strcmp(nova, sombra[l]) == 0) continue;       // I2C é lento: só o que mudou
    tela->setCursor(0, l);
    tela->print(nova);
    memcpy(sombra[l], nova, sizeof(nova));
  }
}

void led(bool aceso) { digitalWrite(PINO_LED, aceso ? HIGH : LOW); }

}  // namespace hal
