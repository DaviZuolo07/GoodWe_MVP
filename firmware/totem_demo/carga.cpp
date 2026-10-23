#include "carga.h"

#include <math.h>

namespace carga {

float Celular::pedida(const Parametros& k) const {
  float cheia = potenciaMaxW;
  if (cheia > k.pPortaMaxW) cheia = k.pPortaMaxW;
  if (cheia <= 0) return 0;
  if (soc >= 100.0f) return k.pManutencaoW;
  if (soc <= k.socJoelho) return cheia;
  float fim = cheia * k.pFimFracao;
  float t = (soc - k.socJoelho) / (100.0f - k.socJoelho);
  return cheia + (fim - cheia) * t;                  // linha reta do joelho até o fim
}

float Celular::avancar(const Parametros& k, float dtS, bool fechado) {
  if (!fechado || dtS <= 0) return 0;
  float p = pedida(k);
  if (capacidadeWh > 0 && soc < 100.0f) {
    float ganhoWh = p * k.eficiencia * dtS / 3600.0f;
    soc += 100.0f * ganhoWh / capacidadeWh;
    if (soc > 100.0f) soc = 100.0f;
  }
  return p;
}

void Celular::sincronizar(float capacidade, float potenciaMax, float percentual, float alvoNovo,
                          float tolerancia) {
  if (capacidade > 0) capacidadeWh = capacidade;
  if (potenciaMax > 0) potenciaMaxW = potenciaMax;
  if (alvoNovo > 0) alvo = alvoNovo;
  if (percentual >= 0 && percentual <= 100 && (!doBackend || fabsf(percentual - soc) > tolerancia))
    soc = percentual;
  doBackend = true;
}

float tensaoNaPorta(const Parametros& k, float potenciaW) {
  if (potenciaW <= 0) return 0;
  return k.vUsb - k.rCabo * (potenciaW / k.vUsb);
}

void escalonar(const float* fracao, uint8_t n, float minima, float cheia,
               Fatia (*fatias)[2], uint8_t* nFatias) {
  // McNaughton: põe as vagas uma atrás da outra numa fita de tamanho 1 que dá
  // a volta. Com frações que somam S, cada instante fica coberto por no máximo
  // teto(S) vagas - é o mesmo limite que o water-filling respeitou.
  float acumulado = 0;
  for (uint8_t p = 1; p <= n; p++) {
    nFatias[p] = 0;
    float f = fracao[p];
    if (f <= 0) continue;
    if (f >= cheia) {                                  // sem divisão: sempre fechado
      fatias[p][0] = {0.0f, 1.0f};
      nFatias[p] = 1;
      continue;
    }
    if (f < minima) f = minima;
    float ini = fmodf(acumulado, 1.0f);
    float fim = ini + f;
    if (fim <= 1.0f) {
      fatias[p][0] = {ini, fim};
      nFatias[p] = 1;
    } else {                                           // passa do fim: continua no começo
      fatias[p][0] = {ini, 1.0f};
      fatias[p][1] = {0.0f, fim - 1.0f};
      nFatias[p] = 2;
    }
    acumulado += f;
  }
}

bool fechadaEm(const Fatia* fatias, uint8_t n, float fase) {
  for (uint8_t i = 0; i < n; i++)
    if (fase >= fatias[i].ini && fase < fatias[i].fim) return true;
  return false;
}

uint8_t picoSimultaneo(Fatia (*fatias)[2], const uint8_t* nFatias, uint8_t n, uint16_t passos) {
  uint8_t pico = 0;
  for (uint16_t i = 0; i < passos; i++) {
    float fase = (i + 0.5f) / passos;
    uint8_t juntos = 0;
    for (uint8_t p = 1; p <= n; p++) juntos += fechadaEm(fatias[p], nFatias[p], fase) ? 1 : 0;
    if (juntos > pico) pico = juntos;
  }
  return pico;
}

}  // namespace carga
