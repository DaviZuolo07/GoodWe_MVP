# Mapa de estudo — GoodWe EV ChargeOps

**Para: todos os membros do grupo · 19/10/2026 · banca em 22/10 (3 dias)**
Contrato da experiência: `docs/contratos/experiencia_next.md`.
O que foi corrigido em 19/10: `docs/CORRECOES_NEXT_B1_B5.md`.

---

## Como usar este mapa

O projeto tem ~13.500 linhas de Python, 37 componentes React, 22 migrations e um
firmware em C++. **Ninguém vai ler tudo em três dias, e ninguém precisa.**

- **Nível 0 (90 min, todo mundo):** a base comum.
- **Nível 1 (uma trilha por pessoa, 3–4 h):** sua especialidade. Você é o dono.
- **Nível 2 (90 min, em grupo):** o cruzamento. Cada um é sabatinado pelos outros.

A regra que vale mais que todas: **ninguém apresenta um número sem saber a
conta que o produziu.** Prefira "essa é a área do Daniel" a inventar.

---

## Nível 0 — a base comum (90 min, todo mundo)

### 0.1 A frase (decore)

> O totem carrega celular em vez de carro, mas roda o **mesmo software, a mesma
> matemática e o mesmo controle de demanda** que rodaria num condomínio com seis
> carros elétricos. **O produto não é o totem — é o software de gestão de
> demanda e cobrança que roda nele.**

### 0.2 Os quatro problemas que o sistema resolve

1. **O quadro do prédio tem limite.** Seis carros de 7,4 kW somam 44,4 kW. Num
   quadro de 30 kW o disjuntor geral desarma e **o prédio inteiro** fica sem
   luz. Um alocador divide a potência a cada 10 s e recusa quem não cabe.
2. **A cobrança precisa ser conferente.** Preço antes, reserva, medição por
   horário e fonte, teto, estorno automático.
3. **A energia precisa ser medida.** INA219 nas quatro vagas **e no painel**;
   o backend deriva carga, tempo e custo do que o sensor viu.
4. **O assistente não pode inventar número.** Quatro guardrails + uma camada de
   saída que reprova número sem lastro.

### 0.3 Os quatro entregáveis que a banca cobra

(PDF `1CC - EV CHALLENGE GOODWEFIAP 2026`, slide "O Que Esperamos de Vocês")

| Cobrança | Resposta de uma linha |
|---|---|
| **Arquitetura funcional** | INA219 → lote assinado → alocador único → banco → app/painel. |
| **Papel da IA integrada** | O assistente lê o mesmo fato que a tela; a camada de saída reprova número sem lastro, e um redator determinístico responde. O modelo nunca escreve SQL. |
| **Aderência ao contexto** (Condominial) | Limite do quadro, ponta, rateio, fila por ordem de chegada, piso de 6 A. |
| **Visão de produto real** | Pico evitado de 14,4 kW; morador paga o que mediu; REN ANEEL 1.000/2021; Modbus do HCA G2 como alvo. |

> *"O código é apenas o veículo; a avaliação foca no raciocínio arquitetônico,
> de negócios e de gestão de dados."* — **vão perguntar por quê, não como.**

### 0.4 Os números que todo mundo decora

| Número | O que é |
|---|---|
| **3,85 V** | tensão nominal de uma célula Li-ion de celular |
| **92 %** | eficiência de carga (`EFICIENCIA_CARGA`) |
| **80 %** | joelho da curva CC/CV |
| **6 A por fase** | IEC 61851 → **1,4 kW** mono, **4,2 kW** trifásico |
| **44,4 → 30 kW** | **14,4 kW de pico evitado** |
| **21 carros** | o que cabe em 30 kW sem ninguém abaixo do mínimo |
| **10 s** | período do alocador |
| **×1000** | escala de bancada: 7,5 W medidos → 7,5 kW de produto |
| **30 kW** | limite do estande: 4 vagas × 7,5 kW cabem juntas |
| **100 min** | 20→80 % de um Galaxy A15 a 7,5 W. **Ninguém verá recarga completa.** |
| **~50 min** | o que a 18650 cheia segura a vaga 4 sem sol |

