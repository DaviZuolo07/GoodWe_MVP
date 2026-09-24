# Auditoria de produto — 24/09/2026

Revisão linha a linha do backend antes da banca final. Este arquivo registra
**o que estava errado, por que importava e o que mudou**. Serve para o Gus
saber o que rodar, e para a equipe responder com precisão se a banca perguntar
"o que vocês mudaram desde a CP?".

---

## 1. Bugs de matemática e de regra (os que mudavam número na tela)

### 1.1 Admissão de demanda recusava recarga com o prédio vazio

`demanda.verificar_admissao()` comparava o **menor valor alocado** com o
mínimo de 1,4 kW. Um carro a 99% de bateria pede ~0,9 kW pela própria curva —
e isso fazia o prédio recusar toda recarga nova, mesmo com 29 kW livres.

```
antes:  menor = 0,9 kW  →  0,9 < 1,4  →  409 "condomínio no limite"   (com 29 kW sobrando)
agora:  cada carro precisa de min(1,4 kW, o que ele pede)  →  admite
```

A recusa legítima continua: o 22º carro de 7,4 kW num quadro de 30 kW ainda
recebe 409, porque aí todos ficariam com 1,36 kW. Coberto por dois testes.

### 1.2 Curva de carga aplicada duas vezes

`simulador.py` fazia `potencia_no_soc(limite_alocado, soc)` — aplicando a
queda acima de 80% **em cima de um valor que já era o resultado da curva**.

```
carro a 90%, teto 7,4 kW, alocador liberou os 4,44 kW que ele pede
antes:  potencia_no_soc(4,44, 90) = 2,66 kW   (40% a menos, do nada)
agora:  min(curva, alocado)       = 4,44 kW
```

Efeito visível: recarga mais lenta que o previsto e tempo estimado inflado.
Agora existe `fisica.potencia_efetiva(teto, soc, limite)`, com um dono só para
essa regra, e `tempo_de_carga_min` aceita o limite do alocador.

### 1.3 Reserva estourava em recarga que entra na ponta

A estimativa usava a tarifa do **instante do clique** para a recarga inteira.
Quem começasse às 17h30 uma recarga de 2h via o preço fora da ponta, reservava
por esse valor, e a recarga era cortada no meio ao bater no teto reservado.

```
recarga 20%→80% em 40 kWh, início 17h30 (quarta-feira)
antes:  reserva R$ 52,17  →  custo real R$ 74,35  →  corta no meio
agora:  estimativa integrada no tempo, reserva R$ 74,35
```

`_integrar()` percorre a recarga em passos de 1% de SoC e precifica cada passo
pelo horário em que ele vai acontecer. A mesma função devolve
`energia_ponta_estimada_kwh` e alimenta a dica de economia.

### 1.4 `PATCH /gestor/condominio` aceitava `"25:99"`

A validação era `^\d{2}:\d{2}$`. Um horário impossível gravado em
`ponta_inicio` quebrava `em_horario_de_ponta()` — e com ela a prévia, a
cobrança e o laço do simulador **de todos os condomínios**, porque o laço roda
sobre a tabela inteira. Agora o padrão é `^([01]\d|2[0-3]):[0-5]\d$` (422 em
vez de 500 silencioso).

### 1.5 Simulador contava 10 s por ciclo, mas o ciclo não dura 10 s

`HORAS_POR_CICLO` era constante; o laço dorme 10 s **depois** de fazer as
consultas ao Supabase, que levam de centenas de ms a segundos. A energia
simulada saía sistematicamente abaixo do relógio. Agora usa o tempo real
decorrido, com teto de 30 s para que um servidor que ficou parado não despeje
horas de energia de uma vez.

---

## 2. Bugs de concorrência e de estado

### 2.1 Duas recargas no mesmo ponto

`preparar()` checava "já existe espera aqui?" e depois inseria. Entre a
checagem e o insert cabe outro clique. Agora há índice único parcial no banco
(`uq_sessao_viva_por_carregador` e `..._por_veiculo`, migration 14) e o
segundo pedido recebe 409 com mensagem clara.

### 2.2 Fila nunca esvaziava

Quem entrava na fila e depois conseguia carregar **continuava na fila para
sempre**, ocupando posição e recebendo aviso de vaga. Agora `confirmar()`
remove a pessoa de todas as filas e renumera as posições.

---

## 3. Código morto removido

- `chatbot/`, `testes/` e `evals/` duplicados na **raiz** do repositório. As
  cópias da raiz estavam desatualizadas — a de `chatbot/` nem tinha o
  `verificador.py`. Quem abrisse o arquivo errado depuraria código que não roda.
