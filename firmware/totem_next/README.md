# Totem Next: firmware do ESP32 (sem INA219, sem solar)

<<<<<<< HEAD
O hardware que foi para a banca do Next: **ESP32, LCD 16x2, MFRC522, botão, módulo relé, USB-A e USB-C de painel**. Não há sensor de corrente nem painel solar.

**Uma vaga (23/10).** A montagem tem uma vaga, e o relé dela libera energia de verdade. Quem manda é `PORTAS`, em `config.h`:

```cpp
constexpr uint8_t PORTAS = 1;   // 1 = a montagem de 23/10 | 4 = o totem de quatro vagas
```

Esse número **tem de ser igual** ao `--vagas` do `backend/preparar_totem.py` (padrão `--next`: 1). O firmware confere no handshake e avisa no serial se diferirem. Contrato completo: [`docs/UMA_VAGA.md`](../../docs/UMA_VAGA.md).
=======
O hardware que vai para a banca do Next: **ESP32, LCD 16x2, MFRC522, 4 botões, relé de 4 canais, 2 USB-A + 2 USB-C**. Não há sensor de corrente nem painel solar.
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93

A máquina de estados é a mesma do `firmware/totem_central/`, que é a tradução testada do `totem_virtual/firmware.py`: protocolo v2 com HMAC, handshake, tag primeiro, travas e fila offline. O `totem_central` continua no repositório como referência do hardware com 5 INA219 (ADR-022).

| Arquivo | O quê |
|---|---|
| `carga.h/.cpp` | **modelo de carga** do celular e **divisão por tempo** (escalonador McNaughton). C++ puro, testado no PC |
<<<<<<< HEAD
| `maquina.h/.cpp` | máquina de estados: enlace, interface, rodízio dos relés, telemetria, LCD, comandos do serial |
| `hal.h/.cpp` | relés, botões, RFID, LCD, LED e Wi-Fi |
| `enlace.h/.cpp`, `textos.h/.cpp` | iguais aos do `totem_central` |
| `config.h` | **`PORTAS`**, pinos, `USAR_RELE`, `ACELERAR` e constantes |
| `teste/teste_carga.cpp` | teste do modelo e da divisão no PC (não entra na gravação) |

Dois interruptores em `config.h`, além do `PORTAS`:

| Constante | Padrão | Para quê |
|---|---|---|
| `USAR_RELE` | `1` | `0` não toca em nenhum pino de relé: bancada sem o módulo ligado |
| `ACELERAR` | `1.0f` | acima de 1, o modelo anda em time-lapse para a demonstração. A energia vira **projeção**: não apresente o valor cobrado como medido |

=======
| `maquina.h/.cpp` | máquina de estados: enlace, interface, rodízio dos relés, telemetria, LCD |
| `hal.h/.cpp` | relés, botões, RFID, LCD, LED e Wi-Fi |
| `enlace.h/.cpp`, `textos.h/.cpp` | iguais aos do `totem_central` |
| `config.h` | pinos (a fiação que já existe) e constantes |
| `teste/teste_carga.cpp` | teste do modelo e da divisão no PC (não entra na gravação) |

>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
## Como a energia é "medida" sem sensor

O ESP32 sabe duas coisas de verdade: **quando cada relé está fechado** (é ele quem fecha) e **qual celular está na vaga**. O backend informa a bateria em Wh, a potência máxima em W, o % de partida e o alvo. A cada 200 ms, para cada vaga com o relé fechado, ele faz:

```
potência = curva do celular no % atual    (cheia até 80%, cai em linha reta até 100%, depois 0,1 W)
energia += potência × 0,2 s
%       += energia × 92% / bateria
tomada   = soma do USB / 85% (fonte de 5 V) + 0,8 W da placa + 0,36 W por bobina fechada
```

A telemetria vai a cada 6 s, com o mesmo formato de antes (W, Wh, V, A e `rele_ligado`). O backend grava tudo com origem **`simulado`**, nunca `medido`. O painel e o app explicam de onde vem cada número.

O % real do celular corrige o modelo: se a pessoa abre o app no próprio celular que está carregando (Chrome do Android), o app manda o % da bateria, o backend recalcula e a placa sincroniza na resposta seguinte.

