#include "maquina.h"

#include <WiFi.h>
#include <ctype.h>
#include <stdarg.h>
#include <stdlib.h>

#include "segredos.h"

// ---------------------------------------------------------------------------
// Ferramentas
// ---------------------------------------------------------------------------

// a < b à prova da volta do millis() (49 dias): nunca compare marcas com "<".
static inline bool antes(uint32_t a, uint32_t b) { return (int32_t)(a - b) < 0; }

static const char* const NOME_ESTADO[] = {"livre", "aguardando_energia", "carregando", "pausada",
                                          "completa_tolerancia", "completa_taxa"};
static const char* const ROTULO[] = {"LIVRE", "FILA", "CARGA", "PAUSA", "CHEIO", "TAXA"};

// Os números do modelo de carga (config.h), num só lugar para carga.cpp.
static const carga::Parametros FISICA = {SOC_JOELHO, P_FIM_FRACAO, P_MANUTENCAO_W, EFICIENCIA_CARGA,
                                         V_USB, R_CABO, P_PORTA_MAX_W};

static EstadoVaga estadoDoTexto(const char* s) {
  if (!s) return DESCONHECIDO;
  for (int8_t i = 0; i < 6; i++)
    if (strcmp(s, NOME_ESTADO[i]) == 0) return (EstadoVaga)i;
  return DESCONHECIDO;
}

static bool ehLigar(const char* a) { return strcmp(a, "ligar") == 0 || strcmp(a, "liberar") == 0; }
static bool ehDesligar(const char* a) { return strcmp(a, "desligar") == 0 || strcmp(a, "bloquear") == 0; }

// sessao_id ausente, null ou "" = não veio
static const char* sessaoDe(JsonVariantConst v) {
  const char* s = v.as<const char*>();
  return (s && *s) ? s : nullptr;
}

// O campo "tela" do contrato: lista de 1 a 4 textos.
static bool telaValida(JsonVariantConst t) {
  if (!t.is<JsonArrayConst>()) return false;
  JsonArrayConst a = t.as<JsonArrayConst>();
  if (a.size() == 0 || a.size() > 4) return false;
  for (JsonVariantConst x : a)
    if (!x.is<const char*>()) return false;
  return true;
}

static uint32_t hashTela(JsonArrayConst a) {   // FNV-1a: só para saber se a tela mudou
  uint32_t h = 2166136261u;
  for (JsonVariantConst x : a) {
    for (const char* c = x.as<const char*>(); *c; c++) { h ^= (uint8_t)*c; h *= 16777619u; }
    h ^= 0xFF; h *= 16777619u;
  }
  return h;
}

void Totem::evento(const char* formato, ...) {
  char texto[480];
  va_list args;
  va_start(args, formato);
  vsnprintf(texto, sizeof(texto), formato, args);
  va_end(args);
  Serial.printf("[%9lu ms] %s\n", (unsigned long)millis(), texto);
}

// ===========================================================================
// setup() e loop()
// ===========================================================================

void Totem::setup() {
  hal::iniciar();                                 // todo relé ABERTO
  uint32_t agora = millis();
  for (uint8_t p = 1; p <= PORTAS; p++) { vagas_[p] = Vaga(); vagas_[p].porta = p; }

  ui_ = INICIANDO; tUi_ = agora; duracaoTela_ = 0;
  uid_[0] = '\0';
  link_ = SEM_HORA; handshakeFeito_ = false;
  proximaTentativa_ = agora; esperaMs_ = RETENTATIVA_MIN_MS;
  offline_ = false; wifiEstavaOk_ = true; cortouOffline_ = false;
  recusa_[0] = '\0'; recusasSeguidas_ = 0; bloqueado_ = false; reconciliouAlguma_ = false;
  tMedicao_ = tAmostra_ = tEnvio_ = tComandos_ = tJanela_ = agora;
  comandosMs_ = COMANDOS_MS; loteMax_ = MAX_LEITURAS_LOTE; drenando_ = false;
  assinatura_ = 0;

  if (!enlace_.iniciar(DEVICE_ID, DEVICE_KEY_HEX, BACKEND_URL)) {
    strncpy(recusa_, "assinatura_invalida", sizeof(recusa_));   // LCD: "Chave invalida"
    configOk_ = false;
    evento("DEVICE_KEY_HEX de segredos.h nao tem 64 caracteres hexadecimais: corrija e grave de novo");
  }
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  evento("placa ligou: reles abertos (boot %lu, firmware %s, sem sensor: modelo de carga)",
         (unsigned long)enlace_.boot(), FIRMWARE_VERSAO);
  evento("%u vaga(s) neste firmware%s%s", (unsigned)PORTAS,
         USAR_RELE ? "" : " | SEM RELE (modelo apenas)",
         ACELERAR > 1.0f ? " | MODELO ACELERADO: energia e projecao, nao medida" : "");
  if (hal::lcdEndereco()) evento("LCD 16x2 em 0x%02X", hal::lcdEndereco());
  else evento("LCD nao encontrado (0x27 nem 0x3F): seguindo sem tela, o serial e a tela");
  evento("monitor serial (Nova linha): t <UID> = tag | b [vaga] = botao | s = status");
}