- `backend/hardware_serial.py` (123 linhas): implementava o fluxo antigo por
  cabo USB. O cabeçalho do `hardware_api.py` já dizia que ele tinha sido
  removido — mas o arquivo continuava lá.

---

## 4. Segurança

| O quê | Situação | Ação |
|---|---|---|
| Token real do ESP32 dentro de `segredos.exemplo.h` | estava versionado e **está no histórico do git** | placeholder no arquivo; **gerar token novo é obrigatório** |
| `segredos.h` fora do `.gitignore` | o arquivo real podia ser commitado | adicionado ao `.gitignore` |
| `VITE_API_URL=http://127.0.0.1:8000` no `.env` | quebrava celular e a máquina do Gus | linha comentada (o app deduz a URL) |
| CORS com lista fixa de origens | cada IP novo de WiFi exigia editar `.env` | regex para IPs privados (RFC 1918) na porta 5173 |
| `requirements.txt` sem versões | `pip install` na véspera podia trazer quebra de API | faixas testadas, com teto na próxima versão maior |
| `eventos_demanda` (tabela nova) | — | nasce com RLS ligada e `revoke` para anon/authenticated; coberta por 2 casos novos no `provisionar.py verificar` (agora 17) |

**Ainda pendente, decisão sua:** `CHAT_MODO=regras` está ativo no `.env`.
Nessa configuração o assistente responde só pelo redator determinístico, sem
chamar o modelo. É o "botão de pânico" — decida antes da banca se apresenta
assim (previsível, 0 ms) ou com `llm`.

---

## 5. O que foi acrescentado para responder ao feedback da GoodWe

### Cobrança
- `GET /recargas/{id}/recibo`: conta linha a linha, com subtotais que somam o
  total no centavo, reservado × cobrado × devolvido, e as movimentações da
  carteira daquela sessão.
- Prévia devolve `valor_reserva` (o que sai do saldo agora, diferente do custo
  estimado por causa da reserva mínima), `economia_se_esperar`,
  `ponta_termina_em` e `energia_ponta_estimada_kwh`.

### Gestão de demanda
- `consumo_horario` passa a guardar **dois picos**: `pico_kw` (o que o prédio
  puxou, com gestão) e `demanda_kw` (o que teria puxado sem gestão). A
  diferença é o pico evitado.
- Recarga barrada pelo limite vira linha em `eventos_demanda` — vira número no
  painel em vez de sumir.
- `POST /gestor/simular-demanda`: "e se N carros ligarem juntos?" rodando o
  **mesmo** `distribuir()` da operação, sem tocar no banco.
- O assistente responde sobre demanda com os números da recarga da própria
  pessoa, vindos do alocador real.

### Valor
- Painel do gestor ganhou receita × custo de energia × margem, participação da
  ponta e `economia_potencial_armazenamento_mes` (o gancho para bateria e
  inversor híbrido da GoodWe).
- As tarifas da distribuidora são **premissas configuráveis**, e o endpoint
  devolve os valores usados junto com o resultado. Apresentar como estimativa,
  nunca como leitura de fatura.

---

## 6. Testes

| Suíte | Antes | Agora |
|---|---|---|
| `testes/test_unidades.py` | 37 | **52** |
| `testes/test_fluxo_esp32.py` | 51 | **62** |

As 26 verificações novas cobrem exatamente os bugs acima — cada correção tem
um teste que falha se ela for desfeita. Nenhuma das duas suítes precisa de
banco, rede ou placa.

---

## 7. Checklist para rodar na máquina do Gus

1. **Supabase → SQL Editor: rode `db/14_valor_e_integridade.sql`.**
   Banco que já tem 01–13 precisa só do 14. É obrigatório: sem ele, as rotas
   novas do painel falham.
   Se o índice único reclamar de duplicata, rode `db/99_limpeza.sql` antes.
2. `cd backend && pip install -r ../requirements.txt`
3. `uvicorn main:app --reload --host 0.0.0.0` (o `0.0.0.0` não é opcional:
   é o que deixa celular e ESP32 alcançarem o servidor)
4. `cd frontend && npm install && npm run dev -- --host`
5. `python provisionar.py verificar` → **17/17**
6. `python provisionar.py token-esp --carregador <uuid>` → token **novo** no
   `segredos.h` → gravar a placa
7. `python testes/test_unidades.py` → 52/52
   `python testes/test_fluxo_esp32.py` → 62/62

O passo 6 não é burocracia: o token antigo está no histórico do git e vale
enquanto não for trocado.
