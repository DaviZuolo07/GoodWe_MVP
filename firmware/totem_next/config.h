// ============================================================================
<<<<<<< HEAD
// config.h - Pinos e constantes do Totem Next (23/10/2026)
// ============================================================================
// O hardware da banca: ESP32, LCD 16x2 I2C, MFRC522, botão, módulo relé e
// USB-A/USB-C de painel. SEM INA219 e SEM solar.
//
// UMA VAGA (23/10): a montagem que funciona tem UMA vaga, e o relé dela LIBERA
// ENERGIA de verdade. Tudo neste firmware é parametrizado por `PORTAS`: com 1
// o totem é de uma vaga; com 4, volta a ser o de quatro, sem mais nenhuma
// mudança de código. O backend segue as portas que `preparar_totem.py --vagas`
// gravou - os dois números têm de bater.
=======
// config.h - Pinos e constantes do Totem Next (22/10/2026)
// ============================================================================
// O hardware da banca: ESP32, LCD 16x2 I2C, MFRC522, 4 botões, módulo relé de
// 4 canais, 2 USB-A + 2 USB-C de painel. SEM INA219 e SEM solar.
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
//
// As constantes de tempo da máquina de estados têm os MESMOS nomes e valores
// de firmware/totem_central/config.h (a tradução testada do totem virtual).
// O que é novo aqui: o MODELO DE CARGA (a energia sai da física do celular,
<<<<<<< HEAD
// não de um sensor) e a DIVISÃO POR TEMPO do relé (water-filling).
=======
// não de um sensor) e a DIVISÃO POR TEMPO dos relés (water-filling).
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
// ============================================================================
#pragma once
#include <Arduino.h>

<<<<<<< HEAD
#define FIRMWARE_VERSAO "totem-next-1.1"   // vai no handshake; o painel lê o "totem-next"

// ---------------------------------------------------------------------------
// QUANTAS VAGAS - o único número a mudar quando o hardware mudar
// ---------------------------------------------------------------------------
// 1 = a montagem de 23/10 (um relé, um botão). 4 = o totem de quatro vagas.
// Tem de ser igual ao `--vagas` do backend/preparar_totem.py: o handshake
// imprime "handshake ok: N porta(s)" e N é o do BANCO. Vagas que o backend
// conhece e o firmware não existem para a placa (nenhum relé é tocado).
constexpr uint8_t PORTAS = 1;

// ---------------------------------------------------------------------------
// PINOS - a fiação que já está montada (a mesma do sketch de bancada do
// Gustavo). Índice = número da vaga; a posição 0 não é usada. Com PORTAS = 1
// só a posição 1 é lida: os pinos 12, 14, 27, 33, 25 e 26 ficam livres.
// ---------------------------------------------------------------------------
constexpr uint8_t PINO_RELE[5]  = {0, 13, 12, 14, 27};   // IN1..IN4 do módulo de relé
=======
#define FIRMWARE_VERSAO "totem-next-1.0"   // vai no handshake; o painel lê o "totem-next"

// ---------------------------------------------------------------------------
// PINOS - a fiação que já está montada (a mesma do sketch de bancada do
// Gustavo). Índice = número da vaga; a posição 0 não é usada.
// ---------------------------------------------------------------------------
constexpr uint8_t PINO_RELE[5]  = {0, 13, 12, 14, 27};   // IN1..IN4 do módulo de 4 canais
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
constexpr uint8_t PINO_BOTAO[5] = {0, 32, 33, 25, 26};   // ao GND, com pull-up interno
constexpr uint8_t PINO_LED      = 2;    // LED da placa: aceso = servidor aceitando a placa

constexpr uint8_t PINO_RFID_SS  = 5;    // MFRC522: SCK 18, MISO 19, MOSI 23 (SPI padrão), 3,3 V
constexpr uint8_t PINO_RFID_RST = 4;
constexpr uint8_t PINO_SDA = 21, PINO_SCL = 22;   // LCD
constexpr uint8_t ENDERECO_LCD = 0x27;            // PCF8574 (alguns vêm em 0x3F)

// O módulo da bancada liga com HIGH (o sketch antigo escrevia LOW para
// desligar). Se o seu ligar com LOW (optoacoplador), troque para 1.
<<<<<<< HEAD
// TESTE: com a placa recém-ligada, NENHUM relé pode estalar.
#define RELE_ATIVO_EM_LOW 0
// ATENÇÃO GPIO 12: é pino de boot (MTDI). Se o ESP32 não iniciar com o módulo
// de relé ligado (reinicia em laço, "flash read err"), passe o fio do IN2
// para o GPIO 16 e troque o 12 por 16 acima. (Com PORTAS = 1 o IN2 nem é
// usado: o relé da vaga 1 é o GPIO 13.)

// Bancada SEM módulo de relé ligado: 0 não toca em nenhum pino de relé, e a
// recarga roda só no modelo. Na montagem de verdade isto é 1 - é ele que
// LIBERA A ENERGIA para o celular.
#define USAR_RELE 1

// ---------------------------------------------------------------------------
// DEMONSTRAÇÃO: modelo em time-lapse
// ---------------------------------------------------------------------------
// 1 = tempo real (o certo: a energia cobrada é a que a porta entregou).
// Acima de 1 o MODELO anda mais rápido que o relógio, para o % subir durante
// uma apresentação de 2 minutos. A potência continua a de verdade, mas a
// energia passa a ser uma PROJEÇÃO: não use com dinheiro de verdade em jogo
// nem apresente o valor cobrado como medido.
constexpr float ACELERAR = 1.0f;