void Totem::loop() {
  uint32_t agora = millis();
  rede(agora);
  interface(agora);
  divisao(agora);
  medir(agora);
  telemetria(agora);
  comandos(agora);
  travaOffline(agora);
  statusSerial(agora);
  desenhar(agora);
  hal::led(online());
}

// ===========================================================================
// Enlace: hora -> handshake -> pronto, com nova tentativa espaçada
// ===========================================================================

bool Totem::online() const { return link_ == PRONTO && !offline_ && hal::wifiOk(); }

void Totem::sucesso() {
  if (offline_) evento("servidor voltou a responder");
  offline_ = false;
  esperaMs_ = RETENTATIVA_MIN_MS;
  if (bloqueado_) evento("servidor voltou a aceitar a placa");
  recusa_[0] = '\0'; recusasSeguidas_ = 0; bloqueado_ = false;
}

void Totem::esperarMais(uint32_t agora) {
  proximaTentativa_ = agora + esperaMs_;
  esperaMs_ = min(RETENTATIVA_MAX_MS, esperaMs_ * 2);
}

void Totem::falha(uint32_t agora) {
  if (!offline_) { offline_ = true; offlineDesde_ = agora; evento("sem resposta do servidor"); }
  esperarMais(agora);
}

void Totem::recusado(const char* codigo, uint32_t agora) {
  // Servidor que não aceita a placa = servidor que não acompanha a recarga (ADR-021 D2).
  if (!offline_) { offline_ = true; offlineDesde_ = agora; }
  if (strcmp(codigo, recusa_) == 0) { if (recusasSeguidas_ < 250) recusasSeguidas_++; }
  else { recusasSeguidas_ = 1; strncpy(recusa_, codigo, sizeof(recusa_) - 1); recusa_[sizeof(recusa_) - 1] = '\0'; }
  if (strcmp(codigo, "fora_da_janela") == 0) link_ = SEM_HORA;   // o relógio da placa pode ter derivado
  if (recusasSeguidas_ < RECUSAS_PARA_BLOQUEAR) {
    evento("recusado (%s): tentativa %u", codigo, recusasSeguidas_);
    esperarMais(agora);
    return;
  }
  proximaTentativa_ = agora + BLOQUEIO_MS;
  if (recusasSeguidas_ == RECUSAS_PARA_BLOQUEAR) {
    bloqueado_ = true;
    evento("BLOQUEADO (%s): %s", codigo, diagnosticoDaRecusa(codigo));
  }
}

bool Totem::tratar(const Resposta& r, uint32_t agora) {
  if (!r.chegou) { falha(agora); return false; }
  if (r.status == 401 && (r.codigo == "assinatura_invalida" || r.codigo == "fora_da_janela")) {
    recusado(r.codigo.c_str(), agora);
    return false;
  }
  sucesso();
  if (r.status == 200) return true;
  if (r.codigo == "boot_desconhecido") {
    link_ = SEM_HANDSHAKE;
  } else if (r.codigo == "replay") {
    enlace_.novoBoot();                           // numeração fora de sincronia
    link_ = SEM_HANDSHAKE;
    evento("replay: boot novo e handshake");
  }
  return false;
}

void Totem::rede(uint32_t agora) {
  if (!configOk_) return;
  if (!hal::wifiOk()) {
    if (!offline_) { offline_ = true; offlineDesde_ = agora; evento("Wi-Fi caiu"); }
    wifiEstavaOk_ = false;
    return;
  }
  if (!wifiEstavaOk_) {                           // voltou agora: tenta já
    wifiEstavaOk_ = true;
    proximaTentativa_ = agora;
    esperaMs_ = RETENTATIVA_MIN_MS;
    evento("Wi-Fi voltou (%s)", WiFi.localIP().toString().c_str());
  }
  if (link_ == PRONTO || antes(agora, proximaTentativa_)) return;

  if (link_ == SEM_HORA) {
    Resposta r = enlace_.acertarRelogio();
    if (!r.ok()) { falha(agora); return; }
    link_ = handshakeFeito_ ? PRONTO : SEM_HANDSHAKE;
    // /hora é pública: responder não prova que o servidor aceita a placa.
    if (link_ == PRONTO && !recusa_[0]) sucesso();
    return;
  }

  Resposta r = enlace_.handshake(FIRMWARE_VERSAO);
  if (tratar(r, agora)) {
    aplicarHandshake(r.dados.as<JsonVariantConst>(), agora);
    link_ = PRONTO; handshakeFeito_ = true;
    cortouOffline_ = false;
  } else if (r.chegou && link_ == SEM_HANDSHAKE && antes(proximaTentativa_, agora + RETENTATIVA_MIN_MS)) {
    proximaTentativa_ = agora + RETENTATIVA_MIN_MS;
  }
}

