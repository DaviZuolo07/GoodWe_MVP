# Máquina de estados do totem — base do firmware

- **Origem:** ADR-020 (totem virtual). **Implementação de referência:** `totem_virtual/firmware.py`.
- **Protocolo:** v2 do ADR-015 (HMAC, boot/seq, lote) + Totem v2.1 do contrato (ADR-018). A assinatura é a de `backend/testes/placa_v2.py`.
- **Regra de manutenção:** este arquivo e `firmware.py` mudam juntos. Se o `.ino` precisar se desviar daqui, primeiro muda-se aqui (via ADR + PR), depois no totem virtual, depois no firmware.

Hardware alvo: 1 ESP32, 1 LCD 20x4, 1 leitor RFID, 4 botões, 4 vagas com relé + INA219. A vaga 4 é solar: painel **ou** bateria 18650, com uma chave de fonte intertravada.

---

## 1. Regras gerais

1. **Nada de `delay()`.** Toda espera é `millis() - marca >= prazo`. A única chamada que bloqueia é o HTTP, com timeout de 3 s.
2. **Ao ligar, todo relé aberto** e a chave de fonte em `nenhuma`.
3. **O relé só fecha por ordem do backend.** `autorizado: true` sozinho **não** fecha (pode vir com `aguardando_energia`).
4. **O totem não inventa estado de vaga.** Mostra o `estado` que o backend informou; sem ele, usa `carregando` (relé fechado) ou `livre` (relé aberto).
5. **Energia é acumulada por sessão**, nunca delta. Um lote perdido se corrige no próximo.
6. **Tudo em unidade bruta:** W, V, A, Wh. A escala 1:1000 é do backend.
7. **LCD só ASCII**, 4 linhas de 20. Texto do backend passa pelo mesmo corte.

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
| `MAX_LEITURAS_LOTE` | 30 | teto do servidor |
| `MAX_FONTES_LOTE` | 20 | |
| `CORPO_MAX_BYTES` | 7000 | o servidor recusa acima de 8 KB |
| `FILA_LEITURAS_MAX` / `FILA_FONTES_MAX` | 240 / 120 | o que se guarda sem rede |
| `TROCA_FONTE_MS` | 200 | tempo com as duas fontes abertas na troca |
| `QUEDA_MS` | 1000 | tensão baixa precisa durar isto |
| `V_PAINEL_ENTRA` | 5,60 V | **calibrar na bancada** |
| `V_BARRA_MINIMA` | 4,75 V | **calibrar na bancada** |
| `V_BATERIA_CORTE` / `VOLTA` | 3,30 / 3,60 V | **calibrar na bancada** |

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
            proxima_tentativa, espera_ms, offline_desde, cortou_offline
filas:      fila_leituras (anel), fila_fontes (anel), drenando, lote_max
solar:      fonte_alvo ∈ {painel, bateria, nenhuma}, t_troca, queda_desde, bateria_ok
protocolo:  boot (u32 aleatório ao ligar), seq (+1 a cada requisição assinada), offset do relógio
```

## 4. `setup()` e `loop()`

```
setup():
  para cada vaga: rele(porta, ABERTO)
  selecionar_fonte(nenhuma)
  ui = INICIANDO ; link = SEM_HORA ; boot = aleatorio32() ; seq = 0
  filas vazias ; fonte_alvo = nenhuma ; bateria_ok = true

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
    retorna

  # link == SEM_HANDSHAKE
  POST /hardware/v2/handshake {mac, ip, firmware}
  200 -> aplicar_handshake() ; link = PRONTO ; handshake_feito = true ; cortou_offline = false

falha(agora):                        # servidor não respondeu
  se offline_desde vazio: offline_desde = agora
  proxima_tentativa = agora + espera_ms ; espera_ms = min(MAX, espera_ms * 2)

sucesso():                           # servidor respondeu qualquer coisa assinável
  offline_desde = vazio ; espera_ms = MIN

tratar(resposta, agora) -> bool:     # roda em TODA resposta do v2
  sem resposta                  -> falha(agora) ; false
  401 assinatura_invalida       -> tela "Chave invalida" ; proxima_tentativa = agora + MAX ; false
  sucesso()
  200                           -> true
  409 boot_desconhecido         -> link = SEM_HANDSHAKE
  409 replay                    -> boot = aleatorio32() ; seq = 0 ; link = SEM_HANDSHAKE
  401 fora_da_janela            -> link = SEM_HORA
  false
