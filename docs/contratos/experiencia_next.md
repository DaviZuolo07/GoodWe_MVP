# Contrato da experiência NEXT — EV ChargeOps

**Versão 1.1 · 19/10/2026 · base: commit `ef4e9d7` + branch `gus/next-b1-b5`**
Registro do que foi implementado: `docs/CORRECOES_NEXT_B1_B5.md`.

---

## 0. O que este documento é

É o acordo do grupo sobre **o que o visitante vive no estande e o que o sistema
promete**. Não é roteiro de fala nem plano de slides: é a lista de coisas que,
se mudarem, mudam primeiro **aqui**, depois no código.

| Documento | Do que trata |
|---|---|
| `docs/contratos/maquina_de_estados_totem.md` | como a placa se comporta (firmware) |
| `docs/contratos/totem_v2_1.md` | o protocolo HTTP entre placa e backend |
| **este arquivo** | o que o visitante vê e o que o sistema garante |

**Regra de manutenção:** mudou a experiência → muda aqui → muda no totem
virtual → muda no firmware → muda no app. Nunca na ordem inversa.

---

## 1. A promessa, em uma frase

> O totem carrega celular em vez de carro, mas roda o **mesmo software, a mesma
> matemática e o mesmo controle de demanda** que rodaria num condomínio com seis
> carros elétricos — e uma das quatro vagas é alimentada por sol de verdade,
> **medido** por um INA219 no painel.

O produto não é o totem. O produto é **o software de gestão de demanda, de
fontes e de cobrança** que roda nele. O totem é a maquete que prova que a conta
fecha contra sensor, não contra planilha.

| O que a banca cobra | Nossa resposta de uma linha |
|---|---|
| **Arquitetura funcional** | INA219 → lote assinado → alocador único → banco → app/painel. Um caminho só. |
| **Papel da IA integrada** | O assistente lê o mesmo fato que a tela; quatro guardrails + uma camada de saída reprovam número sem lastro. |
| **Aderência ao contexto** (Condominial) | Limite do quadro, ponta, rateio por morador, fila por ordem de chegada, piso de 6 A da IEC 61851 e do manual HCA G2. |
| **Visão de produto real** | Síndico evita trocar o padrão de entrada; morador paga o que mediu; REN ANEEL 1.000/2021; mapa Modbus do HCA G2 é o alvo de integração. |

---

## 2. Escopo congelado (19/10)

### Dentro

- Quatro vagas USB físicas no totem, medidas por INA219.
- **Painel solar medido** por INA219; bateria 18650 lida pelo ADC do ESP32.
- Vaga 4 alimentada pelo sol (painel + 18650), com queda para a rede quando a
  bateria chega no mínimo.
- Cadastro ao vivo do visitante, com o celular escolhido na lista embarcada
  (`frontend/src/lib/celulares.js`) ou digitado à mão (mAh). **Nada vem do
  celular em tempo real**: o USB não manda dados.
- Prévia de custo, reserva no saldo, medição por faixa de horário e fonte,
  teto na reserva, estorno e recibo linha a linha.
- Alocador de potência a cada 10 s e no início/fim de cada recarga.
- Painel do gestor com curva do dia, pico evitado, recusas, rateio e o
  simulador de cenário.
- Assistente com guardrails e o botão de pânico `CHAT_MODO=regras`.
- **Tudo roda no PC do Gustavo**: backend (`:8000`), API do gestor (`:8001`),
  app do morador (`:5173`) e painel (`:5174`). Todos os cadastros são feitos
  ali, ao vivo. O banco é o **Supabase do Davi**, acessado desse PC.

### Fora (dito de frente se perguntarem)

- Modbus RS485 contra um HCA G2 real — os registradores são **armazenados e
  simulados**; num equipamento real o alocado iria no **10029** e a parcela de
  rede corresponderia ao **10039**.