void Totem::aplicarHandshake(JsonVariantConst dados, uint32_t agora) {
  // Reconcilia cada vaga com o que o servidor diz que deveria estar acontecendo.
  float intervalo = dados["intervalo_comandos_s"] | 0.0f;
  if (intervalo > 0) comandosMs_ = (uint32_t)(intervalo * 1000);
  int maxLote = dados["max_leituras_lote"] | 0;
  if (maxLote > 0) loteMax_ = min<int>(MAX_LEITURAS_LOTE, maxLote);
  for (uint8_t p = 1; p <= PORTAS; p++) vagas_[p].existe = false;
  uint8_t n = 0, usadas = 0;
  for (JsonVariantConst p : dados["portas"].as<JsonArrayConst>()) {
    n++;
    uint8_t porta = p["porta"] | 0;
    if (porta < 1 || porta > PORTAS) continue;
    usadas++;
    Vaga& v = vagas_[porta];
    v.existe = true;
    v.divergente = false;
    JsonVariantConst ativa = p["sessao_ativa"];
    if (p["rele_esperado"] | false) {
      ligar(v, sessaoDe(ativa["sessao_id"]), "handshake", agora, ativa["energia_wh"] | 0.0);
      modeloDoBackend(v, ativa);                  // reboot: o mesmo celular, do % de agora
    } else {
      desligar(v, "handshake", agora);
    }
    EstadoVaga e = estadoDoTexto(p["estado"] | "");
    if (e != DESCONHECIDO) mudarEstado(v, e, agora);
    pedido(v, p["pedido"], agora);
  }
  evento("handshake ok: %u porta(s) no backend, %u nesta placa", n, usadas);
  // Os dois números têm de bater. Backend com mais portas que o firmware = vaga
  // que o painel mostra e nenhum relé atende: rode preparar_totem.py --vagas N.
  if (n != PORTAS)
    evento("ATENCAO: o backend tem %u porta(s) e este firmware tem PORTAS = %u "
           "(backend/preparar_totem.py --vagas %u, ou mude o PORTAS em config.h)",
           n, (unsigned)PORTAS, (unsigned)PORTAS);
}

// ===========================================================================
// Vaga: liberar, cortar e o modelo do celular
// ===========================================================================

void Totem::mudarEstado(Vaga& v, EstadoVaga e, uint32_t agora, bool doBackend) {
  if (e != v.estado) { v.estado = e; v.tEstadoMs = agora; }
  v.estadoDoBackend = doBackend;
  // Só o BACKEND encerra a sessão. Um desligar pode ser pausa: se a mesma
  // sessão voltar, o contador de energia continua.
  if (doBackend && e == LIVRE && !v.rele) v.sessaoId[0] = '\0';
}

void Totem::ligar(Vaga& v, const char* sessaoId, const char* origem, uint32_t agora, double energiaWh) {
  bool nova = (sessaoId && strcmp(sessaoId, v.sessaoId) != 0) || (!sessaoId && !v.sessaoId[0] && !v.rele);
  if (nova) {                                     // sessão nova: contador e modelo do zero
    v.energiaWh = 0;
    v.celular = carga::Celular();
    v.celular.capacidadeWh = CAPACIDADE_PADRAO_WH;
    v.celular.soc = SOC_PADRAO;
    v.fracao = 1.0f;
    v.tempoMin = -1;
  }
  if (sessaoId) { strncpy(v.sessaoId, sessaoId, sizeof(v.sessaoId) - 1); v.sessaoId[sizeof(v.sessaoId) - 1] = '\0'; }
  if (energiaWh >= 0) v.energiaWh = max(v.energiaWh, energiaWh);   // reboot: continua de onde parou
  v.temPedido = false;
  v.divergente = false;
  if (!v.rele) {
    v.rele = true;                                // o contato fecha no rodízio (divisao)
    evento("vaga %u LIBERADA (%s)", v.porta, origem);
  }
  if (!v.estadoDoBackend || v.estado == LIVRE) mudarEstado(v, CARREGANDO, agora, false);
}

void Totem::desligar(Vaga& v, const char* origem, uint32_t agora) {
  if (v.rele || v.fechado) {
    hal::rele(v.porta, false);                    // corta JÁ, sem esperar o rodízio
    v.fechado = false;
    v.rele = false;
    evento("vaga %u CORTADA (%s)", v.porta, origem);
  }
  if (!v.estadoDoBackend || v.estado == CARREGANDO) mudarEstado(v, LIVRE, agora, false);
}

void Totem::pedido(Vaga& v, JsonVariantConst p, uint32_t agora) {
  if (p.isNull() || (p.is<JsonObjectConst>() && p.size() == 0)) { v.temPedido = false; return; }
  float segundos = p["segundos_para_aproximar"] | 0.0f;
  if (segundos <= 0) segundos = 120;
  v.temPedido = true;
  v.pedidoAteMs = agora + (uint32_t)(segundos * 1000);
}

void Totem::modeloDoBackend(Vaga& v, JsonVariantConst o) {
  // `fracao`: quanto da janela esta vaga fica fechada (water-filling).
  // `carga`: o celular cadastrado (Wh, W) e o % que o backend considera -
  // inclusive o % lido do próprio celular, que corrige o modelo.
  if (o.isNull()) return;
  JsonVariantConst f = o["fracao"];
  if (f.is<float>()) v.fracao = constrain(f.as<float>(), 0.0f, 1.0f);
  JsonVariantConst c = o["carga"];
  if (c.is<JsonObjectConst>()) {
    bool novo = !v.celular.doBackend;
    v.celular.sincronizar(c["capacidade_wh"] | 0.0f, c["potencia_max_w"] | 0.0f,
                          c["percentual"] | -1.0f, c["alvo"] | 0.0f);
    if (novo)
      evento("vaga %u: celular de %.1f Wh, ate %.1f W, partindo de %.0f%% (modelo)", v.porta,
             v.celular.capacidadeWh, v.celular.potenciaMaxW, v.celular.soc);
  }
  JsonVariantConst t = o["tempo_restante_min"];
  if (t.is<int>()) v.tempoMin = t.as<int>();
}

