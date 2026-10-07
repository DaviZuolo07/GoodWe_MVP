// ============================================================================
// config.h - Pinos e constantes do Totem Central (ADR-022)
// ============================================================================
// As constantes de tempo têm os MESMOS nomes e valores de
// totem_virtual/config.py: o totem virtual é a referência testada, este
// firmware é a tradução. Mudou aqui sem mudar lá? Primeiro o contrato
// (docs/contratos/maquina_de_estados_totem.md), depois o virtual, depois aqui.
// ============================================================================
#pragma once
#include <Arduino.h>

#define FIRMWARE_VERSAO "totem-central-1.0"   // vai no handshake (até 32 caracteres)

// ---------------------------------------------------------------------------
// PINOS (ADR-022 D4). Índice = número da vaga; a posição 0 não é usada.
// ---------------------------------------------------------------------------
constexpr uint8_t PINO_RELE[5]  = {0, 26, 27, 25, 33};   // módulo de 4 canais
constexpr uint8_t PINO_BOTAO[5] = {0, 13, 14, 15, 34};   // ao GND. O 34 NÃO tem pull-up
                                                         // interno: resistor de 10 kΩ ao 3V3
constexpr uint8_t PINO_REVERSOR = 32;   // relé SPDT da vaga 4: desligado = rede, ligado = solar
constexpr uint8_t PINO_LED      = 2;    // LED da placa: aceso = servidor aceitando a placa

constexpr uint8_t PINO_RFID_SS  = 5;    // MFRC522: SCK 18, MISO 19, MOSI 23 (SPI padrão)
constexpr uint8_t PINO_RFID_RST = 4;

constexpr uint8_t PINO_SDA = 21, PINO_SCL = 22;               // Wire: LCD + INA219 das vagas
constexpr uint8_t PINO_SDA_SOLAR = 17, PINO_SCL_SOLAR = 16;   // Wire1: INA219 da bateria

constexpr uint8_t ENDERECO_LCD = 0x27;                        // PCF8574 (alguns vêm em 0x3F)
constexpr uint8_t ENDERECO_INA[5] = {0, 0x40, 0x41, 0x44, 0x45};  // sem solda, A0, A1, A0+A1
constexpr uint8_t ENDERECO_INA_SOLAR = 0x40;                  // sozinho no Wire1, sem solda

// Módulos com optoacoplador ligam com LOW. Troque para 0 se o seu ligar com HIGH.
#define RELE_ATIVO_EM_LOW      1
#define REVERSOR_ATIVO_EM_LOW  1

constexpr uint8_t PORTAS = 4;
constexpr uint8_t PORTA_SOLAR = 4;

// ---------------------------------------------------------------------------
// Tempos da máquina de estados (iguais a totem_virtual/config.py)
// ---------------------------------------------------------------------------
constexpr uint32_t TIMEOUT_ESCOLHA_MS = 15000;   // tempo para apertar o botão da vaga
constexpr uint32_t TELA_MS            = 4000;    // resposta do backend na tela
constexpr uint32_t AVISO_MS           = 2000;    // avisos curtos
constexpr uint32_t MEDICAO_MS         = 200;     // INA219 + integração da energia
constexpr uint32_t AMOSTRA_MS         = 2000;    // uma leitura por vaga vai para a fila
constexpr uint32_t ENVIO_MS           = 6000;    // um lote de telemetria
constexpr uint32_t COMANDOS_MS        = 2000;    // o handshake pode trocar
constexpr uint32_t OFFLINE_CORTE_MS   = 120000;  // sem servidor por isto: abre os relés
constexpr uint32_t RETENTATIVA_MIN_MS = 1000;
constexpr uint32_t RETENTATIVA_MAX_MS = 10000;
constexpr uint8_t  RECUSAS_PARA_BLOQUEAR = 3;    // ADR-021
constexpr uint32_t BLOQUEIO_MS        = 60000;
constexpr uint32_t TROCA_FONTE_MS     = 200;     // medida estabilizando depois do reversor
constexpr uint32_t FONTE_MIN_MS       = 30000;   // forçada para a rede: fica pelo menos isto
constexpr uint32_t QUEDA_MS           = 1000;    // tensão baixa precisa durar isto
constexpr uint32_t PAGINA_MS          = 2000;    // LCD 16x2: uma página de 2 linhas
constexpr uint32_t ALTERNA_MS         = 3000;    // tela de espera: convite <-> quadro
constexpr uint32_t HTTP_TIMEOUT_MS    = 3000;    // a ÚNICA espera que bloqueia
constexpr uint32_t DIVERGENTE_MS      = 10000;   // servidor acha que carrega e o relé está aberto
constexpr uint32_t RECONCILIAR_MS     = 30000;   // no máximo um handshake de reconciliação por isto

// Hardware: não são do contrato, são do jeito de ler as peças
constexpr uint32_t DEBOUNCE_MS        = 30;
constexpr uint32_t RFID_MS            = 100;     // procura tag a cada 100 ms
constexpr uint32_t MESMA_TAG_MS       = 1500;    // a mesma tag parada no leitor não conta de novo

// ---------------------------------------------------------------------------
// Limites do protocolo v2 (ADR-015 D4)
// ---------------------------------------------------------------------------
constexpr uint8_t  MAX_LEITURAS_LOTE = 30;
constexpr uint8_t  MAX_FONTES_LOTE   = 20;
constexpr size_t   CORPO_MAX_BYTES   = 7000;
constexpr uint16_t FILA_LEITURAS_MAX = 240;
constexpr uint16_t FILA_FONTES_MAX   = 120;

// ---------------------------------------------------------------------------
// Bateria solar: limiares a CALIBRAR na bancada real
// ---------------------------------------------------------------------------
constexpr float V_BATERIA_CORTE = 3.30f;
constexpr float V_BATERIA_VOLTA = 3.60f;

// ---------------------------------------------------------------------------
// LCD 16x2
// ---------------------------------------------------------------------------
constexpr uint8_t COLUNAS = 16, LINHAS = 2;
constexpr uint8_t TELA_MAX_LINHAS = 8;   // 4 linhas de 20 do backend re-quebradas em 16
