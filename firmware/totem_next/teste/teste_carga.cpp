// ============================================================================
// teste_carga.cpp - Testa no PC o modelo de carga e a divisão por tempo
// ============================================================================
// Fica numa subpasta de propósito: a IDE do Arduino só compila a raiz do
// sketch, e este arquivo tem main().
//
//   g++ -std=c++17 -O2 -o teste_carga teste/teste_carga.cpp carga.cpp && ./teste_carga
//
// Os números do modelo são os de config.h (copiados aqui para não puxar o
// Arduino.h). Mudou lá, mude aqui.
// ============================================================================
#include <math.h>
#include <stdio.h>

#include "../carga.h"

static const carga::Parametros K = {80.0f, 0.5f / 7.5f, 0.10f, 0.92f, 5.05f, 0.04f, 7.5f};
static int falhas = 0;

#define CONFERE(cond, ...)                                       \
  do {                                                           \
    if (!(cond)) { printf("FALHOU: " __VA_ARGS__); printf("\n"); falhas++; } \
  } while (0)

static void curva_do_contrato() {
  carga::Celular c;
  c.potenciaMaxW = 27;                          // celular de 27 W numa porta de 7,5 W
  c.soc = 50;
  CONFERE(fabsf(c.pedida(K) - 7.5f) < 1e-4, "a porta limita a 7,5 W");
  c.soc = 90;
  CONFERE(fabsf(c.pedida(K) - 4.0f) < 1e-3, "no meio da queda (90%%): 4,0 W, deu %.3f", c.pedida(K));
  c.soc = 100;
  CONFERE(fabsf(c.pedida(K) - 0.10f) < 1e-4, "cheio: manutenção 0,1 W");
  c.potenciaMaxW = 5; c.soc = 30;
  CONFERE(fabsf(c.pedida(K) - 5.0f) < 1e-4, "celular de 5 W puxa 5 W");
}

static void energia_e_percentual() {
  // 15 Wh, de 20% a 80% a 7,5 W: 9 Wh na bateria = 9 / 0,92 = 9,78 Wh no USB
  // = 9,78 / 7,5 h = 4696 s (1 h 18 min: um celular de verdade, não um atalho).
  carga::Celular c;
  c.capacidadeWh = 15; c.potenciaMaxW = 7.5; c.soc = 20;
  double energia = 0;
  float t = 0;
  while (c.soc < 80.0f && t < 10000) { energia += c.avancar(K, 0.2f, true) * 0.2 / 3600.0; t += 0.2f; }
  CONFERE(fabs(energia - 9.0 / 0.92) < 0.01, "energia no USB até 80%%: %.4f Wh", energia);
  CONFERE(fabsf(t - 4695.7f) < 2.0f, "tempo até 80%%: %.1f s", t);
  float antes = c.soc;
  CONFERE(c.avancar(K, 10, false) == 0 && c.soc == antes, "relé aberto: nada entra");
  while (c.soc < 100.0f && t < 20000) { c.avancar(K, 0.2f, true); t += 0.2f; }
  CONFERE(c.soc == 100.0f && c.avancar(K, 1, true) < 0.5f, "cheio: abaixo de 0,5 W (o backend encerra)");
}

static void sincronizar() {
  carga::Celular c;
  c.sincronizar(18.5f, 7.5f, 42.0f, 90.0f);
  CONFERE(c.doBackend && c.soc == 42.0f && c.capacidadeWh == 18.5f, "primeiro dado do backend vale");
  c.soc = 42.6f;
  c.sincronizar(18.5f, 7.5f, 42.0f, 90.0f);
  CONFERE(c.soc == 42.6f, "diferença pequena: o modelo segue (sem pulo)");
  c.sincronizar(18.5f, 7.5f, 55.0f, 90.0f);
  CONFERE(c.soc == 55.0f, "o %% do celular corrige o modelo");
}

static void divisao(const char* nome, const float* f, uint8_t picoEsperado, uint8_t vagas = 4) {
  carga::Fatia fatias[5][2];
  uint8_t n[5];
  carga::escalonar(f, vagas, 2000.0f / 30000.0f, 0.97f, fatias, n);
  for (uint8_t p = 1; p <= vagas; p++) {
    float soma = 0;
    for (uint8_t i = 0; i < n[p]; i++) soma += fatias[p][i].fim - fatias[p][i].ini;
    float alvo = f[p] >= 0.97f ? 1.0f : f[p] <= 0 ? 0.0f : (f[p] < 2.0f / 30 ? 2.0f / 30 : f[p]);
    CONFERE(fabsf(soma - alvo) < 1e-4, "%s: vaga %u fica %.3f da janela (queria %.3f)", nome, p, soma, alvo);
  }
  uint8_t pico = carga::picoSimultaneo(fatias, n, vagas);
  CONFERE(pico == picoEsperado, "%s: pico de %u vagas juntas (esperado %u)", nome, pico, picoEsperado);
  printf("  %-26s pico %u |", nome, pico);
  for (uint8_t p = 1; p <= vagas; p++) {
    printf(" %u:", p);
    for (uint8_t i = 0; i < n[p]; i++) printf("[%.2f-%.2f)", fatias[p][i].ini, fatias[p][i].fim);
  }
  printf("\n");
}

int main() {
  curva_do_contrato();
  energia_e_percentual();
  sincronizar();
  printf("Divisão por tempo (janela = 1):\n");
  const float sem_limite[5] = {0, 1, 1, 1, 1};
  const float tres_de_quatro[5] = {0, 0.75f, 0.75f, 0.75f, 0.75f};   // quadro para 3 celulares
  const float ponta[5] = {0, 0.5f, 0.5f, 0.5f, 0.5f};                // ponta: limite pela metade
  const float duas_vagas[5] = {0, 0.5f, 0, 0.5f, 0};                 // 1 celular cheio, 2 dividindo
  const float desigual[5] = {0, 1.0f, 0.4f, 0.3f, 0.3f};             // um no fim da curva pede menos
  divisao("sem limite", sem_limite, 4);
  divisao("limite para 3 (75%)", tres_de_quatro, 3);
  divisao("ponta (50%)", ponta, 2);
  divisao("2 vagas, 1 cheio (50%)", duas_vagas, 1);
  divisao("frações diferentes", desigual, 2);

  // UMA VAGA (a montagem de 23/10). O water-filling de um ponto só é o teto
  // do estande: fração 1 = relé fechado direto; 0,5 = 15 s de cada 30 s.
  printf("Uma vaga (PORTAS = 1):\n");
  const float so_uma[5] = {0, 1.0f, 0, 0, 0};
  const float so_uma_ponta[5] = {0, 0.5f, 0, 0, 0};
  const float so_uma_migalha[5] = {0, 0.01f, 0, 0, 0};   // abaixo da fatia mínima
  divisao("uma vaga, sem limite", so_uma, 1, 1);
  divisao("uma vaga, ponta (50%)", so_uma_ponta, 1, 1);
  divisao("uma vaga, fatia minima", so_uma_migalha, 1, 1);

  printf(falhas ? "\n%d FALHA(S)\n" : "\nTUDO PASSOU\n", falhas);
  return falhas ? 1 : 0;
}
