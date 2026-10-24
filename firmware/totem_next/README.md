# Totem Next: firmware do ESP32 (sem INA219, sem solar)

O hardware da banca do Next (24/10/2026): **ESP32, MFRC522, dois botões, módulo de relé, duas portas USB e LCD 16x2 (opcional)**. Não há sensor de corrente nem painel solar.

**Duas vagas.** Cada vaga é `carregador 5 V → relé → porta USB`. O relé **libera energia de verdade**, e só fecha depois de **dois passos**: o leitor lê uma tag **vinculada a uma conta no app** e a pessoa aperta o **botão da vaga**. O botão decide qual vaga recebe energia. Nenhuma tag fica fixa no código: quem autoriza é o backend (saldo, reserva, fila).

Quem manda no número de vagas é `PORTAS`, em `config.h`:

```cpp
constexpr uint8_t PORTAS = 2;   // 2 = a montagem de 24/10 | 1 ou 4 também funcionam
```

Esse número **tem de ser igual** ao `--vagas` do `backend/preparar_totem.py` (o padrão do `--next` é 2). O firmware confere no handshake e avisa no serial se diferirem. Contrato de integração: [`docs/UMA_VAGA.md`](../../docs/UMA_VAGA.md).

A máquina de estados é a mesma do `firmware/totem_central/` (a tradução testada do `totem_virtual/firmware.py`): protocolo v2 com HMAC, handshake, tag primeiro, travas de sessão e offline, fila de telemetria. O `totem_central` continua no repositório como referência do hardware com 5 INA219 (ADR-022).

| Arquivo | O quê |
|---|---|
| `carga.h/.cpp` | **modelo de carga** do celular e **divisão por tempo** (escalonador McNaughton). C++ puro, testado no PC |
| `maquina.h/.cpp` | máquina de estados: enlace, interface, rodízio dos relés, telemetria, LCD, comandos do serial |
| `hal.h/.cpp` | relés, botões, RFID, LCD (procurado no boot), LED e Wi-Fi |
| `enlace.h/.cpp`, `textos.h/.cpp` | iguais aos do `totem_central` |
| `config.h` | **`PORTAS`**, pinos, `USAR_RELE`, `ACELERAR` e constantes |
| `segredos.exemplo.h` | modelo do `segredos.h` (Wi-Fi, IP do notebook, placa). O `segredos.h` **não vai para o git** |
| `teste/teste_carga.cpp` | teste do modelo e da divisão no PC (não entra na gravação) |

Dois interruptores em `config.h`, além do `PORTAS`:

| Constante | Padrão | Para quê |
|---|---|---|
| `USAR_RELE` | `1` | `0` não toca em nenhum pino de relé: bancada sem o módulo ligado |
| `ACELERAR` | `1.0f` | acima de 1, o modelo anda em time-lapse. A energia vira **projeção**: não apresente o valor cobrado como medido. **Na banca: 1** |

## Pinos (a fiação do Gustavo, com UMA troca)

| Ligação | GPIO | Observação |
|---|---|---|
| Relé da vaga 1 (IN1) | **13** | módulo **ativo em HIGH** (`RELE_ATIVO_EM_LOW 0`) |
| Relé da vaga 2 (IN2) | **16** | **mudou**: o sketch de validação usava o 12 |
| Botão da vaga 1, ao GND | **32** | pull-up interno |
| Botão da vaga 2, ao GND | **33** | pull-up interno |
| MFRC522 | SCK 18, MISO 19, MOSI 23, SDA/SS 5, RST 4 | **3,3 V**, nunca 5 V |
| LCD I2C (opcional) | SDA 21, SCL 22 | 0x27 ou 0x3F: o firmware procura os dois |
| LED de status | 2 | aceso = servidor aceitando a placa |
| VCC do módulo de relé | 5 V (VIN) | GND comum com o ESP32 |

**Por que o IN2 saiu do GPIO 12.** O 12 (MTDI) é lido no boot: em HIGH, a flash vai para 1,8 V e a placa reinicia em laço com `flash read err, 1000` — e também pode falhar a gravação. Se acontece ou não depende do módulo de relé, do jumper H/L e de a placa estar ligando a frio. O 16 não tem função no boot. **Exceção:** em módulo **ESP32-WROVER** (escrito na lata metálica) o 16 é da PSRAM — use o **27**: mova o fio e troque `16` por `27` em `PINO_RELE`.

### USB só com VCC/GND

- **USB-A:** ligue **D+ com D−** na porta. Sem isso o celular puxa só ~0,5 A, e o modelo (7,5 W) fica otimista.
- **USB-C fêmea:** um resistor de **22 kΩ do VBUS a cada pino CC** anuncia 1,5 A. Sem ele, cabo C-C pode não carregar nada.
- Fio de 1 mm² do +5 V até o relé e do relé até a porta.

