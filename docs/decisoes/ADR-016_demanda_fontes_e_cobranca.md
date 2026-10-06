# ADR-016 — Gestão de demanda em duas fontes (rede + solar opcional), cobrança por origem e painel de valor

- **Status:** ACEITO em 04/10/2026 — todos os pontos da seção 12 aprovados
- **Data:** 04/10/2026
- **Entrega prevista:** `db/16_fontes_e_cobranca.sql` + `db/16_verificacao.sql` + backend + testes + cenários + documento do pitch
- **Fontes:** handoff do Chat 2, ADR-015, `demanda.py`, `fisica.py`, `simulador.py`, `recarga.py`, `rotas_gestor.py`, `hardware_api.py`, `db/12`, `db/14`, `db/15`, Mapa Modbus HCA G2, Manual HCA G2 (3.3 e 3.5), Mentoria 1

---

## 0. Estado verificado (o que o código diz, além do handoff)

| # | Item | Verificado | Consequência |
|---|------|-----------|--------------|
| 1 | Preço ao morador | `carregadores.tarifa_kwh` (seed 2,10) × `ponta_multiplicador_tarifa` (1,5) = **2,10 / 3,15** | O handoff fixa custo da rede (0,95/1,45) e solar (0,35 → 0,75), mas **não** o preço da rede ao morador. Com 2,10 o incentivo fica invertido (D6, P1) |
| 2 | Registradores 10024/10025/10026/10032 | Colunas existem, nenhum código lê | "Com e sem controle dinâmico" não existe hoje: todo carro é modulado igual |
| 3 | Mínimo de potência | `MINIMO_CONTROLAVEL_KW = 1.4` para todos | Manual 3.5: 1,4 kW no 7 kW (monofásico), **4,2 kW** no 11/22 kW (trifásico). Carro no 22 kW é admitido abaixo do que o carregador sinaliza |
| 4 | Limite que cai no meio da recarga (início da ponta) | Water-filling pode dar 0,8 kW a um carro e o simulador o faz andar | Fisicamente ele **pausa** (manual: "reduz até pausar"). O número do painel é irreal nesse caso |
| 5 | Sessão | Guarda `energia_entregue_kwh`, `energia_ponta_kwh`, `tarifa_kwh` e `multiplicador_ponta` congelados | Não há onde guardar kWh solar nem preço solar congelado |
| 6 | `consumo_horario` | energia, energia_ponta, pico_kw, demanda_kw | Sem separação rede × solar |
| 7 | Extrato | `CarteiraPage` lê `movimentacoes_carteira` direto; linhas são dinheiro (reserva/estorno) | Não existe rota de extrato no backend; a energia por origem precisa de outro caminho (D8) |
| 8 | `ReciboModal.jsx` | Lê `linhas.energia_fora_ponta_kwh` e `subtotal_ponta` | Chaves antigas precisam continuar existindo |
| 9 | Solar | `fv_potencia_kwp` e `geracao_solar` existem, vazios, ninguém lê | Interface pronta, falta produtor e consumidor |
| 10 | Numeração | ADR-015 reservou a **16** para o contract (apagar `dispositivos.carregador_id`) | Conflito (P7) |
| 11 | `CenarioDemanda` | `potencia_carro_kw` default 7,4 | Modelo inexistente na linha HCA G2 (ADR-015 D7) → 7 |

---

## D1. Vocabulário: fonte, faixa e origem

- Todo kWh entregue a uma sessão é exatamente um de: **solar**, **rede fora ponta**, **rede ponta**.
- `origem` (rótulo de auditoria exposto na API): `rede` · `solar_simulado` · `solar_medido` · `solar_estimado`. A parte solar herda a origem da linha de `geracao_solar` usada no ciclo (`"solar_" + geracao_solar.origem`). **Nenhum `if` testa a origem.**
- Ponta é conceito tarifário **da rede**: só se aplica à rede. Solar tem preço único, sem multiplicador.
- Invariantes (testados): `energia_entregue = solar + rede_fora + rede_ponta`; `total = Σ subtotais arredondados` (antes do teto da reserva).

