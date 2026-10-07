# ADR-022 — Totem Central físico: o hardware real e o que muda no contrato

- **Status:** ACEITO em 06/10/2026 (Davi) para `totem_virtual/`, `firmware/` e a máquina de estados; P1–P4 são pedidos ao Daniel
- **Chat:** V2 — laço de 401, totem físico e firmware
- **Entrega:** `docs/contratos/maquina_de_estados_totem.md` (§2, §8, §9, §13), `totem_virtual/` (física, LCD, firmware, página, roteiro, testes), `firmware/totem_central/`
- **Regra seguida:** o contrato muda primeiro, depois o totem virtual, depois o `.ino` (contrato, cabeçalho)
- **Pedido:** `docs/decisoes/pedidos/2026-10-06_totem_para_backend_v2.md`

---

## 0. Hardware confirmado em 06/10

| Peça | Como entra |
|---|---|
| ESP32 DevKit V1 (WROOM) | cérebro |
| Fonte chaveada 5 V 10 A | barramento de 5 V (perfboard, fio de 1 mm²) — a "rede" da maquete |
| Módulo relé de 4 canais | um canal por vaga, no +5 V de cada USB |
| **1 relé reversor SPDT** (módulo de 1 canal, NA/NF/COM) | **fonte da vaga 4**: NF = barramento (rede), NA = saída do MT3608 (solar) |
| Painel 5 V 1 W → TP4056 → 18650 2000 mAh → MT3608 (5 V) | subsistema solar, **dedicado à vaga 4**, nunca no barramento |
| **5 × INA219** | 4 vagas + 1 na bateria solar |
| MFRC522 (SPI) | leitor de tag |
| **LCD 16x2** com módulo I2C (PCF8574) | tela |
| 4 botões NA | escolha da vaga |
| USB fêmea de painel (A e C), só VCC/GND | saída de cada vaga |

## D1. Solar: comutado só na vaga 4, nunca em paralelo

**Decisão.** A bateria solar (via MT3608) alimenta **só a vaga 4**, por um relé reversor: COM → relé da vaga 4 → INA219 → USB. Desenergizado (NF) = rede; energizado (NA) = solar. O reversor é *break-before-make* por construção: as duas fontes nunca se tocam.

| Situação | Reversor | Por quê |
|---|---|---|
| Relé da vaga 4 aberto | rede (bobina desligada) | sem carga, o TP4056 carrega a bateria inteira com o painel |
| Backend mandou `fonte: "rede"` | rede | Modbus 10024 ligado e bateria abaixo do 10030 (ADR-018 D6) |
| Bateria abaixo de `V_BATERIA_CORTE` por `QUEDA_MS` | rede, e `bateria_ok = false` | proteção local da 18650, vale também offline |
| Caso contrário (`solar` ou sem resposta ainda) e `bateria_ok` | **solar** | é a vaga solar |
| Voltar de rede para solar | só depois de `FONTE_MIN_MS` (30 s) na rede | não gastar o relé com vai-e-volta |

`bateria_ok` volta a `true` com a bateria em repouso ≥ `V_BATERIA_VOLTA`.

**Rejeitado — injetar o MT3608 no barramento (o plano original).** Duas fontes em paralelo sem balanceamento: com o MT3608 acima da fonte, os 4 celulares (~8 A) puxam dele (o módulo aguenta ~2 A); abaixo, ele não entrega nada. Ou queima, ou enfeita.
**Rejeitado — dois relés simples (painel / bateria) com intertravamento por software.** Era o contrato antigo; com o reversor o "nunca os dois" é mecânico, não depende de o firmware acertar.

**Consequência no contrato:** a fonte `painel` deixa de ser uma fonte da vaga (não há caminho direto painel → vaga; o painel só carrega a bateria). O estado `nenhuma` some: o reversor sempre aponta para uma das duas. A troca deixa de passar 200 ms "sem fonte" — quem garante a separação é o contato.

## D2. Medição: 5 INA219 em dois barramentos I2C

| Barramento | Pinos | Endereços |
|---|---|---|
| `Wire` | SDA 21, SCL 22 | LCD 0x27 · vaga 1 0x40 (sem solda) · vaga 2 0x41 (A0) · vaga 3 0x44 (A1) · vaga 4 0x45 (A0+A1) |
| `Wire1` | SDA 17, SCL 16 | **solar 0x40** (sem solda) |

O INA219 só tem 4 endereços fáceis por jumper; o ESP32 tem **dois controladores I2C de hardware**, então o quinto sensor vai sozinho no segundo barramento. Sem multiplexador e sem solda em pino.

**Sensor solar em série com a bateria** (entre o B+ do TP4056 e o + da 18650, Vin+ do lado da bateria): mede a tensão da 18650 (é dela que o backend estima o SOC) e a corrente **com sinal** — positiva descarregando, negativa carregando. Atende o pedido do Daniel (ADR-018 P3) agora que a vaga 4 tem caminho de rede.