// O monitor serial imprime o estado das vagas a cada STATUS_MS (o "painel" da
// placa) e aceita comandos - ver `Totem::lerSerial` em maquina.cpp.
constexpr uint32_t STATUS_MS = 5000;
=======
#define RELE_ATIVO_EM_LOW 0
// ATENÇÃO GPIO 12: é pino de boot (MTDI). Se o ESP32 não iniciar com o módulo
// de relé ligado (reinicia em laço, "flash read err"), passe o fio do IN2
// para o GPIO 16 e troque o 12 por 16 acima.

constexpr uint8_t PORTAS = 4;
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93

// ---------------------------------------------------------------------------
// MODELO DE CARGA (sem sensor): a física do celular, a mesma do contrato
// (docs/contratos/maquina_de_estados_totem.md, seção C, e totem_virtual/fisica.py)
// ---------------------------------------------------------------------------
// Até 80% o celular puxa a potência cheia; cai em linha reta até P_FIM em
// 100%; depois fica na manutenção. A potência cheia é a MENOR entre a do
// celular cadastrado e a da porta (o backend manda as duas, já no bruto).
constexpr float SOC_JOELHO        = 80.0f;
constexpr float P_FIM_FRACAO      = 0.5f / 7.5f;   // 0,5 W de 7,5 W no fim da curva
constexpr float P_MANUTENCAO_W    = 0.10f;         // cheio: o celular quase não puxa
constexpr float EFICIENCIA_CARGA  = 0.92f;         // USB -> bateria (o backend usa a mesma)
constexpr float V_USB             = 5.05f;         // barramento sem carga
constexpr float R_CABO            = 0.04f;         // ohms: a tensão cede com a corrente
constexpr float P_PORTA_MAX_W     = 7.5f;          // 5 V x 1,5 A (USB-A com D+/D-, USB-C com 22k)
// Sem dado do backend ainda (relé ligado por comando antigo): um celular típico.
constexpr float CAPACIDADE_PADRAO_WH = 15.0f;
constexpr float SOC_PADRAO           = 20.0f;

// Energia da TOMADA (derivada, não medida): fonte chaveada 5 V 10 A.
constexpr float EFICIENCIA_FONTE  = 0.85f;         // tomada -> 5 V
constexpr float P_BASE_W          = 0.80f;         // ESP32 com Wi-Fi + LCD + RFID
constexpr float P_BOBINA_RELE_W   = 0.36f;         // ~72 mA por bobina fechada

// ---------------------------------------------------------------------------
// DIVISÃO POR TEMPO (water-filling no relé)
// ---------------------------------------------------------------------------
// O backend manda, por vaga, a fração da janela em que o relé fica fechado
// (`fracao`). As vagas são ESCALONADAS uma depois da outra na janela
// (McNaughton): a qualquer instante a soma das fechadas cabe no limite.
constexpr uint32_t JANELA_MS       = 30000;   // uma volta completa do rodízio
constexpr float    FRACAO_CHEIA    = 0.97f;   // acima disto: sempre fechado (sem estalo à toa)
constexpr uint32_t FATIA_MINIMA_MS = 2000;    // menos que isto fechado não carrega nada

// ---------------------------------------------------------------------------
// Tempos da máquina de estados (iguais a firmware/totem_central/config.h)
// ---------------------------------------------------------------------------
constexpr uint32_t TIMEOUT_ESCOLHA_MS = 15000;   // tempo para apertar o botão da vaga
constexpr uint32_t TELA_MS            = 4000;    // resposta do backend na tela
constexpr uint32_t AVISO_MS           = 2000;    // avisos curtos
constexpr uint32_t MEDICAO_MS         = 200;     // passo do modelo de carga
constexpr uint32_t AMOSTRA_MS         = 2000;    // uma leitura por vaga vai para a fila
constexpr uint32_t ENVIO_MS           = 6000;    // um lote de telemetria
constexpr uint32_t COMANDOS_MS        = 2000;    // o handshake pode trocar
constexpr uint32_t OFFLINE_CORTE_MS   = 120000;  // sem servidor por isto: abre os relés
constexpr uint32_t RETENTATIVA_MIN_MS = 1000;
constexpr uint32_t RETENTATIVA_MAX_MS = 10000;
constexpr uint8_t  RECUSAS_PARA_BLOQUEAR = 3;    // ADR-021
constexpr uint32_t BLOQUEIO_MS        = 60000;
constexpr uint32_t PAGINA_MS          = 2000;    // LCD 16x2: uma página de 2 linhas
constexpr uint32_t ALTERNA_MS         = 3000;    // tela de espera: convite -> quadro -> detalhes
constexpr uint32_t HTTP_TIMEOUT_MS    = 8000;    // a ÚNICA espera que bloqueia (Supabase no Canadá)
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
constexpr size_t   CORPO_MAX_BYTES   = 7000;
constexpr uint16_t FILA_LEITURAS_MAX = 240;

// ---------------------------------------------------------------------------
// LCD 16x2
// ---------------------------------------------------------------------------
constexpr uint8_t COLUNAS = 16, LINHAS = 2;
constexpr uint8_t TELA_MAX_LINHAS = 8;   // 4 linhas de 20 do backend re-quebradas em 16
