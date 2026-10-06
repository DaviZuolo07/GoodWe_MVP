# Como o ChargeOps gere a demanda e cobra cada kWh

Documento curto para o pitch. Responde ao comentário da GoodWe: *"expliquem com maior precisão como o app apoia a gestão de demanda, as cobranças e o valor para empresas, gestores e usuários."*

> **Honestidade primeiro.** Os parâmetros Modbus do HCA G2 são armazenados e simulados (o sistema não escreve em RS485). A geração solar é simulada (curva de céu limpo) e rotulada como tal em cada número. Preços e custos são premissas configuráveis pelo síndico, não leitura de fatura. A energia do ponto físico (ESP32) é medida.

---

## 1. O problema

O quadro de um prédio aguenta uma potência máxima. Três carros de 7 kW num quadro de 10 kW somam 21 kW: sem gestão, ou se recusa recarga, ou o disjuntor geral desarma e o prédio inteiro fica sem luz. Às 18h a situação piora: o prédio consome mais e a energia fica mais cara.

## 2. Como o ChargeOps gere a demanda

Um único alocador decide, a cada 10 segundos e a cada recarga que começa ou termina, **quanto cada ponto pode puxar e de qual fonte**. Ele opera os mesmos parâmetros que o GoodWe HCA G2 já tem no mapa Modbus:

| Registrador | O que faz no ChargeOps |
|---|---|
| 10025 Controle dinâmico | Ligado: o alocador divide a potência entre os carros. Desligado: o ponto puxa o máximo, como sem gestão |
| 10026 Disjuntor (A) | Teto do ponto, convertido em kW pela tensão |
| 10029 Potência máxima | Teto do ponto, dentro da faixa do modelo (7 / 11 / 22 kW) |
| 10032 Modo de carga | Rápido (rede + sol) ou prioridade FV (só sol) |
| 10024 Garantir mínimo | No modo FV, completa da rede só até 1,4 kW (7 kW) ou 4,2 kW (11/22 kW) |

Regras que o alocador segue:
1. **Duas fontes, nunca misturadas:** rede (limitada pelo quadro, menor na ponta) e excedente solar (opcional — sem FV o sistema funciona igual).
2. **Sol primeiro**, depois a rede completa.
3. **Ninguém carrega abaixo do mínimo** do carregador (6 A por fase): quem não alcança pausa, como o HCA G2 faz; na falta, pausa quem chegou por último.
4. **Admissão conta só a rede:** o sol não é garantido, então nenhum carro é liberado contando com o meio-dia.

## 3. Como o ChargeOps cobra

- O morador prepara a recarga no app; o cartão RFID confirma a presença no ponto.
- O sistema **reserva** o valor estimado no pior caso (tudo pela rede) e devolve a diferença no fim. O sol só aumenta o estorno.
- Cada kWh entregue cai em exatamente uma fonte, com preço **congelado** no início da recarga:

| Fonte | Preço ao morador | Custo do condomínio |
|---|---|---|
| Solar | R$ 0,75 | R$ 0,35 |
| Rede fora da ponta | R$ 1,15 | R$ 0,95 |
| Rede na ponta (18h–21h, dias úteis) | R$ 1,725 (1,15 × 1,5) | R$ 1,45 |

- O recibo tem uma linha por fonte, cada uma com energia, origem e preço; o total é a soma das linhas, centavo a centavo. O extrato da carteira mostra a mesma divisão.
- **Incentivo alinhado:** a margem do kWh solar (R$ 0,40) é maior que a da rede (R$ 0,20). O condomínio ganha mais quando o sol brilha, e o painel avisa o síndico se as premissas inverterem isso.

## 4. Os números — mesmas 3 recargas, quatro configurações

Quadro de 10 kW (6 kW na ponta), três carregadores GoodWe HCA G2 de 7 kW, três carros de 50 kWh indo de 20% a 80%. Gerado por `backend/testes/cenarios_demanda.py`, com as mesmas funções da operação e relógio simulado minuto a minuto.

### Cenário A — Sem solar, controle dinâmico desligado (10025 = 0)

| Carro | Chegou | Começou | Terminou | Solar kWh | Rede fora kWh | Rede ponta kWh | Pago (R$) |
|---|---|---|---|---|---|---|---|
| Carro 1 | 17:30 | 17:30 | 22:10 | 0,00 | 11,67 | 21,00 | 49,65 |
| Carro 2 | 17:31 | 22:10 | 02:50 (+1d) | 0,00 | 32,67 | 0,00 | 37,57 |
| Carro 3 | 17:32 | 02:50 (+1d) | 07:30 (+1d) | 0,00 | 32,67 | 0,00 | 37,57 |

- Pico da rede: **7,00 kW** (garagem: 7,00 kW). **Estouro do quadro:** até 1,00 kW por 180 min — o disjuntor geral desarmaria.
- Última recarga concluída: 07:30 (+1d).
- Condomínio: receita R$ 124,79, custo da energia R$ 103,60, margem R$ 21,19.

### Cenário B — Sem solar, controle dinâmico ligado (10025 = 1)

