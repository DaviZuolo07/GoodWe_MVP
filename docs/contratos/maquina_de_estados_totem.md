# Máquina de estados do totem — base do firmware

- **Origem:** ADR-020 (totem virtual), ADR-021 (recusa de autenticação), ADR-022 (hardware real). **Implementação de referência:** `totem_virtual/firmware.py`. **Tradução:** `firmware/totem_central/`.
- **Protocolo:** v2 do ADR-015 (HMAC, boot/seq, lote) + Totem v2.1 do contrato (ADR-018). A assinatura é a de `backend/testes/placa_v2.py`.
- **Regra de manutenção:** este arquivo e `firmware.py` mudam juntos. Se o `.ino` precisar se desviar daqui, primeiro muda-se aqui (via ADR + PR), depois no totem virtual, depois no firmware.

Hardware alvo (ADR-022): 1 ESP32, 1 LCD **16x2**, 1 leitor RFID, 4 botões, 4 vagas com relé + INA219, 1 INA219 na bateria solar. A vaga 4 é solar: um **relé reversor** escolhe bateria solar (MT3608) **ou** rede (barramento de 5 V), nunca as duas.

---

## 1. Regras gerais

1. **Nada de `delay()`.** Toda espera é `millis() - marca >= prazo`. A única chamada que bloqueia é o HTTP, com timeout de 3 s.
2. **Ao ligar, todo relé aberto** e o reversor da vaga 4 em `rede` (bobina desligada).
3. **O relé só fecha por ordem do backend.** `autorizado: true` sozinho **não** fecha (pode vir com `aguardando_energia`).
4. **O totem não inventa estado de vaga.** Mostra o `estado` que o backend informou; sem ele, usa `carregando` (relé fechado) ou `livre` (relé aberto).
5. **Energia é acumulada por sessão**, nunca delta. Um lote perdido se corrige no próximo.
6. **Tudo em unidade bruta:** W, V, A, Wh. A escala 1:1000 é do backend.
7. **LCD só ASCII**, 2 linhas de 16. Texto do backend é re-quebrado em 16 colunas e paginado (§13).

## 2. Constantes

| Nome | Valor | Para quê |
|---|---|---|
| `TIMEOUT_ESCOLHA_MS` | 15000 | tempo para apertar o botão da vaga |
| `TELA_MS` | 4000 | resposta do backend na tela |
| `AVISO_MS` | 2000 | avisos curtos |
| `MEDICAO_MS` | 200 | leitura do INA219 e integração da energia |
| `AMOSTRA_MS` | 2000 | uma leitura por vaga vai para a fila |
| `ENVIO_MS` | 6000 | um lote de telemetria |
| `COMANDOS_MS` | 2000 | busca de comandos (o handshake pode trocar: `intervalo_comandos_s`) |
| `OFFLINE_CORTE_MS` | 120000 | sem servidor por este tempo, abre os relés |
| `RETENTATIVA_MIN_MS` / `MAX_MS` | 1000 / 10000 | espera entre tentativas de rede (dobra a cada falha) |
| `RECUSAS_PARA_BLOQUEAR` | 3 | 401 de autenticação seguidos do mesmo tipo até bloquear (ADR-021) |
| `BLOQUEIO_MS` | 60000 | espera depois de bloquear |
| `MAX_LEITURAS_LOTE` | 30 | teto do servidor |
| `MAX_FONTES_LOTE` | 20 | |
| `CORPO_MAX_BYTES` | 7000 | o servidor recusa acima de 8 KB |
| `FILA_LEITURAS_MAX` / `FILA_FONTES_MAX` | 240 / 120 | o que se guarda sem rede |
| `TROCA_FONTE_MS` | 200 | medida estabilizando depois de virar o reversor |
| `FONTE_MIN_MS` | 30000 | tempo mínimo na rede antes de voltar à solar |
| `QUEDA_MS` | 1000 | tensão baixa precisa durar isto |
| `V_BATERIA_CORTE` / `VOLTA` | 3,30 / 3,60 V | **calibrar na bancada** |
| `PAGINA_MS` | 2000 | uma página de 2 linhas da tela |
| `ALTERNA_MS` | 3000 | tela de espera: convite ↔ quadro das vagas |

