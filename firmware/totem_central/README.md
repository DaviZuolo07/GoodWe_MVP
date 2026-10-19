# Totem Central — firmware do ESP32

Tradução de `totem_virtual/firmware.py` (a referência testada) para o ESP32. Mesma máquina de estados, mesmos nomes de constantes, mesmo protocolo (v2 com HMAC + Totem v2.1). Contrato: `docs/contratos/maquina_de_estados_totem.md`. Hardware: `docs/decisoes/ADR-022_totem_fisico.md`.

| Arquivo | Equivale a |
|---|---|
| `maquina.h/.cpp` | `totem_virtual/firmware.py` |
| `hal.h/.cpp` | a parte HAL de `totem_virtual/bancada.py` |
| `enlace.h/.cpp` | `backend/testes/placa_v2.py` + `totem_virtual/rede.py` |
| `textos.h/.cpp` | `totem_virtual/lcd.py` + as tabelas de tela |
| `config.h` | `totem_virtual/config.py` + pinos |

A placa v1 (`firmware/chargeops_esp32/`) continua como está.

## Montagem

```
Fonte 5 V 10 A ─┬─ barramento 5 V ─┬─ relé 1 ─ INA219 0x40 ─ USB vaga 1
                │                  ├─ relé 2 ─ INA219 0x41 ─ USB vaga 2
                │                  ├─ relé 3 ─ INA219 0x44 ─ USB vaga 3
                │                  └─ NF ┐
                │                        ├─ COM do REVERSOR ─ relé 4 ─ INA219 0x45 ─ USB vaga 4
Painel 1 W ─ INA219 painel ─ TP4056 ─ B+ ─ 18650 ─┐     │
                             OUT+ ─ MT3608 (5,0 V) ─ NA ┘
                └─ VIN do ESP32 (5 V) e VCC dos módulos

18650 (+) ── R1 10 kΩ ──┬── GPIO 35 (ADC1)      divisor da bateria:
                        ├── R2 10 kΩ ── GND     mede nos terminais da 18650,
                        └── C 100 nF ── GND     ANTES do MT3608
```

**São 5 INA219: 4 nas vagas e 1 no painel** (ADR-022 revisto em 19/10/2026).
A 18650 não tem INA219: a tensão dela vem do ADC, e a corrente é **deduzida**
(o que a vaga 4 consome e o painel não entrega, sai da bateria).

| Ligação | GPIO / endereço |
|---|---|
| Relés das vagas 1–4 (IN1–IN4) | 26, 27, 25, 33 |
| Relé reversor da vaga 4 | 32 (desligado = rede/NF, ligado = solar/NA) |
| Botões 1–4, ao GND | 13, 14, 15, 34 — **o 34 precisa de 10 kΩ ao 3V3** |
| MFRC522 | SCK 18, MISO 19, MOSI 23, SDA/SS 5, RST 4, **3,3 V** |
| I2C principal (`Wire`) | SDA 21, SCL 22: LCD 0x27 e os 4 INA219 das vagas |
| I2C solar (`Wire1`) | SDA 17, SCL 16: o INA219 do **painel**, 0x40 sem solda |
| ADC da bateria 18650 | **35** (ADC1_CH7, só entrada) pelo divisor 10k + 10k. **Nunca um pino do ADC2**: ele não funciona com o Wi-Fi ligado |
| LED de status | 2 (o da placa): aceso = servidor aceitando a placa |

INA219 das vagas: 0x40 sem solda, 0x41 com A0, 0x44 com A1, 0x45 com A0+A1. Cada um em série no +5 V **depois** do relé (Vin+ do lado do relé, Vin− do lado da USB).

INA219 do painel: lado alto, **Vin+ no + do painel** e Vin− no IN+ do TP4056. Mede a GERAÇÃO que entra no carregador (com a 18650 cheia o TP4056 para de puxar e a leitura cai — é a geração aproveitada, não a potencial). Calibrado em 16 V / 400 mA: 8x mais resolução que a faixa de 2 A, e enxerga o painel em luz fraca.

Divisor da bateria: **o GND da 18650 tem de ser o GND do ESP32** (sem terra comum o ADC lê lixo). Abaixo de 2,0 V (`V_BATERIA_AUSENTE`) a leitura vale "ausente": a vaga 4 fica na rede e a bateria não vai no lote — não se decide no escuro.

Ajuste o MT3608 para 5,0–5,1 V **antes** de ligar no reversor.

### USB só com VCC/GND