- Gateway de pagamento — o crédito é simulado.
- HTTPS entre placa e backend (é HTTP assinado com HMAC, na rede local).
- **Deploy em nuvem: fora do escopo.** `docs/DEPLOY.md` e `render.yaml` ficam
  no repositório só como histórico.
- Limitador de tentativas distribuído (vive na memória do processo).

---

## 3. Hardware do estande

| Peça | Qtd | Papel |
|---|---|---|
| ESP32 | 1 | cérebro do totem; cliente HTTP, nunca servidor |
| LCD 16x2 (I²C, 0x27) | 1 | fala com o visitante; só ASCII, paginado |
| MFRC522 | 1 | lê a tag: "tem alguém aqui mandando começar" |
| Botões | 4 | escolha da vaga |
| **INA219** | **5** | **4 nas vagas + 1 no painel** |
| Fonte chaveada 5 V 10 A | 1 | barramento da rede |
| Mini painel solar 5 V | 2 | geração da vaga 4 |
| TP4056 | 1 | carrega a 18650 com o que o painel dá |
| Bateria 18650 | 1 | buffer solar; **tensão lida pelo ADC** (divisor 10k + 10k) |
| MT3608 (step-up) | 1 | eleva a 18650 para 5 V |
| Relé 4 canais | 1 | liga/desliga cada vaga |
| Relé 1 canal (SPDT) | 1 | **reversor** da vaga 4: solar **ou** rede, nunca as duas |
| USB-A / USB-C fêmea | 2 + 2 | as quatro vagas |

### 3.2 Mapa de pinos — fonte: `firmware/totem_central/config.h`

```
Relés das vagas    GPIO 26, 27, 25, 33     (vagas 1 a 4)
Reversor da vaga 4 GPIO 32                 (desligado = rede · ligado = solar)
Botões             GPIO 13, 14, 15, 34     ao GND
LED da placa       GPIO 2                  aceso = servidor aceitando
RFID (SPI)         SS 5 · RST 4 · SCK 18 · MISO 19 · MOSI 23
I²C principal      SDA 21 · SCL 22         LCD + INA219 das 4 vagas
I²C solar (Wire1)  SDA 17 · SCL 16         INA219 do PAINEL (0x40)
ADC da bateria     GPIO 35 (ADC1)          divisor 10k + 10k nos terminais da 18650
Endereços INA219   0x40 · 0x41 · 0x44 · 0x45   (vagas 1 a 4, via A0/A1)
```

**Cinco armadilhas de montagem:**

1. **GPIO 34 não tem pull-up interno.** Botão da vaga 4: resistor de 10 kΩ ao 3V3.
2. **Relé com optoacoplador liga em LOW** (`RELE_ATIVO_EM_LOW 1`). Se o de
   vocês ligar em HIGH, troque a constante — não o fio.
3. **O reversor é SPDT** para que painel e rede nunca se toquem. Não existe
   "versão de teste em paralelo".
4. **O ADC da bateria tem de ser ADC1** (GPIO 32–39). O ADC2 não funciona com
   o Wi-Fi ligado.
5. **GND da 18650 = GND do ESP32**, e o divisor mede **antes** do MT3608
   (depois dele são 5 V regulados, que não dizem nada sobre a carga).

### 3.3 Painel medido, bateria deduzida (resolvido em 19/10)

O 5º INA219 fica **entre o painel e o TP4056** e mede a geração. A 18650 não
tem sensor: a tensão vem do ADC e a potência é **deduzida** — o que a vaga 4
consome e o painel não entrega, sai da bateria. A geração entra em
`geracao_solar` com `origem = 'medido'` e o alocador passa a usar o sol de
verdade. Detalhes e a frase para a banca: ADR-022 (revisão de 19/10).

> *"São cinco INA219: quatro nas vagas e um no painel. A geração solar é
> medida. A carga da bateria vem da tensão, pelo ADC, com a curva de circuito
> aberto da 18650 — é uma estimativa, e erra para o lado seguro: sob carga a
> tensão cai e o SoC sai menor que o real."*

---

## 4. As quatro vagas e o papel de cada uma