**O que o modelo não sabe:** se o celular foi desplugado. Sem corrente medida, a vaga segue contando até a tag encerrar, o alvo chegar ou o valor reservado acabar. Diga isso na banca. É a razão de existir um INA219 no projeto completo.

## Divisão por tempo (water-filling no relé)

O relé só liga ou desliga. Para dividir potência, o backend calcula a água no balde (`demanda.distribuir_fontes`) e manda a `fracao` de cada vaga, ou seja, quanto da janela de **30 s** ela fica fechada. O ESP32 monta o rodízio: as vagas ficam uma atrás da outra numa fita que dá a volta na janela (McNaughton). Assim, a qualquer instante, as vagas fechadas cabem no limite.

```
<<<<<<< HEAD
UMA VAGA (hoje), quadro de 7,5 kW baixado para 3,75 -> 50%:
  vaga 1 [0,00-0,50)      15 s fechado, 15 s aberto, e a conta segue andando

QUATRO VAGAS, limite para 3 celulares -> 75% cada:
=======
limite para 3 celulares, 4 carregando -> 75% cada:
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
  vaga 1 [0,00-0,75)              vaga 3 [0,50-1,00)+[0,00-0,25)
  vaga 2 [0,75-1,00)+[0,00-0,50)  vaga 4 [0,25-1,00)
  em todo instante: 3 fechadas, 1 aberta, e a aberta vai rodando
```

<<<<<<< HEAD
Com uma vaga o water-filling não some: o quadro do estande é do tamanho dela, e o que sobra do limite vira tempo de relé aberto. Abaixo de 20% da vaga (1,5 kW) ela **pausa** — fatia menor que isso não carrega e só faz o relé estalar.

=======
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
- O rodízio é remontado a cada janela, e na hora se uma vaga entra ou sai.
- Fração ≥ 97%: o relé fica fechado direto, sem estalo à toa. Fatia mínima de 2 s.
- Desligar a recarga corta o relé na hora, sem esperar o rodízio.
- No painel do gestor, **Sala Next → Divisão por tempo** liga e desliga o Modbus 10025 de cada vaga. Desligado, a vaga volta a ser carga fixa e a gestão vira só admissão e fila.

<<<<<<< HEAD
O LCD alterna entre convite, quadro das vagas, uma página por vaga e a tomada. Com uma vaga:

```
GoodWe ChargeOps   Vaga 1            V1  45%  7.5W     Tomada   9.6W
Aproxime cartao    7.5W              Fim  32m T 50%    Total   0.42Wh
```

Com quatro, o quadro vira `1:7.5W 2:75%` / `3:CARGA 4:LIVRE`.

=======
O LCD alterna entre convite, quadro das 4 vagas, uma página por vaga e a tomada:

```
GoodWe ChargeOps   1:7.5W 2:75%     V2  45%  7.5W     Tomada  18.3W
Aproxime cartao    3:CARGA 4:LIVRE  Fim  32m T 75%    Total   0.42Wh
```

>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
No quadro, `75%` é a vaga liberada esperando a vez dela no rodízio.

## Pinos (a fiação que já está montada)

<<<<<<< HEAD
Com `PORTAS = 1`, só a **primeira linha** de cada vetor é usada: o relé é o GPIO 13 e o botão é o GPIO 32. Os outros pinos ficam livres.

| Ligação | GPIO |
|---|---|
| Relés das vagas 1–4 (IN1–IN4) | **13**, 12, 14, 27. Módulo **ativo em HIGH** (`RELE_ATIVO_EM_LOW 0`) |
| Botões 1–4, ao GND | **32**, 33, 25, 26 (pull-up interno) |
=======
| Ligação | GPIO |
|---|---|
| Relés das vagas 1–4 (IN1–IN4) | 13, 12, 14, 27. Módulo **ativo em HIGH** (`RELE_ATIVO_EM_LOW 0`) |
| Botões 1–4, ao GND | 32, 33, 25, 26 (pull-up interno) |
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
| MFRC522 | SCK 18, MISO 19, MOSI 23, SDA/SS 5, RST 4, **3,3 V** |
| LCD I2C | SDA 21, SCL 22, endereço 0x27 (alguns vêm em 0x3F) |
| LED de status | 2: aceso = servidor aceitando a placa |