---

## D2. Excedente solar — interface única

- O alocador lê **só** `geracao_solar`: a linha mais recente do condomínio com `momento ≥ agora − 10 min` → `potencia_kw`. Sem linha recente = 0 (falha segura: sem sol, nada promete energia que não existe).
- `fv_potencia_kwp = 0` → nem consulta. O sistema roda exatamente como hoje.
- Excedente = geração inteira (P6): a carga base do prédio não é modelada. Rotulado no painel.
- `solar_nao_aproveitado = excedente − solar alocado`: aparece no painel como "não absorvido pela garagem". Injeção na rede e créditos (Lei 14.300) ficam fora de escopo.

---

## D3. Alocador de duas fontes — `distribuir_fontes()` (função pura)

**Entrada por item:** `demanda_kw` (curva × teto), `minimo_kw` (por modelo; 0 na bancada), `fixa` (hardware **ou** 10025 = 0), `modo` efetivo (0 se FV = 0), `garantir_minimo`, ordem de chegada.
**Entrada global:** `limite_rede_kw` (o `limite_efetivo` de hoje, já com o fator de ponta) e `solar_kw`.

1. **Fixas** recebem a demanda inteira. Fonte: sol primeiro, depois rede.
2. **Sol restante** → water-filling primeiro entre itens em **modo FV (1)**, que não têm alternativa; o que sobrar, entre os de **modo rápido (0)**.
3. **Rede restante** → water-filling da demanda que falta aos itens modo 0. Itens modo FV com **10024 ligado** recebem da rede só o que falta para o mínimo (manual 3.5: "garantir potência mínima").
4. **Mínimo:** item modulável cujo total ficaria abaixo de `minimo_kw` é **pausado** (0) e a potência dele volta ao pote; na falta, pausa quem chegou por último (P4). Modo FV sem 10024 e sem sol suficiente → pausado com motivo `sem_excedente_fv` (equivale ao status 10 do registrador 10017).
5. **Teto por item** = mínimo entre 10029 (`potencia_maxima_kw`), veículo, derating térmico e — **só com 10025 ligado e 10026 preenchido** — a potência do disjuntor: `V × I` (monofásico) ou `√3 × V × I` (trifásico), com `carregadores.tensao_v`. Como no manual, quem lê o disjuntor é o controle dinâmico.

**Saída por item:** `alocado_kw`, `alocado_solar_kw`, `alocado_rede_kw`, `pausado_motivo`.
**Saída global:** `rede_kw`, `solar_absorvido_kw`, `solar_nao_aproveitado_kw`, `estouro_kw` (> 0 só quando cargas fixas passam do limite da rede — ex.: começa a ponta com carregadores sem controle dinâmico; o painel diz "o disjuntor geral desarmaria").

**Regressão garantida:** FV = 0, todos com 10025 = 1 e modo 0 → mesmo resultado do `distribuir()` atual, salvo a pausa abaixo do mínimo. Vira teste.

**Gravação:** `sessoes_recarga.potencia_alocada_kw` (existe) + `potencia_alocada_solar_kw` (nova).

**Honestidade:** num HCA G2 real, `alocado_kw` seria escrito no 10029 e a parcela da rede corresponde ao 10039 (limite de compra da rede). Aqui não há escrita RS485.

---

## D4. Admissão — o sol nunca é capacidade garantida

- Admissão conta **só a rede** (P3). Sol não é despachável: admitir um carro contando com o sol do meio-dia é prometer o que não se cumpre às 17h.
- Modo FV sem 10024: admitido sem checar a rede (não usa rede; espera sol pausado).
- Modo 0 ou modo FV com 10024: o **mínimo por modelo** precisa caber na rede. Fixa: a demanda inteira precisa caber.
- Mínimo por modelo: 7 kW → 1,4 · 11/22 kW → 4,2 · bancada → sem mínimo.

