# Totem de UMA vaga — integração (23/10/2026)

A montagem que foi para a banca tem **uma vaga**, e o relé dela **libera energia de
verdade** para o celular. Este documento é o contrato entre o firmware do Gustavo e
o backend: o que mudou, o que precisa bater, e como voltar para quatro vagas.

Para levantar tudo na ordem: [`RODAR_NO_NOTEBOOK.md`](RODAR_NO_NOTEBOOK.md).

---

## 1. O número de vagas mora em dois lugares, e eles têm de bater

| Onde | O quê | Valor hoje |
|---|---|---|
| `firmware/totem_next/config.h` | `constexpr uint8_t PORTAS` | `1` |
| banco (via `backend/preparar_totem.py`) | `--vagas N` | `1` (é o padrão com `--next`) |

```powershell
# de backend/ - uma vaga (padrão)
python preparar_totem.py --next
# quatro vagas
python preparar_totem.py --next --vagas 4
```

O firmware confere sozinho no handshake e avisa no monitor serial:

```
handshake ok: 1 porta(s) no backend, 1 nesta placa
```

Se os números diferirem, a linha vira um `ATENCAO:` dizendo exatamente o que
corrigir. **Vaga que o backend conhece e o firmware não, não existe para a placa:**
nenhum relé é tocado, e o comando de liberar volta com `porta_inexistente`. Por isso
`--vagas 1` **apaga** T2..T4 do banco — para o painel não mostrar vaga sem relé e o
alocador não dividir o limite com uma vaga fantasma. Se as vagas que saem já tiverem
histórico de recarga, elas ficam offline e fora da placa, em vez de serem apagadas.

Nada mais no projeto depende do número de vagas: backend, painel e app montam a lista
a partir do banco.

## 2. O que mudou de 4 para 1

| Item | 4 vagas | 1 vaga |
|---|---|---|
| Limite do estande | 30 kW | **7,5 kW** (`7,5 × vagas`) |
| Limite na ponta (× 0,5) | 15 kW | **3,75 kW** |
| Vagas no banco | T1..T4 | **T1** |
| Portas da placa | 1..4 | **1** |
| Water-filling | reparte entre as vagas | **recorta a própria vaga no tempo** |
| LCD, página do quadro | `1:7.5W 2:75%` / `3:CARGA 4:LIVRE` | `Vaga 1` / `7.5W` |
| Relés usados | GPIO 13, 12, 14, 27 | **GPIO 13** |
| Botões usados | GPIO 32, 33, 25, 26 | **GPIO 32** |

Com uma vaga o water-filling não some — ele aparece **dentro** da vaga. O quadro do
estande é do tamanho dela, então baixar o limite vira tempo de relé fechado:

| Limite do estande | A vaga recebe | Fração | O relé, numa janela de 30 s |
|---|---|---|---|
| 7,5 kW | 7,5 kW | 100% | fechado direto (sem estalo à toa) |
| 3,75 kW | 3,75 kW | 50% | 15 s fechado, 15 s aberto |
| 1,5 kW | 1,5 kW | 20% | 6 s fechado, 24 s aberto |
| 1 kW | 0 | — | aberto: **pausada**, abaixo do mínimo da vaga |

O mínimo é 20% da vaga (`demanda.MINIMO_FRACAO_POR_TEMPO`): fatia menor que isso não
carrega nada e só faz o relé estalar. Uma tag nova nesse estado vai para a **fila de
energia**, com o saldo já reservado, e liga sozinha quando sobra potência.

## 3. Fiação da vaga única

| Ligação | GPIO | Observação |
|---|---|---|
| Relé da vaga 1 (IN1) | **13** | módulo **ativo em HIGH** (`RELE_ATIVO_EM_LOW 0`) |
| Botão da vaga 1, ao GND | **32** | pull-up interno |
| MFRC522 | SCK 18, MISO 19, MOSI 23, SDA/SS 5, RST 4 | **3,3 V**, nunca 5 V |
| LCD I2C 16x2 | SDA 21, SCL 22 | endereço 0x27 (alguns vêm em 0x3F) |
| LED de status | 2 | aceso = servidor aceitando a placa |

- **Teste de segurança:** com a placa recém-ligada, **nenhum relé pode estalar**. Se
  estalar, o módulo liga com LOW: troque `RELE_ATIVO_EM_LOW` para `1`.
