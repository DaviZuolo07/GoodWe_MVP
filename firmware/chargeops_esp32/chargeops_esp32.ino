/*
 * ============================================================================
 * GoodWe ChargeOps - Firmware ESP32 (WiFi)
 * ============================================================================
 * Ponto de recarga conectado por WiFi. NÃO usa cabo USB para falar com o
 * backend: o USB serve só para alimentar a placa e ver o monitor serial.
 *
 * COMO CONVERSA COM O BACKEND
 * ---------------------------
 * O ESP32 é CLIENTE. Ele chama o backend; o backend nunca chama a placa.
 * Sem IP fixo, sem porta aberta, sem precisar estar na mesma sub-rede.
 *
 *   a cada 2 s  -> GET  /hardware/comandos      "tem ordem pra mim?"
 *   a cada 2 s  -> POST /hardware/telemetria    "estou medindo isto"
 *   por evento  -> POST /hardware/rfid          "leram este cartão"
 *   ao ligar    -> POST /hardware/handshake     "cheguei; o que eu perdi?"
 *
 * A MÁQUINA DE ESTADOS (é o fluxo que a banca vai ver)
 * ----------------------------------------------------
 *   OCIOSO            LED pisca devagar. Nada preparado.
 *     | comando solicitar_cartao (morador confirmou no app)
 *   AGUARDANDO_CARTAO LED pisca rápido. Serial mostra quem deve aproximar,
 *     |               o veículo, o local, o alvo e o custo estimado.
 *     | cartão lido -> POST /rfid
 *     |   - cartão de outro morador  -> continua aguardando
 *     |   - sem saldo                -> continua aguardando ("ponha saldo
 *     |                                  no app e aproxime de novo")
 *     |   - aprovado                 -> AUTORIZADO
 *   AUTORIZADO        espera o comando `liberar` (chega em até 2 s)
 *     |
 *   CARREGANDO        relé fechado, energia integrada e reportada a cada 2 s.
 *                     O backend responde com SoC, tempo restante e custo; e
 *                     manda abrir o relé quando a recarga acaba.
 *
 * SEGURANÇA
 * ---------
 *   - Relé SEMPRE abre ao ligar a placa: ponto morto é melhor que ponto
 *     entregando energia sem ninguém pagando.
 *   - Sem WiFi ou sem resposta do backend por 20 s com o relé fechado, o
 *     relé abre sozinho (watchdog). O backend encerra a sessão do lado dele.
 *   - Credenciais ficam em `segredos.h`, que NÃO vai para o git.
 *
 * O QUE VOCÊ PRECISA MEXER
 * ------------------------
 *   1. Copie `segredos.exemplo.h` para `segredos.h` e preencha.
 *   2. Escolha SENSOR_TIPO e USAR_RFID logo abaixo.
 *   3. Confira os pinos conforme a sua montagem.
 *
 * MONTAGEM SUGERIDA (carregador de celular por USB)
 * -------------------------------------------------
 *   Relé no fio +5 V do cabo USB      -> GPIO 26
 *   LED de status (LED da placa)      -> GPIO 2
 *   INA219 (mede V e A do USB) I2C    -> SDA 21, SCL 22
 *   MFRC522 (RFID) SPI                -> SDA 5, SCK 18, MOSI 23, MISO 19, RST 4
 *   (o RST do RC522 saiu do 22 para o 4: o 22 é o SCL do INA219)
 *
 * BIBLIOTECAS (Gerenciador de Bibliotecas do Arduino IDE)
 * -------------------------------------------------------
 *   ArduinoJson         (Benoit Blanchon)     7.x
 *   Adafruit INA219     (Adafruit)            só se SENSOR_TIPO = SENSOR_INA219
 *   PZEM004Tv30         (Jakub Mandula)       só se SENSOR_TIPO = SENSOR_PZEM
 *   MFRC522             (GithubCommunity)     só se USAR_RFID = 1
 *
 * SEM HARDWARE NENHUM: deixe SENSOR_SIMULADO e USAR_RFID 0. A placa simula um
 * carregador de celular e você "aproxima o cartão" digitando o UID no monitor
 * serial (ex.: `A1B2C3D4` + Enter). O fluxo inteiro funciona assim.
 * ============================================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "segredos.h"     // WIFI_SSID, WIFI_SENHA, BACKEND_URL, DEVICE_TOKEN

// ============================================================================
// CONFIGURAÇÃO
// ============================================================================

#define SENSOR_SIMULADO 0
#define SENSOR_INA219   1
#define SENSOR_PZEM     2

#define SENSOR_TIPO  SENSOR_SIMULADO
#define USAR_RFID    0

const char* FIRMWARE_VER = "2.0.0";

const int PINO_RELE = 26;
const int PINO_LED  = 2;

// Alguns módulos de relé acionam em nível BAIXO. Se o seu ligar ao contrário,
// troque para true.
const bool RELE_INVERTIDO = false;

// Pinos do RFID (só usados se USAR_RFID = 1)
const int PINO_RFID_SS  = 5;
const int PINO_RFID_RST = 4;

// Com o relé fechado e nenhum contato bem-sucedido com o backend por este
// tempo, a energia é cortada por segurança.
const unsigned long WATCHDOG_MS = 20000;

// ============================================================================
// Bibliotecas condicionais
// ============================================================================

#if SENSOR_TIPO == SENSOR_INA219
  #include <Wire.h>
  #include <Adafruit_INA219.h>
  Adafruit_INA219 ina219;
#elif SENSOR_TIPO == SENSOR_PZEM
  #include <PZEM004Tv30.h>
  PZEM004Tv30 pzem(Serial2, 16, 17);
#endif

#if USAR_RFID
  #include <SPI.h>
  #include <MFRC522.h>
  MFRC522 rfid(PINO_RFID_SS, PINO_RFID_RST);
#endif

// ============================================================================
// Estado
// ============================================================================

enum Estado { OCIOSO, AGUARDANDO_CARTAO, AUTORIZADO, CARREGANDO };
Estado estado = OCIOSO;

struct Pedido {
  String sessaoId, usuario, veiculo, local, carregador;
  float alvo = 0, inicial = 0, custo = 0, energiaEstimadaWh = 0;
  unsigned long recebidoEm = 0;
  int segundosParaAproximar = 0;
} pedido;

unsigned long intervaloComandos = 2000, intervaloTelemetria = 2000;
unsigned long ultimoComando = 0, ultimaTelemetria = 0, ultimaMedicao = 0;
unsigned long ultimoContatoOk = 0, ultimoPiscar = 0, ultimoCartao = 0;
String uidUltimoCartao = "";

bool  releLigado = false;
float energiaWh = 0;          // acumulada NA SESSÃO (o backend espera o total)
float potenciaW = 0, tensaoV = 0, correnteA = 0, temperaturaC = 25.0;

String carregadorNumero = "?";
float  potenciaMaximaKw = 0.025;

// ============================================================================
// Utilidades de tela (monitor serial) e LED
// ============================================================================

void linha() { Serial.println(F("--------------------------------------------------")); }

void painelPedido() {
  linha();
  Serial.println(F("  APROXIME O CARTAO NO LEITOR"));
  Serial.printf("  Morador ...: %s\n", pedido.usuario.c_str());
  Serial.printf("  Dispositivo: %s\n", pedido.veiculo.c_str());
  Serial.printf("  Local .....: %s - ponto %s\n", pedido.local.c_str(), pedido.carregador.c_str());
  Serial.printf("  Carga .....: %.0f%% -> %.0f%%  (~%.1f Wh)\n",
                pedido.inicial, pedido.alvo, pedido.energiaEstimadaWh);
  Serial.printf("  Estimativa : R$ %.2f\n", pedido.custo);
  Serial.printf("  Prazo .....: %d s\n", pedido.segundosParaAproximar);
#if !USAR_RFID
  Serial.println(F("  (sem leitor: digite o UID do cartao aqui e tecle Enter)"));
#endif
  linha();
}

void atualizarLed() {
  unsigned long agora = millis();
  int periodo = (estado == AGUARDANDO_CARTAO) ? 150 : (estado == AUTORIZADO ? 400 : 2500);
  if (estado == CARREGANDO) { digitalWrite(PINO_LED, HIGH); return; }
  if (agora - ultimoPiscar >= (unsigned long)periodo) {
    ultimoPiscar = agora;
    digitalWrite(PINO_LED, !digitalRead(PINO_LED));
  }
}

void piscarRapido(int vezes) {
  for (int i = 0; i < vezes; i++) {
    digitalWrite(PINO_LED, HIGH); delay(80);
    digitalWrite(PINO_LED, LOW);  delay(80);
  }
}

// ============================================================================
// Relé
// ============================================================================

void aplicarRele(bool ligar, bool zerarEnergia = true) {
  releLigado = ligar;
  digitalWrite(PINO_RELE, RELE_INVERTIDO ? !ligar : ligar);

  if (ligar) {
    if (zerarEnergia) energiaWh = 0;      // sessão nova começa do zero
    ultimaMedicao = millis();
#if SENSOR_TIPO == SENSOR_PZEM
    if (zerarEnergia) pzem.resetEnergy();
#endif
  } else {
    potenciaW = 0; correnteA = 0;
  }
  Serial.printf("[RELE] %s\n", ligar ? "FECHADO - energia liberada" : "ABERTO");
}

// ============================================================================
// HTTP
// ============================================================================

String requisitar(const char* metodo, const String& caminho, const String& corpo) {
  if (WiFi.status() != WL_CONNECTED) return "";

  HTTPClient http;
  http.begin(String(BACKEND_URL) + caminho);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);
  http.setConnectTimeout(3000);
  http.setTimeout(5000);

  int codigo = (String(metodo) == "GET") ? http.GET() : http.POST(corpo);
  String resposta = "";
  if (codigo > 0) {
    resposta = http.getString();
    if (codigo >= 400) {
      Serial.printf("[HTTP] %s %s -> %d: %s\n", metodo, caminho.c_str(), codigo, resposta.c_str());
      resposta = "";
    } else {
      ultimoContatoOk = millis();
    }
  } else {
    Serial.printf("[HTTP] %s %s falhou (%s)\n", metodo, caminho.c_str(),
                  http.errorToString(codigo).c_str());
  }
  http.end();
  return resposta;
}

// ============================================================================
// Handshake
// ============================================================================

void lerPedido(JsonObjectConst p) {
  pedido.sessaoId  = p["sessao_id"].as<String>();
  pedido.usuario   = p["usuario"].as<String>();
  pedido.veiculo   = p["veiculo"].as<String>();
  pedido.local     = p["local"].as<String>();
  pedido.carregador = p["carregador"].as<String>();
  pedido.inicial   = p["percentual_inicial"] | 0.0f;
  pedido.alvo      = p["alvo"] | 100.0f;
  pedido.custo     = p["custo_estimado"] | 0.0f;
  pedido.energiaEstimadaWh = p["energia_estimada_wh"] | 0.0f;
  pedido.segundosParaAproximar = p["segundos_para_aproximar"] | 0;
  pedido.recebidoEm = millis();
  estado = AGUARDANDO_CARTAO;
  painelPedido();
}

bool handshake() {
  JsonDocument doc;
  doc["mac"] = WiFi.macAddress();
  doc["ip"] = WiFi.localIP().toString();
  doc["firmware"] = FIRMWARE_VER;
  String corpo; serializeJson(doc, corpo);

  String resposta = requisitar("POST", "/hardware/handshake", corpo);
  if (resposta.length() == 0) return false;

  JsonDocument r;
  if (deserializeJson(r, resposta) || !r["ok"]) {
    Serial.println(F("[HANDSHAKE] recusado - confira o DEVICE_TOKEN"));
    return false;
  }

  carregadorNumero    = r["carregador"]["numero"].as<String>();
  potenciaMaximaKw    = r["carregador"]["potencia_maxima_kw"] | 0.025f;
  intervaloComandos   = (r["intervalo_comandos_s"]   | 2) * 1000UL;
  intervaloTelemetria = (r["intervalo_telemetria_s"] | 2) * 1000UL;

  Serial.printf("[HANDSHAKE] ponto %s em %s (ate %.0f W)\n", carregadorNumero.c_str(),
                r["condominio"].as<String>().c_str(), potenciaMaximaKw * 1000.0);

  // Reiniciou no meio de uma recarga: o relé volta a fechar e a energia
  // CONTINUA de onde o backend parou, em vez de recomeçar do zero.
  bool esperado = r["rele_esperado"] | false;
  if (esperado) {
    energiaWh = r["sessao_ativa"]["energia_wh"] | 0.0f;
    aplicarRele(true, false);
    estado = CARREGANDO;
    Serial.printf("[HANDSHAKE] retomando sessao com %.2f Wh ja entregues\n", energiaWh);
  } else if (releLigado) {
    aplicarRele(false);
    estado = OCIOSO;
  }

  if (!r["pedido"].isNull()) lerPedido(r["pedido"].as<JsonObjectConst>());
  piscarRapido(2);
  return true;
}

// ============================================================================
// Comandos
// ============================================================================

void confirmarComando(const String& id, bool sucesso, const String& erro) {
  JsonDocument doc;
  doc["sucesso"] = sucesso;
  if (erro.length()) doc["erro"] = erro;
  String corpo; serializeJson(doc, corpo);
  requisitar("POST", "/hardware/comandos/" + id + "/confirmar", corpo);
}

void buscarComandos() {
  String resposta = requisitar("GET", "/hardware/comandos", "");
  if (resposta.length() == 0) return;

  JsonDocument doc;
  if (deserializeJson(doc, resposta)) return;

  for (JsonObjectConst c : doc["comandos"].as<JsonArrayConst>()) {
    String id = c["id"].as<String>();
    String acao = c["acao"].as<String>();
    Serial.printf("[COMANDO] %s\n", acao.c_str());

    if (acao == "solicitar_cartao") {
      lerPedido(c["payload"].as<JsonObjectConst>());
      confirmarComando(id, true, "");

    } else if (acao == "cancelar_cartao") {
      if (estado == AGUARDANDO_CARTAO || estado == AUTORIZADO) {
        Serial.println(F("[FLUXO] espera cancelada pelo backend"));
        estado = OCIOSO;
      }
      confirmarComando(id, true, "");

    } else if (acao == "liberar") {
      aplicarRele(true);
      estado = CARREGANDO;
      Serial.println(F("[FLUXO] recarga iniciada"));
      confirmarComando(id, true, "");

    } else if (acao == "bloquear") {
      if (releLigado) {
        Serial.printf("[FLUXO] recarga encerrada - %.2f Wh entregues\n", energiaWh);
      }
      aplicarRele(false);
      estado = OCIOSO;
      confirmarComando(id, true, "");

    } else if (acao == "ping") {
      piscarRapido(3);
      confirmarComando(id, true, "");

    } else {
      confirmarComando(id, false, "acao desconhecida: " + acao);
    }
  }
}

// ============================================================================
// Medição
// ============================================================================

void medir() {
  unsigned long agora = millis();
  float horas = (agora - ultimaMedicao) / 3600000.0;
  ultimaMedicao = agora;
  if (horas <= 0 || horas > 0.1) horas = 0;      // proteção contra overflow do millis

#if SENSOR_TIPO == SENSOR_INA219
  float shunt = ina219.getShuntVoltage_mV() / 1000.0;
  tensaoV   = ina219.getBusVoltage_V() + shunt;
  correnteA = ina219.getCurrent_mA() / 1000.0;
  if (correnteA < 0.005) correnteA = 0;          // ruído com a carga desligada
  potenciaW = tensaoV * correnteA;
  energiaWh += potenciaW * horas;

#elif SENSOR_TIPO == SENSOR_PZEM
  tensaoV   = pzem.voltage();
  correnteA = pzem.current();
  potenciaW = pzem.power();
  float wh = pzem.energy() * 1000.0;             // o PZEM devolve kWh acumulado
  if (!isnan(wh)) energiaWh = wh;
  if (isnan(tensaoV)) { tensaoV = 0; correnteA = 0; potenciaW = 0; }

#else
  // Simulação de um carregador de celular: ~9 W, caindo no fim da carga.
  if (releLigado) {
    float fracao = (pedido.energiaEstimadaWh > 0)
                 ? min(1.0f, energiaWh / pedido.energiaEstimadaWh) : 0.0f;
    float fator = (fracao < 0.8) ? 1.0 : (1.0 - (fracao - 0.8) * 3.0);   // taper
    if (fator < 0.12) fator = 0.12;
    tensaoV   = 5.05 + random(-5, 5) / 100.0;
    potenciaW = potenciaMaximaKw * 1000.0 * 0.36 * fator;                // ~9 W em 25 W
    correnteA = potenciaW / tensaoV;
    temperaturaC = min(36.0, temperaturaC + 0.05);
    energiaWh += potenciaW * horas;
  } else {
    tensaoV = 5.05; potenciaW = 0; correnteA = 0;
    temperaturaC = max(26.0, temperaturaC - 0.05);
  }
#endif
}

// ============================================================================
// Telemetria
// ============================================================================

void enviarTelemetria() {
  JsonDocument doc;
  doc["potencia_w"]    = round(potenciaW * 1000) / 1000.0;
  doc["energia_wh"]    = round(energiaWh * 10000) / 10000.0;   // ACUMULADA
  doc["tensao_v"]      = tensaoV;
  doc["corrente_a"]    = correnteA;
  doc["temperatura_c"] = temperaturaC;
  doc["rele_ligado"]   = releLigado;
  String corpo; serializeJson(doc, corpo);

  String resposta = requisitar("POST", "/hardware/telemetria", corpo);
  if (resposta.length() == 0) return;

  JsonDocument r;
  if (deserializeJson(r, resposta)) return;

  // A resposta da telemetria já diz se o relé continua fechado. Isso corta a
  // latência do fim da recarga: não esperamos o próximo poll de comandos.
  bool deveLiberar = r["deve_liberar"] | false;
  if (releLigado && !deveLiberar) {
    Serial.printf("[FIM] %s - %.2f Wh entregues, R$ %.2f\n",
                  r["motivo"].as<String>().c_str(), energiaWh, r["custo_ate_agora"] | 0.0);
    aplicarRele(false);
    estado = OCIOSO;
    piscarRapido(2);
    return;
  }

  if (releLigado) {
    Serial.printf("[MEDINDO] %.2f W | %.2f V | %.3f A | %.2f Wh | bateria %.1f%% | "
                  "faltam %d min | R$ %.2f de R$ %.2f reservados\n",
                  potenciaW, tensaoV, correnteA, energiaWh,
                  r["percentual"] | 0.0, r["tempo_restante_min"] | 0,
                  r["custo_ate_agora"] | 0.0, r["valor_reservado"] | 0.0);
  } else if (estado == OCIOSO && (r["aguardando_cartao"] | false)) {
    Serial.println(F("[FLUXO] backend diz que ha cartao pendente - pedindo detalhes"));
    handshake();
  }
}

// ============================================================================
// Cartão
// ============================================================================

void enviarCartao(String uid) {
  uid.trim(); uid.toUpperCase();
  if (uid.length() < 4) return;
  Serial.printf("[CARTAO] %s\n", uid.c_str());

  JsonDocument doc;
  doc["uid"] = uid;
  String corpo; serializeJson(doc, corpo);

  String resposta = requisitar("POST", "/hardware/rfid", corpo);
  if (resposta.length() == 0) { piscarRapido(1); return; }

  JsonDocument r;
  if (deserializeJson(r, resposta)) return;

  String mensagem = r["mensagem"].as<String>();
  if (r["autorizado"] | false) {
    Serial.printf("[CARTAO] APROVADO - %s (reservado R$ %.2f)\n",
                  mensagem.c_str(), r["valor_reservado"] | 0.0);
    estado = AUTORIZADO;
    piscarRapido(2);
    buscarComandos();                 // o `liberar` costuma já estar na fila
  } else {
    Serial.printf("[CARTAO] NEGADO - %s\n", mensagem.c_str());
    piscarRapido(4);
    if (!(r["continuar_aguardando"] | false) && estado == AGUARDANDO_CARTAO) {
      estado = OCIOSO;
    }
  }
}

void lerCartao() {
  // Monitor serial como leitor de reserva: digite o UID e tecle Enter.
  if (Serial.available()) {
    String digitado = Serial.readStringUntil('\n');
    if (digitado.length() >= 4) enviarCartao(digitado);
  }

#if USAR_RFID
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;
  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();

  // Antirrepique: o leitor devolve o mesmo cartão várias vezes por segundo.
  if (uid == uidUltimoCartao && millis() - ultimoCartao < 3000) return;
  uidUltimoCartao = uid; ultimoCartao = millis();
  enviarCartao(uid);
#endif
}

// ============================================================================
// WiFi
// ============================================================================

void conectarWifi() {
  Serial.printf("[WIFI] conectando em %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_SENHA);

  int tentativas = 0;
  while (WiFi.status() != WL_CONNECTED && tentativas < 40) {
    delay(500); Serial.print("."); tentativas++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WIFI] conectado. IP: %s\n", WiFi.localIP().toString().c_str());
    ultimoContatoOk = millis();
  } else {
    Serial.println(F("\n[WIFI] falhou. Reiniciando em 5s..."));
    delay(5000);
    ESP.restart();
  }
}

// ============================================================================
// setup / loop
// ============================================================================

void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(PINO_RELE, OUTPUT);
  pinMode(PINO_LED, OUTPUT);
  aplicarRele(false);        // NUNCA energizar por padrão

  Serial.println(F("\n=== GoodWe ChargeOps - ESP32 ==="));
  Serial.printf("firmware %s | sensor %d | rfid %d\n", FIRMWARE_VER, SENSOR_TIPO, USAR_RFID);

#if SENSOR_TIPO == SENSOR_INA219
  Wire.begin();
  if (!ina219.begin()) Serial.println(F("[SENSOR] INA219 nao encontrado - confira SDA/SCL"));
  else ina219.setCalibration_16V_400mA();      // faixa boa para carregador USB
#elif SENSOR_TIPO == SENSOR_PZEM
  Serial2.begin(9600, SERIAL_8N1, 16, 17);
#endif

#if USAR_RFID
  SPI.begin();
  rfid.PCD_Init();
  Serial.println(F("[RFID] leitor MFRC522 iniciado"));
#endif

  conectarWifi();
  while (!handshake()) {
    Serial.println(F("[HANDSHAKE] falhou, tentando de novo em 5s..."));
    delay(5000);
  }
  ultimaMedicao = millis();
}

void loop() {
  unsigned long agora = millis();

  if (WiFi.status() != WL_CONNECTED) {
    if (releLigado) {
      Serial.println(F("[WIFI] queda de rede - abrindo rele por seguranca"));
      aplicarRele(false);
      estado = OCIOSO;
    }
    conectarWifi();
    handshake();
    return;
  }

  // Watchdog: relé fechado e backend mudo há tempo demais.
  if (releLigado && agora - ultimoContatoOk > WATCHDOG_MS) {
    Serial.println(F("[WATCHDOG] sem resposta do backend - cortando energia"));
    aplicarRele(false);
    estado = OCIOSO;
    handshake();
  }

  if (agora - ultimaMedicao >= 500) medir();

  if (agora - ultimoComando >= intervaloComandos) {
    ultimoComando = agora;
    buscarComandos();
  }

  // Ocioso não precisa reportar a cada 2 s: 10 s bastam para dizer "estou vivo".
  unsigned long ritmo = (estado == CARREGANDO) ? intervaloTelemetria : 10000;
  if (agora - ultimaTelemetria >= ritmo) {
    ultimaTelemetria = agora;
    enviarTelemetria();
  }

  // Prazo do cartão estourou: volta a ficar ocioso sem esperar o backend.
  if (estado == AGUARDANDO_CARTAO && pedido.segundosParaAproximar > 0 &&
      agora - pedido.recebidoEm > (unsigned long)pedido.segundosParaAproximar * 1000UL) {
    Serial.println(F("[FLUXO] prazo para aproximar o cartao esgotado"));
    estado = OCIOSO;
  }

  lerCartao();
  atualizarLed();
  delay(20);
}