---

## D5. Atribuição da energia de cada sessão

- **Simulador:** potência real = `min(curva, alocado)`; solar usado = `min(potência, alocado_solar)`; fração solar = solar usado / potência.
- **ESP32:** mesma conta com a potência **medida** e a `potencia_alocada_solar_kw` da sessão. O kWh é medido; a divisão entre fontes é atribuída pela alocação do ciclo.
- `registrar_progresso(..., fracao_solar, origem_solar)`: `delta_solar = delta × fração`, `delta_rede = resto`; `energia_ponta_kwh` soma **só** `delta_rede` em horário de ponta. Continua um único UPDATE condicional (atomicidade mantida).
- `registrar_consumo` passa a receber energia solar e pico da rede.

---

## D6. Preços e custos — premissas por condomínio, nunca no código

| Fonte | Preço ao morador | Custo do condomínio | Situação |
|---|---|---|---|
| Rede fora ponta | `carregadores.tarifa_kwh` | `condominios.custo_energia_kwh` (0,95) | Existe |
| Rede ponta | `tarifa_kwh × ponta_multiplicador_tarifa` | `condominios.custo_energia_ponta_kwh` (1,45) | Existe |
| Solar | `condominios.preco_solar_kwh` (0,75) | `condominios.custo_solar_kwh` (0,35) | **Nova** |

- Congelados na sessão em `preparar()`: `tarifa_kwh`, `multiplicador_ponta` (já) e `tarifa_solar_kwh` (nova). Mudar a tabela não muda a conta de quem está carregando.
- Custos não são congelados: são premissas aplicadas no painel, exibidas junto com o número (como hoje).
- Valores novos só têm default na coluna. O Python não ganha constante de preço.

**Por que o preço da rede importa (exemplo: 10 kWh, 6 vindos do sol, fora da ponta):**

| Preço da rede ao morador | Morador, só rede | Morador, com sol | Margem do condomínio, só rede | Margem do condomínio, com sol |
|---|---|---|---|---|
| 2,10 (atual) | R$ 21,00 | R$ 12,90 | R$ 11,50 | **R$ 7,00 ↓** |
| 1,15 (proposta) | R$ 11,50 | R$ 9,10 | R$ 2,00 | **R$ 3,20 ↑** |

Com 2,10 a margem da rede (1,15/kWh) é quase o triplo da solar (0,40/kWh): **o condomínio ganha menos quando o sol brilha**. A banca pergunta "por que o síndico ligaria o modo FV?" e não há resposta. Com 1,15 (ponta: 1,15 × 1,5 = 1,725) a margem da rede fica em 0,20/0,275 e a solar em 0,40: morador, condomínio e GoodWe ganham juntos com o sol.

O painel calcula `incentivo_solar_alinhado = margem_solar ≥ margem_rede_fora` e alerta o síndico quando for falso — a regra vale para qualquer valor que ele configure.

---

## D7. Estimativa e reserva — pior caso

`calcular_estimativa` continua 100% rede. A reserva cobre a recarga mesmo que o sol suma; o sol só aumenta o estorno. Nenhuma promessa de desconto antes de a energia existir.

---

## D8. Recibo, extrato e notificação

- `detalhar_custo(sessao)` ganha `itens`: `[{origem, faixa, energia_kwh, tarifa_kwh, subtotal}]`, só linhas com energia > 0, ordem solar → rede fora → rede ponta. Total = Σ subtotais.
- Chaves antigas continuam (`energia_fora_ponta_kwh` passa a significar rede fora ponta). O `ReciboModal` atual não quebra; com sol ele mostra só as duas linhas da rede até o chat de frontend adotar `itens` — registrado para esse chat.
- `recibo()` ganha `itens` e `economia_vs_so_rede` (a mesma energia toda pela rede, com as tarifas congeladas; origem `estimado`).
- **Extrato:** o dinheiro continua reserva → estorno (saldo = soma do extrato, intacto). Nova rota `GET /me/extrato`: movimentos + resumo por origem da sessão de cada movimento. A notificação de encerramento passa a listar as linhas por origem.
- **Rejeitado:** um movimento de carteira por origem. Mudaria o modelo reserva/estorno do ADR-015 e criaria três lançamentos por recarga sem ganho de rastreabilidade: o recibo já liga sessão → itens → movimentos.

