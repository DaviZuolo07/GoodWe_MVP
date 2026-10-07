#include "textos.h"

// Latin-1 0xA0..0xFF -> ASCII, gerada de totem_virtual/lcd.sem_acento (NFKD sem
// marcas; o que não vira um caractere ASCII vira '?'). UTF-8: C2 xx e C3 xx.
static const char LATIN1_A0[] = " ??????? ?a???? ??23 ??? 1o?????";
static const char LATIN1_C0[] = "AAAAAA?CEEEEIIII?NOOOOO??UUUUY??aaaaaa?ceeeeiiii?nooooo??uuuuy?y";

void semAcento(const char* e, char* s, size_t tamanho) {
  size_t j = 0;
  for (size_t i = 0; e[i] && j + 1 < tamanho;) {
    uint8_t c = (uint8_t)e[i];
    if (c < 0x80) {                                     // ASCII
      s[j++] = (c >= 32 && c <= 126) ? (char)c : '?';   // igual ao Python
      i++;
    } else if ((c == 0xC2 || c == 0xC3) && e[i + 1]) {  // Latin-1 em UTF-8
      uint8_t b = (uint8_t)e[i + 1];
      uint16_t cp = ((c & 0x1F) << 6) | (b & 0x3F);
      s[j++] = cp >= 0xC0 ? LATIN1_C0[cp - 0xC0] : cp >= 0xA0 ? LATIN1_A0[cp - 0xA0] : '?';
      i += 2;
    } else {                                            // qualquer outro: um '?' por caractere
      s[j++] = '?';
      i++;
      while (e[i] && ((uint8_t)e[i] & 0xC0) == 0x80) i++;   // pula os bytes de continuação
    }
  }
  s[j] = '\0';
}

void Tela::acrescentar(const char* texto) {
  char limpo[96];
  semAcento(texto ? texto : "", limpo, sizeof(limpo));
  char atual[COLUNAS + 1] = "";
  uint8_t tam = 0;
  bool algo = false;

  auto fechar = [&]() {
    if (n < TELA_MAX_LINHAS) { memcpy(linha[n], atual, tam); linha[n][tam] = '\0'; n++; }
    tam = 0; atual[0] = '\0';
  };

  const char* p = limpo;
  while (*p) {
    while (*p == ' ') p++;
    if (!*p) break;
    const char* ini = p;
    while (*p && *p != ' ') p++;
    size_t len = p - ini;
    algo = true;
    while (len > COLUNAS) {                        // palavra maior que a tela: corta
      if (tam) fechar();
      memcpy(atual, ini, COLUNAS); tam = COLUNAS; fechar();
      ini += COLUNAS; len -= COLUNAS;
    }
    if (tam == 0) {
      memcpy(atual, ini, len); tam = len;
    } else if (tam + 1 + len <= COLUNAS) {
      atual[tam++] = ' '; memcpy(atual + tam, ini, len); tam += len;
    } else {
      fechar();
      memcpy(atual, ini, len); tam = len;
    }
  }
  if (tam || !algo) fechar();                       // linha vazia continua vazia
}

const char* Tela::daPagina(uint8_t p, uint8_t i) const {
  uint8_t ultima = paginas() - 1;
  if (p > ultima) p = ultima;
  uint8_t k = p * LINHAS + i;
  return k < n ? linha[k] : "";
}

// ---------------------------------------------------------------------------
// Telas do contrato (§6), cada linha em até 16 colunas. "#" = número da vaga.
// ---------------------------------------------------------------------------
struct Motivo { const char* motivo; const char* linhas[4]; };

static const Motivo MOTIVOS[] = {
  {"iniciada",                    {"Vaga # liberada", "Boa recarga!"}},
  {"encerrada",                   {"Vaga # encerrou", "Retire o celular"}},
  {"confirmada_app",              {"Vaga # liberada", "Recarga do app"}},
  {"aguardando_energia",          {"Vaga # na fila", "Limite atingido", "Liga sozinha", "quando liberar"}},
  {"vaga_ocupada",                {"Vaga # ocupada", "Escolha outra"}},
  {"ja_carregando_em_outra_vaga", {"Voce ja carrega", "em outra vaga"}},
  {"saldo_insuficiente",          {"Sem saldo", "Adicione no app"}},
  {"taxa_pendente",               {"Taxa pendente", "Quite no app"}},
  {"cartao_nao_cadastrado",       {"Tag desconhecida", "Cadastre no app"}},
  {"cartao_de_outro_usuario",     {"Tag de outro", "morador"}},
  {"cartao_de_outro_condominio",  {"Tag de outro", "condominio"}},
  {"sem_veiculo",                 {"Sem veiculo", "Cadastre no app"}},
  {"uid_invalido",                {"Leitura falhou", "Aproxime de novo"}},
  {"sem_recarga_preparada",       {"Sem recarga", "preparada no app"}},
  {"limite_de_potencia",          {"Sem energia", "Tente mais tarde"}},
  {"espera_encerrada",            {"Espera encerrada", "Prepare de novo"}},
};

uint8_t telaDoMotivo(const char* motivo, uint8_t vaga, Tela& tela) {
  if (!motivo) return 0;
  for (const Motivo& m : MOTIVOS) {
    if (strcmp(m.motivo, motivo) != 0) continue;
    tela.limpar();
    for (const char* l : m.linhas) {
      if (!l) break;
      char buf[COLUNAS + 2];
      size_t j = 0;
      for (const char* c = l; *c && j < sizeof(buf) - 1; c++) buf[j++] = (*c == '#') ? char('0' + vaga) : *c;
      buf[j] = '\0';
      tela.acrescentar(buf);
    }
    return tela.n;
  }
  return 0;
}

const char* telaDaRecusa(const char* codigo) {
  return strcmp(codigo, "fora_da_janela") == 0 ? "Relogio servidor" : "Chave invalida";
}

const char* diagnosticoDaRecusa(const char* codigo) {
  if (strcmp(codigo, "fora_da_janela") == 0)
    return "handshake recusado (401 fora_da_janela) 3 vezes seguidas, mesmo logo depois de "
           "acertar a hora pelo /hora: o relogio do computador do backend discorda do relogio "
           "do banco (Supabase) em mais que a janela anti-replay. Sincronize o relogio do "
           "Windows (Configuracoes > Hora e idioma > Sincronizar agora, ou 'w32tm /resync' "
           "como administrador) e reinicie o backend. Nova tentativa a cada 60 s.";
  return "handshake recusado (401 assinatura_invalida) 3 vezes seguidas: a DEVICE_KEY_HEX de "
         "segredos.h nao bate com a DEVICE_MASTER_KEY do backend (ou o DEVICE_ID nao existe no "
         "banco que o backend usa). Rode backend/preparar_totem.py --fisico de novo, copie a "
         "chave para segredos.h e grave o firmware. Nova tentativa a cada 60 s.";
}
