# Handoff para a sessão de frontend

Este arquivo existe para uma conversa nova não precisar reler o backend
inteiro. Ele traz **os contratos reais** (payloads capturados do app rodando,
não inventados) e a ordem de prioridade do que construir.

Regra que vale para tudo aqui: **o backend já calcula. O frontend só
apresenta.** Nenhuma tela deve recalcular custo, tempo, potência ou economia —
se a tela fizer a própria conta, um dia ela vai discordar da cobrança, e é
exatamente esse tipo de divergência que derruba a credibilidade na banca.

---

## 0. O que a banca pediu, traduzido em tela

> "Tornem a interface mais atrativa e expliquem com maior precisão como o app
> apoia a gestão de demanda, as cobranças e o valor para empresas, gestores e
> usuários." — feedback da GoodWe, CP 87/100 (Gestão de Demanda 5/15)

Os três substantivos viram três entregas visuais:

| Pedido | Onde vive | Prioridade |
|---|---|---|
| **cobranças** | card de economia na prévia + tela de recibo | 1 e 2 |
| **gestão de demanda** | gráfico "sem gestão × com gestão" + KPIs no painel | 3 |
| **valor para empresas/gestores/usuários** | bloco de valor no painel + simulador de cenário | 4 |

A nota foi perdida em **Gerenciamento de Demanda (5/15)**. É a prioridade 3
que recupera ponto, não a 1. Mas a 1 e a 2 são baratas e aparecem no fluxo
principal da demo, então vêm antes por custo/benefício de tempo.

---

## 1. `POST /recargas/previa` — card de economia

Payload real (ponto de bancada, celular de 30% a 80%):

```json
{
  "potencia_efetiva_kw": 0.018,
  "potencia_agora_kw": 0.018,
  "energia_necessaria_kwh": 0.00815,
  "energia_bateria_kwh": 0.0075,
  "energia_ponta_estimada_kwh": 0.0,
  "tempo_estimado_min": 27,
  "custo_estimado": 0.02,
  "tarifa_kwh": 1.95,
  "tarifa_base_kwh": 1.95,
  "em_ponta": false,
  "multiplicador_ponta": 1.5,
  "ponta_termina_em": null,
  "economia_se_esperar": null,
  "fator_termico": 1.0,
  "temperatura_c": 31.2,
  "eficiencia": 0.92,
  "limitado_pela_demanda": false,
  "saldo": 49.0,
  "saldo_suficiente": true,
  "valor_reserva": 1.0,
  "admissao": { "ok": true, "mensagem": null },
  "potencia_prevista_kw": 0.018,
  "perfil_carregador": "bancada",
  "leitor_fisico": true
}
```

**Campos novos desta auditoria** (o frontend atual ainda não usa nenhum):

- `valor_reserva` — o que **sai do saldo agora**. É diferente de
  `custo_estimado` por causa da reserva mínima de R$ 1,00. Hoje a tela mostra
  só o custo estimado, e o morador leva um susto ao ver R$ 1,00 sumir.
  **Mostre os dois, com a frase "a diferença volta no fim".**
- `economia_se_esperar` — `null` fora da ponta; um número em reais quando
  está na ponta. Só renderize o card quando vier número maior que zero.
- `ponta_termina_em` — ISO 8601, para escrever "depois das 21h".
- `energia_ponta_estimada_kwh` — quanto da recarga cai na ponta. Serve para a
  frase "27 min, sendo 12 dentro da ponta".
- `limitado_pela_demanda` — `true` quando o alocador liberou menos que o teto
  do ponto. É o gancho para "sua recarga vai mais devagar porque o prédio está
  cheio" — conectando a tela do morador à gestão de demanda.

Card sugerido (renderizar **apenas** quando `em_ponta === true`):

```
⏱  Agora é horário de ponta
    Começando agora:        R$ 74,35
    Começando após as 21h:  R$ 65,65
    Você economiza R$ 8,70 esperando.
    [ Carregar agora ]  [ Me lembre às 21h ]
```

O segundo botão pode ser só visual nesta versão (ou um `alert`) — não invente
backend de agendamento na véspera. Se preferir não ter botão falso, deixe só
o primeiro.

`admissao.ok === false` → o condomínio está no limite. Mostre
`admissao.mensagem` (já vem escrita em português, explicando o porquê) e
ofereça o botão de entrar na fila. **Não reescreva a mensagem no frontend**:
ela é a explicação de gestão de demanda que a banca quer ouvir.

---

## 2. `GET /recargas/{sessao_id}/recibo` — tela nova

Só o dono da sessão acessa (outro morador recebe 404, não 403). Payload real:

```json
{
  "sessao_id": "5e80fce2-...",
  "status": "finalizada",
  "carregador": "01",
  "iniciado_em": "2026-09-24T03:14:26+00:00",
  "finalizado_em": "2026-09-24T03:14:28+00:00",
  "duracao_min": 0.0,
  "encerrado_por": "alvo_atingido",
  "motivo_legivel": "alvo de carga atingido",
  "percentual_inicial": 40.0,
  "percentual_final": 80.0,
  "linhas": {
    "energia_kwh": 0.006515,
    "energia_fora_ponta_kwh": 0.006515,
    "energia_ponta_kwh": 0.0,
    "tarifa_kwh": 1.95,
    "tarifa_ponta_kwh": 2.925,
    "multiplicador_ponta": 1.5,
    "subtotal_fora_ponta": 0.01,
    "subtotal_ponta": 0.0,
    "total": 0.01
  },
  "custo_estimado": 0.01,
  "valor_reservado": 1.0,
  "valor_cobrado": 0.01,
  "valor_estornado": 0.99,
  "limitado_pela_reserva": false,
  "preco_medio_kwh": 1.5349,
  "movimentacoes": [
    { "tipo": "pre_autorizacao", "valor": 1.0, "saldo_apos": 4.0,
      "descricao": "Reserva da recarga no ponto 01", "criado_em": "..." },
    { "tipo": "estorno", "valor": 0.99, "saldo_apos": 4.99,
      "descricao": "Devolução da diferença entre o reservado e o consumido",
      "criado_em": "..." }
  ]
}
```

Layout sugerido — uma tabela que **soma na frente da pessoa**:

```
Recarga no ponto 01 · 24/09, 00h14 · alvo de carga atingido
Bateria 40% → 80%

  6,5 Wh fora da ponta × R$ 1,95/kWh .......... R$ 0,01
  0,0 Wh na ponta      × R$ 2,93/kWh .......... R$ 0,00
  ─────────────────────────────────────────────────────
  Total consumido ............................. R$ 0,01

  Reservado no cartão ......................... R$ 1,00
  Cobrado ..................................... R$ 0,01
  Devolvido à carteira ........................ R$ 0,99
```

Detalhes que importam:

- `linhas.subtotal_fora_ponta + linhas.subtotal_ponta === linhas.total`,
  garantido no backend e coberto por teste. **Não arredonde de novo no
  frontend** — é o que quebraria a soma.
- Use `energia_legivel`: abaixo de 1 kWh mostre em Wh. O ponto de bancada
  entrega miliwatt-hora; "0,01 kWh" some na tela, "6,5 Wh" não.
- `limitado_pela_reserva === true` → a recarga parou porque bateu no valor
  reservado, não porque a bateria encheu. Vale um aviso explícito.
- `movimentacoes` é o extrato da própria sessão: prova visual da reserva e do
  estorno. Já existe extrato na Carteira; aqui é o recorte de uma recarga.

**Onde colocar o link:** no Histórico (cada linha vira clicável) e na
notificação de fim de recarga.

---

## 3. `GET /gestor/painel` — gestão de demanda (a prioridade de nota)

Três chaves novas: `demanda`, `valor`, e `demanda_kw` dentro de `por_hora`.

### 3.1 Gráfico "sem gestão × com gestão"

`por_hora` continua com 24 posições (0 a 23), agora assim:

```json
{ "hora": 19, "energia_kwh": 0.0, "energia_ponta_kwh": 0.0,
  "pico_kw": 0.0, "demanda_kw": 0.0 }
```

- `pico_kw` — o que o prédio **puxou de fato** (com gestão).
- `demanda_kw` — o que teria puxado se ninguém fosse limitado (sem gestão).
- `demanda_kw >= pico_kw` sempre, por construção no banco.

Gráfico de barras com duas séries e uma linha horizontal em
`demanda.limite_kw`. A área entre as duas séries **é** a gestão de demanda.
Se a barra "sem gestão" ultrapassa a linha do limite e a "com gestão" não,
essa é a imagem inteira do argumento — vale mais que qualquer parágrafo.

Sugestão de cor: "sem gestão" em traço/hachura e tom fraco (é hipotético),
"com gestão" em cor sólida (é o real). Legenda explícita:
`sem gestão (hipotético)` e `com gestão (real)`.

### 3.2 KPIs

```json
"demanda": {
  "limite_kw": 30.0,
  "limite_ponta_kw": 18.0,
  "hoje": { "pico_com_gestao_kw": 0.0, "pico_sem_gestao_kw": 0.0,
            "pico_evitado_kw": 0.0, "horas_com_limitacao": 0,
            "recusas_por_limite": 0 },
  "mes":  { "pico_com_gestao_kw": 0.0, "pico_sem_gestao_kw": 0.0,
            "pico_evitado_kw": 0.0, "horas_com_limitacao": 0,
            "recusas_por_limite": 0, "estouraria_limite": false }
}
```

Quatro números em destaque, no mês:

```
Limite do quadro     30 kW
Pico sem gestão      44,4 kW      ← teria estourado
Pico com gestão      30,0 kW
Pico evitado         14,4 kW      ← o disjuntor que não desarmou
```