---

## D9. Solar simulado

- Só quando `fv_potencia_kwp > 0`. Curva de céu limpo, determinística:
  `P(t) = kWp × 0,75 × sen²(π · (h − 6) / 12)` entre 6h e 18h locais; 0 fora disso.
  Rende ≈ 4,5 kWh/kWp/dia, ordem de grandeza de São Paulo. Sem nuvens (testável). Os dois parâmetros ficam em `config.py` como parâmetros **do simulador**, não de preço.
- Grava `geracao_solar` em baldes de 5 min: `momento` = início do balde, `energia_kwh` = integral da curva no balde, `potencia_kw = energia / (5/60)`, `origem = 'simulado'`. Upsert idempotente (reescrever o balde dá o mesmo valor) → sem RPC nova. À noite não grava.
- Ordem no ciclo: gera solar → aloca → avança recargas.
- Com inversor real: algo grava `origem = 'medido'` na mesma tabela e o simulador deixa de gravar naquele condomínio. Nada mais muda.

---

## D10. API do gestor

**`GET` e `PATCH /gestor/carregadores/{id}/modbus`**

| Reg. | Campo | Validação |
|---|---|---|
| 10024 | `garantir_minimo` | bool |
| 10025 | `controle_dinamico` | bool |
| 10026 | `limite_disjuntor_a` | 0–2000 ou null |
| 10029 | `potencia_maxima_kw` | 7 kW: 1,4–7 · 11 kW: 4,2–11 · 22 kW: 4,2–22 |
| 10032 | `modo_carga` | 0 ou 1; 2 recusado (P5); 1 recusado se FV = 0 |

- Resposta: `{registrador, valor, rótulo}` por campo + aviso "parâmetros equivalentes ao mapa Modbus, simulados". Bancada → 409. Só carregadores do condomínio do gestor. Depois do PATCH, `alocar()` na hora.

**`PATCH /gestor/condominio`** aceita também `fv_potencia_kwp` (0–1000), `custo_solar_kwh`, `preco_solar_kwh`. FV → 0 desliga a camada na hora.

**Painel** ganha o bloco `energia` (hoje e mês):
- `linhas`: rede fora · rede ponta · solar — energia, receita, custo, margem, cada uma com `origem`; `total` = soma das linhas.
- `economia_vs_so_rede`: `{morador, condominio}`, origem `estimado`.
- `solar`: `{gerado, absorvido, nao_aproveitado}`, origem `simulado`.
- `pico`: `{sem_gestao, com_gestao, da_rede, evitado_pela_gestao, coberto_pelo_sol}`.
- `incentivo_solar_alinhado`.
- Cada carregador do painel ganha os cinco registradores, `alocado_solar_kw` e `pausado_motivo`.

**`/gestor/simular-demanda`:** default 7 kW (era 7,4). *Se couber:* parâmetro `fv_potencia_kwp` para "e se o condomínio tivesse X kWp?" — ferramenta de dimensionamento que também vende FV GoodWe.

---

## D11. Hardware v2

Cada item de `portas[]` na resposta da telemetria ganha `alocado_kw` (= `potencia_alocada_kw` da sessão; 0 sem sessão). Informativo: o relé do ESP32 não modula e o firmware do Chat 3 pode ignorar. v1 intacto.

---

## D12. Migration 16 — por que é inevitável

Sem colunas novas não há como (a) o síndico configurar preço e custo solar, (b) o recibo provar o kWh solar e o preço congelado, (c) o painel separar rede × sol por hora. Alternativas sem migration (constante em `config.py`, `.env`) violam "configurável pelo síndico, jamais hardcoded".