| Vaga | Fonte | Papel no estande |
|---|---|---|
| 1 | rede | recarga longa, começada 20–30 min antes: telemetria viva e curva |
| 2 | rede | segunda recarga longa |
| 3 | rede | **vaga do visitante** — é aqui que ele cadastra e carrega |
| 4 | **solar → rede** | o cenário que diferencia o projeto (§8) |

---

## 5. O percurso do visitante

| # | Passo | Quem age | O que tem de aparecer |
|---|---|---|---|
| 1 | Chegada | operador | LCD alternando convite ↔ quadro das vagas (3 s) |
| 2 | Cadastro no app | visitante, no PC | nome, senha; perfil Totem esconde Bloco/Apto |
| 3 | Escolhe o celular | visitante | lista embarcada ou "Outro" + mAh |
| 4 | App calcula a energia | sistema | `Wh = mAh × 3,85 V / 1000` |
| 5 | Escolhe a vaga e o alvo | visitante | alvo padrão 80 % |
| 6 | **Prévia do custo** | sistema | tempo, energia, custo **com a ponta embutida** |
| 7 | **Aproxima a tag** | visitante | reserva no saldo (mín. R$ 1,00); sem saldo, não começa |
| 8 | Relé fecha | placa | LCD confirma |
| 9 | Telemetria a cada 2 s | placa → backend | W, V, A, Wh brutos, lote assinado a cada 6 s |
| 10 | Tela viva | app | % derivado, potência, tempo restante, custo |
| 11 | Encerramento | sistema ou visitante | alvo, teto da reserva, ou "parou de puxar" |
| 12 | **Estorno e recibo** | sistema | cobra o real, devolve a diferença, linha a linha |

Só dois passos decidem: o **7** (saldo conferido e reservado) e o **9** (de
onde sai todo número da tela). Entre o 2 e o 6 nada toca a placa.

### O que o cartão é e o que não é

O cartão **não identifica quem paga**. Quem paga é quem preparou a recarga no
app. O cartão responde: *tem alguém aqui, na frente do carregador, mandando
começar?* Com o cartão compartilhado, o pior caso é **iniciar a recarga que o
vizinho acabou de pedir** — não carregar no nome do vizinho. Trava forte =
cartão pessoal em Configurações.

---

## 6. Os quatro números que o sistema promete

### 6.1 Capacidade do celular
`Energia (Wh) = mAh × 3,85 V / 1000` (3,85 V: célula Li-ion atual; 3,7 V é a antiga).

### 6.2 Percentual de carga — derivado, nunca informado
`SoC atual = SoC inicial + (energia medida × 0,92 / capacidade) × 100`.
Se a pessoa mentir no inicial, o percentual erra pelo mesmo tanto — **a
cobrança não erra**, porque é pela energia medida.

### 6.3 Tempo — uma integral
`tempo = Σ (capacidade/100) / (0,92 × P(SoC do trecho))`, passos de 1 %. Num
Galaxy A15 a 7,5 W: 20→80 % leva 100 min e 12,6 Wh; 80→100 % leva mais 97 min
e só 4,2 Wh.

### 6.4 Custo — integrado no tempo, por fonte
Cada kWh é preçado pela tarifa do horário em que vai ser entregue, e é de uma
fonte só: **solar** · **rede fora da ponta** · **rede na ponta**. Preços
congelados na sessão quando ela começa.

---

## 7. O contrato de gestão de demanda

### As invariantes

1. **Nunca estourar o limite** da rede disponível (para o que é modulável).
2. **Nunca entregar a um ponto mais do que ele pede.**
3. **Nunca deixar um ponto ativo abaixo do mínimo** que ele consegue sinalizar.
4. **Nunca contar o mesmo kWh duas vezes** entre sol e rede.
5. **Admissão conta só a rede.** O sol não é despachável — inclusive a vaga 4
   que hoje está no sol conta pela rede na hora de admitir alguém novo.

### O algoritmo: water-filling em quatro etapas