// ===========================================================================
// Interface: tag -> botão da vaga -> POST /v2/rfid -> tela
// ===========================================================================

void Totem::mostrar(uint32_t agora, uint32_t duracaoMs) {
  // tela_ já preenchida (re-quebrada em 16 colunas); pagina de 2 em 2 linhas.
  ui_ = MOSTRA_TELA;
  tUi_ = agora;
  duracaoTela_ = max(duracaoMs, (uint32_t)tela_.paginas() * PAGINA_MS);
}

void Totem::mostrarLinhas(const char* l0, const char* l1, uint32_t agora, uint32_t duracaoMs) {
  tela_.limpar();
  tela_.acrescentar(l0);
  if (l1) tela_.acrescentar(l1);
  mostrar(agora, duracaoMs);
}

void Totem::interface(uint32_t agora) {
  char tag[33];
  bool temTag = hal::tagLida(tag, sizeof(tag));
  uint8_t botao = hal::botao();
  lerSerial(tag, sizeof(tag), temTag, botao);   // plano B: tag e botão pelo computador

  if (ui_ == INICIANDO) {
    if (link_ != PRONTO) return;                  // ainda sem servidor: ignora tag e botão
    ui_ = AGUARDANDO_TAG; tUi_ = agora;
  }
  if (temTag) {                                   // vale em qualquer tela: a pessoa não espera
    strncpy(uid_, tag, sizeof(uid_));
    ui_ = ESCOLHA_VAGA; tUi_ = agora;
    evento("tag %s: escolha a vaga", uid_);
    return;
  }
  if (ui_ == ESCOLHA_VAGA) {
    if (botao) {
      enviarTag(botao, agora);
    } else if (agora - tUi_ >= TIMEOUT_ESCOLHA_MS) {
      uid_[0] = '\0';
      evento("timeout na escolha da vaga");
      mostrarLinhas("Tempo esgotado", "Aproxime de novo", agora, AVISO_MS);   // NÃO chama o backend
    }
  } else if (botao && ui_ == AGUARDANDO_TAG) {
    mostrarLinhas("Aproxime o", "cartao primeiro", agora, AVISO_MS);
  } else if (ui_ == MOSTRA_TELA && agora - tUi_ >= duracaoTela_) {
    ui_ = AGUARDANDO_TAG; tUi_ = agora;
  }
}

void Totem::enviarTag(uint8_t porta, uint32_t agora) {
  char uid[33];
  strncpy(uid, uid_, sizeof(uid));
  uid_[0] = '\0';
  Vaga& v = vagas_[porta];
  // Sem servidor NÃO guarda para depois: iniciar recarga minutos mais tarde,
  // sem ninguém na frente do totem, seria pior que recusar.
  if (link_ != PRONTO || !hal::wifiOk()) { mostrarLinhas("Sem conexao", "Tente de novo", agora); return; }

  Resposta r = enlace_.rfid(porta, uid);
  if (!tratar(r, agora)) {
    if (!r.chegou) {
      mostrarLinhas("Sem conexao", "Tente de novo", agora);
    } else if (r.status == 422) {
      char l0[COLUNAS + 1];
      snprintf(l0, sizeof(l0), "Vaga %u", porta);
      mostrarLinhas(l0, "indisponivel", agora);
    } else {
      mostrarLinhas("Nao deu certo", "Aproxime de novo", agora);
    }
    return;
  }

  JsonVariantConst d = r.dados.as<JsonVariantConst>();
  const char* acao = d["acao"] | "";
  if (ehLigar(acao)) {
    ligar(v, sessaoDe(d["sessao_id"]), "rfid", agora);
    modeloDoBackend(v, d);                        // o celular e a fração já vêm na resposta
  } else if (ehDesligar(acao)) {
    desligar(v, "rfid", agora);
  }
  // "nenhuma" ou ausente: não mexe no relé (autorizado SOZINHO não fecha: pode ser fila de energia)

  bool autorizado = d["autorizado"] | false;
  const char* motivo = d["motivo"] | "";
  evento("rfid vaga %u: %s / %s", porta, motivo, acao);
  if (telaValida(d["tela"])) {
    tela_.limpar();
    for (JsonVariantConst x : d["tela"].as<JsonArrayConst>()) tela_.acrescentar(x.as<const char*>());
  } else {
    if (!*motivo) motivo = autorizado ? "confirmada_app" : "";
    if (!telaDoMotivo(motivo, porta, tela_)) {
      tela_.limpar();
      tela_.acrescentar(d["mensagem"] | (autorizado ? "Liberado" : "Nao autorizado"));
      if (tela_.n > 4) tela_.n = 4;
    }
  }
  // Tag que ninguém cadastrou: mostra o UID para a pessoa vincular no app.
  if (strcmp(motivo, "cartao_nao_cadastrado") == 0) {
    char l[COLUNAS + 1];
    snprintf(l, sizeof(l), "Tag %.12s", uid);      // 4 bytes = 8 hexa; 7 bytes = 14 (corta)
    tela_.acrescentar(l);
  }
  mostrar(agora);
}