## 3. Dados

```
struct Vaga {
  porta            1..4
  existe           veio no handshake?
  rele             bool
  estado           livre | aguardando_energia | carregando | pausada |
                   completa_tolerancia | completa_taxa      (lista fechada)
  estado_do_backend  bool   (false = derivado do relé)
  t_estado_ms      relógio próprio da vaga
  sessao_id        texto ou vazio
  energia_wh       acumulada na sessão
  medida           {tensao_v, corrente_a, potencia_w}
  pedido_ate_ms    recarga preparada no app esperando a tag (ou vazio)
  divergente_desde_ms
}

interface:  ui ∈ {INICIANDO, AGUARDANDO_TAG, ESCOLHA_VAGA, MOSTRA_TELA}, t_ui, uid, tela[4]
enlace:     link ∈ {SEM_HORA, SEM_HANDSHAKE, PRONTO}, handshake_feito,
            proxima_tentativa, espera_ms, offline_desde, cortou_offline,
            recusa (código do último 401), recusas_seguidas, diagnostico
filas:      fila_leituras (anel), fila_fontes (anel), drenando, lote_max
solar:      fonte ∈ {rede, solar}, t_troca, queda_desde, bateria_ok, fonte_backend ∈ {solar, rede, vazio}
protocolo:  boot (u32 aleatório ao ligar), seq (+1 a cada requisição assinada), offset do relógio
```

## 4. `setup()` e `loop()`

```
setup():
  para cada vaga: rele(porta, ABERTO)
  selecionar_fonte(rede)
  ui = INICIANDO ; link = SEM_HORA ; boot = aleatorio32() ; seq = 0
  filas vazias ; fonte = rede ; fonte_backend = vazio ; bateria_ok = true

loop():
  agora = millis()
  rede(agora)            # 5
  interface(agora)       # 6
  medir(agora)           # 8
  fonte_solar(agora)     # 9
  telemetria(agora)      # 10
  comandos(agora)        # 11
  trava_offline(agora)   # 12
  desenhar(agora)        # 13
```

## 5. Enlace

```
rede(agora):
  se Wi-Fi caído:
    se offline_desde vazio: offline_desde = agora
    retorna
  se o Wi-Fi acabou de voltar: proxima_tentativa = agora ; espera_ms = MIN
  se link == PRONTO ou agora < proxima_tentativa: retorna

  se link == SEM_HORA:
    GET /hardware/v2/hora            (pública; guarda offset = ts_servidor - ts_local)
    falhou -> falha(agora) ; retorna
    link = PRONTO se handshake_feito, senão SEM_HANDSHAKE
    se link == PRONTO e recusa vazia: sucesso()      # /hora não prova que a placa é aceita
    retorna

  # link == SEM_HANDSHAKE
  POST /hardware/v2/handshake {mac, ip, firmware}
  200 -> aplicar_handshake() ; link = PRONTO ; handshake_feito = true ; cortou_offline = false

esperar_mais(agora):
  proxima_tentativa = agora + espera_ms ; espera_ms = min(MAX, espera_ms * 2)

falha(agora):                        # servidor não respondeu
  se offline_desde vazio: offline_desde = agora
  esperar_mais(agora)

sucesso():                           # servidor respondeu e ACEITOU a placa
  offline_desde = vazio ; espera_ms = MIN
  recusa = vazio ; recusas_seguidas = 0 ; diagnostico = vazio

recusado(codigo, agora):             # 401 assinatura_invalida | fora_da_janela (ADR-021)
  se offline_desde vazio: offline_desde = agora     # quem não aceita a placa não acompanha a recarga
  recusas_seguidas = (codigo == recusa) ? recusas_seguidas + 1 : 1 ; recusa = codigo
  se codigo == fora_da_janela: link = SEM_HORA      # o relógio da placa pode ter derivado
  se recusas_seguidas < RECUSAS_PARA_BLOQUEAR: esperar_mais(agora) ; retorna
  proxima_tentativa = agora + BLOQUEIO_MS
  se recusas_seguidas == RECUSAS_PARA_BLOQUEAR:
    diagnostico = DIAGNOSTICO[codigo] ; registra no serial/terminal UMA vez

tratar(resposta, agora) -> bool:     # roda em TODA resposta do v2
  sem resposta                         -> falha(agora) ; false
  401 assinatura_invalida/fora_da_janela -> recusado(codigo, agora) ; false
  sucesso()
  200                           -> true
  409 boot_desconhecido         -> link = SEM_HANDSHAKE
  409 replay                    -> boot = aleatorio32() ; seq = 0 ; link = SEM_HANDSHAKE
  false
```