1. **Cargas fixas primeiro**, pelo que estão medindo. Sol primeiro, depois rede.
   A vaga solar do totem com o reversor **no sol** fica **fora do barramento**:
   é toda solar (painel + 18650) e não ocupa um kW da rede.
2. **Sol restante** — modo FV (10032 = 1), depois modo rápido.
3. **Rede restante** — modo rápido; FV com 10024 recebe só o que falta ao piso.
4. **Ninguém abaixo do mínimo** — quem não alcança é pausado (o último a chegar).

### Ponto modulável × porta do totem — **a diferença que a banca vai notar**

| | Ponto modulável (HCA G2) | Porta USB do totem |
|---|---|---|
| Atuador | potência alocada no 10029 | relé: **liga ou desliga** |
| O que o alocador faz | **divide** (water-filling) | **contabiliza** pelo que mede |
| Quando não cabe | reduz todos até o piso; pausa o último | **admissão**: a nova espera em "aguardando energia" |

O celular puxa o que quiser; o totem não tem como dar "5 W" a um celular que
pede 7,5. Por isso, **no totem a gestão é de admissão e de fonte**; a divisão
igual é do ponto modulável — e se mostra ao vivo no **simulador de cenário** e
nos pontos simulados do condomínio, rodando **o mesmo algoritmo de produção**.

### O piso de 6 A

`Monofásico: 6 × 230 / 1000 = 1,4 kW` · `Trifásico: √3 × 6 × 230 / 1000 = 4,2 kW`.
Num quadro de 30 kW cabem **21 carros a 1,43 kW**; o 22º é recusado — não por
falta de energia, mas porque admiti-lo deixaria todos abaixo do mínimo.

### Horário de ponta

Dias úteis, 18h–21h por padrão; limite cai para 60 % e a tarifa sobe 1,5×.
**No estande a ponta está desligada** (`ponta 00:00–00:00`): o valor não muda
com a hora da banca.

### O número para o síndico

Seis carros de 7,4 kW = 44,4 kW; com gestão, 30 kW → **14,4 kW de pico evitado**.

---

## 8. A vaga solar — o cenário do Davi, estado por estado

> *"Três vagas ocupadas puxando da tomada e sendo gerenciadas. Chega um carro na
> vaga 4 (solar) e carrega. Se acabar a energia solar, o sistema distribui
> igualmente a energia com a 4ª vaga."*

| Estado | Condição | O que o sistema faz | O que aparece |
|---|---|---|---|
| **A — Sol** | painel + 18650 dando conta | vaga 4 toda solar, **fora do barramento**; as três de rede usam o quadro | vaga 4 `solar`; rede = só as três |
| **B — Sol caindo** | painel insuficiente, 18650 acima do mínimo | a 18650 cobre a diferença (balanço positivo) | `solar`, SoC da bateria caindo |
| **C — Bateria no mínimo** | SoC < 10030 (20 %) **e** descarregando — ou tensão < `V_BATERIA_CORTE` (3,30 V, proteção local) | **reversor vira para a rede**; a vaga entra no alocador como **modo rápido**, `so_rede` | vaga 4 `rede` |
| **D — Volta** | backend manda `solar` (SoC ≥ 10030 + 5) — e, se o corte foi local, tensão ≥ `V_BATERIA_VOLTA` (3,60 V); sempre ≥ 30 s na rede (`FONTE_MIN_MS`) | reversor volta ao sol | `solar` |

### O que foi corrigido (B2) e o que isso significa no totem

`decidir_vaga_solar()` gravava o estado do reversor na sessão
(`modo_vaga_solar`), mas o alocador lia só o `modo_carga` do carregador. Agora
`item_de()` recebe o estado: na **rede**, o ponto vira modo rápido e disputa a
rede em igualdade (`so_rede`, para o painel que carrega a 18650 não ser contado
de novo); no **sol**, a porta fixa do totem fica fora do barramento.

