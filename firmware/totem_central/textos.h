// ============================================================================
// textos.h - Tudo que vai para o LCD 16x2 (ADR-022 D3)
// ============================================================================
// Tradução de totem_virtual/lcd.py e das tabelas de totem_virtual/firmware.py.
// O HD44780 não tem acento: todo texto passa por semAcento().
// ============================================================================
#pragma once
#include <Arduino.h>
#include "config.h"

// Uma tela já re-quebrada em 16 colunas, pronta para paginar de 2 em 2.
struct Tela {
  char linha[TELA_MAX_LINHAS][COLUNAS + 1];
  uint8_t n = 0;

  void limpar() { n = 0; }
  // Acrescenta UMA linha de origem (até 20 colunas do backend, ou texto livre),
  // re-quebrada em 16 colunas sem cortar palavra. Linha vazia continua vazia.
  void acrescentar(const char* texto);
  uint8_t paginas() const { return n == 0 ? 1 : (n + LINHAS - 1) / LINHAS; }
  // Linha `i` (0 ou 1) da página `p`; "" se não houver.
  const char* daPagina(uint8_t p, uint8_t i) const;
};

// 'Não' -> 'Nao'. Mesma tabela do Python (gerada de lcd.sem_acento). Fora do ASCII visível vira '?'.
void semAcento(const char* entrada, char* saida, size_t tamanho);

// Linhas que o totem monta quando o backend não manda "tela". {n} já trocado pela vaga.
// Devolve quantas linhas (0 = motivo desconhecido).
uint8_t telaDoMotivo(const char* motivo, uint8_t vaga, Tela& tela);

// Recusa de autenticação (ADR-021): texto do LCD e diagnóstico para o serial.
const char* telaDaRecusa(const char* codigo);
const char* diagnosticoDaRecusa(const char* codigo);