| `recusa` | Diagnóstico (terminal / serial) | LCD |
|---|---|---|
| `assinatura_invalida` | a chave não bate com a `DEVICE_MASTER_KEY` do backend (ou o id não existe no banco dele): rodar `backend/preparar_totem.py` de novo | `Chave invalida` |
| `fora_da_janela` | recusado mesmo logo depois de acertar a hora: o relógio do PC do backend discorda do banco; sincronizar o relógio e reiniciar o backend | `Relogio servidor` |

**Handshake = reconciliação.** Para cada porta da resposta:

```
aplicar_handshake(portas):
  todas as vagas: existe = false
  para cada p em portas:
    v = vaga[p.porta] ; v.existe = true
    se p.rele_esperado: ligar(v, p.sessao_ativa.sessao_id, energia = p.sessao_ativa.energia_wh)
    senão:              desligar(v)
    se p.estado veio: v.estado = p.estado
    se p.pedido veio: v.pedido_ate_ms = agora + p.pedido.segundos_para_aproximar
```

## 6. Interface: tag → botão → backend → tela

```
interface(agora):
  tag = leitor.tag_lida()      # uma vez por aproximação
  botao = botoes.apertado()    # 1..4, com debounce

  se ui == INICIANDO:
    se link != PRONTO: retorna            # ignora tag e botão
    ui = AGUARDANDO_TAG

  se tag:                                 # vale em qualquer tela
    uid = tag ; ui = ESCOLHA_VAGA ; t_ui = agora ; retorna

  se ui == ESCOLHA_VAGA:
    se botao:                              enviar_tag(botao)
    senão se agora - t_ui >= TIMEOUT_ESCOLHA_MS:
      uid = vazio ; mostrar("Tempo esgotado / Aproxime de novo", AVISO_MS)   # NÃO chama o backend
  senão se botao e ui == AGUARDANDO_TAG:   mostrar("Aproxime o / cartao primeiro", AVISO_MS)
  senão se ui == MOSTRA_TELA e agora - t_ui >= duracao:  ui = AGUARDANDO_TAG

enviar_tag(porta):
  u = uid ; uid = vazio
  se link != PRONTO ou Wi-Fi caído:
    mostrar("Sem conexao / Tente de novo") ; retorna          # NÃO guarda para depois
  r = POST /hardware/v2/rfid {porta, uid: u}
  se não tratar(r):
    sem resposta -> "Sem conexao / Tente de novo" ; 422 -> "Vaga N / indisponivel" ;
    outro -> "Nao deu certo / Aproxime de novo"
    retorna
  se r.acao == "ligar":     ligar(vaga[porta], r.sessao_id)
  se r.acao == "desligar":  desligar(vaga[porta])
  # r.acao == "nenhuma" ou ausente: não mexe no relé
  tela = r.tela se veio (até 4 linhas) ; senão TELA_DO_MOTIVO[r.motivo] ; senão r.mensagem quebrada
  mostrar(tela, TELA_MS)
```

Diagrama:

```
            tag                    botão N                  TELA_MS
AGUARDANDO ─────► ESCOLHA_VAGA ───────────► [POST rfid] ──► MOSTRA_TELA ───► AGUARDANDO
   ▲                 │  ▲ tag (troca a tag, reinicia 15 s)        │ tag
   │   15 s sem botão│  └──────────────────────────────────────────┘
   └── MOSTRA_TELA ◄─┘ ("Tempo esgotado", AVISO_MS)
```

