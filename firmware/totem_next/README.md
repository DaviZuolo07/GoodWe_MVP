# Totem Next: firmware do ESP32 (sem INA219, sem solar)

O hardware que vai para a banca do Next: **ESP32, LCD 16x2, MFRC522, 4 botões, relé de 4 canais, 2 USB-A + 2 USB-C**. Não há sensor de corrente nem painel solar.

A máquina de estados é a mesma do `firmware/totem_central/`, que é a tradução testada do `totem_virtual/firmware.py`: protocolo v2 com HMAC, handshake, tag primeiro, travas e fila offline. O `totem_central` continua no repositório como referência do hardware com 5 INA219 (ADR-022).

| Arquivo | O quê |
|---|---|
| `carga.h/.cpp` | **modelo de carga** do celular e **divisão por tempo** (escalonador McNaughton). C++ puro, testado no PC |
| `maquina.h/.cpp` | máquina de estados: enlace, interface, rodízio dos relés, telemetria, LCD |
| `hal.h/.cpp` | relés, botões, RFID, LCD, LED e Wi-Fi |
| `enlace.h/.cpp`, `textos.h/.cpp` | iguais aos do `totem_central` |
| `config.h` | pinos (a fiação que já existe) e constantes |
| `teste/teste_carga.cpp` | teste do modelo e da divisão no PC (não entra na gravação) |

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
limite para 3 celulares, 4 carregando -> 75% cada:
  vaga 1 [0,00-0,75)              vaga 3 [0,50-1,00)+[0,00-0,25)
  vaga 2 [0,75-1,00)+[0,00-0,50)  vaga 4 [0,25-1,00)
  em todo instante: 3 fechadas, 1 aberta, e a aberta vai rodando
```

- O rodízio é remontado a cada janela, e na hora se uma vaga entra ou sai.
- Fração ≥ 97%: o relé fica fechado direto, sem estalo à toa. Fatia mínima de 2 s.
- Desligar a recarga corta o relé na hora, sem esperar o rodízio.
- No painel do gestor, **Sala Next → Divisão por tempo** liga e desliga o Modbus 10025 de cada vaga. Desligado, a vaga volta a ser carga fixa e a gestão vira só admissão e fila.

O LCD alterna entre convite, quadro das 4 vagas, uma página por vaga e a tomada:

```
GoodWe ChargeOps   1:7.5W 2:75%     V2  45%  7.5W     Tomada  18.3W
Aproxime cartao    3:CARGA 4:LIVRE  Fim  32m T 75%    Total   0.42Wh
```

No quadro, `75%` é a vaga liberada esperando a vez dela no rodízio.

## Pinos (a fiação que já está montada)

| Ligação | GPIO |
|---|---|
| Relés das vagas 1–4 (IN1–IN4) | 13, 12, 14, 27. Módulo **ativo em HIGH** (`RELE_ATIVO_EM_LOW 0`) |
| Botões 1–4, ao GND | 32, 33, 25, 26 (pull-up interno) |
| MFRC522 | SCK 18, MISO 19, MOSI 23, SDA/SS 5, RST 4, **3,3 V** |
| LCD I2C | SDA 21, SCL 22, endereço 0x27 (alguns vêm em 0x3F) |
| LED de status | 2: aceso = servidor aceitando a placa |

**GPIO 12 é pino de boot.** Se a placa ficar reiniciando com o módulo de relé ligado, passe o fio do IN2 para o **GPIO 16** e troque `12` por `16` em `PINO_RELE`.

Se o seu módulo de relé ligar com LOW (optoacoplador), troque para `RELE_ATIVO_EM_LOW 1`. Teste: com a placa recém-ligada, **nenhum relé pode estalar**.

### USB só com VCC/GND (vale para as 4 portas)

- **USB-A:** ligue **D+ com D−** em cada porta. Sem isso o celular puxa só ~0,5 A, e o modelo (7,5 W) fica otimista.
- **USB-C fêmea:** um resistor de **22 kΩ do VBUS a cada pino CC** anuncia 1,5 A. Sem ele, cabo C-C pode não carregar nada.
- Fio de 1 mm² do +5 V até cada relé e de cada relé até a porta. Fonte 5 V com folga para 4 × 1,5 A.

## Bibliotecas

| Biblioteca | Versão testada |
|---|---|
| Placa **esp32** (Espressif), "ESP32 Dev Module" | 3.3.12 |
| ArduinoJson (Benoit Blanchon) | 7.4.3 |
| MFRC522 (GithubCommunity) | 1.4.12 |
| LiquidCrystal I2C (Frank de Brabander) | 1.1.2 |

Compilado em 22/10/2026 com `arduino-cli compile --fqbn esp32:esp32:esp32`: 83% da flash, 17% da RAM, **nenhum aviso destes arquivos**. Não precisa da Adafruit INA219.

Teste do modelo no PC (qualquer g++ ou `zig c++`), a partir desta pasta:

```
g++ -std=c++17 -O2 -o teste_carga teste/teste_carga.cpp carga.cpp && ./teste_carga
```

Deve terminar em `TUDO PASSOU` e imprimir o rodízio de 5 cenários.

## Gravar (no notebook do estande)

1. Dentro de `backend/`: `python preparar_totem.py --next`. Ele imprime o bloco do `segredos.h` com `DEVICE_ID` e `DEVICE_KEY_HEX`.
2. Copie `segredos.exemplo.h` para `segredos.h` e preencha a rede **2,4 GHz**, o `BACKEND_URL` (IP do notebook, visto com `ipconfig`) e a placa. O `segredos.h` não vai para o git.
3. Backend com `uvicorn main:app --host 0.0.0.0 --port 8000`. Libere a porta 8000 no firewall do Windows e **sincronize o relógio** (ADR-021).
4. Abra `totem_next.ino` na IDE do Arduino, placa "ESP32 Dev Module", grave e abra o monitor serial em 115200.

## Primeira ligação (ordem sugerida)

| # | Faça | Espere ver |
|---|---|---|
| 1 | Ligue **sem** celular | serial `placa ligou: reles abertos`; nenhum relé estala; LCD `Sem Wi-Fi` → `Acertando hora` → `Conectando...` |
| 2 | — | serial `handshake ok: 4 porta(s)`; LED aceso; LCD alterna convite e quadro |
| 3 | Tag desconhecida + botão 1 | LCD `Tag desconhecida` / `Cadastre no app` / `Tag D3F5BFD9`. Vincule esse UID no app (Configurações → cartão RFID) |
| 4 | Tag vinculada + botão 1 | `vaga 1 LIBERADA`; relé 1 fecha; saldo reservado no app; gráfico começa a andar |
| 5 | Mais 3 tags/contas nas vagas 2–4 | quatro relés fechados (limite 30 kW = 4 × 7,5) |
| 6 | Painel → Sala Next → Demanda do estande → 22,5 kW | serial `divisao por tempo: 1:75% 2:75% 3:75% 4:75%`; os relés passam a revezar, sempre 3 fechados |
| 7 | A mesma tag na vaga 1 | `vaga 1 CORTADA`; recibo com estorno no app |
| 8 | Desligue o Wi-Fi 2 min | aos 120 s, `trava offline`: relés abertos; com o Wi-Fi de volta, o handshake religa o que o backend ainda tem ativo |