### Uma fonte para as duas portas

Cada celular puxa até ~1,5 A (7,5 W). Duas vagas fechadas **ao mesmo tempo** pedem até 3 A do mesmo carregador. Com um carregador de 1 A ou 2 A a tensão cai, o celular conecta e desconecta, e o modelo fica otimista.

O water-filling resolve isso do jeito que o produto resolve um quadro de condomínio: com o limite do estande em **7,5 kW** (ou no pico), cada vaga recebe **50%** e o rodízio põe uma vaga em `[0–15 s)` e a outra em `[15–30 s)` — **nunca as duas fechadas juntas**. As duas recargas seguem ativas e cobrando; a fonte só alimenta um celular por vez. Ver a tabela abaixo.

## Como a energia é "medida" sem sensor

O ESP32 sabe duas coisas de verdade: **quando cada relé está fechado** (é ele quem fecha) e **qual celular está na vaga**. O backend informa a bateria em Wh, a potência máxima em W, o % de partida e o alvo. A cada 200 ms, para cada vaga com o relé fechado:

```
potência = curva do celular no % atual    (cheia até 80%, cai em linha reta até 100%, depois 0,1 W)
energia += potência × 0,2 s
%       += energia × 92% / bateria
tomada   = soma do USB / 85% (fonte de 5 V) + 0,8 W da placa + 0,36 W por bobina fechada
```

A telemetria vai a cada 6 s (W, Wh, V, A e `rele_ligado`). O backend grava tudo com origem **`simulado`**, nunca `medido`. O % real do celular (app aberto no Chrome do Android) corrige o modelo na resposta seguinte.

**O que o modelo não sabe:** se o celular foi desplugado. Sem corrente medida, a vaga segue contando até a tag encerrar, o alvo chegar ou o valor reservado acabar. É a razão de existir um INA219 no projeto completo.

## Divisão por tempo (water-filling no relé)

O backend calcula a água no balde (`demanda.distribuir_fontes`) e manda a `fracao` de cada vaga: quanto da janela de **30 s** ela fica fechada. O ESP32 põe as vagas uma atrás da outra numa fita que dá a volta na janela (McNaughton). A qualquer instante, as fechadas cabem no limite.

**Duas vagas, celulares abaixo de 80%** (cada uma pede 7,5 kW na escala 1:1000 = 7,5 W reais):

| Limite do estande | Cada vaga | Serial do ESP32 | Relés, numa janela de 30 s | Fechados juntos |
|---|---|---|---|---|
| 15 kW (o padrão) | 7,5 kW | `1:100% 2:100%` | os dois fechados direto | **2** |
| 7,5 kW, ou **pico** (15 × 0,5) | 3,75 kW | `1:50% 2:50%` | vaga 1 de 0 a 15 s, vaga 2 de 15 a 30 s | **1** |
| 5 kW | 1,667 kW | `1:33% 2:33%` | 10 s cada, 10 s os dois abertos | **1** |
| 3 kW | 1,5 kW (o mínimo) | `1:20% 2:20%` | 6 s cada, 18 s os dois abertos | **1** |
| 2,5 kW | vaga 1: 2,5 kW · vaga 2: **0** | `1:33% 2:0%` | só a vaga 1, 10 s; a 2 pausa sem encerrar | **1** |

- O mínimo é 20% da vaga (`demanda.MINIMO_FRACAO_POR_TEMPO`): fatia menor que isso não carrega nada e só faz o relé estalar. Quem chegou por último pausa primeiro.
- Uma **tag nova** que ficaria abaixo do mínimo vai para a **fila de energia**, com o saldo já reservado, e liga sozinha quando sobra potência.
- Fração ≥ 97%: o relé fica fechado direto. Fatia mínima de 2 s. Desligar a recarga corta o relé na hora.
- **Sala Next → Divisão por tempo** liga e desliga o Modbus 10025 de cada vaga. Desligado, a vaga volta a ser carga fixa (só admissão e fila).

O LCD alterna entre convite, quadro das vagas, uma página por vaga carregando e a tomada:

```
GoodWe ChargeOps   1:7.5W            V1  21%  7.5W     Tomada  19.2W
Aproxime cartao    2:50%             Fim  96m T 50%    Total   0.42Wh
```

No quadro, `7.5W` é a vaga com o relé fechado agora e `50%` é a vaga liberada esperando a vez dela no rodízio.

## Bibliotecas (instalar na Arduino IDE 2)