`recusas_por_limite` pode vir `null` se a migration 14 não rodou naquele
banco — trate como "—", não como zero.

### 3.3 Bloco de valor

```json
"valor": {
  "receita_mes": 0.01,
  "custo_energia_mes": 0.01,
  "margem_mes": 0.0,
  "margem_percentual": 0.0,
  "energia_mes_kwh": 0.0065,
  "energia_ponta_mes_kwh": 0.0,
  "participacao_ponta_percentual": 0.0,
  "economia_potencial_armazenamento_mes": 0.0,
  "premissas": {
    "custo_energia_kwh": 0.95,
    "custo_energia_ponta_kwh": 1.45,
    "configuravel_em": "PATCH /gestor/condominio",
    "observacao": "Tarifas da distribuidora são premissas do síndico, não leitura da fatura."
  }
}
```

**Renderize `premissas.observacao` na tela, em letra menor, junto do bloco.**
Isso não é excesso de zelo: é a diferença entre "eles sabem o que estão
mostrando" e "eles confundiram estimativa com fatura" quando a banca
perguntar de onde vem R$ 0,95.

`economia_potencial_armazenamento_mes` é o gancho comercial da GoodWe: a
energia que hoje é comprada cara na ponta poderia vir de bateria carregada
fora dela. Uma linha só, com a mesma ressalva de premissa.

`margem_percentual` e `participacao_ponta_percentual` vêm `null` quando não há
base para a divisão (receita ou energia zeradas). Trate `null` como "—".

---

## 4. `POST /gestor/simular-demanda` — simulador

Body: `{ "carros": 6, "potencia_carro_kw": 7.4, "limite_kw": null, "em_ponta": false }`
(`limite_kw` omitido usa o do condomínio; `em_ponta: true` aplica o fator de ponta.)

Resposta (6 carros num quadro de 30 kW):

```json
{ "limite_kw": 30.0, "carros": 6, "potencia_carro_kw": 7.4,
  "pico_sem_gestao_kw": 44.4, "estouraria_limite": true,
  "excesso_evitado_kw": 14.4, "admitidos": 6, "na_fila": 0,
  "kw_por_carro": 5.0, "pico_com_gestao_kw": 30.0,
  "fracao_da_potencia_nominal": 0.676, "minimo_por_carro_kw": 1.4,
  "em_ponta": false }
```

Com 30 carros: `admitidos: 21`, `na_fila: 9`, `kw_por_carro: 1.429`.

Um slider de carros (1 a 30) e um toggle de ponta, recalculando ao soltar.
É a peça que deixa a banca **ver o alocador funcionando** sem precisar de 30
carros — e é o mesmo código que roda em produção, não uma maquete.

Só gestor acessa (morador recebe 403). Não grava nada no banco.

---

## 5. Assistente — o que mudou

A intenção `demanda` agora responde com os números da recarga **da própria
pessoa**, vindos do mesmo alocador da operação. Três respostas diferentes,
conforme o caso:

- recarga limitada pelo condomínio → quanto está recebendo de quanto poderia,
  e por quê;
- ponto físico (ESP32) → a potência é a que o aparelho puxa, medida pelo sensor;
- bateria acima de 80% → explica a curva de carga.

Antes ele dizia "é a bateria acima de 80%" para qualquer recarga lenta,
inclusive quando a causa era o limite do prédio. Se o frontend tiver sugestões
de pergunta prontas no chat, **"por que minha recarga está lenta?" merece
virar um chip fixo** — é a pergunta que demonstra gestão de demanda no
vocabulário do morador.

---

## 6. Ordem de execução sugerida

1. Card de economia na prévia (`economia_se_esperar`, `valor_reserva`) — rápido, aparece no fluxo principal.
2. Tela de recibo — rápida, é uma tabela.
3. Gráfico sem/com gestão + KPIs no painel — **é aqui que está a nota**.
4. Bloco de valor com as premissas visíveis.
5. Simulador de cenário.
6. Polimento visual geral (o "interface mais atrativa" do feedback).

Se o tempo acabar no meio, pare depois do 3. Os itens 1 a 3 já respondem
"cobranças" e "gestão de demanda"; o 4 responde "valor".

---

## 7. Coisas que o frontend atual já tem e não devem regredir

- `src/config.js` deduz a URL da API do endereço que abriu a página. **Não
  volte a fixar `localhost`** — quebra celular e a máquina do Gus.
- O token vive em memória (`supabaseClient.js`), não em `localStorage`. Isso é
  decisão de segurança, não esquecimento: recarregar a página pede login de
  novo, em troca um script injetado não acha o token no disco.
- Nenhuma chamada manda `usuario_id` no corpo. A identidade sai do JWT.
- 401 em qualquer chamada derruba a sessão (`lib/api.js`).