### 0.5 Leitura obrigatória (30 min)

1. `README.md` seções 1 a 3.
2. `docs/contratos/experiencia_next.md` — **o contrato da experiência**.
3. `backend/fisica.py` — **só os docstrings**.

---

## Nível 1 — as cinco trilhas

### Trilha A — Física da recarga

**Arquivos:** `backend/fisica.py` · `frontend/src/lib/celulares.js` · `totem_virtual/fisica.py`

- **Energia da bateria ≠ energia da tomada:** `tomada = bateria / 0,92`.
- **CC/CV:** até 80 % potência cheia; acima, rampa até 20 % da potência em 100 %.
- **O tempo é uma integral** em passos de 1 % de SoC.
- **Derating térmico:** acima de 35 °C cai 2 %/grau, piso 70 %.
- **Teto = o menor de quatro:** carregador (10029), dispositivo, disjuntor
  (10026) e alocado — vezes o fator térmico.
- **Disjuntor:** mono `V × I / 1000`; tri `√3 × V × I / 1000` (32 A, 230 V tri = 12,7479 kW).

**Perguntas:**
- *"Se o USB não manda dados, como sabem a porcentagem?"* → **Derivamos**: inicial
  + energia medida × eficiência ÷ capacidade.
- *"E se mentir no inicial?"* → O percentual erra pelo mesmo tanto; **a cobrança não**.
- *"Por que 92 %?"* → Premissa declarada, numa constante única.
- *"Como validaram?"* → Funções puras; 108 testes de backend e 57 do totem virtual.

**Exercício:** à mão, iPhone 17 (3.988 mAh) de 30 % a 80 % começando às 17h40,
tarifa R$ 2,10 e ponta 1,5× a partir das 18h. Confira contra o app (ligue a
ponta num condomínio que não seja o do estande).

### Trilha B — Gestão de demanda (o alocador)

**Arquivos:** `backend/demanda.py` (**leia o docstring do módulo inteiro**) ·
`admin/src/components/SimuladorDemanda.jsx`

- **Water-filling em duas fontes** (§7 do contrato).
- **Cargas fixas entram pelo que estão medindo** — o relé do totem só liga ou
  desliga. **No totem o alocador contabiliza; quem divide é o ponto modulável.**
- **Vaga solar no sol = fora do barramento**: não ocupa rede.
- **Vaga solar na rede = modo rápido**, disputa a rede em igualdade (B2).
- **O piso de 6 A separa "dividir" de "gerir".**
- **Admissão conta só a rede** — inclusive a vaga 4 que hoje está no sol.
- **Ordem de chegada decide quem pausa.**
- **Modbus:** 10024 garantir mínimo · 10025 controle dinâmico · 10026 disjuntor ·
  10029 potência máxima · 10030 SoC mínimo da bateria · 10032 modo de carga.

**Perguntas:**
- *"Por que não dividir igual entre todos?"* → Abaixo de 6 A por fase o carro não carrega.
- *"O totem divide igual entre as quatro vagas?"* → **Não, e diga isso de
  frente:** o relé só liga ou desliga, e o celular puxa o que quiser. No totem,
  a gestão é de **admissão** (quem não cabe espera) e de **fonte** (sol ou
  rede, sem contar duas vezes). A divisão igual é do ponto modulável — e o
  simulador mostra ao vivo, com o algoritmo de produção.
- *"Isso fala Modbus de verdade?"* → **Não.** Armazenado e simulado; o alocado
  iria no 10029.
- *"E se o inversor solar cair?"* → Leitura de geração vale 10 min; sem leitura
  recente o sol vale **zero**.

**Exercício:** simulador de cenário, número pedido por um colega, explicação em
voz alta sem olhar a tela. **Use isso ao vivo com a banca.**

### Trilha C — Cobrança, carteira e rateio