// ===========================================================================
// Divisão por tempo: o water-filling executado no relé (o FOCO do Next)
// ===========================================================================
// O backend reparte o limite do estande entre as vagas (água no balde) e diz
// a fração de cada uma. Aqui a fração vira TEMPO de relé fechado numa janela
// de JANELA_MS, com as vagas escalonadas uma depois da outra (McNaughton).
// Ex.: limite para 3 celulares, 4 carregando -> 75% para cada; em todo
// instante 3 relés fechados e 1 aberto, e o aberto vai rodando.
// O rodízio é remontado a cada janela, ou na hora se uma vaga entra ou sai.

void Totem::divisao(uint32_t agora) {
  uint8_t liberadas = 0;
  for (uint8_t p = 1; p <= PORTAS; p++) if (vagas_[p].rele) liberadas |= (1 << p);

  bool virou = agora - tJanela_ >= JANELA_MS;
  if (virou) tJanela_ = (agora - tJanela_ >= 2 * JANELA_MS) ? agora : tJanela_ + JANELA_MS;
  if (virou || liberadas != assinatura_) {
    float fr[PORTAS + 1] = {0};
    for (uint8_t p = 1; p <= PORTAS; p++) fr[p] = vagas_[p].rele ? vagas_[p].fracao : 0.0f;
    carga::escalonar(fr, PORTAS, (float)FATIA_MINIMA_MS / JANELA_MS, FRACAO_CHEIA, fatias_, nFatias_);
    bool mudou = liberadas != assinatura_;
    for (uint8_t p = 1; p <= PORTAS; p++) {
      if (fabsf(fr[p] - fracoesMontadas_[p]) > 0.005f) mudou = true;
      fracoesMontadas_[p] = fr[p];
    }
    assinatura_ = liberadas;
    if (mudou) {
      char resumo[64];
      size_t j = 0;
      for (uint8_t p = 1; p <= PORTAS; p++)
        j += snprintf(resumo + j, sizeof(resumo) - j, " %u:%.0f%%", p, fr[p] * 100.0f);
      evento("divisao por tempo (janela %lus):%s", (unsigned long)(JANELA_MS / 1000), resumo);
    }
  }

  float fase = (float)((agora - tJanela_) % JANELA_MS) / JANELA_MS;
  for (uint8_t p = 1; p <= PORTAS; p++) {
    Vaga& v = vagas_[p];
    bool quer = v.rele && carga::fechadaEm(fatias_[p], nFatias_[p], fase);
    if (quer != v.fechado) {
      hal::rele(p, quer);
      v.fechado = quer;
    }
  }
}

// ===========================================================================
// Modelo de carga: a energia de cada vaga, sem sensor
// ===========================================================================

void Totem::medir(uint32_t agora) {
  uint32_t dt = agora - tMedicao_;
  if (dt < MEDICAO_MS) return;
  tMedicao_ = agora;
  float dtS = dt / 1000.0f;
  float usbW = 0;
  uint8_t bobinas = 0;
  for (uint8_t p = 1; p <= PORTAS; p++) {
    Vaga& v = vagas_[p];
    // ACELERAR = 1 em operação: o modelo anda com o relógio. Acima disso é
    // time-lapse de demonstração (config.h), e a energia vira projeção.
    float dtModelo = dtS * ACELERAR;
    float w = v.celular.avancar(FISICA, dtModelo, v.fechado);   // 0 com o contato aberto
    v.potenciaW = w;
    v.tensaoV = carga::tensaoNaPorta(FISICA, w);
    v.correnteA = v.tensaoV > 0.1f ? w / v.tensaoV : 0.0f;
    if (v.fechado) { v.energiaWh += w * dtModelo / 3600.0; usbW += w; bobinas++; }
    if (v.temPedido && !antes(agora, v.pedidoAteMs)) v.temPedido = false;
  }
  // Da TOMADA (derivado): o USB passa pela fonte de 5 V, mais a placa e as bobinas.
  tomadaW_ = usbW / EFICIENCIA_FONTE + P_BASE_W + bobinas * P_BOBINA_RELE_W;
  tomadaWh_ += tomadaW_ * dtS * ACELERAR / 3600.0;

  if (agora - tAmostra_ < AMOSTRA_MS) return;
  tAmostra_ = agora;
  for (uint8_t p = 1; p <= PORTAS; p++) {
    const Vaga& v = vagas_[p];
    if (!v.existe) continue;
    if (filaLeituras_.cheia()) descartadas_++;    // a mais antiga sai; a energia é acumulada
    filaLeituras_.empurra({v.porta, v.fechado, agora, v.potenciaW, (float)v.energiaWh,
                           v.tensaoV, v.correnteA});
  }
}

// ===========================================================================
// Telemetria em lote
// ===========================================================================

