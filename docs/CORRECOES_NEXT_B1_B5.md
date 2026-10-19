# Correções B1 a B5 — o que foi implementado (19/10/2026)

**Base: `ef4e9d7` · branch `gus/next-b1-b5` · banca em 22/10**
Contrato: `docs/contratos/experiencia_next.md` · Hardware: ADR-022 (revisão de 19/10).

Override do contrato v1 de pastas (como nas rodadas de 07 e 08/10): mexi em
`backend/` e registro tudo para o Daniel na seção 7.

**Resultado:** `python -m pytest backend/testes -q` → **108 passed** (eram 101);
`python -m pytest totem_virtual/testes -q` → **57 passed** (eram 56);
`arduino-cli compile --fqbn esp32:esp32:esp32` (core 3.3.12) → **83 % da
flash, 18 % da RAM, nenhum aviso dos nossos arquivos**. O firmware **ainda não
rodou numa placa**.

---

## 1. B2 + B4 — alocador (`backend/demanda.py`)

### B2 — o estado do reversor chega ao alocador

`decidir_vaga_solar()` gravava `sessoes_recarga.modo_vaga_solar`, mas
`item_de()` lia só o `modo_carga` do carregador (10032). Agora:

| Função | Mudança |
|---|---|
| `modo_efetivo()` | parâmetro `modo_vaga_solar`; `"rede"` → modo 0 (rápido) |
| `item_de()` | repassa o estado; `"rede"` liga `so_rede` (o painel carrega a 18650: atribuir sol à vaga contaria duas vezes) |
| `_sessoes_ativas()` | passa `s.get("modo_vaga_solar")` |

Ponto modulável, quadro de 20 kW, três na tomada e o quarto no sol: 6,67 kW
para cada um dos três; o sol acaba → **5,0 kW para cada um dos quatro, soma
20,000**. Teste: `test_vaga_solar_na_rede_entra_na_divisao_igual`.

### B4 — vaga com zero não sai como "atendida"

Ponto sem mínimo (bancada) que pedia e recebia zero saía com
`pausado_motivo = None`. Agora: modo FV → `sem_excedente_fv`; rápido →
**`sem_potencia_disponivel`** (novo, **só de relato**: `avaliar_admissao()`
olha `limite_da_rede`, e reaproveitá-lo faria a bancada cheia devolver 409).
Testes: `test_bancada_sem_potencia_nao_sai_como_atendida`,
`test_relato_de_zero_nao_mexe_na_admissao`.

---

## 2. Achado da revisão — **as portas do totem não são divididas**

O B2 resolve o ponto **modulável**. Rodando o alocador com as portas reais do
totem (`origem = 'hardware'`), a história era outra: porta de hardware é
**carga fixa** (`controlavel = False`) — o relé só liga ou desliga e o celular
puxa o que quiser — então ela entra na etapa 1 pelo que **mede** e nunca passa
pelo water-filling. O `modo` não muda nada para ela.

Medido com `item_de()` + `distribuir_fontes()` (escala ×1000, painel 1 kW):

| Situação | Antes | Depois |
|---|---|---|
| limite 20 kW (o do `preparar_totem.py`), 4 vagas a 7,5 | rede 29–30 kW, **estouro de 9–10 kW**; a 3ª vaga nem seria admitida (3 × 7,5 > 20) | limite agora **30 kW**: as quatro cabem |
| vaga 4 **no sol** | 1 kW do sol + **6,5 kW lançados na REDE** (era a 18650 fornecendo) | **toda solar, fora do barramento**: rede = 22,5 kW das três |
| vaga 4 **pausada** (relé aberto) | contava 7,5 kW teóricos | demanda zero |

**Correções (pequenas, em `demanda.py` e `hardware_api.py`):**

1. `item_de()` marca `fora_da_rede = True` para carga fixa com
   `modo_vaga_solar == "solar"`, e zera a demanda com `"pausada"`.
2. `distribuir_fontes()`, etapa 1: `fora_da_rede` é todo solar (painel +
   18650) e não consome rede. `solar_absorvido_kw` continua limitado ao que o
   painel gerou — o resto é sol guardado na bateria.
3. `avaliar_admissao()` **ignora** o `fora_da_rede`: a vaga que hoje está no
   sol pode cair para a rede no meio, então conta pela rede para admitir (a
   invariante 5: o sol não é despachável).
4. `_aplicar_vaga_solar()` grava o `"solar"` implícito na primeira decisão —
   sem isso `modo_vaga_solar` ficava `None` até a primeira troca e o alocador
   não sabia que a vaga estava fora do barramento.

Testes: `test_vaga_solar_do_totem_no_sol_fica_fora_do_barramento`,
`test_admissao_conta_a_vaga_solar_do_totem_pela_rede`,
`test_vaga_solar_grava_o_solar_implicito_para_o_alocador`.

**O que isso significa para o cenário do Davi.** "As quatro dividem
igualmente" acontece no ponto modulável e no simulador. No totem, quando o sol
acaba, a vaga 4 passa para a rede, **cabe no limite** (30 kW exatos) e o kWh
passa a ser cobrado como rede — mas nenhuma vaga recebe "menos", porque um relé
não tem meio-termo. Isso está dito de frente no §7 e no §12 do contrato.

> **Decisão em aberto (não implementada):** dá para fazer o totem dividir de
> verdade cortando o relé em ciclos (ex.: 2 de cada 3 períodos de 30 s a
> 7,5 W = média de 5 W). Muda o contrato da máquina de estados, gasta relé e
> faz o celular "reconectar" a cada ciclo. Não fiz sem perguntar.

---

## 3. B3 — 5 INA219: 4 vagas + painel, bateria pelo ADC