| O quê | Onde | Versão testada |
|---|---|---|
| Placa **esp32** (Espressif Systems) | Ferramentas → Placa → **Gerenciador de Placas** → "esp32" | **3.3.12** |
| **ArduinoJson** (Benoit Blanchon) | Ferramentas → **Gerenciar Bibliotecas** | **7.4.3** |
| **MFRC522** (GithubCommunity) | Gerenciar Bibliotecas | **1.4.12** |
| **LiquidCrystal I2C** (Frank de Brabander) | Gerenciar Bibliotecas | **1.1.2** |
| Driver USB da placa | CP210x (Silicon Labs) ou CH340 (WCH), conforme o chip ao lado do conector | — |

`SPI`, `Wire`, `WiFi` e `HTTPClient` vêm com a placa esp32. Não precisa da Adafruit INA219 nem da `Arduino_JSON` (é outra biblioteca, com nome parecido; pode ficar instalada, não atrapalha). `ArduinoJson.h: No such file or directory` = biblioteca não instalada **neste** computador.

Na IDE: **Placa** "ESP32 Dev Module" · **Upload Speed** 921600 (se falhar, 115200) · **Porta** a COM que aparece ao plugar a placa.

Teste do modelo no PC (qualquer g++ ou `zig c++`), a partir desta pasta:

```
g++ -std=c++17 -O2 -o teste_carga teste/teste_carga.cpp carga.cpp && ./teste_carga
```

Deve terminar em `TUDO PASSOU` e imprimir o rodízio de 12 cenários (5 com quatro vagas, 3 com uma, 4 com duas). Nos de duas vagas, o `pico` tem de ser **1** sempre que a fração for 50% ou menos.

## Gravar

1. `backend/`: `python preparar_totem.py --next`. Ele imprime o bloco do `segredos.h` (`DEVICE_ID`, `DEVICE_KEY_HEX`) e termina com `Pronto (totem Next, 2 vaga(s))`.
2. Confira `constexpr uint8_t PORTAS = 2;` em `config.h`.
3. Copie `segredos.exemplo.h` para `segredos.h` e preencha: rede **2,4 GHz** (nome **exato**, com maiúsculas e espaços), senha, `BACKEND_URL` (`http://192.168.137.1:8000` no hotspot do Windows) e o bloco da placa.
4. Backend no ar com `uvicorn main:app --host 0.0.0.0 --port 8000`, e `http://192.168.137.1:8000/hardware/v2/hora` abrindo **num celular** da mesma rede.
5. Abra `totem_next.ino` (a IDE abre a pasta inteira, com as abas `carga.cpp`, `config.h`...), **Verificar** (✓), depois **Carregar** (→). Se travar em `Connecting....`, segure o botão **BOOT** da placa até começar a gravar.
6. Monitor serial em **115200**, final de linha **Nova linha**.

## O que o monitor serial tem de mostrar (partida boa)

```
[      120 ms] placa ligou: reles abertos (boot 2913471023, firmware totem-next-1.2, sem sensor: modelo de carga)
[      121 ms] 2 vaga(s) neste firmware
[      122 ms] LCD 16x2 em 0x27                      <- ou: LCD nao encontrado (...): seguindo sem tela
[      123 ms] monitor serial (Nova linha): t <UID> = tag | b [vaga] = botao | s = status
[      124 ms] Wi-Fi caiu                            <- normal: é a placa ainda conectando
[     5124 ms] status: sem Wi-Fi
[     6890 ms] Wi-Fi voltou (192.168.137.57)
[     7400 ms] servidor voltou a responder
[     7650 ms] handshake ok: 2 porta(s) no backend, 2 nesta placa
[    10124 ms] status: vaga 1 livre
[    10125 ms] status: vaga 2 livre
```

Os números de `ms`, o `boot` e o IP mudam; a **ordem** e os **textos** são esses. O LED da placa acende depois do handshake. A partir daí, a cada 5 s, uma linha `status:` por vaga.

Uma recarga, do começo ao fim (conta de teste com o celular padrão de 15 Wh, partindo de 20%):

```
tag D3F5BFD9: escolha a vaga
rfid vaga 2: iniciada / ligar
vaga 2 LIBERADA (rfid)
vaga 2: celular de 15.0 Wh, ate 7.5 W, partindo de 20% (modelo)
divisao por tempo (janela 30s): 1:0% 2:100%
status: vaga 2 carregando | 20.4% de 100% | 7.50 W (rele fechado) | 0.031 Wh | tempo fechado 100% | fim ... min
...
tag D3F5BFD9: escolha a vaga
rfid vaga 2: encerrada / desligar
vaga 2 CORTADA (rfid)
```

## Primeira ligação (ordem sugerida)