String Totem::montarLote(uint32_t agora, uint16_t& n) {
  n = min<uint16_t>(filaLeituras_.tamanho(), loteMax_);
  while (true) {
    JsonDocument doc;
    doc["t_envio_ms"] = agora;
    JsonArray leituras = doc["leituras"].to<JsonArray>();
    for (uint16_t i = 0; i < n; i++) {
      const Leitura& x = filaLeituras_[i];
      JsonObject o = leituras.add<JsonObject>();
      o["porta"] = x.porta;
      o["t_ms"] = x.tMs;
      o["potencia_w"] = serialized(String(x.potenciaW, 3));
      o["energia_wh"] = serialized(String(x.energiaWh, 4));
      o["tensao_v"] = serialized(String(x.tensaoV, 3));
      o["corrente_a"] = serialized(String(x.correnteA, 4));
      o["rele_ligado"] = x.fechado;               // o CONTATO: aberto pelo rodízio = false
    }
    String corpo;
    serializeJson(doc, corpo);
    if (corpo.length() <= CORPO_MAX_BYTES || n <= 1) return corpo;
    n = max<uint16_t>(1, n * 3 / 4);
  }
}

void Totem::telemetria(uint32_t agora) {
  if (filaLeituras_.vazia() || link_ != PRONTO || !hal::wifiOk()) return;
  if (antes(agora, proximaTentativa_)) return;
  if (!drenando_ && agora - tEnvio_ < ENVIO_MS) return;
  tEnvio_ = agora;
  uint16_t n;
  String corpo = montarLote(agora, n);
  Resposta r = enlace_.telemetria(corpo);         // reenvio = requisição nova = seq novo
  if (tratar(r, agora)) {
    filaLeituras_.retira(n);
    lotesEnviados_++;
    drenando_ = filaLeituras_.tamanho() >= loteMax_;
    for (JsonVariantConst p : r.dados["portas"].as<JsonArrayConst>()) respostaDaPorta(p, agora);
    return;
  }
  drenando_ = false;
  if (!r.chegou) return;                          // fica na fila para a próxima
  if (r.status == 413) {
    loteMax_ = max<uint8_t>(1, loteMax_ / 2);
  } else if (r.status == 422) {
    // Lote que o servidor nunca vai aceitar: jogar fora, senão trava a fila.
    filaLeituras_.retira(n);
    lotesDescartados_++;
    evento("lote recusado (%s): descartado", r.codigo.c_str());
  }
}

void Totem::respostaDaPorta(JsonVariantConst p, uint32_t agora) {
  uint8_t porta = p["porta"] | 0;
  if (porta < 1 || porta > PORTAS) return;
  Vaga& v = vagas_[porta];
  EstadoVaga e = estadoDoTexto(p["estado"] | "");
  if (e != DESCONHECIDO) mudarEstado(v, e, agora);
  if (v.rele) modeloDoBackend(v, p);              // fração nova e % corrigido a cada lote
  if (telaValida(p["tela"])) {
    JsonArrayConst t = p["tela"].as<JsonArrayConst>();
    uint32_t h = hashTela(t);
    if (h != v.telaBackend) {
      v.telaBackend = h;
      if (ui_ == AGUARDANDO_TAG) {
        tela_.limpar();
        for (JsonVariantConst x : t) tela_.acrescentar(x.as<const char*>());
        mostrar(agora);
      }
    }
  }

  JsonVariantConst deve = p["deve_liberar"];
  if (deve.is<bool>() && !deve.as<bool>() && v.rele) {
    // Trava de sessão: sem sessão no servidor, o relé não fica fechado.
    const char* motivo = p["motivo"] | "trava de sessao";
    desligar(v, motivo, agora);
  }
  if (deve.is<bool>() && deve.as<bool>() && !v.rele) {
    // O servidor acha que a vaga carrega e o relé está aberto (um comando se
    // perdeu?). NÃO fecha por conta própria: reconcilia pelo handshake.
    if (!v.divergente) {
      v.divergente = true;
      v.divergenteDesdeMs = agora;
    } else if (agora - v.divergenteDesdeMs >= DIVERGENTE_MS &&
               (!reconciliouAlguma_ || agora - tReconciliou_ >= RECONCILIAR_MS)) {
      tReconciliou_ = agora; reconciliouAlguma_ = true;
      v.divergente = false;
      link_ = SEM_HANDSHAKE;
      evento("vaga %u divergente do servidor: novo handshake", porta);
    }
  } else {
    v.divergente = false;
  }
}

// ===========================================================================
// Comandos
// ===========================================================================

void Totem::comandos(uint32_t agora) {
  if (link_ != PRONTO || !hal::wifiOk() || antes(agora, proximaTentativa_)) return;
  if (agora - tComandos_ < comandosMs_) return;
  tComandos_ = agora;
  Resposta r = enlace_.comandos();
  if (!tratar(r, agora)) return;
  for (JsonVariantConst c : r.dados["comandos"].as<JsonArrayConst>()) {
    const char* erro = executar(c, agora);
    enlace_.confirmar(c["id"] | "", erro == nullptr, erro);
  }
}