### Tela quando o backend não manda `tela`

Cada linha cabe em 16 colunas (LCD 16x2, ADR-022). Mais de 2 linhas = 2 páginas.

| `motivo` | Linhas (`{n}` = vaga) |
|---|---|
| `iniciada` | `Vaga {n} liberada` / `Boa recarga!` |
| `encerrada` | `Vaga {n} encerrou` / `Retire o celular` |
| `confirmada_app` | `Vaga {n} liberada` / `Recarga do app` |
| `aguardando_energia` | `Vaga {n} na fila` / `Limite atingido` / `Liga sozinha` / `quando liberar` |
| `vaga_ocupada` | `Vaga {n} ocupada` / `Escolha outra` |
| `ja_carregando_em_outra_vaga` | `Voce ja carrega` / `em outra vaga` |
| `saldo_insuficiente` | `Sem saldo` / `Adicione no app` |
| `taxa_pendente` | `Taxa pendente` / `Quite no app` |
| `cartao_nao_cadastrado` | `Tag desconhecida` / `Cadastre no app` |
| `cartao_de_outro_usuario` | `Tag de outro` / `morador` |
| `cartao_de_outro_condominio` | `Tag de outro` / `condominio` |
| `sem_veiculo` | `Sem veiculo` / `Cadastre no app` |
| `uid_invalido` | `Leitura falhou` / `Aproxime de novo` |
| `sem_recarga_preparada` (legado) | `Sem recarga` / `preparada no app` |
| `limite_de_potencia` (legado) | `Sem energia` / `Tente mais tarde` |
| `espera_encerrada` (legado) | `Espera encerrada` / `Prepare de novo` |

## 7. Relé e estado da vaga

```
ligar(v, sessao_id, energia = vazio):
  sessao_nova = (sessao_id veio e sessao_id != v.sessao_id)
                ou (sessao_id não veio e v.sessao_id vazio e relé aberto)
  se sessao_nova: v.energia_wh = 0
  se sessao_id veio: v.sessao_id = sessao_id
  se energia veio: v.energia_wh = max(v.energia_wh, energia)      # reboot: continua
  v.pedido_ate_ms = vazio
  rele(v.porta, FECHADO)
  se o estado não veio do backend (ou era livre): v.estado = carregando (derivado)

desligar(v):
  rele(v.porta, ABERTO)
  se o estado não veio do backend (ou era carregando): v.estado = livre (derivado)
  # NÃO apaga sessao_id: pode ser pausa. Só o backend dizendo "livre" encerra a sessão.
```

Quem pode chamar:

| Origem | `ligar` | `desligar` |
|---|---|---|
| Resposta do RFID (`acao`) | `ligar` | `desligar` |
| `/v2/comandos` | `ligar` ou `liberar` | `desligar` ou `bloquear` |
| Handshake | `rele_esperado: true` | `rele_esperado: false` |
| Telemetria (`deve_liberar: false` com relé fechado) | — | trava de sessão |
| Sem servidor por `OFFLINE_CORTE_MS` | — | trava offline |

A ação é idempotente: `ligar` com o relé já fechado e a mesma sessão não muda nada.

## 8. Medição

```
medir(agora):
  se agora - t_medicao < MEDICAO_MS: retorna
  dt = agora - t_medicao ; t_medicao = agora
  para cada vaga:
    v.medida = ina219[v.porta].ler()
    se v.rele: v.energia_wh += v.medida.potencia_w * dt / 3.600.000
    se v.pedido_ate_ms venceu: v.pedido_ate_ms = vazio

  se agora - t_amostra < AMOSTRA_MS: retorna
  t_amostra = agora
  para cada vaga que existe:
    fila_leituras.empurra({porta, t_ms: agora, potencia_w, energia_wh, tensao_v, corrente_a, rele_ligado})
    # fila cheia: a mais antiga sai (a energia é acumulada, a última basta)
  se vaga[PORTA_SOLAR].existe:
    fila_fontes.empurra({fonte: "bateria", t_ms: agora, potencia_w, tensao_v, corrente_a})
    # INA219 em série com a 18650 (ADR-022 D2): COM SINAL, + descarregando, - carregando.
    # O painel não é medido: não vai "painel" no lote.
```