Decisão do Davi (ADR-022, revisão de 19/10). Na ordem do contrato: totem
virtual → firmware.

| Onde | O quê |
|---|---|
| `totem_virtual/bancada.py` | HAL `ler_painel()` (INA219 painel → TP4056) e `tensao_bateria()` (ADC; 0 = ausente); `bateria_vista()` só para a página; `divisor_ligado` no MUNDO |
| `totem_virtual/fisica.py` | `adc_18650()`, `DIVISOR_BATERIA`, `V_BATERIA_AUSENTE = 2,0 V` |
| `totem_virtual/firmware.py` | `_medir_solar()`: painel medido, bateria = tensão + balanço deduzido; lote com `painel` e `bateria`; sem tensão → rede e sem `bateria` no lote |
| `firmware/totem_central/config.h` | `ENDERECO_INA_PAINEL`, `PINO_ADC_BATERIA = 35`, `DIVISOR_BATERIA`, `AJUSTE_ADC`, `AMOSTRAS_ADC`, `V_BATERIA_AUSENTE` |
| `hal.h/.cpp` | `lerPainel()` (calibração 16 V / 400 mA), `tensaoBateria()` (`analogReadMilliVolts`, média de 16, atenuação 11 dB) |
| `maquina.h/.cpp` | `LeituraFonte.painel`, `medirSolar()`, `"fonte": painel/bateria`, guarda de tensão ausente em `fonteSolar()` |

```
reversor no sol:   bateria_w = consumo da vaga 4 − painel_w
reversor na rede:  bateria_w = − painel_w
```

**Diferença em relação à proposta original.** A proposta dizia que a guarda
`if (vBateria <= 0) return;` impedia a vaga de "travar na rede". Não impede: só
congela a fonte onde estiver — inclusive no **sol**, com a bateria sem
vigilância. Implementei o contrário: **sem tensão, vai para a rede** (a fonte
que sempre funciona), sem marcar a bateria como ruim, e volta ao sol assim que
a leitura voltar. Teste:
`test_vaga_solar_com_divisor_solto_fica_na_rede_e_nao_manda_bateria`.

O backend não mudou para o B3: `_gravar_geracao()` (já coberto por
`test_lote_so_com_fontes_grava_painel_medido_e_soc_estimado`) passa a receber
`painel` do totem físico. `painel_w + bateria_w` = o que a vaga 4 recebe do
lado solar → fração solar 1 no sol e 0 na rede.

**Limites declarados:** o balanço ignora as perdas do TP4056/MT3608 (~10 %);
com a 18650 cheia o TP4056 para de puxar e o painel mede ~0 (geração
**aproveitada**, não potencial); com o divisor solto e o reversor na rede, o
backend ainda atribui a geração do painel à vaga 4 como fração solar até a
leitura voltar.

**Na bancada (Gustavo):** fiação e calibração em
`firmware/totem_central/README.md` (seções Montagem e Calibrar).

---

## 4. B1 — rodar no PC do Gustavo, banco no Supabase do Davi

Decisão: tudo local no PC do Gustavo, o banco é o projeto Supabase do Davi,
internet pelo hotspot. Sem deploy.

| Feito | Onde |
|---|---|
| `HTTP_TIMEOUT_MS` 3000 → **8000** (handshake ~5 s do Brasil ao Canadá) | `config.h`; totem virtual `TOTEM_HTTP_TIMEOUT_S` padrão 8; contrato da máquina de estados |
| Firewall, IP fixo, medida de latência, checklist do hotspot, plano B | README §3, Passo 6 |
| `preparar_totem.py`: limite **30 kW**; T4 com `modo_carga = 1` e `garantir_minimo = true` | os `update` SQL da proposta deixam de ser necessários — rode o script de novo |

**Não feito:** medir a latência no hotspot (precisa do PC do Gustavo no 4G) e
migrar o Supabase para São Paulo (só se a medida passar de 4 s).

---

## 5. B5 — README

Lista das 22 migrations, `98`/`99`, verificações, Python 3.13, testes em
pytest (108 + 57), Totem Central no lugar da placa v1, rede do estande, sem
deploy, limites novos. Seções antigas da placa v1 (§4 "Qualquer carregador pode
ser físico", §5 roteiro do Gus Bancada) ficaram, marcadas como v1.

---

## 6. O que o grupo precisa fazer

1. **Rodar de novo** `python preparar_totem.py --fisico --sem-env` no banco
   (grava o limite de 30 kW e a T4 com 10032/10024).
2. Montar o painel no INA219 do `Wire1` e o divisor no GPIO 35; calibrar.
3. Gravar o firmware novo e conferir no serial `fonte` com `painel` > 0 ao sol.
4. B1 com o hotspot (README Passo 6).
5. Ensaiar a troca solar → rede **com a 18650 já baixa** (~3,65 V): cheia, ela
   segura a vaga 4 por ~50 min e a troca não acontece na frente da banca.

---

## 7. Registro para o Daniel (backend)

| Arquivo | Mudança | Teste |
|---|---|---|
| `backend/demanda.py` | B2 (`modo_vaga_solar`), B4 (`PAUSA_SEM_POTENCIA`), `fora_da_rede`, pausada = 0, admissão ignora `fora_da_rede` | `test_demanda_fontes.py` (+6) |
| `backend/hardware_api.py` | `_aplicar_vaga_solar` grava o `"solar"` implícito | `test_totem_v21.py` (+1) |
| `backend/preparar_totem.py` | limite 30 kW; T4 FV + garantir mínimo | `test_preparar_totem.py` |

Nenhuma migration nova; nenhum contrato de API mudou (a resposta da telemetria
é a mesma; `pausado_motivo` ganhou um valor possível).