- **Ponto modulável:** quadro de 20 kW, três pontos de 7,4 kW na tomada e o
  quarto no sol → 6,67 kW para cada um dos três; o sol acaba → **5,0 kW para
  cada um dos quatro, soma 20,000**. Teste:
  `test_vaga_solar_na_rede_entra_na_divisao_igual`.
- **Totem (relé):** quadro de 30 kW (escala ×1000), três vagas a 7,5 kW → rede
  22,5 kW e a vaga 4 toda solar; o sol acaba → as quatro na rede, **30,0 kW,
  exatamente o limite**. Não há como "dividir" um relé; o que o sistema garante
  é que cabe, e que o kW passa a ser cobrado como rede. Teste:
  `test_vaga_solar_do_totem_no_sol_fica_fora_do_barramento`.

**Configuração obrigatória** (o `preparar_totem.py` já grava): na T4,
`garantir_minimo = true` (10024) e `modo_carga = 1` (10032); no condomínio,
`fv_potencia_kwp > 0`. Sem o 10024, a vaga **pausa** em vez de ir para a rede.

### Como demonstrar ao vivo

Tape o painel com a mão com a vaga 4 carregando: a leitura do painel cai a
zero **na tela, na hora** — isso é a geração medida. O reversor **não** vira em
10 s: uma 18650 de 2000 mAh (~7,4 Wh) cheia segura um celular a 7,5 W por
~50 min. Para a troca acontecer na frente da banca, **comece a demonstração
com a 18650 já baixa** (~3,65 V, logo acima do mínimo): com o painel tapado
ela cruza os 20 % em poucos minutos, o reversor estala — dá para **ouvir** — e
a vaga vira `rede`. Meça na bancada quanto tempo leva a partir de cada tensão.
**Ensaie pelo menos cinco vezes antes do dia 22.**

Para mostrar a **divisão igual**, abra o simulador de cenário no painel do
gestor e peça à banca um número de carros.

---

## 9. De onde vem cada dado

| Dado | Fonte | Nunca vem de |
|---|---|---|
| Capacidade e potência do celular | `frontend/src/lib/celulares.js`, embarcado, ou digitado | do celular (o USB não manda dados) / API externa |
| Tensão, corrente, potência, energia das vagas | INA219, a cada 200 ms, amostra a cada 2 s | estimativa |
| **Geração solar** | **INA219 do painel** → `geracao_solar` (`origem = 'medido'`) | chute (a curva de céu limpo só entra sem placa) |
| Tensão da 18650 | ADC do ESP32 (divisor) | — |
| Potência da 18650 | **deduzida**: consumo da vaga 4 − painel | — |
| Percentual de carga | derivado da energia medida (§6.2) | do celular |
| Limite do quadro | `condominios.limite_potencia_kw`, editável no painel | hardcode |
| Identidade de quem paga | **sempre do token JWT** | corpo da requisição |

**Escala de bancada:** a placa mede watts; o backend multiplica por **1000 na
entrada da telemetria** (7,5 W medidos → 7,5 kW de produto). *"A medição é
real, a escala é de maquete — um fator de mil, num ponto só do código, e
reversível."*

---

## 10. Papéis no estande

| Papel | Responsabilidade | Nunca faz |
|---|---|---|
| **Operador do totem** | recebe o visitante, conduz a vaga 3, resolve vaga travada | explica matemática |
| **Dono da conta** | prévia, reserva, estorno, recibo | mexe no hardware |
| **Dono da energia** | demanda, piso de 6 A, pico evitado, simulador | abandona o painel do gestor |
| **Dono do hardware** | placa, sensores, reversor, painel tapado | improvisa fiação ao vivo |
| **Dono da IA e do produto** | guardrails, ANEEL, Modbus, visão de produto | promete o que não tem |

---

## 11. Critérios de aceite

Marcar com data e quem testou.