| Carro | Chegou | Começou | Terminou | Solar kWh | Rede fora kWh | Rede ponta kWh | Pago (R$) |
|---|---|---|---|---|---|---|---|
| Carro 1 | 17:30 | 17:30 | 04:28 (+1d) | 0,00 | 26,64 | 6,00 | 40,99 |
| Carro 2 | 17:31 | 17:31 | 04:29 (+1d) | 0,00 | 26,61 | 6,00 | 40,95 |
| Carro 3 | 17:32 | 17:32 | 04:30 (+1d) | 0,00 | 26,64 | 6,00 | 40,99 |

- Pico da rede: **10,00 kW** (garagem: 10,00 kW). Quadro respeitado o tempo todo.
- Última recarga concluída: 04:30 (+1d).
- Condomínio: receita R$ 122,93, custo da energia R$ 102,00, margem R$ 20,93.

### Cenário C — 10 kWp, modo FV + garantir mínimo (10032 = 1, 10024 = 1)

| Carro | Chegou | Começou | Terminou | Solar kWh | Rede fora kWh | Rede ponta kWh | Pago (R$) |
|---|---|---|---|---|---|---|---|
| Carro 1 | 10:00 | 10:00 | 06:35 (+1d) | 12,16 | 16,26 | 4,20 | 35,07 |
| Carro 2 | 10:01 | 10:01 | 06:39 (+1d) | 12,07 | 16,35 | 4,20 | 35,10 |
| Carro 3 | 10:02 | 10:02 | 06:41 (+1d) | 12,03 | 16,39 | 4,20 | 35,11 |

- Pico da rede: **4,20 kW** (garagem: 7,50 kW). Quadro respeitado o tempo todo.
- Última recarga concluída: 06:41 (+1d).
- Condomínio: receita R$ 105,28, custo da energia R$ 77,50, margem R$ 27,78.
- Sol: 36,26 kWh gerados no período, 36,26 kWh absorvidos pela garagem; moradores economizaram R$ 14,50 frente a pagar tudo pela rede.

### Cenário D — 10 kWp, modo rápido (10032 = 0)

| Carro | Chegou | Começou | Terminou | Solar kWh | Rede fora kWh | Rede ponta kWh | Pago (R$) |
|---|---|---|---|---|---|---|---|
| Carro 1 | 10:00 | 10:00 | 16:15 | 11,85 | 20,81 | 0,00 | 32,83 |
| Carro 2 | 10:01 | 10:01 | 16:16 | 11,77 | 20,87 | 0,00 | 32,84 |
| Carro 3 | 10:02 | 10:02 | 16:17 | 11,75 | 20,90 | 0,00 | 32,84 |

- Pico da rede: **10,00 kW** (garagem: 17,50 kW). Quadro respeitado o tempo todo.
- Última recarga concluída: 16:17.
- Condomínio: receita R$ 98,51, custo da energia R$ 71,84, margem R$ 26,67.
- Sol: 35,37 kWh gerados no período, 35,37 kWh absorvidos pela garagem; moradores economizaram R$ 14,15 frente a pagar tudo pela rede.

### Leitura

- **A × B (controle dinâmico):** no mesmo quadro, sem gestão só um carro carrega por vez e a ponta **estoura o quadro em 1 kW por 3 horas**. Com o 10025 ligado, os três carregam juntos, o quadro é respeitado o tempo todo e a última recarga termina **3 horas antes**. O primeiro morador paga R$ 40,99 em vez de R$ 49,65, porque menos energia cai na ponta.
- **C (modo FV + garantir mínimo):** a rede nunca passa de **4,2 kW** (só o mínimo dos três carros); 36 kWh vêm do sol e o resto entra devagar, a 1,4 kW por carro, até a manhã seguinte. É o modo para quem deixa o carro parado muito tempo. Dá a maior margem para o condomínio dos quatro cenários.
- **D (modo rápido com sol):** o sol soma à rede: a garagem chega a 17,5 kW com só 10 kW da rede, e as três recargas terminam **antes das 16h20**, fora da ponta.

## 5. Valor para cada um

| Para quem | O que ganha | Onde aparece |
|---|---|---|
| **GoodWe (empresa)** | Os recursos que o HCA G2 já tem (10024–10032) operados em escala de condomínio; o FV vira argumento de venda mensurável — "com X kWp, a garagem tira Y kW da rede" | Simulador de cenário do síndico (`fv_potencia_kwp`) |
| **Síndico (gestor)** | Mais carros no mesmo quadro sem obra elétrica; receita, custo e margem por fonte; pico evitado pela gestão e pico coberto pelo sol; alerta de incentivo invertido | Painel do gestor |
| **Morador (usuário)** | Paga cada kWh pela fonte e horário em que o recebeu; recarga mais barata com sol; reserva no pior caso com estorno automático; recibo que confere com calculadora | Prévia, recibo e extrato |

## 6. O que é medido, simulado ou estimado

| Número | Origem |
|---|---|
| Energia do ponto ESP32 | **Medido** (sensor) |
| Energia dos pontos veiculares | Simulado (modelo físico de carga) |
| Geração solar | Simulado (`solar_simulado`); um inversor real gravaria `solar_medido` na mesma tabela, sem mudar o resto |
| Divisão rede × sol de cada kWh | Atribuída pela alocação do ciclo |
| Economia frente a pagar tudo pela rede | Estimado (rotulado no recibo e no painel) |
| Preços e custos | Premissas do síndico, simuladas |
