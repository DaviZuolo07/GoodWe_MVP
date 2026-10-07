# ADR-020 — Totem virtual (gêmeo digital do ESP32 "Totem Central")

- **Status:** ACEITO (seção 9 respondida no ADR-018). **Substituído em parte:** D4 (LCD 20x4) e D5 (vaga 4 painel/bateria) pelo ADR-022; a linha `401 assinatura_invalida` do D6 pelo ADR-021
- **Chat:** V1 — Totem virtual
- **Entrega:** `totem_virtual/` + `docs/contratos/maquina_de_estados_totem.md` + pedido em `docs/decisoes/pedidos/`
- **Não toca:** `backend/`, `db/`, `backend/testes/placa_v2.py` (só importa)
- **Numeração:** o contrato cita ADR-018 (Totem v2.1) e ADR-019 (taxa de ocupação), que ainda não estão no repositório. Usei 020 para não colidir; se o 017 estiver livre e preferirem, é só renomear.

---

## 0. Estado verificado (o que o código diz hoje)

| # | Item | Verificado em | Consequência para o totem |
|---|------|---------------|---------------------------|
| 1 | `/hardware/v2/rfid` só confirma recarga **preparada no app**; tag numa vaga livre responde `sem_recarga_preparada` | `recarga.processar_cartao` | O fluxo tag-primeiro depende do D1. O totem trata as duas respostas |
| 2 | A resposta do RFID hoje **não tem** `acao` nem `tela`, e o sucesso não traz `motivo` | idem | Relé liga pelo comando `liberar`; a tela é montada no totem a partir do `motivo` |
| 3 | Comandos de hoje: `solicitar_cartao`, `cancelar_cartao`, `liberar`, `bloquear`, `ping` | `dispositivos.py` | O totem aceita os dois vocabulários: `liberar`/`ligar` e `bloquear`/`desligar` |
| 4 | Telemetria v2 exige `leituras` com 1 a 30 itens e corpo ≤ 8 KB; campo desconhecido (`fontes`) é **ignorado**, não recusado | `hardware_api.TelemetriaV2Payload` | Dá para mandar `fontes` desde já. Lote só com `fontes` ainda seria recusado, então o totem sempre manda leituras das vagas junto |
| 5 | A resposta por porta traz `deve_liberar` e `sessao_ativa`; `estado` e `tela` ainda não | `_processar_leitura` | Sem `estado`, o totem deriva "livre/carregando" do relé e marca como derivado |
| 6 | O handshake devolve, por porta, `rele_esperado` e `sessao_ativa.energia_wh`, e descarta comandos pendentes | `handshake_v2` | É o que permite reconciliar depois de um reboot |
| 7 | Fim por celular cheio/desplugado é decisão do **backend**: 30 s abaixo de 0,5 W com relé fechado **e** mais de 0,2 Wh entregues | `_processar_leitura` | O totem só mede e reporta. Vaga sem celular (0 Wh) não encerra hoje: depende do D1 |
| 8 | Leituras gravadas pelo lote recebem `origem = 'medido'` | RPC `registrar_lote_telemetria` | **Conflito com a regra 5**: leitura do totem virtual é simulada. Ver P4 |
| 9 | O atraso de uma leitura (`t_envio_ms − t_ms`) é limitado a 10 min no servidor | idem | Guardar mais de 10 min de leituras offline perde a noção de tempo. Ver D6 |
| 10 | Davi desenvolve em Windows | pasta `Z:\GoodWe_MVP` | Pesa na escolha da interface (D7) |

---

## D1. Três camadas, para o firmware poder copiar

**Decisão.** O totem virtual é separado em três partes que não se misturam:

```
bancada.py   o "hardware": relés, INA219, celulares, painel, bateria, LCD, leitor, botões, Wi-Fi
firmware.py  a lógica: só enxerga a bancada pela HAL (millis, ler_ina, rele, tag_lida, botao, lcd...)
rede.py      o enlace: PlacaV2 (importada) + tratamento de falha; nunca levanta exceção
```

`firmware.py` não sabe que o celular é de mentira. Cada função da HAL tem um equivalente direto em C++ (`millis()`, `digitalWrite`, `ina219.getCurrent_mA()`, `mfrc522.PICC_ReadCardSerial()`), então o `.ino` é uma tradução, não um redesenho.

**Rejeitado.** Um arquivo só, com física e lógica juntas (como o `simular_esp32.py` do v1): é mais curto, mas o firmware copiaria atalhos que só existem na simulação (por exemplo, "saber" que o celular foi desplugado em vez de medir corrente zero).

## D2. Máquina de estados: uma da interface, uma por vaga

**Decisão.**

- **Interface (uma só, porque há um leitor e uma tela):**
  `INICIANDO → AGUARDANDO_TAG → ESCOLHA_VAGA (15 s) → POST /v2/rfid → MOSTRA_TELA (4 s) → AGUARDANDO_TAG`