**Arquivos:** `backend/recarga.py` (por seção) · `backend/carteira.py` · `backend/fisica.py` (`detalhar_custo`)

- Prévia → reserva → medição → teto → estorno → recibo.
- **A prévia é integrada no tempo.**
- **Três fontes, nunca misturadas; preços congelados na sessão.** O kWh que sai
  da 18650 é **solar** (é sol guardado), e é medido na vaga 4.
- **Concorrência:** `UPDATE ... where saldo >= valor`, numa instrução só.
- **Reserva mínima de R$ 1,00.**

**Perguntas:** dois carregando com o mesmo cartão · **o cartão identifica quem
paga? (decore o §5 do contrato)** · trava forte · rateio no painel.

**Exercício:** recarga completa com celular quase cheio; confira o recibo na
calculadora. Se não bater no centavo, é bug.

### Trilha D — Hardware, firmware e protocolo

**Arquivos:** `firmware/totem_central/config.h` (**comece aqui**) ·
`firmware/totem_central/README.md` (fiação) · `maquina.cpp` ·
`docs/contratos/maquina_de_estados_totem.md` · `backend/hardware_api.py` ·
`docs/decisoes/ADR-022_totem_fisico.md` (com a revisão de 19/10)

- **ESP32 é cliente HTTP**; não precisa de IP fixo, só SSID e URL.
- **Protocolo v2 assinado:** HMAC-SHA256 + `boot` + `seq` + timestamp.
- **Idempotência:** o `seq` é consumido na transação que grava as leituras.
- **Wi-Fi caindo:** até 240 leituras na fila.
- **Energia acumulada por sessão, nunca delta.**
- **Nada de `delay()`**; o HTTP bloqueia no máximo **8 s** (`HTTP_TIMEOUT_MS`).
- **5 INA219: 4 vagas + painel.** A 18650 é lida pelo **ADC** (GPIO 35, ADC1,
  divisor 10k + 10k) e a potência dela é **deduzida**: consumo da vaga 4 −
  painel. Sem tensão (divisor solto), a vaga 4 fica na rede.

**Perguntas:** token como hash · clonar a tag · energia contada duas vezes ·
*"como vocês medem a bateria sem sensor?"* → tensão pelo ADC + curva de
circuito aberto da 18650; a corrente é o balanço entre o que a vaga consome e
o painel gera. Estimativa declarada, que erra para o lado seguro.

**Montagem:** GPIO 34 com 10 kΩ ao 3V3 · relés em LOW · **ADC1, nunca ADC2** ·
**GND comum** · calibrar `AJUSTE_ADC`, `V_BATERIA_CORTE` e `V_BATERIA_VOLTA`.

**Exercício:** desligue o Wi-Fi do hotspot 60 s no meio de uma recarga e
confira que a energia não se perde nem é contada duas vezes.

### Trilha E — IA, segurança e produto

**Arquivos:** `backend/chatbot/` · `backend/chatbot/prompts/system.md` ·
`backend/evals/casos.json` · `backend/seguranca.py`

- Quatro camadas + saída; o modelo **nunca escreve SQL** (funções de leitura
  com lista branca).
- Saída reprovada → redator determinístico. `CHAT_MODO=regras` = sem modelo.
- **Identidade sempre do JWT.** Três níveis: morador · gestor · placa.
- **RLS em todas as tabelas.** Painel do gestor é **outro aplicativo** (`:8001`).

**Perguntas:** inventar número · FastAPI × Node · **Supabase × Postgres
próprio** → Postgres com Realtime e RLS prontos; no estande, o backend roda no
PC do Gustavo e fala com o projeto Supabase do Davi · papel da IA.

**Exercício:** `python backend/evals/rodar_eval.py` e tente fazer o assistente mentir.

---

## Nível 2 — o cruzamento (90 min, dia 21)

### 2.1 Sabatina cruzada
Cada dono apresenta em **5 min**; os outros perguntam da trilha **do colega**.