| # | Faça | Espere ver |
|---|---|---|
| 1 | Ligue **sem** celular | a partida acima; **nenhum relé estala**; LCD `Sem Wi-Fi` → `Acertando hora` → `Conectando...` → convite |
| 2 | Tag desconhecida + botão 1 | LCD `Tag nao cadastrada` / `Cadastre no app` / `Tag D3F5BFD9`. Vincule esse UID no app (Configurações → cartão RFID) |
| 3 | Botão **sem** tag | LCD `Aproxime o` / `cartao primeiro`; nada fecha |
| 4 | Tag vinculada + botão 1 | LCD `Vaga 1 liberada` / `Boa recarga, <nome>!`; serial `vaga 1 LIBERADA (rfid)`; o relé 1 fecha (**clique**) e o celular começa a carregar; saldo reservado no app |
| 5 | Outra tag vinculada + botão 2 | `vaga 2 LIBERADA`; serial `1:100% 2:100%`; os dois relés fechados |
| 6 | Painel → Sala Next → Demanda do estande → 7,5 kW | em ≤ 10 s, `1:50% 2:50%`; os relés **alternam a cada 15 s**, um clique de cada lado |
| 7 | Volte para 15 kW | `1:100% 2:100%`, sem perder as sessões |
| 8 | A mesma tag na mesma vaga | LCD `Vaga N encerrada` / `Custo R$ x,xx` / `Retire o celular`; serial `vaga N CORTADA (rfid)`; recibo com estorno no app |
| 9 | Desligue o Wi-Fi 2 min | aos 120 s, `tempo demais sem servidor: reles abertos`; com o Wi-Fi de volta, o handshake religa o que o backend ainda tem ativo |

O LCD tem 16 colunas: texto do backend maior que isso quebra na palavra e vira páginas de 2 linhas a cada 2 s. A tag nova aparece como `Tag nao` / `cadastrada`, depois `Cadastre no app` / `Tag D3F5BFD9`; a fila, como `Vaga 2 na espera` / `Sem energia`, depois `agora` / `Fila: 1`...

## Conduzir pelo monitor serial (plano B do leitor e do botão)

115200, com **Nova linha**. Vale como a tag e o botão de verdade — passa pelo mesmo `POST /hardware/v2/rfid`:

| Digite | Faz |
|---|---|
| `t D3F5BFD9` | aproxima a tag com esse UID |
| `b` / `b 2` | aperta o botão da vaga 1 / da vaga 2 |
| `s` | imprime %, W, Wh, tempo fechado e previsão de fim agora |

## Se der errado

| Sintoma | Causa | O que fazer |
|---|---|---|
| Reinicia em laço, `flash read err, 1000`, ou a gravação não passa de `Connecting...` | algo segurando um pino de boot (12, 0, 2, 15) em nível errado | confira que **nada** está no GPIO 12 (o IN2 vai no 16); desligue o VCC do módulo de relé, grave, e religue; segure **BOOT** durante o `Connecting...` |
| `LCD nao encontrado` | LCD não montado, solto, ou em outro endereço | sem LCD o totem funciona: o serial é a tela. Com LCD montado: confira SDA 21 / SCL 22 / 5 V / GND e o potenciômetro de contraste atrás |
| LCD aceso sem letras (blocos ou nada) | contraste | gire o potenciômetro azul atrás do LCD |
| Relé estala ao ligar a placa | módulo ativo em LOW, ou o pino flutua antes do `setup` | se ficar **fechado** depois do boot: `RELE_ATIVO_EM_LOW 1` e grave. Um clique curto no boot com o relé abrindo em seguida não é perigoso: o firmware abre todos antes de qualquer outra coisa |
| `recusado (fora_da_janela)` / LCD `Relogio servidor` | relógio do notebook errado | Windows → Data e hora → **Sincronizar agora**; reinicie o `uvicorn` |
| `recusado (assinatura_invalida)` / LCD `Chave invalida` | `segredos.h` de outro `.env` (outra `DEVICE_MASTER_KEY`) ou de outra placa | `python preparar_totem.py --next` no notebook **do estande**, recopie o bloco e grave de novo |
| `BLOQUEADO (...)` | 3 recusas seguidas (ADR-021) | corrija a causa acima; a placa tenta de novo sozinha a cada 1 min (ou aperte EN) |
| `ATENCAO: o backend tem 1 porta(s) e este firmware tem PORTAS = 2` | `--vagas` ≠ `PORTAS` | `python preparar_totem.py --next --vagas 2` e reinicie a placa (EN) |
| `status: sem Wi-Fi` para sempre | rede 5 GHz, nome ou senha diferentes | hotspot em **2,4 GHz**; `WIFI_SSID` idêntico ao nome da rede |
| `sem resposta do servidor` | IP errado, firewall, uvicorn sem `--host 0.0.0.0` | abra `http://<IP>:8000/hardware/v2/hora` num celular da mesma rede; se não abrir, o problema é a rede, não a placa |
| Celular conecta e desconecta com as duas vagas fechadas | o carregador não aguenta duas portas | limite do estande em 7,5 kW: uma vaga por vez (seção da fonte acima) |
