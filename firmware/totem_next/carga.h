// ============================================================================
// carga.h - Modelo de carga do celular e divisão por tempo dos relés
// ============================================================================
// O totem Next NÃO tem sensor de corrente. O que ele sabe de verdade:
//   - QUANDO cada relé está fechado (é ele quem fecha);
//   - QUAL celular está na vaga (o backend manda: bateria em Wh, potência
//     máxima em W, o % de partida e o alvo).
// Com isso a energia sai da FÍSICA da recarga, passo a passo (MEDICAO_MS):
//   potência = curva do celular no % atual   (CC até 80%, cai até 100%)
//   energia += potência x tempo com o relé FECHADO
//   %       += energia x eficiência / bateria
// É um modelo, não uma medida, e é declarado assim: o backend grava tudo com
// origem 'simulado'. O % lido do próprio celular (app no Chrome do Android)
// volta pelo backend e corrige o modelo (`sincronizar`).
//
// A DIVISÃO POR TEMPO é o water-filling executado num relé que só liga e
// desliga: o backend diz a fração da janela de cada vaga e `escalonar` monta
// o rodízio (McNaughton) - as vagas uma depois da outra, dando a volta na
// janela. Assim, a qualquer instante, a soma das vagas fechadas cabe no limite.
//
// Arquivo sem Arduino.h de propósito: compila e é testado no PC
// (teste_carga.cpp, `g++ -std=c++17 teste_carga.cpp carga.cpp`).
// ============================================================================
#pragma once
#include <stdint.h>

namespace carga {

// Parâmetros (os valores reais ficam em config.h; o teste usa os mesmos).
struct Parametros {
  float socJoelho, pFimFracao, pManutencaoW, eficiencia, vUsb, rCabo, pPortaMaxW;
};

class Celular {
 public:
  float capacidadeWh = 15.0f;   // bateria (Wh, bruto da maquete)
  float potenciaMaxW = 7.5f;    // menor entre o celular e a porta
  float soc = 20.0f;            // % do MODELO
  float alvo = 100.0f;
  bool doBackend = false;       // false = valores padrão (sem dado ainda)

  // W que o celular pede neste % (a curva do contrato, escalada pela potência cheia).
  float pedida(const Parametros& k) const;
  // Avança `dtS` segundos. Relé fechado: devolve a potência entregue e soma
  // energia/%; relé aberto: devolve 0 e nada muda.
  float avancar(const Parametros& k, float dtS, bool fechado);
  // O backend é a fonte de verdade do %: sincroniza quando ele diverge mais
  // que `tolerancia` (o % lido do celular chega por aqui).
  void sincronizar(float capacidade, float potenciaMax, float percentual, float alvoNovo,
                   float tolerancia = 1.0f);
};

// Tensão no conector com a corrente do momento (o cabo cede um pouco).
float tensaoNaPorta(const Parametros& k, float potenciaW);

// --- Divisão por tempo --------------------------------------------------------
struct Fatia { float ini = 0, fim = 0; };   // em fração da janela, [ini, fim)

// `fracao[p]` para p = 1..n (0 = vaga sem recarga). Escreve até 2 fatias por
// vaga (a que dá a volta na janela vira duas). `minima` = menor fração útil
// (fatia curta demais não carrega: sobe para ela). `cheia` = acima disto,
// sempre fechado.
void escalonar(const float* fracao, uint8_t n, float minima, float cheia,
               Fatia (*fatias)[2], uint8_t* nFatias);

// A vaga está numa fatia fechada neste ponto da janela (0 <= fase < 1)?
bool fechadaEm(const Fatia* fatias, uint8_t n, float fase);

// Quantas vagas ficam fechadas ao mesmo tempo no pior instante (teste).
uint8_t picoSimultaneo(Fatia (*fatias)[2], const uint8_t* nFatias, uint8_t n, uint16_t passos = 1000);

}  // namespace carga