<<<<<<< HEAD
**GPIO 12 é pino de boot** (não usado com uma vaga). Se com quatro relés a placa ficar reiniciando, passe o fio do IN2 para o **GPIO 16** e troque `12` por `16` em `PINO_RELE`.

Se o seu módulo de relé ligar com LOW (optoacoplador), troque para `RELE_ATIVO_EM_LOW 1`. Teste: com a placa recém-ligada, **nenhum relé pode estalar**.

### USB só com VCC/GND

- **USB-A:** ligue **D+ com D−** na porta. Sem isso o celular puxa só ~0,5 A, e o modelo (7,5 W) fica otimista.
- **USB-C fêmea:** um resistor de **22 kΩ do VBUS a cada pino CC** anuncia 1,5 A. Sem ele, cabo C-C pode não carregar nada.
- Fio de 1 mm² do +5 V até o relé e do relé até a porta. Fonte 5 V com folga para 1,5 A por vaga.

## Conduzir pelo monitor serial (plano B do leitor e do botão)

115200, com **Nova linha**. Vale como a tag e o botão de verdade — passa pelo mesmo `POST /hardware/v2/rfid`:

| Digite | Faz |
|---|---|
| `t D3F5BFD9` | aproxima a tag com esse UID |
| `b` / `b 2` | aperta o botão da vaga 1 / da vaga 2 |
| `s` | imprime %, W, Wh, tempo fechado e previsão de fim |

A cada 5 s a placa imprime esse status sozinha.
=======
**GPIO 12 é pino de boot.** Se a placa ficar reiniciando com o módulo de relé ligado, passe o fio do IN2 para o **GPIO 16** e troque `12` por `16` em `PINO_RELE`.

Se o seu módulo de relé ligar com LOW (optoacoplador), troque para `RELE_ATIVO_EM_LOW 1`. Teste: com a placa recém-ligada, **nenhum relé pode estalar**.

### USB só com VCC/GND (vale para as 4 portas)

- **USB-A:** ligue **D+ com D−** em cada porta. Sem isso o celular puxa só ~0,5 A, e o modelo (7,5 W) fica otimista.
- **USB-C fêmea:** um resistor de **22 kΩ do VBUS a cada pino CC** anuncia 1,5 A. Sem ele, cabo C-C pode não carregar nada.
- Fio de 1 mm² do +5 V até cada relé e de cada relé até a porta. Fonte 5 V com folga para 4 × 1,5 A.
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93

## Bibliotecas

| Biblioteca | Versão testada |
|---|---|
| Placa **esp32** (Espressif), "ESP32 Dev Module" | 3.3.12 |
| ArduinoJson (Benoit Blanchon) | 7.4.3 |
| MFRC522 (GithubCommunity) | 1.4.12 |
| LiquidCrystal I2C (Frank de Brabander) | 1.1.2 |

<<<<<<< HEAD
As três bibliotecas se instalam pela própria IDE (Ferramentas → **Gerenciar Bibliotecas**). `ArduinoJson.h: No such file or directory` quer dizer que falta instalar neste computador — não é erro do código. Não precisa da Adafruit INA219.

Compilado em 22/10/2026 com `arduino-cli compile --fqbn esp32:esp32:esp32`: 83% da flash, 17% da RAM, **nenhum aviso destes arquivos**.
=======
Compilado em 22/10/2026 com `arduino-cli compile --fqbn esp32:esp32:esp32`: 83% da flash, 17% da RAM, **nenhum aviso destes arquivos**. Não precisa da Adafruit INA219.
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93

Teste do modelo no PC (qualquer g++ ou `zig c++`), a partir desta pasta:

```
g++ -std=c++17 -O2 -o teste_carga teste/teste_carga.cpp carga.cpp && ./teste_carga
```

<<<<<<< HEAD
Deve terminar em `TUDO PASSOU` e imprimir o rodízio de 8 cenários (5 com quatro vagas, 3 com uma).

## Gravar (no notebook do estande)