- **USB-A:** ligue **D+ com D−** na porta. Sem isso o celular puxa ~0,5 A e o modelo
  (7,5 W) fica otimista.
- **USB-C fêmea:** **22 kΩ do VBUS a cada pino CC** anuncia 1,5 A. Sem isso, cabo C-C
  pode não carregar nada.
- Fio de 1 mm² do +5 V ao relé e do relé à porta. Fonte de 5 V com folga para 1,5 A.
- **GPIO 12 é pino de boot**, mas com uma vaga ele nem é usado. Se um dia voltarem os
  quatro relés e a placa reiniciar em laço, passe o IN2 para o GPIO 16.

## 4. O que a placa manda e o que o backend responde

Protocolo v2 (ADR-015): toda requisição vai assinada com HMAC-SHA256 derivada da
`DEVICE_MASTER_KEY`, com `boot`, `seq` e `ts` contra repetição.

| Momento | Rota | A placa manda | O backend responde |
|---|---|---|---|
| ao ligar | `GET /hardware/v2/hora` | nada (rota pública) | `ts` do servidor, para a placa acertar o relógio |
| ao ligar | `POST /hardware/v2/handshake` | mac, ip, firmware | **as portas** (estado, `rele_esperado`, sessão aberta), `fator_escala`, intervalos |
| tag + botão | `POST /hardware/v2/rfid` | `porta`, `uid` | `acao` (`ligar`/`desligar`/`nenhuma`), `motivo`, `tela`, `fracao`, `carga` |
| a cada 6 s | `POST /hardware/v2/telemetria` | lote de leituras (W, Wh, V, A, `rele_ligado`) | por porta: `deve_liberar`, `estado`, `percentual`, `tempo_restante_min`, **`fracao`**, `carga`, custo |
| a cada 2 s | `GET /hardware/v2/comandos` | nada | ordens do app/painel (`ligar`, `desligar`, `solicitar_cartao`, `ping`) |

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

- **Reais:** o relé, o tempo que ele fica fechado, a tag, o botão, o saldo, a cobrança
  e a energia que o celular recebe de fato.
- **Modelo:** os **números** de potência e energia. Não há INA219, então a placa calcula
  a recarga pela física do celular (curva CC-CV: cheia até 80%, caindo até 100%) e
  grava tudo com origem **`simulado`**, nunca `medido`.
- **O que o modelo não sabe:** se o celular foi desplugado. Sem corrente medida, a vaga
  segue contando até a tag encerrar, o alvo chegar ou o valor reservado acabar. É a
  razão de existir um INA219 no projeto completo (ADR-022).
- `ACELERAR` em `config.h` é **1** em operação. Acima disso o modelo anda mais rápido
  que o relógio (time-lapse de demonstração) e a energia vira projeção — não apresente
  o valor cobrado como medido nesse modo.

## 6. Conduzir pelo computador (plano B do leitor e do botão)

Monitor serial a **115200**, com **Nova linha**. Passa pelo mesmo
`POST /hardware/v2/rfid` da tag de verdade:

| Digite | Faz |
|---|---|
| `t D3F5BFD9` | aproxima a tag com esse UID |
| `b` | aperta o botão da vaga 1 (`b 2` para a vaga 2, quando houver) |
| `s` | imprime %, W, Wh, tempo fechado e previsão de fim |

A cada 5 s a placa imprime esse mesmo status sozinha.

## 7. Validar

```powershell
cd backend
python -m pytest testes -q                       # 124 testes
cd ..
python -m pytest totem_virtual/testes -q         # 57 testes (~3 min)
cd firmware\totem_next
g++ -std=c++17 -O2 -o teste_carga teste/teste_carga.cpp carga.cpp && .\teste_carga
```

O último termina em `TUDO PASSOU` e imprime o rodízio, inclusive os três cenários de
uma vaga. Os testes de backend que seguram esta versão estão em
`backend/testes/test_next_sem_sensor.py`:

- `test_uma_vaga_e_o_padrao_e_o_estande_inteiro_cabe_nela`
- `test_diminuir_as_vagas_apaga_as_que_sobraram`
- `test_sem_next_a_vaga_solar_exige_quatro`

Na bancada, o roteiro de ponta a ponta é a seção 9 de
[`RODAR_NO_NOTEBOOK.md`](RODAR_NO_NOTEBOOK.md).
