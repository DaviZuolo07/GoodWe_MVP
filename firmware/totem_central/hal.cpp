#include "hal.h"

#include <Adafruit_INA219.h>
#include <LiquidCrystal_I2C.h>
#include <MFRC522.h>
#include <SPI.h>
#include <WiFi.h>
#include <Wire.h>

#include "config.h"

namespace {
  Adafruit_INA219 ina[5] = {Adafruit_INA219(0x40), Adafruit_INA219(ENDERECO_INA[1]),
                            Adafruit_INA219(ENDERECO_INA[2]), Adafruit_INA219(ENDERECO_INA[3]),
                            Adafruit_INA219(ENDERECO_INA[4])};
  Adafruit_INA219 inaSolar(ENDERECO_INA_SOLAR);
  bool inaOk[5] = {false, false, false, false, false};   // [0] = bateria

  LiquidCrystal_I2C tela(ENDERECO_LCD, COLUNAS, LINHAS);
  char sombra[LINHAS][COLUNAS + 1];                      // o que está no vidro agora

  MFRC522 rfid(PINO_RFID_SS, PINO_RFID_RST);
  uint32_t tRfid = 0, tUltimaTag = 0;
  char ultimaTag[33] = "";

  bool botaoEstavel[5], botaoLido[5];
  uint32_t botaoMudou[5];

  inline uint8_t nivel(bool ligado, bool ativoEmLow) { return (ligado != ativoEmLow) ? HIGH : LOW; }

  Medida medir(Adafruit_INA219& s, bool ok, bool assinado) {
    Medida m;
    if (!ok) return m;                                   // sensor ausente: mede zero
    float bus = s.getBusVoltage_V();
    float shunt = s.getShuntVoltage_mV() / 1000.0f;
    float i = s.getCurrent_mA() / 1000.0f;
    // Vaga: tensão no lado do celular (bus). Bateria: no lado da 18650 (bus + shunt).
    m.tensao_v = assinado ? bus + shunt : bus;
    m.corrente_a = assinado ? i : max(0.0f, i);
    m.potencia_w = m.tensao_v * m.corrente_a;
    return m;
  }
}

namespace hal {

void iniciar() {
  // 1) Segurança primeiro: todo relé ABERTO e reversor na rede (bobina desligada).
  //    O pinMode deixa o pino em LOW por microssegundos antes do digitalWrite;
  //    um relé leva milissegundos para atracar, então não chega a fechar.
  for (uint8_t p = 1; p <= PORTAS; p++) {
    pinMode(PINO_RELE[p], OUTPUT);
    digitalWrite(PINO_RELE[p], nivel(false, RELE_ATIVO_EM_LOW));
  }
  pinMode(PINO_REVERSOR, OUTPUT);
  digitalWrite(PINO_REVERSOR, nivel(false, REVERSOR_ATIVO_EM_LOW));
  pinMode(PINO_LED, OUTPUT);
  digitalWrite(PINO_LED, LOW);

  for (uint8_t p = 1; p <= PORTAS; p++) {
    pinMode(PINO_BOTAO[p], PINO_BOTAO[p] >= 34 ? INPUT : INPUT_PULLUP);   // 34..39 sem pull-up
    botaoEstavel[p] = botaoLido[p] = digitalRead(PINO_BOTAO[p]);
    botaoMudou[p] = 0;
  }

  Wire.begin(PINO_SDA, PINO_SCL);
  Wire1.begin(PINO_SDA_SOLAR, PINO_SCL_SOLAR);
  for (uint8_t p = 1; p <= PORTAS; p++) {
    inaOk[p] = ina[p].begin(&Wire);
    if (inaOk[p]) ina[p].setCalibration_32V_2A();      // até ~3,2 A com o shunt de 0,1 ohm
    else Serial.printf("[hal] INA219 da vaga %u (0x%02X) NAO respondeu\n", p, ENDERECO_INA[p]);
  }
  inaOk[0] = inaSolar.begin(&Wire1);
  if (inaOk[0]) inaSolar.setCalibration_32V_2A();
  else Serial.println("[hal] INA219 da bateria solar (Wire1 0x40) NAO respondeu");

  tela.init();
  tela.backlight();
  tela.clear();
  for (uint8_t l = 0; l < LINHAS; l++) { memset(sombra[l], ' ', COLUNAS); sombra[l][COLUNAS] = '\0'; }

  SPI.begin();
  rfid.PCD_Init();

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
}

void rele(uint8_t porta, bool ligado) {
  if (porta >= 1 && porta <= PORTAS) digitalWrite(PINO_RELE[porta], nivel(ligado, RELE_ATIVO_EM_LOW));
}

Medida lerIna(uint8_t porta) { return medir(ina[porta], inaOk[porta], false); }

Medida lerBateria() { return medir(inaSolar, inaOk[0], true); }

void selecionarFonte(bool solar) { digitalWrite(PINO_REVERSOR, nivel(solar, REVERSOR_ATIVO_EM_LOW)); }

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
  const char* linhas[LINHAS] = {l0, l1};
  for (uint8_t l = 0; l < LINHAS; l++) {
    char nova[COLUNAS + 1];
    snprintf(nova, sizeof(nova), "%-16.16s", linhas[l] ? linhas[l] : "");
    if (strcmp(nova, sombra[l]) == 0) continue;       // I2C é lento: só o que mudou
    tela.setCursor(0, l);
    tela.print(nova);
    memcpy(sombra[l], nova, sizeof(nova));
  }
}

void led(bool aceso) { digitalWrite(PINO_LED, aceso ? HIGH : LOW); }

bool sensorOk(uint8_t porta) { return porta <= PORTAS && inaOk[porta]; }

}  // namespace hal
