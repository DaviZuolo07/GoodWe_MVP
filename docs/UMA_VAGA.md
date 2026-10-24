# Totem de DUAS vagas — integração (24/10/2026)

> O arquivo manteve o nome `UMA_VAGA.md` (a montagem de 23/10) para não quebrar os
> links. O conteúdo vale para a montagem de **24/10: duas vagas**.

Cada vaga é `carregador 5 V → relé → porta USB`, e o relé **libera energia de verdade**.
Ele só fecha depois de **dois passos**: o MFRC522 lê uma tag **vinculada a uma conta no
app** e a pessoa aperta o **botão da vaga**. O botão decide qual vaga recebe energia.
Este documento é o contrato entre o firmware do Gustavo e o backend: o que precisa
bater e como mudar o número de vagas.

Para levantar tudo na ordem: [`RODAR_NO_NOTEBOOK.md`](RODAR_NO_NOTEBOOK.md).

---

## 1. O número de vagas mora em dois lugares, e eles têm de bater

| Onde | O quê | Valor hoje |
|---|---|---|
| `firmware/totem_next/config.h` | `constexpr uint8_t PORTAS` | `2` |
| banco (via `backend/preparar_totem.py`) | `--vagas N` | `2` (é o padrão com `--next`) |

```powershell
# de backend/ - duas vagas (padrão)
python preparar_totem.py --next
# uma ou quatro vagas
python preparar_totem.py --next --vagas 1
python preparar_totem.py --next --vagas 4
```

O firmware confere sozinho no handshake e avisa no monitor serial
(`firmware/totem_next/maquina.cpp`, `aplicarHandshake`):

```
handshake ok: 2 porta(s) no backend, 2 nesta placa
```

Se os números diferirem, vem logo abaixo uma linha
`ATENCAO: o backend tem N porta(s) e este firmware tem PORTAS = M (...)` dizendo o que
corrigir. **Vaga que o backend conhece e o firmware não, não existe para a placa:**
nenhum relé é tocado, e o comando de liberar volta com `porta_inexistente`. Botão de vaga
que o backend não conhece leva `422` (LCD `Vaga N` / `indisponivel`). Por isso diminuir
o `--vagas` **apaga** as vagas que sobram — para o painel não mostrar vaga sem relé e o
alocador não dividir o limite com uma vaga fantasma. Vagas com histórico de recarga
ficam offline e fora da placa, em vez de serem apagadas.

Nada mais no projeto depende do número de vagas: backend, painel e app montam a lista
a partir do banco.

## 2. Os números com duas vagas

| Item | Valor |
|---|---|
| Limite do estande | **15 kW** (`7,5 × vagas`) |
| Limite na ponta (× 0,5) | **7,5 kW** |
| Vagas no banco | **T1, T2** |
| Portas da placa | **1, 2** |
| Relés | GPIO **13** (vaga 1), **16** (vaga 2) |
| Botões | GPIO **32** (vaga 1), **33** (vaga 2) |
| Tarifa | R$ 1,15/kWh na escala (= por Wh real); na ponta × `ponta_multiplicador_tarifa` (padrão 1,5 do db/12 = R$ 1,725; o painel mostra o valor do estande) |

Water-filling com os dois celulares abaixo de 80% (cada um pede a vaga cheia, 7,5 kW).
Conferido em `backend/testes/test_next_sem_sensor.py::test_duas_vagas_e_o_padrao_e_os_numeros_do_roteiro`:

| Limite do estande | `fracao` vaga 1 / vaga 2 | Relés, numa janela de 30 s | Fechados juntos |
|---|---|---|---|
| 15 kW | 1,0 / 1,0 | os dois fechados direto | 2 |
| 7,5 kW (ou o pico) | 0,5 / 0,5 | vaga 1 de 0 a 15 s, vaga 2 de 15 a 30 s | 1 |
| 5 kW | 0,3333 / 0,3333 | 10 s cada | 1 |
| 3 kW | 0,2 / 0,2 | 6 s cada (o mínimo da vaga) | 1 |
| 2,5 kW | 0,3333 / **0** | só a primeira a chegar; a segunda pausa **sem encerrar** | 1 |

O mínimo é 20% da vaga (`demanda.MINIMO_FRACAO_POR_TEMPO`). Uma **tag nova** que ficaria
abaixo dele vai para a **fila de energia** com o saldo reservado (`test_duas_vagas_fila_de_energia_e_volta_sozinha`)
e liga sozinha no laço de 10 s do backend (`simulador.ciclo` → `recarga.promover_aguardando_energia`)
quando sobra potência.

**A fonte.** As duas portas saem do mesmo carregador de 5 V. Com fração ≤ 0,5 o
escalonador nunca fecha os dois relés juntos (`teste/teste_carga.cpp`, cenários de duas
vagas, `pico 1`) — o limite do estande protege a fonte do mesmo jeito que protege o quadro
de um condomínio.

## 3. Fiação

| Ligação | GPIO | Observação |
|---|---|---|
| Relé da vaga 1 (IN1) | **13** | módulo **ativo em HIGH** (`RELE_ATIVO_EM_LOW 0`) |
| Relé da vaga 2 (IN2) | **16** | **não o 12** (abaixo) |
| Botão da vaga 1, ao GND | **32** | pull-up interno |
| Botão da vaga 2, ao GND | **33** | pull-up interno |
| MFRC522 | SCK 18, MISO 19, MOSI 23, SDA/SS 5, RST 4 | **3,3 V**, nunca 5 V |
| LCD I2C 16x2 (opcional) | SDA 21, SCL 22 | 0x27 ou 0x3F, procurado no boot |
| LED de status | 2 | aceso = servidor aceitando a placa |