1. Dentro de `backend/`: `python preparar_totem.py --next`. Ele imprime o bloco do `segredos.h` com `DEVICE_ID` e `DEVICE_KEY_HEX`, e diz quantas vagas o banco ficou tendo.
2. Confira que o `PORTAS` do `config.h` é esse mesmo número.
3. Copie `segredos.exemplo.h` para `segredos.h` e preencha a rede **2,4 GHz**, o `BACKEND_URL` (IP do notebook, visto com `ipconfig`) e a placa. O `segredos.h` não vai para o git.
4. Backend com `uvicorn main:app --host 0.0.0.0 --port 8000`. Libere a porta 8000 no firewall do Windows e **sincronize o relógio** (ADR-021).
5. Abra `totem_next.ino` na IDE do Arduino, placa "ESP32 Dev Module", grave e abra o monitor serial em 115200.
=======
Deve terminar em `TUDO PASSOU` e imprimir o rodízio de 5 cenários.

## Gravar (no notebook do estande)

1. Dentro de `backend/`: `python preparar_totem.py --next`. Ele imprime o bloco do `segredos.h` com `DEVICE_ID` e `DEVICE_KEY_HEX`.
2. Copie `segredos.exemplo.h` para `segredos.h` e preencha a rede **2,4 GHz**, o `BACKEND_URL` (IP do notebook, visto com `ipconfig`) e a placa. O `segredos.h` não vai para o git.
3. Backend com `uvicorn main:app --host 0.0.0.0 --port 8000`. Libere a porta 8000 no firewall do Windows e **sincronize o relógio** (ADR-021).
4. Abra `totem_next.ino` na IDE do Arduino, placa "ESP32 Dev Module", grave e abra o monitor serial em 115200.
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93

## Primeira ligação (ordem sugerida)

| # | Faça | Espere ver |
|---|---|---|
| 1 | Ligue **sem** celular | serial `placa ligou: reles abertos`; nenhum relé estala; LCD `Sem Wi-Fi` → `Acertando hora` → `Conectando...` |
<<<<<<< HEAD
| 2 | — | serial `handshake ok: 1 porta(s) no backend, 1 nesta placa`; LED aceso; LCD alterna convite e quadro |
| 3 | Tag desconhecida + botão | LCD `Tag desconhecida` / `Cadastre no app` / `Tag D3F5BFD9`. Vincule esse UID no app (Configurações → cartão RFID) |
| 4 | Tag vinculada + botão | `vaga 1 LIBERADA`; o relé fecha e **o celular começa a carregar**; saldo reservado no app; gráfico andando |
| 5 | Digite `s` no serial | `status: vaga 1 carregando \| 21.3% de 100% \| 7.50 W (rele fechado) \| ...` |
| 6 | Painel → Sala Next → Demanda do estande → 3,75 kW | serial `divisao por tempo (janela 30s): 1:50%`; o relé passa a alternar 15 s fechado e 15 s aberto, e dá para ouvir |
| 7 | Volte para 7,5 kW | `1:100%`: o relé fecha direto de novo, sem perder a sessão |
| 8 | A mesma tag na vaga 1 | `vaga 1 CORTADA`; recibo com estorno no app |
| 9 | Desligue o Wi-Fi 2 min | aos 120 s, `trava offline`: relés abertos; com o Wi-Fi de volta, o handshake religa o que o backend ainda tem ativo |

Com quatro vagas, o passo 6 é o limite em 22,5 kW → `1:75% 2:75% 3:75% 4:75%`, com três relés fechados em rodízio.
=======
| 2 | — | serial `handshake ok: 4 porta(s)`; LED aceso; LCD alterna convite e quadro |
| 3 | Tag desconhecida + botão 1 | LCD `Tag desconhecida` / `Cadastre no app` / `Tag D3F5BFD9`. Vincule esse UID no app (Configurações → cartão RFID) |
| 4 | Tag vinculada + botão 1 | `vaga 1 LIBERADA`; relé 1 fecha; saldo reservado no app; gráfico começa a andar |
| 5 | Mais 3 tags/contas nas vagas 2–4 | quatro relés fechados (limite 30 kW = 4 × 7,5) |
| 6 | Painel → Sala Next → Demanda do estande → 22,5 kW | serial `divisao por tempo: 1:75% 2:75% 3:75% 4:75%`; os relés passam a revezar, sempre 3 fechados |
| 7 | A mesma tag na vaga 1 | `vaga 1 CORTADA`; recibo com estorno no app |
| 8 | Desligue o Wi-Fi 2 min | aos 120 s, `trava offline`: relés abertos; com o Wi-Fi de volta, o handshake religa o que o backend ainda tem ativo |
>>>>>>> a2c95a3286904a05abfc2a0d5e2c35817827cf93
