// ============================================================================
// enlace.h - Protocolo v2 (ADR-015): HMAC, boot/seq, relógio
// ============================================================================
// Tradução de backend/testes/placa_v2.py (a referência do protocolo) + o que
// totem_virtual/rede.py põe em volta: NUNCA trava o laço além do timeout do
// HTTP, nunca assina nada com o Wi-Fi caído (não gasta seq), e toda chamada
// devolve uma Resposta.
//
// Assinatura (uma linha por campo):
//   MÉTODO \n /hardware/v2/<rota> \n boot \n seq \n ts \n sha256_hex(corpo)
//   X-Sig = hex(HMAC-SHA256(chave, mensagem))
// ============================================================================
#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

struct Resposta {
  bool chegou = false;       // o servidor respondeu (com qualquer status)
  int status = 0;
  String codigo;             // o "detail" dos erros v2 (replay, fora_da_janela...)
  JsonDocument dados;
  bool ok() const { return chegou && status == 200; }
};

class Enlace {
 public:
  bool iniciar(const char* dispositivoId, const char* chaveHex, const char* base);
  void novoBoot();                     // boot aleatório, seq do zero

  Resposta acertarRelogio();           // GET /hora (pública)
  Resposta handshake(const char* firmware);
  Resposta comandos();
  Resposta confirmar(const char* comandoId, bool sucesso, const char* erro);
  Resposta rfid(uint8_t porta, const char* uid);
  Resposta telemetria(const String& corpo);

  uint32_t boot() const { return boot_; }
  uint32_t seq() const { return seq_; }

 private:
  Resposta chamar(const char* metodo, const char* rota, const String& corpo);
  int64_t agoraTs() const { return offset_s_ + (int64_t)(millis() / 1000); }

  String base_, id_;
  uint8_t chave_[32];
  uint32_t boot_ = 0, seq_ = 0;
  int64_t offset_s_ = 0;               // hora do servidor - segundos desde o boot
};