- **GPIO 12 é pino de boot (MTDI).** Em HIGH no boot a flash vai para 1,8 V e a placa
  reinicia em laço (`flash read err, 1000`), ou a gravação falha. O sketch de validação
  usava o 12 para a vaga 2; o firmware usa o **16**. Em módulo **WROVER**, o 16 é da
  PSRAM: use o **27**.
- **Sem LCD**, o firmware imprime `LCD nao encontrado (...)` e segue: o serial vira a tela.
- **Teste de segurança:** com a placa recém-ligada, **nenhum relé pode ficar fechado**.
  Se ficar, o módulo liga com LOW: troque `RELE_ATIVO_EM_LOW` para `1`.
- **USB-A:** ligue **D+ com D−** na porta. **USB-C fêmea:** 22 kΩ do VBUS a cada pino CC.

## 4. O que a placa manda e o que o backend responde

Protocolo v2 (ADR-015): toda requisição vai assinada com HMAC-SHA256 derivada da
`DEVICE_MASTER_KEY`, com `boot`, `seq` e `ts` contra repetição.

| Momento | Rota | A placa manda | O backend responde |
|---|---|---|---|
| ao ligar | `GET /hardware/v2/hora` | nada (rota pública) | `ts` do servidor, para a placa acertar o relógio |
| ao ligar | `POST /hardware/v2/handshake` | mac, ip, firmware | **as portas** (estado, `rele_esperado`, sessão aberta), `fator_escala`, intervalos |
| tag + botão | `POST /hardware/v2/rfid` | `porta`, `uid` | `acao` (`ligar`/`desligar`/`nenhuma`), `motivo`, `tela`, `fracao`, `carga` |
| a cada 6 s | `POST /hardware/v2/telemetria` | lote de leituras (W, Wh, V, A, `rele_ligado`) | por porta: `deve_liberar`, `estado`, `percentual`, `tempo_restante_min`, **`fracao`**, `carga`, custo |
| a cada 2 s | `GET /hardware/v2/comandos` | nada | ordens do app/painel/fila (`liberar`, `bloquear`, `solicitar_cartao`, `ping`) |

O UID vai **sem espaços e em maiúsculas** (`D3F5BFD9`; o sketch de validação imprimia
`D3 F5 BF D9`). Tag que ninguém vinculou volta com `cartao_nao_cadastrado` e o LCD mostra
o UID para a pessoa vincular no app.

Os dois campos que fazem o water-filling andar:

- **`fracao`** (0 a 1): quanto da janela de 30 s o relé fica fechado. É
  `alocado ÷ demanda`, calculado em `demanda.fracao_de_tempo`.
- **`carga`**: `capacidade_wh`, `potencia_max_w`, `percentual` e `alvo` do celular
  cadastrado. É com isso que a placa calcula a energia sem sensor — e é por aí que o
  **% real lido do celular** (Battery API, no Chrome do Android) corrige o modelo.

Tudo em **unidade bruta** (W, Wh, V, A). A escala 1:1000 (7,5 W da porta aparecem como
7,5 kW no produto, ADR-017) é aplicada só no backend.

## 5. O que é real e o que é modelo

Diga isto na banca, e está escrito no painel:

- **Reais:** o relé, o tempo que ele fica fechado, a tag, o botão, o saldo, a reserva, a
  cobrança, o estorno e a energia que o celular recebe de fato.
- **Modelo:** os **números** de potência e energia. Não há INA219, então a placa calcula
  a recarga pela física do celular (curva CC-CV: cheia até 80%, caindo até 100%) e
  grava tudo com origem **`simulado`**, nunca `medido`.
- **O que o modelo não sabe:** se o celular foi desplugado, nem se a fonte cedeu. Sem
  corrente medida, a vaga segue contando até a tag encerrar, o alvo chegar ou o valor
  reservado acabar. É a razão de existir um INA219 no projeto completo (ADR-022).
- `ACELERAR` em `config.h` é **1** em operação. Acima disso o modelo anda mais rápido
  que o relógio e a energia vira projeção — não apresente o valor cobrado como medido.

## 6. Conduzir pelo computador (plano B do leitor e do botão)

Monitor serial a **115200**, com **Nova linha**. Passa pelo mesmo
`POST /hardware/v2/rfid` da tag de verdade:

| Digite | Faz |
|---|---|
| `t D3F5BFD9` | aproxima a tag com esse UID |
| `b` / `b 2` | aperta o botão da vaga 1 / da vaga 2 |
| `s` | imprime %, W, Wh, tempo fechado e previsão de fim |

A cada 5 s a placa imprime esse mesmo status sozinha.

## 7. Validar

```powershell
cd backend
python -m pytest testes -q                       # 126 testes
cd ..
python -m pytest totem_virtual/testes -q         # 57 testes (~3,5 min)
cd firmware\totem_next
g++ -std=c++17 -O2 -o teste_carga teste/teste_carga.cpp carga.cpp && .\teste_carga
```

O último termina em `TUDO PASSOU` (precisa de um g++; o notebook do estande não tem).
Os testes de backend que seguram esta versão estão em
`backend/testes/test_next_sem_sensor.py`:

- `test_duas_vagas_e_o_padrao_e_os_numeros_do_roteiro`
- `test_duas_vagas_fila_de_energia_e_volta_sozinha`
- `test_uma_vaga_continua_funcionando_e_o_estande_inteiro_cabe_nela`
- `test_diminuir_as_vagas_apaga_as_que_sobraram`

Na bancada, o roteiro de ponta a ponta é a seção 9 de
[`RODAR_NO_NOTEBOOK.md`](RODAR_NO_NOTEBOOK.md).