O firmware não "sabe" que o celular foi desplugado: ele mede corrente zero com o relé fechado e reporta. Quem conclui é o backend.

## 9. Vaga 4: solar ou rede, nunca as duas (ADR-022 D1)

Um relé reversor (SPDT): bobina desligada = `rede` (barramento de 5 V), ligada = `solar` (MT3608 da 18650). O contato é *break-before-make*: as duas fontes nunca se tocam, nem durante a troca.

```
virar(nova, agora, forcada):
  se nova == fonte: retorna
  reversor(nova) ; fonte = nova ; t_troca = agora ; queda_desde = vazio
  t_forcada = agora se forcada, senão vazio

fonte_solar(agora):
  se agora - t_troca < TROCA_FONTE_MS: retorna                 # medida estabilizando
  v_bat = ina_solar.tensao_v
  se não bateria_ok e fonte == rede e v_bat >= V_BATERIA_VOLTA: bateria_ok = true
  se relé da vaga 4 aberto: virar(rede, nao forcada) ; retorna   # sem carga: o painel carrega a 18650
  se fonte == solar e v_bat < V_BATERIA_CORTE por QUEDA_MS:     # proteção local, vale offline
    bateria_ok = false ; virar(rede, forcada) ; retorna
  se fonte_backend == rede ou não bateria_ok: virar(rede, forcada) ; retorna
  se fonte == rede e t_forcada e agora - t_forcada < FONTE_MIN_MS: retorna   # sem vai-e-volta
  virar(solar, nao forcada)
```

`fonte_backend` vem do campo `fonte` (`solar` | `rede`) da porta solar na telemetria (§10). Pausar a vaga solar é do backend (`deve_liberar: false`, trava de sessão), não do totem.

## 10. Telemetria em lote

```
telemetria(agora):
  se fila_leituras vazia ou link != PRONTO ou Wi-Fi caído ou agora < proxima_tentativa: retorna
  se não drenando e agora - t_envio < ENVIO_MS: retorna
  t_envio = agora
  n = min(tamanho(fila_leituras), lote_max) ; m = min(tamanho(fila_fontes), MAX_FONTES_LOTE)
  encolhe n e m até o JSON caber em CORPO_MAX_BYTES
  r = POST /hardware/v2/telemetria {t_envio_ms: agora, leituras: [n mais antigas], fontes: [m mais antigas]}
       # reenvio = requisição NOVA = seq novo. t_ms de cada leitura não muda.
  se tratar(r):
    retira n e m das filas
    drenando = tamanho(fila_leituras) >= lote_max        # ainda há lote cheio: manda na próxima volta
    para cada p em r.portas: resposta_da_porta(p)
    retorna
  drenando = false
  sem resposta -> fica na fila
  413          -> lote_max = max(1, lote_max / 2)
  422          -> descarta ESTE lote (o servidor nunca vai aceitá-lo) e registra

resposta_da_porta(p):
  se p.estado veio: v.estado = p.estado (do backend) ; se livre e relé aberto: v.sessao_id = vazio
  se p.porta == PORTA_SOLAR e p.fonte em (solar, rede): fonte_backend = p.fonte
  se p.tela veio e mudou e ui == AGUARDANDO_TAG: mostrar(p.tela, TELA_MS)
  se p.deve_liberar == false e v.rele: desligar(v)                    # trava de sessão
  se p.deve_liberar == true e não v.rele:
    marca divergente_desde ; se durar 10 s (e o último foi há 30 s): link = SEM_HANDSHAKE
    # NÃO fecha o relé sozinho: reconcilia pelo handshake
```

## 11. Comandos