- **Vaga (quatro, cada uma com relógio próprio):** o estado é o da lista fechada do contrato (`livre | aguardando_energia | carregando | pausada | completa_tolerancia | completa_taxa`). O totem **não inventa estado**: guarda o último que o backend informou; enquanto o backend não manda `estado`, usa `carregando` com o relé fechado e `livre` com ele aberto.
- **Sem `delay()`:** tudo é "já passou X ms desde tal marca?". A única chamada que bloqueia é o HTTP, com timeout de 3 s, igual ao `HTTPClient` do ESP32.
- **Botão sem tag** é ignorado com um aviso de 2 s. **Tag durante a escolha** troca a tag e reinicia os 15 s. **Tag durante MOSTRA_TELA** interrompe a tela (a próxima pessoa não espera).

**Rejeitado.** Estados locais próprios por vaga (`AUTORIZANDO`, `FINALIZANDO`...): seriam códigos novos fora da lista fechada, e o app e o totem passariam a discordar sobre a mesma vaga.

## D3. Quem manda no relé

**Decisão.** O relé só **fecha** por ordem do backend, e por três caminhos equivalentes (a ação é idempotente):

1. `acao: "ligar"` na resposta do RFID (v2.1);
2. comando `liberar` / `ligar` em `/v2/comandos`;
3. `rele_esperado: true` no handshake (depois de um reboot).

Ele **abre** por `acao: "desligar"`, comando `bloquear` / `desligar`, `rele_esperado: false`, e por duas travas locais:

- **Trava de sessão:** relé fechado e a telemetria respondeu `deve_liberar: false` para a porta → abre. É a mesma regra do v1 ("sem sessão o relé tem que estar aberto").
- **Trava offline:** ver D6.

O contador de energia (Wh acumulado) zera quando chega um `ligar` com `sessao_id` diferente do que a vaga tinha; `ligar` repetido ou retomada da mesma sessão não zera.

**Rejeitado.** Fechar o relé localmente quando a resposta diz `autorizado: true`, sem esperar `acao`/comando: com o backend de hoje funcionaria, mas no v2.1 `autorizado: true` também vem com `aguardando_energia`, em que o relé **não** pode fechar.

## D4. Tela LCD 20x4

**Decisão.** Se a resposta traz `tela`, o totem mostra exatamente aquilo (cortando em 4 linhas de 20 e trocando o que não for ASCII). Se não traz, monta a tela a partir do `motivo`, numa tabela fixa que cobre a lista fechada do contrato e os motivos antigos (`sem_recarga_preparada`, `limite_de_potencia`, `espera_encerrada`). Motivo desconhecido cai na `mensagem`, sem acento e quebrada em linhas.

## D5. Física

- **Celular:** a curva do contrato (seção C). Capacidade e % inicial por celular; desplugar zera a corrente com o relé fechado.
- **INA219 virtual:** quantiza como o sensor (4 mV, 0,1 mA) e aplica o ruído de ±2%.
- **Solar (vaga 4), modelo simplificado e rotulado como tal:**
  - Painel: potência disponível = 10 W × luz; tensão em aberto sobe com a luz; sobrecarregado, a tensão desaba.
  - Bateria 18650 (9,62 Wh): tabela SOC → tensão em circuito aberto, menos a queda na resistência interna.
  - **Comutação, nunca em paralelo:** a vaga 4 é alimentada pelo painel **ou** pela bateria. Entra no painel com tensão ≥ 5,60 V; sai dele se o barramento cair abaixo de 4,75 V por 1 s; corta a bateria abaixo de 3,30 V e só volta acima de 3,60 V. Toda troca passa 200 ms sem fonte nenhuma (abre uma antes de fechar a outra).
  - O painel só carrega a bateria quando não está alimentando a vaga e a bateria também não está.
  - Os limiares são ponto de partida: **precisam ser calibrados na bancada real**.
- **Sem aceleração de tempo.** Para cenário rápido, usa-se celular de capacidade pequena. Acelerar o relógio quebraria a relação com os temporizadores do backend (janela de 120 s, 30 s de baixa potência).

## D6. Falhas

| Falha | O que o totem faz |
|---|---|
| **Wi-Fi cai** | Continua medindo e guarda as leituras (até 240 das vagas e 120 das fontes; estourou, descarta as mais antigas — a energia é acumulada, a última basta). Recarga em curso **continua**. Tag lida mostra "Sem conexao" e **não** é reenviada depois |
| **Wi-Fi volta** | Mesmo `boot`, `seq` segue contando. Manda o que guardou em lotes de até 30, do mais antigo para o mais novo, um lote por volta do laço. Cada reenvio é requisição nova, com `seq` novo (ADR-015 D3) |
| **Offline por mais de 120 s** | Abre todos os relés (trava offline). Ninguém carrega sem o servidor acompanhando. Na volta, o handshake/comandos religam o que o backend ainda considerar ativo |
| **Reboot** | `boot` novo, `seq` em 0, relés abertos, memória zerada (inclusive leituras guardadas). Acerta a hora, faz handshake e reconcilia cada porta: `rele_esperado` e `sessao_ativa.energia_wh` |
| `409 boot_desconhecido` | Refaz o handshake |
| `409 replay` | Sorteia `boot` novo e refaz o handshake (numeração dessincronizada) |
| `401 fora_da_janela` | Acerta a hora de novo |
| `401 assinatura_invalida` | Mostra "Chave invalida" e tenta de novo a cada 10 s. Não descarta leituras |
| `422` na telemetria | Descarta aquele lote (senão ele trava a fila para sempre) e registra o erro |
| `413` | Corta o tamanho do lote pela metade |