- **USB-A:** ligue **D+ com D−** em cada porta. Sem isso o celular puxa só ~0,5 A.
- **USB-C fêmea:** um resistor de **22 kΩ do VBUS a cada pino CC** (anuncia 1,5 A). Sem isso, cabo C-C pode não carregar. Módulos com 5,1 kΩ ao GND são do lado do celular e não servem.

## Bibliotecas (Gerenciador de Bibliotecas)

| Biblioteca | Versão testada |
|---|---|
| Placa **esp32** (Espressif), "ESP32 Dev Module" | 3.3.12 |
| ArduinoJson (Benoit Blanchon) | 7.4.3 |
| Adafruit INA219 (instala junto a Adafruit BusIO) | 1.2.3 |
| MFRC522 (GithubCommunity) | 1.4.12 |
| LiquidCrystal I2C (Frank de Brabander) | 1.1.2 |

Compilado com `arduino-cli compile --fqbn esp32:esp32:esp32`: 83% da flash, 18% da RAM, nenhum aviso vindo destes arquivos.

## Gravar

1. Dentro de `backend/`: `python preparar_totem.py --fisico --sem-env` e copie `DEVICE_ID` e `DEVICE_KEY_HEX` da saída (canal privado, nunca chat/commit).
2. Copie `segredos.exemplo.h` para `segredos.h` e preencha Wi-Fi, `BACKEND_URL` (IP do PC, sem barra no fim) e a placa.
3. Backend com `uvicorn main:app --host 0.0.0.0 --port 8000` e **relógio do Windows sincronizado** (ADR-021).
4. Grave e abra o monitor serial em 115200.

O totem virtual e o ESP32 usam a mesma placa no banco: rode um de cada vez.

## Primeira ligação na bancada (ordem sugerida)

| # | Faça | Espere ver |
|---|---|---|
| 1 | Ligue **sem** celulares | serial: `placa ligou: reles abertos`; nenhum relé estala; LCD `ChargeOps GoodWe` / `Sem Wi-Fi` → `Acertando hora` → `Conectando...` |
| 2 | — | serial: `handshake ok: 4 porta(s)`; LED aceso; LCD alterna `Aproxime cartao` e `1:LIVRE 2:LIVRE` |
| 3 | Se o serial avisar que um INA219 não respondeu | confira solda A0/A1 e o barramento (vagas no 21/22, painel no 17/16) |
| 4 | Encoste a tag da Ana, aperte o botão 1 | só o relé 1 fecha; LCD `Vaga 1 liberada`; volta sozinho para a espera |
| 5 | Plugue um celular na vaga 1 | quadro mostra `1:7.4W` (ou o que ele puxar de verdade) |
| 6 | Tag da Bia, botão 3 | relé 3 fecha; 1 e 3 carregando juntos |
| 7 | Tag da Ana, botão 1 | **só** o relé 1 abre; LCD `Vaga 1 encerrou` |
| 8 | Vaga 4 com sol/bateria carregada | `4:7.4WS`; serial `fonte da vaga 4 -> solar` |
| 9 | Desligue o roteador 2 min com uma vaga carregando | a recarga segue; aos 120 s os relés abrem (`trava offline`); com o Wi-Fi de volta, o handshake religa o que o backend ainda considerar ativo |
| 10 | Tire a placa da tomada no meio de uma recarga e religue | relés abertos no boot; depois do handshake, a vaga volta e a energia continua de onde parou |

## Calibrar na bancada (20 min)

1. Com a 18650 carregada, meça a tensão nos terminais dela **com o multímetro** e leia a do serial (`fonte` no lote, ou a página do totem).
2. `AJUSTE_ADC = multímetro / lido` em `config.h`. Recompile.
3. Repita com a bateria mais baixa (~3,5 V): tem de bater em até 0,03 V. Se não bater nos dois pontos, meça R1 e R2 e use os valores reais em `DIVISOR_BATERIA = (R1 + R2) / R2`.
4. Com a vaga 4 carregando no sol, anote em que tensão o celular para de carregar bem: é o `V_BATERIA_CORTE` real (o 3,30 V atual sai do modelo do totem virtual). `V_BATERIA_VOLTA` fica ~0,3 V acima.

`HTTP_TIMEOUT_MS` é **8000** desde 19/10 (o backend consulta o Supabase no Canadá dentro da requisição; o handshake leva ~5 s do Brasil). Antes de mudar, meça: `Measure-Command { Invoke-WebRequest http://localhost:8000/hardware/v2/hora }` cinco vezes e use o dobro do pior.