```
comandos(agora):
  se link != PRONTO ou Wi-Fi caído ou agora < proxima_tentativa: retorna
  se agora - t_comandos < COMANDOS_MS: retorna
  t_comandos = agora
  r = GET /hardware/v2/comandos ; se não tratar(r): retorna
  para cada c em r.comandos:
    erro = executar(c)
    POST /hardware/v2/comandos/{c.id}/confirmar {sucesso: erro vazio, erro}

executar(c):
  ligar | liberar       -> ligar(vaga[c.porta], c.sessao_id)
  desligar | bloquear   -> desligar(vaga[c.porta])
  solicitar_cartao      -> vaga.pedido_ate_ms = agora + payload.segundos_para_aproximar
  cancelar_cartao       -> vaga.pedido_ate_ms = vazio
  ping                  -> "PING / Vaga N ok" por AVISO_MS
  outro                 -> erro "acao_desconhecida"
```

## 12. Trava offline

```
trava_offline(agora):
  se offline_desde vazio ou cortou_offline: retorna
  se agora - offline_desde < OFFLINE_CORTE_MS: retorna
  cortou_offline = true
  para cada vaga: desligar(v)
  se link == PRONTO: link = SEM_HANDSHAKE      # na volta, o handshake diz o que religar
```

## 13. LCD

LCD 16x2 (ADR-022 D3). Toda tela passa por `reflow`: cada linha é re-quebrada em 16 colunas
sem cortar palavra (palavra maior que 16 é cortada), sem acento.

```
mostrar(linhas, agora, duracao):
  tela = reflow(linhas) ; paginas = teto(tamanho(tela) / 2)
  ui = MOSTRA_TELA ; t_ui = agora ; duracao_tela = max(duracao, paginas * PAGINA_MS)

MOSTRA_TELA   -> página min((agora - t_ui) / PAGINA_MS, paginas - 1) da tela guardada
ESCOLHA_VAGA  -> "Escolha vaga 1-4" / "Tempo: NN s"
INICIANDO     -> "ChargeOps GoodWe" / passo: "Chave invalida" | "Relogio servidor" | "Sem Wi-Fi" |
                 "Acertando hora" | "Conectando..."
AGUARDANDO    -> alterna a cada ALTERNA_MS, pela página (agora / ALTERNA_MS) % 2:
  0: "ChargeOps GoodWe" / aviso: "Chave invalida" | "Relogio servidor" | "Sem rede: espere" |
                                 "Vaga N: aproxime" | "Aproxime cartao"
  1: "1:<rot> 2:<rot>" / "3:<rot> 4:<rot>"      cada vaga = "N:" + <rot> em 5 colunas + espaço

<rot>:  carregando -> "7.4W" (< 10 W, uma casa) ou "12W"; vaga 4 com sufixo S (solar) ou R (rede)
        livre -> LIVRE ; aguardando_energia -> FILA ; pausada -> PAUSA ;
        completa_tolerancia -> CHEIO ; completa_taxa -> TAXA ; porta fora do handshake -> "--"
```

## 14. Reboot e Wi-Fi, do ponto de vista do protocolo

| Evento | `boot` | `seq` | Relés | Fila | Recuperação |
|---|---|---|---|---|---|
| Wi-Fi cai e volta | o mesmo | continua | ficam como estavam | guarda e reenvia | automática, sem handshake |
| Offline além do corte | o mesmo | continua | abrem | guarda (até o teto) | handshake na volta |
| Reboot | novo | 0 | abrem | perdida | hora → handshake → `rele_esperado` + `energia_wh` |
| `replay` | novo | 0 | ficam | mantida | handshake |
| `boot_desconhecido` | o mesmo | continua | ficam | mantida | handshake |

## 15. O que este documento NÃO decide

- Pinos e bibliotecas: estão no ADR-022 D4 e em `firmware/totem_central/`.
- Os limiares de tensão da bateria solar: os valores aqui fecham com o **modelo simplificado** do totem virtual e precisam ser medidos na bancada.
- Regras de negócio (taxa de ocupação, quem pode encerrar, prazos de detecção): são do backend. O totem só mostra `estado` e `tela`.