### 2.2 As três respostas que todo mundo sabe
1. **"O cartão identifica quem paga?"** (C)
2. **"Se o USB não manda dados, como sabem a porcentagem?"** (A)
3. **"Por que não dividir igual entre todos?"** (B)

### 2.3 A pergunta hostil

*"Então vocês não falam Modbus, o totem não divide potência e o banco está na
nuvem. O que é real aqui?"*

**A medição é real — nas quatro vagas e no painel —, a matemática é real e
auditada, o algoritmo de alocação é o de produção, e os limites estão escritos
no código, não escondidos.** Depois, liste o §12 do contrato, na ordem.

---

## Calendário: 19 a 22 de outubro

### 19 — montagem
- [ ] Montar conforme `firmware/totem_central/README.md` (painel no INA219 do
      Wire1; 18650 no divisor do GPIO 35)
- [x] B2 + B4 no alocador (108 + 57 testes verdes)
- [x] B3 no totem virtual e no firmware
- [ ] Decidir os donos das trilhas
- [ ] Todo mundo faz o Nível 0

### 20 — subir no PC do Gustavo
- [ ] `git pull`, `pip install -r requirements.txt`, `pip install tzdata`
- [ ] `python -m pytest backend/testes -q` e `python -m pytest totem_virtual/testes -q`
- [ ] Migrations até a 22 no Supabase; `python preparar_totem.py --fisico --sem-env`
- [ ] Firewall + IP fixo + teste do `:8000` de outro celular (README §3.6)
- [ ] Gravar o `segredos.h` (IP do PC, **nunca** `localhost`)
- [ ] Ensaiar o `backend_de_bolso` uma vez

### 21 — ensaio
- [ ] Calibrar o ADC e os limiares da 18650
- [ ] **Carregar um celular de verdade de 20 % a 80 % e cronometrar** — compare com os 100 min previstos
- [ ] Medir quanto a 18650 leva de ~3,65 V até o corte com o painel tapado
- [ ] Ensaiar o painel tapado **cinco vezes**
- [ ] Sabatina cruzada
- [ ] `python provisionar.py verificar` — guardar a saída impressa

### 22 — antes da banca
- [ ] Checklist do hotspot (README §3.6)
- [ ] `w32tm /resync` · `MODO_DEMO=0`
- [ ] Cadastrar o cartão compartilhado
- [ ] Recargas das vagas 1 e 2 começadas 20–30 min antes
- [ ] Um celular em ~78 % para o ciclo de encerramento
- [ ] 18650 em ~3,65 V para a troca solar → rede acontecer na hora
- [ ] Simulador de cenário aberto no painel
- [ ] Plano B: `python -m totem_virtual painel --bolso`

---

## Glossário

| Termo | O que é |
|---|---|
| **SoC** | *state of charge* — percentual de carga |
| **CC/CV** | corrente constante até 80 %, depois tensão constante |
| **Water-filling** | todos sobem juntos até o teto; quem pede menos devolve a sobra |
| **Carga fixa** | ponto que só liga/desliga (o relé do totem): entra pelo que mede |
| **Derating** | redução de potência por temperatura |
| **Pico evitado** | o que teria sido puxado sem gestão menos o que foi |
| **RLS** | *row-level security* — trava de acesso dentro do Postgres |
| **HMAC** | assinatura com chave secreta |
| **Anti-replay** | impedir que uma mensagem capturada seja reenviada |
| **ADC1 / ADC2** | conversores do ESP32; o ADC2 não funciona com Wi-Fi |
| **Balanço da bateria** | consumo da vaga 4 − geração do painel (+ descarregando) |
| **Modbus 10029** | onde a potência alocada seria escrita num HCA G2 real |
| **IEC 61851** | norma de recarga de VE; fixa o mínimo de 6 A |
| **REN ANEEL 1.000/2021** | ampara preço livremente negociado na recarga |

---

Se um número aparecer na tela e você não souber de onde veio, **não é o número
que está errado — é o estudo.**