Conteúdo de `db/16_fontes_e_cobranca.sql` (idempotente, como o 15):
- `condominios`: `custo_solar_kwh` (default 0,35) e `preco_solar_kwh` (default 0,75), ambos `> 0`.
- `carregadores`: default de `tarifa_kwh` → 1,15 e atualização de quem ainda está em 2,10 (P1); default de `controle_dinamico` → true e atualização dos veiculares (P2).
- `sessoes_recarga`: `energia_solar_kwh` (default 0), `origem_solar` (check no domínio do D1), `tarifa_solar_kwh`, `potencia_alocada_solar_kw`; check `energia_solar_kwh + energia_ponta_kwh ≤ energia_entregue_kwh` como `NOT VALID` (não reprova linhas antigas).
- `consumo_horario`: `energia_solar_kwh` e `pico_rede_kw` (default 0).
- `registrar_consumo` com a assinatura nova; EXECUTE revogado de `public, anon, authenticated` e concedido só a `service_role`.

**Roteiro `db/16_verificacao.sql`** (`begin … rollback`): colunas e checks; `registrar_consumo` acumula solar e guarda `pico_rede`; privilégios da função; defaults de tarifa; carregadores veiculares com 10025 ligado.

---

## D13. Testes, cenários e roteiro

**Testes novos (`backend/testes/`):**
- `distribuir_fontes`: regressão com FV = 0; 10025 desligado vira carga fixa; teto do 10026; mínimo 1,4/4,2; pausa do último a chegar; modo FV pausa sem sol; 10024 completa só até o mínimo; `estouro_kw`.
- Admissão ignora o sol.
- `detalhar_custo`: itens fecham o total com sol e ponta; ponta só na rede.
- Curva solar: zero à noite, nunca acima de 0,75 × kWp, energia do balde idempotente.
- Validação Modbus: faixas do 10029 por modelo; modo 2 recusado; modo 1 com FV = 0 recusado; bancada → 409.
- v2: `alocado_kw` em cada porta.

**`testes/cenarios_demanda.py`** — relógio simulado, sem banco. Roda os cenários do critério de pronto e imprime tabelas e recibos; **os números do documento do pitch saem daqui**. Proposta de parâmetros (ajustáveis no script): quadro de 10 kW, 3 × HCA G2 7 kW, carros de 50 kWh indo de 20% a 80%.
- A — sem solar, 10025 desligado, chegada 17h30 (cruza a ponta);
- B — sem solar, 10025 ligado, mesma chegada;
- C — com 10 kWp, modo FV + 10024, chegada 10h;
- D — como C, modo rápido (mostra o sol absorvido primeiro e a rede completando).

**`provisionar.py verificar`:** + colunas novas, + assinatura e privilégio de `registrar_consumo`, + coerência do incentivo solar → de 25 para ~28 checagens.

---

## 11. Impacto por arquivo

| Arquivo | Mudança |
|---|---|
| `db/16_fontes_e_cobranca.sql` | Novo (D12) |
| `db/16_verificacao.sql` | Novo (D12) |
| `demanda.py` | `distribuir_fontes`, mínimo por modelo, leitura de `geracao_solar`, admissão só rede, `alocar` grava a parcela solar |
| `fisica.py` | `detalhar_custo` com `itens`; teto pelo disjuntor (10026) |
| `simulador.py` | Curva solar, baldes de `geracao_solar`, atribuição por fonte |
| `recarga.py` | Congela `tarifa_solar_kwh`; `registrar_progresso` com fração solar; recibo e notificação por origem |
| `rotas_gestor.py` | Rotas Modbus, campos solares do condomínio, bloco `energia`, default 7 kW |
| `rotas_conta.py` | `GET /me/extrato` |
| `hardware_api.py` | Fração solar no ESP32; `alocado_kw` por porta (v2) |
| `config.py` | Parâmetros do simulador solar |
| `provisionar.py` | Checagens novas |
| `backend/testes/` | Testes novos, cenários, RPC nova no `supabase_falso.py` |