**Rejeitado — INA219 na saída do MT3608.** Mediria 5 V constantes: o backend leria a bateria sempre "cheia" pela curva da 18650.
**Rejeitado — multiplexador TCA9548A.** Mais uma peça e mais um ponto de falha para resolver o que o segundo I2C resolve de graça.

**Consequência no contrato:** `fontes` passa a ter **só `bateria`**, com sinal. O painel não é medido; a geração do painel continua vindo do simulador, rotulada `simulado` (fallback que o backend já tem).

## D3. LCD 16x2

- Toda linha tem 16 colunas; a tela tem 2 linhas.
- A `tela` do backend (até 4 linhas de 20) é **re-quebrada** em 16 colunas sem cortar palavra e mostrada em **páginas de 2 linhas**, `PAGINA_MS` (2 s) cada; a tela inteira fica no mínimo `TELA_MS`.
- As telas montadas no totem (sem `tela` do backend) foram reescritas para caber em 16.
- Tela de espera alterna a cada `ALTERNA_MS` (3 s) entre o convite (`ChargeOps GoodWe` / `Aproxime cartao`, ou o aviso da vez) e o quadro das vagas (`1:LIVRE 2:7.4W` / `3:ESPERA4:7.4W S`, 8 colunas por vaga).
- Vaga 4 carregando: `S` = solar, `R` = rede.

**Rejeitado — trocar por 20x4.** A peça é a que existe; a paginação custa pouco e o texto do backend continua válido.

## D4. Pinos (bloco `PINOS` no topo do `.ino`)

| Função | GPIO | Observação |
|---|---|---|
| Relés das vagas 1–4 | 26, 27, 25, 33 | sem pino de *strapping*; escritos em "desligado" **antes** do `pinMode` |
| Relé reversor da vaga 4 | 32 | desligado = rede |
| Botões 1–4 | 13, 14, 15, 34 | ao GND; 13/14/15 com `INPUT_PULLUP`; **34 precisa de resistor de 10 kΩ ao 3V3** (pino só de entrada, sem pull-up interno) |
| MFRC522 | SCK 18, MISO 19, MOSI 23, SS 5, RST 4 | |
| I2C | 21/22 e 17/16 | ver D2 |
| LED de status | 2 | LED da placa |

Relé ativo em LOW por padrão (`RELE_ATIVO_EM_LOW`), como os módulos com optoacoplador.

## D5. Aviso de hardware: USB só com VCC/GND

- **USB-A:** sem nada nos pinos de dados, o celular se vê numa porta de computador e puxa **≤ 0,5 A (~2,5 W)**, não 7,5 W. Para chegar perto de 1,5 A, **ligar D+ com D− em cada USB-A** (carregador dedicado, BC 1.2). iPhone pode continuar abaixo disso.
- **USB-C (fêmea, do lado da fonte):** com cabo C-C, o celular só se reconhece ligado a uma fonte se cada pino CC tiver um **Rp ao VBUS da porta** (depois do relé). **22 kΩ anunciam 1,5 A** (56 kΩ anunciam só o padrão USB). Sem isso, a vaga C pode não carregar nada. Muitos módulos "USB-C fêmea" vêm com 5,1 kΩ ao GND, que é o resistor do lado do *celular*: não servem aqui.
- O motor de demanda **não depende** desses números (ele admite pela potência cadastrada da vaga, 7,5 kW); a cobrança, sim (é a energia medida). Cada número na tela continua rotulado `medido`.

## D6. Firmware

`firmware/totem_central/` é a tradução de `totem_virtual/firmware.py`, função por função, com os mesmos nomes de constantes. A placa v1 (`firmware/chargeops_esp32/`) fica como está.

## Pontos para o Daniel

| # | Ponto | Proposta |
|---|---|---|
| P1 | `fontes` só com `bateria`, com sinal; `painel` nunca vem do totem físico | Nada a mudar no backend (já aceita). Confirmar que a ausência de `painel` mantém o simulador como fallback rotulado |
| P2 | `fonte: "rede"` **fica**: a bancada agora tem caminho de rede na vaga 4 | Manter |
| P3 | Vai-e-volta rede ↔ solar: na rede a bateria descansa, a tensão sobe e o SOC estimado pula acima de 10030 + 5 | Medir o SOC só com a bateria descarregando, ou exigir um tempo mínimo em `rede`. O totem segura 30 s do lado dele |
| P4 | `tela` com até 4 linhas de 20; o LCD é 16x2 | O totem re-quebra e pagina. Se der, linhas de até 16 e no máximo 2 (o totem continua aceitando o formato atual) |
| P5 | Corte local da bateria vai para a rede mesmo com o 10024 desligado | É proteção de hardware e só acontece abaixo de 3,30 V (bem abaixo dos 20% do 10030). Se preferir pausa nesse caso, o handshake precisa mandar o 10024 para o totem |