**Energia e demanda**
- [ ] Quatro vagas medindo ao mesmo tempo; rede ≤ limite (30 kW)
- [ ] Painel iluminado: leitura do painel > 0 na tela e `geracao_solar` com `origem = medido`
- [ ] Vaga 4 em solar: a rede do painel do gestor **não** inclui a vaga 4
- [ ] Painel tapado → reversor vira → `fonte = rede` (no pior caso ~1 s após o corte local)
- [ ] Com a vaga 4 na rede, ela entra na conta da rede e o sol não é atribuído a ela
- [ ] Simulador de cenário responde a um número dado pela banca, com divisão igual
- [x] Alocador: divisão igual de pontos moduláveis com a vaga solar na rede (teste, 19/10)

**Cobrança**
- [ ] Prévia com a ponta embutida (ligar a ponta só para este teste)
- [ ] Sem saldo, a recarga não começa
- [ ] Recibo soma linha a linha na calculadora; separa solar / rede fora / rede ponta

**Experiência**
- [ ] Visitante desconhecido se cadastra e carrega sozinho em menos de 3 min
- [ ] Celular fora da lista: "Outro" + mAh funciona
- [ ] Ciclo completo (celular em ~78 %, alvo 80 %)
- [ ] Assistente não inventa número; `CHAT_MODO=regras` funciona sem modelo

**Infra**
- [ ] Tudo roda no PC do Gustavo, com o Supabase do Davi
- [ ] Rede do hotspot como **Privada** + regra de firewall (README §3.6)
- [ ] `http://<IP do PC>:8000/` abre do celular de outra pessoa
- [ ] Relógio sincronizado (`w32tm /resync`)
- [ ] `MODO_DEMO=0` com a placa conectada
- [x] 108 testes de backend + 57 do totem virtual verdes (19/10)
- [ ] `python provisionar.py verificar` com a saída impressa na mão

---

## 12. Limites declarados — falar antes de perguntarem

1. **Não fala Modbus RS485** com um HCA G2 real; os parâmetros (10024, 10025,
   10026, 10029, 10030, 10032) são do mapa real, armazenados e simulados.
2. **As portas do totem não são moduláveis** (relé): o totem demonstra
   admissão, fila e contabilidade por fonte; a divisão igual é do ponto
   modulável e aparece no simulador.
3. HTTP puro na rede local, assinado com HMAC. Em produção, HTTPS.
4. Sem gateway de pagamento; crédito simulado.
5. Limitador de tentativas na memória do processo.
6. **A carga da 18650 é estimada pela tensão** e a potência dela é deduzida
   (sem as perdas do TP4056/MT3608, ~10 %). Os limiares precisam de
   calibração na bancada.
7. **O banco está na nuvem** (Supabase, Canadá): sem internet no PC do
   Gustavo, o estande cai. Plano B: `backend_de_bolso` (sem rede, dado em
   memória).
8. O detector de "parou de puxar" só arma depois de **0,2 Wh** (96 s a 7,5 W):
   uma vaga ligada sem celular nunca se libera sozinha — encerre pelo app ou
   pela tag.

---

## 13. Bloqueios — situação em 19/10

| # | Bloqueio | Situação |
|---|---|---|
| **B1** | Backend exige Supabase na nuvem | **Decidido:** roda no PC do Gustavo com o Supabase do Davi, internet pelo hotspot. Firewall, IP fixo, timeout de 8 s e checklist no README §3.6. Plano B: `backend_de_bolso` |
| **B2** | Vaga 4 fora da divisão quando vira para a rede | **Corrigido** (`demanda.py`), mais a contabilidade da vaga no sol (fora do barramento) |
| **B3** | Painel sem sensor | **Corrigido** com 5 INA219 (4 vagas + painel) e bateria pelo ADC — falta montar e calibrar |
| **B4** | `pausado_motivo = None` na bancada | **Corrigido** (`sem_potencia_disponivel`, só de relato) |
| **B5** | README desatualizado | **Corrigido** |

---

## 14. Quem assina

| Nome | Papel | Data |
|---|---|---|
| Davi | | |
| Daniel | | |
| Gustavo | | |
