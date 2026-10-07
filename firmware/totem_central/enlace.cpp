#include "enlace.h"

#include <HTTPClient.h>
#include <WiFi.h>
#include <esp_random.h>
#include <mbedtls/md.h>

#include "config.h"

namespace {
  const char* PREFIXO = "/hardware/v2";

  void hex(const uint8_t* bytes, size_t n, char* saida) {
    static const char* H = "0123456789abcdef";
    for (size_t i = 0; i < n; i++) { saida[2 * i] = H[bytes[i] >> 4]; saida[2 * i + 1] = H[bytes[i] & 15]; }
    saida[2 * n] = '\0';
  }

  int nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
  }

  void sha256Hex(const String& corpo, char saida[65]) {
    uint8_t d[32];
    mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),
               (const uint8_t*)corpo.c_str(), corpo.length(), d);
    hex(d, 32, saida);
  }

  void hmacHex(const uint8_t* chave, const String& msg, char saida[65]) {
    uint8_t d[32];
    mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), chave, 32,
                    (const uint8_t*)msg.c_str(), msg.length(), d);
    hex(d, 32, saida);
  }
}

bool Enlace::iniciar(const char* dispositivoId, const char* chaveHex, const char* base) {
  id_ = dispositivoId;
  base_ = base;
  while (base_.endsWith("/")) base_.remove(base_.length() - 1);
  if (strlen(chaveHex) != 64) return false;
  for (int i = 0; i < 32; i++) {
    int a = nibble(chaveHex[2 * i]), b = nibble(chaveHex[2 * i + 1]);
    if (a < 0 || b < 0) return false;
    chave_[i] = (a << 4) | b;
  }
  novoBoot();
  return true;
}

void Enlace::novoBoot() {
  boot_ = esp_random();
  seq_ = 0;
}

Resposta Enlace::acertarRelogio() {
  Resposta r;
  if (WiFi.status() != WL_CONNECTED) return r;
  HTTPClient http;
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(base_ + PREFIXO + "/hora")) return r;
  int codigo = http.GET();
  if (codigo > 0) {
    r.chegou = true;
    r.status = codigo;
    if (deserializeJson(r.dados, http.getString()) == DeserializationError::Ok && codigo == 200
        && r.dados["ts"].is<int64_t>()) {
      offset_s_ = r.dados["ts"].as<int64_t>() - (int64_t)(millis() / 1000);
    } else if (codigo == 200) {
      r.status = 502;                    // 200 sem "ts": não acertou nada
    }
  }
  http.end();
  return r;
}

Resposta Enlace::chamar(const char* metodo, const char* rota, const String& corpo) {
  Resposta r;
  if (WiFi.status() != WL_CONNECTED) return r;   // sem Wi-Fi nem assina: não gasta seq

  String caminho = String(PREFIXO) + rota;
  seq_++;                                        // +1 a CADA requisição, inclusive as que falham
  int64_t ts = agoraTs();
  char hashCorpo[65], assinatura[65];
  sha256Hex(corpo, hashCorpo);
  String msg = String(metodo) + "\n" + caminho + "\n" + String(boot_) + "\n" + String(seq_) + "\n" +
               String((long long)ts) + "\n" + hashCorpo;
  hmacHex(chave_, msg, assinatura);

  HTTPClient http;
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(base_ + caminho)) return r;
  http.addHeader("X-Device-Id", id_);
  http.addHeader("X-Boot", String(boot_));
  http.addHeader("X-Seq", String(seq_));
  http.addHeader("X-Ts", String((long long)ts));
  http.addHeader("X-Sig", assinatura);
  int codigo;
  if (strcmp(metodo, "GET") == 0) {
    codigo = http.GET();
  } else {
    http.addHeader("Content-Type", "application/json");
    codigo = http.POST((uint8_t*)corpo.c_str(), corpo.length());   // os MESMOS bytes assinados
  }
  if (codigo > 0) {                              // <= 0: conexão recusada, timeout, DNS...
    r.chegou = true;
    r.status = codigo;
    if (deserializeJson(r.dados, http.getString()) != DeserializationError::Ok) r.dados.clear();
    if (codigo != 200) {
      JsonVariantConst detalhe = r.dados["detail"];
      r.codigo = detalhe.is<const char*>() ? detalhe.as<const char*>() : "invalido";
    }
  }
  http.end();
  return r;
}

Resposta Enlace::handshake(const char* firmware) {
  JsonDocument d;
  d["mac"] = WiFi.macAddress();
  d["ip"] = WiFi.localIP().toString();
  d["firmware"] = firmware;
  String corpo;
  serializeJson(d, corpo);
  return chamar("POST", "/handshake", corpo);
}

Resposta Enlace::comandos() { return chamar("GET", "/comandos", ""); }

Resposta Enlace::confirmar(const char* comandoId, bool sucesso, const char* erro) {
  JsonDocument d;
  d["sucesso"] = sucesso;
  if (erro && *erro) d["erro"] = String(erro).substring(0, 200);
  String corpo;
  serializeJson(d, corpo);
  return chamar("POST", (String("/comandos/") + comandoId + "/confirmar").c_str(), corpo);
}

Resposta Enlace::rfid(uint8_t porta, const char* uid) {
  JsonDocument d;
  d["porta"] = porta;
  d["uid"] = uid;
  String corpo;
  serializeJson(d, corpo);
  return chamar("POST", "/rfid", corpo);
}

Resposta Enlace::telemetria(const String& corpo) { return chamar("POST", "/telemetria", corpo); }
