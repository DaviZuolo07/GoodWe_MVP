// ============================================================================
// maquina.h - A máquina de estados do Totem Next
// ============================================================================
// A MESMA máquina do Totem Central (firmware/totem_central, tradução testada
// de totem_virtual/firmware.py), com três trocas para o hardware da banca:
//
//   1. medição      sem INA219: a energia de cada vaga sai do modelo de carga
//                   do celular (carga.h), integrado só com o relé FECHADO;
//   2. divisão      o relé de cada vaga segue o rodízio da divisão por tempo
//                   (água no balde): `rele` = a sessão está liberada pelo
//                   backend; `fechado` = o contato está fechado AGORA;
//   3. sem solar    sem painel, bateria 18650, reversor nem lote de fontes.
//
// DUAS MÁQUINAS
//   Interface (uma: há um leitor e uma tela)
//     INICIANDO -> AGUARDANDO_TAG -> ESCOLHA_VAGA (15 s) -> [POST /v2/rfid]
//               -> MOSTRA_TELA (>= 4 s) -> AGUARDANDO_TAG
<<<<<<< HEAD
//   Vaga (PORTAS delas, cada uma com o seu relógio): o estado é o último que
//   o BACKEND informou; sem ele, vale o relé (liberado = carregando).
=======
//   Vaga (quatro, cada uma com o seu relógio): o estado é o último que o
//   BACKEND informou; sem ele, vale o relé (liberado = carregando).
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
//
// NADA DE delay(): tudo é "já passaram X ms desde a marca?". A única espera
// que bloqueia é o HTTP, com timeout de HTTP_TIMEOUT_MS (8 s).
// ============================================================================
#pragma once
#include <Arduino.h>

#include "carga.h"
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
  bool rele = false;                   // sessão LIBERADA pelo backend (o "relé lógico")
  bool fechado = false;                // contato fechado AGORA (rodízio da divisão)
  EstadoVaga estado = LIVRE;
  bool estadoDoBackend = false;        // false = derivado do relé
  uint32_t tEstadoMs = 0;              // relógio próprio da vaga
  char sessaoId[40] = "";
  double energiaWh = 0;                // acumulada na sessão (nunca delta)
  float potenciaW = 0, tensaoV = 0, correnteA = 0;   // do MODELO, neste instante
  carga::Celular celular;              // o modelo de carga do celular da vaga
  float fracao = 1.0f;                 // fração de tempo dada pelo water-filling
  int32_t tempoMin = -1;               // previsão de término do backend (-1 = sem)
  bool temPedido = false;              // recarga preparada no app esperando a tag
  uint32_t pedidoAteMs = 0;
  uint32_t telaBackend = 0;            // "hash" da última tela que o backend mandou
  bool divergente = false;
  uint32_t divergenteDesdeMs = 0;
};

// O que vai na fila sem rede (um struct pequeno: 240 cabem com folga na RAM).
struct Leitura {
  uint8_t porta;
  bool fechado;
  uint32_t tMs;
  float potenciaW, energiaWh, tensaoV, correnteA;
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
  void modeloDoBackend(Vaga& v, JsonVariantConst origem);   // `fracao` + `carga`
  // interface
  void mostrar(uint32_t agora, uint32_t duracaoMs = TELA_MS);
  void mostrarLinhas(const char* l0, const char* l1, uint32_t agora, uint32_t duracaoMs = TELA_MS);
  void interface(uint32_t agora);
  void enviarTag(uint8_t porta, uint32_t agora);
  // divisão por tempo, modelo de carga, telemetria, comandos, travas, tela
  void divisao(uint32_t agora);
  void medir(uint32_t agora);
  String montarLote(uint32_t agora, uint16_t& n);
  void telemetria(uint32_t agora);
  void respostaDaPorta(JsonVariantConst p, uint32_t agora);
  void comandos(uint32_t agora);
  const char* executar(JsonVariantConst c, uint32_t agora);
  void travaOffline(uint32_t agora);
  void rotulo(const Vaga& v, char* saida);
  void desenhar(uint32_t agora);
  void evento(const char* formato, ...);
<<<<<<< HEAD
  // Monitor serial: comandos (tag e botão pelo computador) e estado das vagas
  void lerSerial(char* tag, size_t tamanho, bool& temTag, uint8_t& botao);
  void statusSerial(uint32_t agora);
=======
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93

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

  // divisão por tempo: o rodízio da janela atual
  uint32_t tJanela_ = 0;
  carga::Fatia fatias_[PORTAS + 1][2];
  uint8_t nFatias_[PORTAS + 1] = {0};
  uint8_t assinatura_ = 0;             // quais vagas estavam liberadas ao montar o rodízio
  float fracoesMontadas_[PORTAS + 1] = {0};

  // tomada (derivada): o que a fonte de 5 V puxa da parede
  float tomadaW_ = 0;
  double tomadaWh_ = 0;

  // filas
  Anel<Leitura, FILA_LEITURAS_MAX> filaLeituras_;
  uint32_t descartadas_ = 0, lotesEnviados_ = 0, lotesDescartados_ = 0;
  bool configOk_ = true;               // false: DEVICE_KEY_HEX mal escrita em segredos.h
<<<<<<< HEAD

  // monitor serial
  char linhaSerial_[48] = "";
  uint8_t nSerial_ = 0;
  uint32_t tStatus_ = 0;
=======
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
};