const char* Totem::executar(JsonVariantConst c, uint32_t agora) {
  // Devolve nullptr se executou, ou o texto do erro.
  uint8_t porta = c["porta"] | 1;
  if (porta == 0) porta = 1;
  if (porta > PORTAS) return "porta_inexistente";
  Vaga& v = vagas_[porta];
  const char* acao = c["acao"] | "";
  evento("comando %s na vaga %u", acao, porta);
  if (ehLigar(acao)) {
    ligar(v, sessaoDe(c["sessao_id"]), "comando", agora);
    modeloDoBackend(v, c["payload"]);
  } else if (ehDesligar(acao)) {
    desligar(v, "comando", agora);
  } else if (strcmp(acao, "solicitar_cartao") == 0) {
    JsonVariantConst pl = c["payload"];
    if (pl.isNull()) { v.temPedido = true; v.pedidoAteMs = agora + 120000; }
    else pedido(v, pl, agora);
  } else if (strcmp(acao, "cancelar_cartao") == 0) {
    v.temPedido = false;
  } else if (strcmp(acao, "ping") == 0) {
    if (ui_ == AGUARDANDO_TAG) {
      char l1[COLUNAS + 1];
      snprintf(l1, sizeof(l1), "Vaga %u ok", porta);
      mostrarLinhas("PING", l1, agora, AVISO_MS);
    }
  } else {
    return "acao_desconhecida";
  }
  return nullptr;
}

// ===========================================================================
// Trava offline (ADR-020 P2; ADR-021 D2: recusa também conta)
// ===========================================================================

void Totem::travaOffline(uint32_t agora) {
  if (!offline_ || cortouOffline_) return;
  if (agora - offlineDesde_ < OFFLINE_CORTE_MS) return;
  cortouOffline_ = true;
  for (uint8_t p = 1; p <= PORTAS; p++) desligar(vagas_[p], "trava offline", agora);
  // Na volta, o handshake diz o que o servidor ainda considera ativo.
  if (link_ == PRONTO) link_ = SEM_HANDSHAKE;
  evento("tempo demais sem servidor: reles abertos");
}

// ===========================================================================
// LCD 16x2
// ===========================================================================

void Totem::rotulo(const Vaga& v, char* saida) {   // até 5 colunas: 4 vagas em 2 linhas
  if (!v.existe) { strcpy(saida, "--"); return; }
  if (v.rele && v.estado == CARREGANDO) {
    if (v.fechado) {
      float w = v.potenciaW;
      if (w < 9.95f) snprintf(saida, 7, "%.1fW", w);
      else snprintf(saida, 7, "%.0fW", w);
    } else {
      snprintf(saida, 7, "%u%%", (unsigned)lroundf(v.fracao * 100));   // na vez de outra vaga
    }
    return;
  }
  strcpy(saida, v.estado >= 0 ? ROTULO[v.estado] : "CARGA");
}

void Totem::desenhar(uint32_t agora) {
  char l0[COLUNAS + 8] = "", l1[COLUNAS + 8] = "";
  if (ui_ == MOSTRA_TELA) {
    uint8_t pagina = (agora - tUi_) / PAGINA_MS;
    strncpy(l0, tela_.daPagina(pagina, 0), sizeof(l0));
    strncpy(l1, tela_.daPagina(pagina, 1), sizeof(l1));
  } else if (ui_ == ESCOLHA_VAGA) {
    int32_t resta = ((int32_t)TIMEOUT_ESCOLHA_MS - (int32_t)(agora - tUi_) + 999) / 1000;
    if (PORTAS == 1) strcpy(l0, "Aperte o botao");
    else snprintf(l0, sizeof(l0), "Escolha vaga 1-%u", (unsigned)PORTAS);
    snprintf(l1, sizeof(l1), "Tempo: %2ld s", (long)max<int32_t>(0, resta));
  } else if (ui_ == INICIANDO) {
    strcpy(l0, "GoodWe ChargeOps");
    strcpy(l1, recusa_[0] ? telaDaRecusa(recusa_) : !hal::wifiOk() ? "Sem Wi-Fi"
               : link_ == SEM_HORA ? "Acertando hora" : "Conectando...");
  } else {
    // Espera: convite -> quadro das vagas -> uma página por vaga carregando
    // (% do modelo, potência, fim previsto, fração) -> tomada.
    uint8_t ativas[PORTAS], nAtivas = 0;
    for (uint8_t p = 1; p <= PORTAS; p++) if (vagas_[p].rele && vagas_[p].estado == CARREGANDO) ativas[nAtivas++] = p;
    uint8_t paginas = 2 + nAtivas + (nAtivas ? 1 : 0);
    uint8_t pagina = (agora / ALTERNA_MS) % paginas;
    if (pagina == 0) {
      strcpy(l0, "GoodWe ChargeOps");
      uint8_t comPedido = 0;
      for (uint8_t p = 1; p <= PORTAS && !comPedido; p++) if (vagas_[p].temPedido) comPedido = p;
      if (recusa_[0]) strcpy(l1, telaDaRecusa(recusa_));
      else if (!online()) strcpy(l1, "Sem rede: espere");
      else if (comPedido) snprintf(l1, sizeof(l1), "Vaga %u: aproxime", comPedido);
      else strcpy(l1, "Aproxime cartao");
    } else if (pagina == 1) {
      // Quadro das vagas. Com PORTAS = 1 o nome da vaga cabe por extenso; com
      // mais, duas por linha ("1:CARGA 2:LIVRE"). Nunca lê além de PORTAS:
      // escrever "3:" e "4:" fixos passava do fim do vetor com menos vagas.
      char r[PORTAS + 1][8];
      for (uint8_t p = 1; p <= PORTAS; p++) rotulo(vagas_[p], r[p]);
      if (PORTAS == 1) {
        strcpy(l0, "Vaga 1");
        snprintf(l1, sizeof(l1), "%-16s", r[1]);
      } else {
        char* linha[2] = {l0, l1};
        size_t fim[2] = {0, 0};
        uint8_t porLinha = (PORTAS + 1) / 2;         // metade em cima, metade embaixo
        for (uint8_t p = 1; p <= PORTAS; p++) {
          uint8_t i = (p - 1) / porLinha;
          if (i > 1) break;
          fim[i] += snprintf(linha[i] + fim[i], sizeof(l0) - fim[i], "%s%u:%-5s",
                             fim[i] ? " " : "", p, r[p]);
        }
      }
    } else if (pagina < 2 + nAtivas) {
      const Vaga& v = vagas_[ativas[pagina - 2]];
      snprintf(l0, sizeof(l0), "V%u %3.0f%% %4.1fW", v.porta, v.celular.soc, v.celular.pedida(FISICA));
      if (v.tempoMin >= 0) snprintf(l1, sizeof(l1), "Fim %3ldm T%3u%%", (long)v.tempoMin,
                                    (unsigned)lroundf(v.fracao * 100));
      else snprintf(l1, sizeof(l1), "Calculando T%3u%%", (unsigned)lroundf(v.fracao * 100));
    } else {
      snprintf(l0, sizeof(l0), "Tomada %5.1fW", tomadaW_);
      snprintf(l1, sizeof(l1), "Total %6.2fWh", tomadaWh_);
    }
  }
  hal::lcd(l0, l1);
}

