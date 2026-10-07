// ============================================================================
// maquina.h - A máquina de estados do Totem Central
// ============================================================================
// Tradução de totem_virtual/firmware.py, que é a implementação de referência
// testada de docs/contratos/maquina_de_estados_totem.md. Os nomes das funções
// e dos campos são os mesmos (sem acento e em camelCase onde o C++ pede).
//
// DUAS MÁQUINAS
//   Interface (uma: há um leitor e uma tela)
//     INICIANDO -> AGUARDANDO_TAG -> ESCOLHA_VAGA (15 s) -> [POST /v2/rfid]
//               -> MOSTRA_TELA (>= 4 s) -> AGUARDANDO_TAG
//   Vaga (quatro, cada uma com o seu relógio): o estado é o último que o
//   BACKEND informou; sem ele, vale o relé (fechado = carregando).
//
// NADA DE delay(): tudo é "já passaram X ms desde a marca?". A única espera
// que bloqueia é o HTTP, com timeout de 3 s.
// ============================================================================
#pragma once
#include <Arduino.h>

#include "config.h"
#include "enlace.h"
#include "hal.h"
#include "textos.h"

enum Ui : uint8_t { INICIANDO, AGUARDANDO_TAG, ESCOLHA_VAGA, MOSTRA_TELA };
enum Link : uint8_t { SEM_HORA, SEM_HANDSHAKE, PRONTO };
// Lista fechada do contrato. "Desconhecido" só existe para texto que não é estado.
enum EstadoVaga : int8_t { DESCONHECIDO = -1, LIVRE, AGUARDANDO_ENERGIA, CARREGANDO, PAUSADA,
                           COMPLETA_TOLERANCIA, COMPLETA_TAXA };

struct Vaga {
  uint8_t porta = 0;
  bool existe = false;                 // veio no handshake?
  bool rele = false;
  EstadoVaga estado = LIVRE;
  bool estadoDoBackend = false;        // false = derivado do relé
  uint32_t tEstadoMs = 0;              // relógio próprio da vaga
  char sessaoId[40] = "";
  double energiaWh = 0;                // acumulada na sessão (nunca delta)
  Medida medida;
  bool temPedido = false;              // recarga preparada no app esperando a tag
  uint32_t pedidoAteMs = 0;
  uint32_t telaBackend = 0;            // "hash" da última tela que o backend mandou
  bool divergente = false;
  uint32_t divergenteDesdeMs = 0;
};

// O que vai na fila sem rede (um struct pequeno: 240 cabem com folga na RAM).
struct Leitura {
  uint8_t porta;
  bool rele;
  uint32_t tMs;
  float potenciaW, energiaWh, tensaoV, correnteA;
};
struct LeituraFonte {
  uint32_t tMs;
  float potenciaW, tensaoV, correnteA;
};

// Fila em anel: cheia, a mais antiga sai (a energia é acumulada, a última basta).
template <typename T, uint16_t N>
class Anel {
 public:
  uint16_t tamanho() const { return n_; }
  bool vazia() const { return n_ == 0; }
  bool cheia() const { return n_ == N; }
  const T& operator[](uint16_t i) const { return dados_[(ini_ + i) % N]; }
  void empurra(const T& x) {
    if (n_ == N) { ini_ = (ini_ + 1) % N; n_--; }
    dados_[(ini_ + n_) % N] = x; n_++;
  }
  void retira(uint16_t k) { if (k > n_) k = n_; ini_ = (ini_ + k) % N; n_ -= k; }
 private:
  T dados_[N];
  uint16_t ini_ = 0, n_ = 0;
};

class Totem {
 public:
  void setup();
  void loop();

 private:
  // enlace
  bool online() const;
  void sucesso();
  void esperarMais(uint32_t agora);
  void falha(uint32_t agora);
  void recusado(const char* codigo, uint32_t agora);
  bool tratar(const Resposta& r, uint32_t agora);
  void rede(uint32_t agora);
  void aplicarHandshake(JsonVariantConst dados, uint32_t agora);
  // vaga
  void mudarEstado(Vaga& v, EstadoVaga e, uint32_t agora, bool doBackend = true);
  void ligar(Vaga& v, const char* sessaoId, const char* origem, uint32_t agora, double energiaWh = -1);
  void desligar(Vaga& v, const char* origem, uint32_t agora);
  void pedido(Vaga& v, JsonVariantConst p, uint32_t agora);
  // interface
  void mostrar(uint32_t agora, uint32_t duracaoMs = TELA_MS);
  void mostrarLinhas(const char* l0, const char* l1, uint32_t agora, uint32_t duracaoMs = TELA_MS);
  void interface(uint32_t agora);
  void enviarTag(uint8_t porta, uint32_t agora);
  // medição, fonte, telemetria, comandos, travas, tela
  void medir(uint32_t agora);
  void virar(bool solar, uint32_t agora, bool forcada);
  void fonteSolar(uint32_t agora);
  String montarLote(uint32_t agora, uint16_t& n, uint16_t& m);
  void telemetria(uint32_t agora);
  void respostaDaPorta(JsonVariantConst p, uint32_t agora);
  void comandos(uint32_t agora);
  const char* executar(JsonVariantConst c, uint32_t agora);
  void travaOffline(uint32_t agora);
  void rotulo(const Vaga& v, char* saida);
  void desenhar(uint32_t agora);
  void evento(const char* formato, ...);

  Enlace enlace_;
  Vaga vagas_[PORTAS + 1];             // índice = número da vaga

  // interface
  Ui ui_ = INICIANDO;
  uint32_t tUi_ = 0, duracaoTela_ = 0;
  char uid_[33] = "";
  Tela tela_;

  // enlace
  Link link_ = SEM_HORA;
  bool handshakeFeito_ = false;
  uint32_t proximaTentativa_ = 0, esperaMs_ = RETENTATIVA_MIN_MS;
  bool offline_ = false;               // offline_desde "vazio" = !offline_
  uint32_t offlineDesde_ = 0;
  bool wifiEstavaOk_ = true, cortouOffline_ = false;
  char recusa_[24] = "";               // último 401 de autenticação (ADR-021)
  uint8_t recusasSeguidas_ = 0;
  bool bloqueado_ = false;             // diagnóstico já impresso
  uint32_t tReconciliou_ = 0;
  bool reconciliouAlguma_ = false;

  // ritmo
  uint32_t tMedicao_ = 0, tAmostra_ = 0, tEnvio_ = 0, tComandos_ = 0;
  uint32_t comandosMs_ = COMANDOS_MS;
  uint8_t loteMax_ = MAX_LEITURAS_LOTE;
  bool drenando_ = false;

  // filas
  Anel<Leitura, FILA_LEITURAS_MAX> filaLeituras_;
  Anel<LeituraFonte, FILA_FONTES_MAX> filaFontes_;
  uint32_t descartadas_ = 0, lotesEnviados_ = 0, lotesDescartados_ = 0;
  bool configOk_ = true;               // false: DEVICE_KEY_HEX mal escrita em segredos.h

  // vaga 4: reversor solar/rede
  bool fonteSolar_ = false;            // false = rede (bobina desligada)
  uint32_t tTroca_ = 0;
  bool forcada_ = false;
  uint32_t tForcada_ = 0;
  int8_t fonteBackend_ = -1;           // -1 = não informou, 0 = rede, 1 = solar
  bool quedaAtiva_ = false;
  uint32_t quedaDesde_ = 0;
  bool bateriaOk_ = true;
  Medida bateria_;                     // última leitura do INA219 da 18650
};