**Rejeitado.** Guardar a leitura de tag e reenviar quando a rede voltar: iniciaria uma recarga minutos depois, sem ninguém na frente do totem.

## D7. Interface — página local, servida só em 127.0.0.1

**Decisão.** `python -m totem_virtual painel` sobe uma página em `http://127.0.0.1:8765`, feita com a biblioteca padrão do Python (sem dependência nova) e sem nenhum arquivo externo (funciona sem internet no estande).

- Permite: aproximar tag, apertar o botão de cada vaga, plugar/desplugar celular (capacidade e %), mudar a luz do painel e a carga da bateria, derrubar o Wi-Fi, reiniciar a placa.
- Mostra: o LCD 20x4, relé e medidas de cada vaga, fontes da vaga 4, fila de leituras guardadas, boot/seq e as últimas trocas com o backend.
- **Segurança:** escuta só em `127.0.0.1`; recusa `Host` diferente (DNS rebinding); toda chamada exige um token sorteado a cada execução, que só a própria página conhece (um site aberto em outra aba não consegue apertar botão). A chave da placa **nunca** vai para o navegador.
- **Regra 5:** a página carrega o selo "SIMULADO — gêmeo digital" e cada bloco diz a origem do número (simulado no totem × respondido pelo backend).

**Rejeitado.**
- **Terminal (curses/TUI):** `curses` não vem no Python do Windows, e uma TUI não serve de plano B num telão do estande.
- **Tela dentro do `frontend/` (React):** misturaria ferramenta de bancada com o app do morador e levaria a simulação para um bundle público.
- **Servir em `0.0.0.0`:** qualquer um na rede do evento apertaria os botões.

## D8. Modo roteiro e testes

- `python -m totem_virtual roteiro` roda os cenários contra o backend configurado e imprime, por cenário, **PASSOU / FALHOU / AGUARDANDO BACKEND / PULADO**, sempre a partir das respostas do backend. Sai com código 1 só se houver FALHOU.
- **AGUARDANDO BACKEND** = o backend respondeu no formato de hoje (sem `acao`, ou `sem_recarga_preparada` numa vaga livre). Não é falha.
- **PULADO** = falta configuração (uma tag ou uma conta do app no `.env`).
- `--bolso`: roda contra o **backend de verdade em memória** (o FastAPI de `backend/` com o `supabase_falso.py`, importados sem alteração), com um totem de 4 vagas semeado. Não precisa de Supabase, `.env` nem chave: é o que roda no pytest e antes de cada merge.
- **pytest** (`totem_virtual/testes/`): física, LCD, máquina de estados com relógio manual, falhas, e o roteiro inteiro em dois servidores — o backend atual (`--bolso`) e um **servidor v2.1 de referência** escrito só para teste, a partir do texto do contrato. O segundo é a minha leitura do contrato, não o código do Daniel: serve para o lado v2.1 do totem não entrar sem teste.

## 9. Pontos para o Daniel aprovar

| # | Ponto | Padrão adotado até a resposta |
|---|---|---|
| P1 | Trava de sessão: relé abre com `deve_liberar: false` na telemetria (D3) | Ligada |
| P2 | Trava offline: abre os relés após 120 s sem servidor (D6) | 120 s (`TOTEM_OFFLINE_CORTE_S`) |
| P3 | Sinal em `fontes`: mando a potência **fornecida** pela fonte, sempre ≥ 0. Bateria sendo carregada aparece como 0 W e pela tensão subindo | ≥ 0 |
| P4 | Leitura de placa virtual gravada como `origem = 'medido'` fere a regra 5 | O totem se identifica no handshake (`firmware: "totem-virtual-…"`, `mac: "VIRTUAL"`); o resto é pedido ao backend |
| P5 | Confirmação de que `fontes` foi gravado (hoje a resposta não diz) | O cenário solar fica "aguardando backend" |
| P6 | Prazo do backend para liberar vaga sem celular / desplugada / cheia | O roteiro espera até 90 s (`ROTEIRO_ESPERA_S`) |

Detalhes em `docs/decisoes/pedidos/2026-10-06_totem_virtual_backend.md`.

## 10. Fora deste chat

Firmware C++ (chat próprio, quando o ESP32 chegar), tela do morador, taxa de ocupação na tela do totem além de mostrar o `estado`/`tela` que o backend mandar.