```

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
      uid = vazio ; mostrar("Tempo esgotado", AVISO_MS)      # NÃO chama o backend
  senão se botao e ui == AGUARDANDO_TAG:   mostrar("Aproxime a tag primeiro", AVISO_MS)
  senão se ui == MOSTRA_TELA e agora - t_ui >= duracao:  ui = AGUARDANDO_TAG

enviar_tag(porta):
  u = uid ; uid = vazio
  se link != PRONTO ou Wi-Fi caído:
    mostrar("Sem conexao / Tente de novo") ; retorna          # NÃO guarda para depois
  r = POST /hardware/v2/rfid {porta, uid: u}
  se não tratar(r):
    sem resposta -> "Sem conexao" ; 422 -> "Vaga N indisponivel" ; outro -> "Nao deu certo"
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

| `motivo` | Linhas (`{n}` = vaga) |
|---|---|
| `iniciada` | `Vaga {n} liberada` / `Boa recarga!` |
| `encerrada` | `Vaga {n} encerrada` / `Retire o celular` |
| `confirmada_app` | `Vaga {n} liberada` / `Recarga do app` |
| `aguardando_energia` | `Vaga {n} na espera` / `Sem energia agora` / `Liga sozinha depois` |
| `vaga_ocupada` | `Vaga {n} ocupada` / `Escolha outra vaga` |
| `ja_carregando_em_outra_vaga` | `Voce ja esta` / `carregando em` / `outra vaga` |
| `saldo_insuficiente` | `Saldo insuficiente` / `Recarregue no app` |
| `taxa_pendente` | `Taxa pendente` / `Quite no app` |
| `cartao_nao_cadastrado` | `Tag nao cadastrada` / `Cadastre no app` |
| `cartao_de_outro_usuario` | `Tag de outro` / `morador` |
| `cartao_de_outro_condominio` | `Tag de outro` / `condominio` |
| `sem_veiculo` | `Sem veiculo` / `Cadastre no app` |
| `uid_invalido` | `Leitura falhou` / `Aproxime de novo` |
| `sem_recarga_preparada` (backend de hoje) | `Vaga {n}: sem recarga` / `preparada` / `Use o app primeiro` |

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
  para fonte em (painel, bateria):
    fila_fontes.empurra({fonte, t_ms: agora, potencia_w, tensao_v, corrente_a})
    # potência FORNECIDA pela fonte, >= 0
```

O firmware não "sabe" que o celular foi desplugado: ele mede corrente zero com o relé fechado e reporta. Quem conclui é o backend.

## 9. Vaga 4: painel ou bateria, nunca os dois

```
trocar_fonte(alvo):
  se alvo == fonte_alvo: retorna
  selecionar_fonte(nenhuma)            # abre as duas
  fonte_alvo = alvo ; t_troca = agora ; queda_desde = vazio

fonte_solar(agora):
  se chave != fonte_alvo:                                  # no meio de uma troca
    se agora - t_troca >= TROCA_FONTE_MS: selecionar_fonte(fonte_alvo) ; t_troca = agora
    retorna
  se agora - t_troca < TROCA_FONTE_MS + MEDICAO_MS: retorna   # medida estabilizando
  se relé da vaga 4 aberto: trocar_fonte(nenhuma) ; retorna    # o painel carrega a bateria

  se não bateria_ok e V_bateria >= V_BATERIA_VOLTA: bateria_ok = true

  caso fonte_alvo:
    painel:   se V_barra_vaga4 < V_BARRA_MINIMA por QUEDA_MS:
                trocar_fonte(bateria se bateria_ok, senão nenhuma)
    bateria:  se V_painel >= V_PAINEL_ENTRA: trocar_fonte(painel)
              senão se V_bateria < V_BATERIA_CORTE por QUEDA_MS:
                bateria_ok = false ; trocar_fonte(nenhuma)
    nenhuma:  se V_painel >= V_PAINEL_ENTRA: trocar_fonte(painel)
              senão se bateria_ok: trocar_fonte(bateria)
```

Sem fonte, o relé da vaga 4 **continua fechado** e a corrente medida é zero. O totem reporta isso e as `fontes`; a decisão (pausar, liberar) é do backend.

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

```
MOSTRA_TELA   -> a tela guardada
ESCOLHA_VAGA  -> "Tag lida" / "Escolha a vaga:" / "botoes 1 2 3 4" / "Tempo: NN s"
INICIANDO     -> "ChargeOps     GoodWe" / "Iniciando..." / passo (hora, servidor, Sem Wi-Fi, Chave invalida)
AGUARDANDO    -> "ChargeOps     GoodWe"
                 "1:<rot>   2:<rot>"          <rot> com 7 colunas
                 "3:<rot>   4:<rot>"
                 rodapé: "Chave invalida" | "Sem rede: aguarde" | "Vaga N: aproxime tag" | "Aproxime a tag"

<rot>:  carregando -> "7.4W" (vaga 4: "7.4W S" no painel, "7.4W B" na bateria, "S/FONTE" sem fonte)
        livre -> LIVRE ; aguardando_energia -> ESPERA ; pausada -> PAUSA ;
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

- Pinos, bibliotecas e debounce (são do chat do firmware).
- Os limiares de tensão da vaga 4: os valores aqui fecham com o **modelo simplificado** do totem virtual e precisam ser medidos na bancada.
- Regras de negócio (taxa de ocupação, quem pode encerrar, prazos de detecção): são do backend. O totem só mostra `estado` e `tela`.