**Ordem neste chat:** migration → roteiro SQL → `fisica` → `demanda` → `simulador` → `recarga` → `hardware_api` → `rotas_gestor`/`rotas_conta` → `provisionar` → testes → cenários → documento "como o ChargeOps gere demanda e cobra".
**Fora deste chat:** frontend (adotar `itens`, telas Modbus e solar), firmware v2, migration de contract do ADR-015.

---

## 12. Pontos aprovados (04/10/2026)

1. **P1 — Preço da rede ao morador:** `tarifa_kwh` de 2,10 → **1,15** (default e dados que ainda estão em 2,10), mantendo o mecanismo atual de multiplicador na ponta. Alternativa: manter 2,10 e aceitar o incentivo invertido do D6.
2. **P2 — 10025 desligado = carga fixa** (não modulada, admitida pela demanda inteira). Default vira true e os carregadores veiculares existentes são atualizados para true, preservando o comportamento de hoje.
3. **P3 — Admissão conta só a rede;** o sol nunca é capacidade garantida.
4. **P4 — Abaixo do mínimo, pausa em vez de dividir;** na falta, pausa quem chegou por último. Mínimo por modelo (1,4 / 4,2 kW).
5. **P5 — Modo 2 (FV + bateria) recusado** enquanto não houver bateria modelada; modo 1 recusado com FV = 0 e ignorado pelo alocador se o FV for zerado depois.
6. **P6 — Todo o excedente solar fica disponível à garagem** (carga base do prédio não modelada; rotulado no painel).
7. **P7 — Numeração:** esta migration é a **16**; o contract do ADR-015 vira **17**.

**Ajustes feitos na implementação (04/10/2026):**
- P1 ampliado: os seeds do `07` usavam R$ 1,95 / 2,25 / 2,35, todos com o mesmo incentivo invertido. Na primeira execução do 16, todo preço acima de 1,15 vira 1,15. Reexecutar não mexe no que o síndico definir depois (o default antigo da coluna é o marcador).
- O síndico não tinha como mudar a tarifa da rede: `PATCH /gestor/condominio` ganhou `tarifa_rede_kwh` (aplica a todos os pontos do condomínio; vale para recargas novas).
- Migration ganhou a função `somar_geracao_solar` (baldes de 5 min passam de mil linhas por mês, limite do PostgREST).
- Validado num Postgres local com os papéis do Supabase: 01→16 aplicadas, `16_verificacao` 12/12, `15_verificacao` 30/30.

**Notas da aprovação:** P1 aprovado sabendo que todos os valores são simulados — preço e margem reais não são decisão do time nesta fase; o que se entrega é o mecanismo configurável. P7: o número da migration não importa; se forem necessárias mais, seguem em sequência.

---

## Ligação com o comentário da GoodWe (Gestão de demanda 5/15)

- **Gestão de demanda:** o alocador passa a operar os mesmos parâmetros do HCA G2 (10024, 10025, 10026, 10029, 10032) no nível do prédio, com duas fontes. O cenário A × B mostra, com números, quantas recargas o controle dinâmico viabiliza no mesmo quadro; o painel separa o pico evitado pela gestão do pico coberto pelo sol.
- **Cobranças:** cada kWh tem fonte, faixa, origem e preço congelado; o recibo fecha no centavo e liga energia → dinheiro → extrato.
- **Valor para a empresa (GoodWe):** o software usa os recursos que o hardware já tem e transforma o FV em argumento comercial mensurável ("com X kWp, o condomínio economiza Y").
- **Valor para o gestor:** receita, custo e margem por fonte, alerta de incentivo invertido, limite do quadro respeitado sem obra elétrica.
- **Valor para o morador:** recarga mais barata quando há sol, sem pagar adiantado pela promessa (reserva no pior caso, diferença estornada) e com recibo que ele confere com calculadora.
- **Interface mais atrativa:** fora deste chat.