// ===========================================================================
// Monitor serial: comandos e estado das vagas
// ===========================================================================
// Plano B quando o leitor ou o botão falham na banca, e o jeito de conduzir a
// demonstração sem tocar no totem. Monitor serial a 115200 com "Nova linha":
//
//   t D3F5BFD9   aproxima a tag com esse UID (o mesmo texto que o LCD mostra)
//   b            aperta o botão da vaga 1
//   b 2          aperta o botão da vaga 2 (só com PORTAS >= 2)
//   s            imprime o status agora
//
// Não bloqueia: lê o que já chegou e volta. Vale exatamente como a tag e o
// botão de verdade - passa pelo mesmo POST /hardware/v2/rfid.

void Totem::lerSerial(char* tag, size_t tamanho, bool& temTag, uint8_t& botao) {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c != '\n' && c != '\r') {
      if (nSerial_ < sizeof(linhaSerial_) - 1) linhaSerial_[nSerial_++] = c;
      continue;                                   // linha incompleta: espera o resto
    }
    if (nSerial_ == 0) continue;
    linhaSerial_[nSerial_] = '\0';
    nSerial_ = 0;
    char* s = linhaSerial_;
    while (*s == ' ') s++;
    char cmd = (char)tolower((unsigned char)*s);
    s++;
    while (*s == ' ') s++;
    if (cmd == 't') {
      size_t j = 0;
      for (; *s && *s != ' ' && j + 1 < tamanho; s++) tag[j++] = (char)toupper((unsigned char)*s);
      tag[j] = '\0';
      if (j == 0) { evento("serial: use  t <UID>  (ex.: t D3F5BFD9)"); continue; }
      temTag = true;
      evento("serial: tag %s", tag);
    } else if (cmd == 'b') {
      int porta = *s ? atoi(s) : 1;
      if (porta < 1 || porta > PORTAS) {
        evento("serial: a vaga %d nao existe (este firmware tem %u)", porta, (unsigned)PORTAS);
        continue;
      }
      botao = (uint8_t)porta;
      evento("serial: botao da vaga %d", porta);
    } else if (cmd == 's') {
      tStatus_ = millis() - STATUS_MS;            // imprime no próximo statusSerial
    } else {
      evento("serial: comando desconhecido. t <UID> | b [vaga] | s");
    }
  }
}

void Totem::statusSerial(uint32_t agora) {
  if (agora - tStatus_ < STATUS_MS) return;
  tStatus_ = agora;
  if (!online()) {
    evento("status: %s", !hal::wifiOk()      ? "sem Wi-Fi"
                         : link_ == SEM_HORA ? "acertando a hora com o servidor"
                         : offline_          ? "sem servidor"
                                             : "fazendo o handshake");
    return;
  }
  for (uint8_t p = 1; p <= PORTAS; p++) {
    const Vaga& v = vagas_[p];
    if (!v.existe) { evento("status: vaga %u nao existe no backend", p); continue; }
    if (!v.rele) {
      evento("status: vaga %u %s%s", p, v.estado >= 0 ? NOME_ESTADO[v.estado] : "?",
             v.temPedido ? " (pedido do app: aproxime a tag)" : "");
      continue;
    }
    evento("status: vaga %u %s | %.1f%% de %.0f%% | %.2f W %s | %.3f Wh | tempo fechado %.0f%% | fim %ld min",
           p, v.estado >= 0 ? NOME_ESTADO[v.estado] : "?", v.celular.soc, v.celular.alvo,
           v.celular.pedida(FISICA), v.fechado ? "(rele fechado)" : "(rele aberto: vez de outra)",
           v.energiaWh, v.fracao * 100.0f, (long)v.tempoMin);
  }
}
