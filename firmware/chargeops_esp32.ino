/*
 * ============================================================================
 * GoodWe ChargeOps - Firmware ESP32
 * ============================================================================
 * Ponto de recarga conectado por WiFi.
 *
 * COMO ISSO CONVERSA COM O BACKEND
 * --------------------------------
 * O ESP32 é CLIENTE. Ele chama o backend; o backend nunca chama a placa.
 * Isso significa que você NÃO precisa de IP fixo, port forwarding nem estar
 * na mesma rede do servidor. Funciona em roteador de casa, WiFi da faculdade
 * ou hotspot de celular.
 *
 * Três laços rodando em ritmos diferentes:
 *   - a cada 2s  -> GET  /hardware/comandos      "tem ordem pra mim?"
 *   - a cada 5s  -> POST /hardware/telemetria    "estou medindo isto"
 *   - por evento -> POST /hardware/rfid          "leram um cartão"
 *
 * O QUE VOCÊ PRECISA MEXER
 * ------------------------
 * Só o bloco CONFIGURAÇÃO logo abaixo. O resto funciona como está.
 *
 * LIGAÇÕES (ajuste os pinos conforme sua montagem)
 * ------------------------------------------------
 *   Relé            -> GPIO 26
 *   LED de status   -> GPIO 2  (LED da placa na maioria dos DevKits)
 *   RFID RC522      -> SPI: SDA 5, SCK 18, MOSI 23, MISO 19, RST 22
 *   Medidor PZEM    -> Serial2: RX 16, TX 17
 *
 * BIBLIOTECAS (Gerenciador de Bibliotecas do Arduino IDE)
 * -------------------------------------------------------
 *   ArduinoJson    (Benoit Blanchon)  v6 ou superior
 *   MFRC522        (GithubCommunity)  - só se for usar RFID
 *   PZEM004Tv30    (Jakub Mandula)    - só se for usar o medidor
 * ============================================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ============================================================================
// CONFIGURAÇÃO - é só isto que você mexe
// ============================================================================

const char* WIFI_SSID     = "NOME_DA_SUA_REDE";
const char* WIFI_SENHA    = "SENHA_DA_REDE";

// IP do PC que roda o uvicorn, na mesma rede. Descubra com `ipconfig`
// (Windows) ou `ip addr` (Linux). NÃO use "localhost" nem 127.0.0.1: para o
// ESP32, localhost é ele mesmo.
//
// IMPORTANTE: suba o backend com --host 0.0.0.0, senão ele só aceita conexão
// da própria máquina:
//     uvicorn main:app --reload --host 0.0.0.0
const char* BACKEND_URL   = "http://192.168.0.100:8000";

// Token cadastrado na tabela `dispositivos` (arquivo 09_hardware_esp32.sql).
const char* DEVICE_TOKEN  = "gw-esp32-portal-01-troque-este-token";

const char* FIRMWARE_VER  = "1.0.0";

// Pinos
const int PINO_RELE       = 26;
const int PINO_LED        = 2;

// Ligue em false enquanto não tiver o hardware montado: o firmware simula os
// valores e você testa a ponta inteira só com a placa na USB.
const bool TEM_MEDIDOR    = false;
const bool TEM_RFID       = false;

// Alguns módulos de relé são acionados em nível BAIXO. Se o seu liga ao
// contrário do esperado, troque para true.
const bool RELE_INVERTIDO = false;

// ============================================================================
// Estado interno
// ============================================================================

unsigned long intervaloComandos   = 2000;
unsigned long intervaloTelemetria = 5000;

unsigned long ultimoComando   = 0;
unsigned long ultimaTelemetria = 0;
unsigned long ultimaIntegracao = 0;

bool  releLigado    = false;
float energiaWh     = 0;      // acumulada na sessão atual
float potenciaW     = 0;
float tensaoV       = 0;
float correnteA     = 0;
float temperaturaC  = 25.0;

String carregadorNumero = "?";
float  potenciaMaximaKw = 7.4;

// ============================================================================
// Relé
// ============================================================================

void aplicarRele(bool ligar) {
  releLigado = ligar;
  digitalWrite(PINO_RELE, RELE_INVERTIDO ? !ligar : ligar);
  digitalWrite(PINO_LED, ligar);

  // Sessão nova começa do zero: o backend recebe energia ACUMULADA, e zerar
  // aqui é o que faz a conta bater com o início da recarga.
  if (ligar) {
    energiaWh = 0;
    ultimaIntegracao = millis();
  } else {
    potenciaW = 0;
    correnteA = 0;
  }

  Serial.printf("[RELE] %s\n", ligar ? "FECHADO - energia liberada" : "ABERTO");
}

void piscar(int vezes) {
  for (int i = 0; i < vezes; i++) {
    digitalWrite(PINO_LED, HIGH); delay(120);
    digitalWrite(PINO_LED, LOW);  delay(120);
  }
  digitalWrite(PINO_LED, releLigado);
}

// ============================================================================
// HTTP - toda requisição leva o token
// ============================================================================

String requisitar(const char* metodo, String caminho, String corpo) {
  if (WiFi.status() != WL_CONNECTED) return "";

  HTTPClient http;
  http.begin(String(BACKEND_URL) + caminho);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);
  http.setTimeout(5000);

  int codigo = (String(metodo) == "GET") ? http.GET() : http.POST(corpo);

  String resposta = "";
  if (codigo > 0) {
    resposta = http.getString();
    if (codigo >= 400) {
      Serial.printf("[HTTP] %s %s -> %d: %s\n",
                    metodo, caminho.c_str(), codigo, resposta.c_str());
    }
  } else {
    Serial.printf("[HTTP] %s %s falhou (%s)\n", metodo, caminho.c_str(),
                  http.errorToString(codigo).c_str());
  }

  http.end();
  return resposta;
}

// ============================================================================
// 1. Handshake - "cheguei, quem sou eu?"
// ============================================================================

bool handshake() {
  StaticJsonDocument<256> doc;
  doc["mac"]      = WiFi.macAddress();
  doc["ip"]       = WiFi.localIP().toString();
  doc["firmware"] = FIRMWARE_VER;

  String corpo;
  serializeJson(doc, corpo);

  String resposta = requisitar("POST", "/hardware/handshake", corpo);
  if (resposta.length() == 0) return false;

  StaticJsonDocument<1024> r;
  if (deserializeJson(r, resposta)) {
    Serial.println("[HANDSHAKE] resposta inválida");
    return false;
  }
  if (!r["ok"]) {
    Serial.println("[HANDSHAKE] recusado - confira o DEVICE_TOKEN");
    return false;
  }

  carregadorNumero  = r["carregador"]["numero"].as<String>();
  potenciaMaximaKw  = r["carregador"]["potencia_maxima_kw"] | 7.4;
  intervaloComandos   = (r["intervalo_comandos_s"]   | 2) * 1000UL;
  intervaloTelemetria = (r["intervalo_telemetria_s"] | 5) * 1000UL;

  Serial.printf("[HANDSHAKE] ponto %s em %s, ate %.1f kW\n",
                carregadorNumero.c_str(),
                r["condominio"].as<String>().c_str(),
                potenciaMaximaKw);

  // A placa pode ter reiniciado no meio de uma recarga. O backend diz em que
  // estado o relé deveria estar, e nós obedecemos - senão o carro fica parado
  // com a sessão aberta no banco.
  bool esperado = r["rele_esperado"] | false;
  if (esperado != releLigado) {
    Serial.println("[HANDSHAKE] restaurando estado do rele apos reinicio");
    aplicarRele(esperado);
  }

  piscar(2);
  return true;
}

// ============================================================================
// 2. Comandos - "tem ordem pra mim?"
// ============================================================================

void confirmarComando(String id, bool sucesso, String erro) {
  StaticJsonDocument<192> doc;
  doc["sucesso"] = sucesso;
  if (erro.length()) doc["erro"] = erro;

  String corpo;
  serializeJson(doc, corpo);
  requisitar("POST", "/hardware/comandos/" + id + "/confirmar", corpo);
}

void buscarComandos() {
  String resposta = requisitar("GET", "/hardware/comandos", "");
  if (resposta.length() == 0) return;

  StaticJsonDocument<1024> doc;
  if (deserializeJson(doc, resposta)) return;

  for (JsonObject c : doc["comandos"].as<JsonArray>()) {
    String id   = c["id"].as<String>();
    String acao = c["acao"].as<String>();

    Serial.printf("[COMANDO] %s\n", acao.c_str());

    if (acao == "liberar") {
      aplicarRele(true);
      confirmarComando(id, true, "");
    } else if (acao == "bloquear") {
      aplicarRele(false);
      confirmarComando(id, true, "");
    } else if (acao == "ping") {
      piscar(3);
      confirmarComando(id, true, "");
    } else {
      confirmarComando(id, false, "acao desconhecida: " + acao);
    }
  }
}

// ============================================================================
// 3. Medição
// ============================================================================

void medir() {
  unsigned long agora = millis();
  float horas = (agora - ultimaIntegracao) / 3600000.0;
  ultimaIntegracao = agora;

  if (TEM_MEDIDOR) {
    // ------------------------------------------------------------------
    // Com PZEM-004T v3 ligado no Serial2:
    //
    //   #include <PZEM004Tv30.h>
    //   PZEM004Tv30 pzem(Serial2, 16, 17);
    //
    //   tensaoV   = pzem.voltage();
    //   correnteA = pzem.current();
    //   potenciaW = pzem.power();
    //   energiaWh = pzem.energy() * 1000.0;   // o PZEM devolve kWh
    //
    // O PZEM tem contador próprio, então dá para usar o valor dele direto.
    // Se usar sensor sem contador (INA219, SCT-013), integre como abaixo.
    // ------------------------------------------------------------------
  } else {
    // Simulação para testar a ponta sem o hardware montado.
    if (releLigado) {
      tensaoV   = 220.0 + random(-30, 30) / 10.0;
      potenciaW = potenciaMaximaKw * 1000.0 * (0.92 + random(-40, 40) / 1000.0);
      correnteA = potenciaW / tensaoV;
      temperaturaC = min(45.0, temperaturaC + 0.4);
    } else {
      tensaoV   = 220.0;
      potenciaW = 0;
      correnteA = 0;
      temperaturaC = max(24.0, temperaturaC - 0.3);
    }
  }

  // Integração: potência x tempo = energia. Só quando o relé está fechado.
  if (releLigado && !TEM_MEDIDOR) {
    energiaWh += potenciaW * horas;
  }
}

// ============================================================================
// 4. Telemetria - "estou medindo isto agora"
// ============================================================================

void enviarTelemetria() {
  medir();

  StaticJsonDocument<384> doc;
  doc["potencia_w"]    = potenciaW;
  doc["energia_wh"]    = energiaWh;      // ACUMULADA, não delta
  doc["tensao_v"]      = tensaoV;
  doc["corrente_a"]    = correnteA;
  doc["temperatura_c"] = temperaturaC;
  doc["rele_ligado"]   = releLigado;

  String corpo;
  serializeJson(doc, corpo);

  String resposta = requisitar("POST", "/hardware/telemetria", corpo);
  if (resposta.length() == 0) return;

  StaticJsonDocument<384> r;
  if (deserializeJson(r, resposta)) return;

  // A própria resposta da telemetria diz se o relé deve continuar fechado.
  // Isso corta a latência do "parar recarga": não esperamos o próximo poll de
  // comandos, o desligamento acontece no pacote seguinte.
  bool deveLiberar = r["deve_liberar"] | false;
  if (releLigado && !deveLiberar) {
    Serial.println("[TELEMETRIA] backend encerrou a sessao - abrindo rele");
    aplicarRele(false);
  }

  if (releLigado) {
    Serial.printf("[TELEMETRIA] %.0f W | %.1f Wh | %.1f%% | %.1f C\n",
                  potenciaW, energiaWh,
                  r["percentual"] | 0.0, temperaturaC);
  }
}

// ============================================================================
// 5. RFID - "leram um cartão"
// ============================================================================

void processarCartao(String uid) {
  Serial.printf("[RFID] cartao %s\n", uid.c_str());

  StaticJsonDocument<128> doc;
  doc["uid"] = uid;

  String corpo;
  serializeJson(doc, corpo);

  String resposta = requisitar("POST", "/hardware/rfid", corpo);
  if (resposta.length() == 0) { piscar(1); return; }

  StaticJsonDocument<512> r;
  if (deserializeJson(r, resposta)) return;

  if (r["autorizado"]) {
    Serial.printf("[RFID] %s\n", r["mensagem"].as<String>().c_str());
    // Não fechamos o relé aqui: o backend vai enfileirar o "liberar" e ele
    // chega no próximo poll. Uma porta de entrada só para ligar energia.
    piscar(2);
  } else {
    Serial.printf("[RFID] negado: %s\n", r["mensagem"].as<String>().c_str());
    piscar(4);
  }
}

void lerRfid() {
  if (!TEM_RFID) return;
  // ------------------------------------------------------------------
  // Com MFRC522:
  //
  //   #include <MFRC522.h>
  //   MFRC522 rfid(5, 22);   // SDA, RST
  //
  //   if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;
  //   String uid = "";
  //   for (byte i = 0; i < rfid.uid.size; i++) {
  //     if (rfid.uid.uidByte[i] < 0x10) uid += "0";
  //     uid += String(rfid.uid.uidByte[i], HEX);
  //   }
  //   uid.toUpperCase();
  //   processarCartao(uid);
  //   rfid.PICC_HaltA();
  // ------------------------------------------------------------------
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
    delay(500);
    Serial.print(".");
    tentativas++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WIFI] conectado. IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\n[WIFI] falhou. Reiniciando em 5s...");
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

  // SEGURANÇA: relé aberto ao ligar. Nunca energizar por padrão - se o
  // backend estiver fora do ar, o ponto fica morto, e ponto morto é melhor
  // que ponto entregando energia sem ninguém pagando.
  aplicarRele(false);

  Serial.println("\n=== GoodWe ChargeOps - ESP32 ===");
  conectarWifi();

  while (!handshake()) {
    Serial.println("[HANDSHAKE] falhou, tentando de novo em 5s...");
    delay(5000);
  }

  ultimaIntegracao = millis();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    // Rede caiu: abre o relé por segurança e reconecta. Sem backend não há
    // como saber se a sessão ainda vale.
    if (releLigado) {
      Serial.println("[WIFI] queda de rede - abrindo rele por seguranca");
      aplicarRele(false);
    }
    conectarWifi();
    handshake();
    return;
  }

  unsigned long agora = millis();

  if (agora - ultimoComando >= intervaloComandos) {
    ultimoComando = agora;
    buscarComandos();
  }

  if (agora - ultimaTelemetria >= intervaloTelemetria) {
    ultimaTelemetria = agora;
    enviarTelemetria();
  }

  lerRfid();
  delay(50);
}
