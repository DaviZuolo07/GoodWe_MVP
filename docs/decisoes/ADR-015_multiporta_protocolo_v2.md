# ADR-015 — Multiporta, protocolo v2, carteira com lastro e vocabulário Modbus

- **Status:** ACEITO em 03/10/2026 — todos os pontos da seção 12 aprovados
- **Data:** 03/10/2026
- **Entrega:** `db/15_multiporta_protocolo_v2.sql` + `db/15_verificacao.sql` + backend + testes
- **Fontes:** handoff do Chat 1, `db/01–14`, backend, snapshot do Supabase (policies, grants, colunas), Mapa Modbus HCA G2

---

## 0. Estado verificado (o que o código diz, além do handoff)

| # | Item | Verificado | Consequência |
|---|------|-----------|--------------|
| 1 | Token do ESP32 | **Já é hash** desde o `11` (SHA-256, coluna `token` removida) | O objetivo 2 vira "HMAC + anti-replay"; o hash não é novidade |
| 2 | Views `v_sessoes_local` / `v_fila_local` | Sem filtro de condomínio | Confirmado: qualquer logado vê todos os locais |
| 3 | Saldo inicial | `default 100.00` no `05`, sem movimento | Confirmado: extrato sem lastro |
| 4 | Cadastro | 4 inserts (usuário, credencial, veículo, favorito) + delete compensatório; nome checado com `ILIKE` antes do insert | Além da atomicidade, há corrida no nome |
| 5 | Registrador 10029 | Faixa **depende do modelo**: 7 kW → 1,4–7; 11 kW → 4,2–11; 22 kW → 4,2–22 | "1,4–7" do handoff cobre só o 7 kW. O seed tem "GoodWe AC 7,4kW" (7,4 kW não existe na linha HCA G2) e a bancada tem 0,025 kW |
| 6 | Grant em `fila` | `authenticated` ainda tem SELECT, sem política desde o `13` | Devolve 0 linhas; o grant sobrou |
| 7 | Realtime | `Dashboard.jsx` e `FilaPanel.jsx` escutam `postgres_changes` em `fila` e `sessoes_recarga` | Com RLS, eventos de linhas alheias não chegam: a fila provavelmente **não atualiza ao vivo desde o `13`**. Confirmar no roteiro |
| 8 | Funções | Postgres dá EXECUTE a `PUBLIC` por padrão; o `11` só fechou o padrão de **tabelas** | Toda função nova nasce chamável pelo navegador se ninguém revogar |
| 9 | Testes | `testes/` e `backend/testes/` divergem | Precisa de uma pasta canônica |
| 10 | `provisionar.py limpar` | Faz `update usuarios set saldo` direto | Quebra a regra saldo = extrato |

---

## D1. Multiporta — tabela `portas_dispositivo`

**Decisão.** Nova tabela fechada ao navegador:

```
portas_dispositivo (id, dispositivo_id → dispositivos, numero smallint 1..8,
                    carregador_id → carregadores UNIQUE, criado_em)
unique (dispositivo_id, numero)
```

- `comandos_dispositivo.porta` e `leituras_hardware.porta`: `smallint not null default 1`.
- **Expand/contract.** O `15` cria a tabela, faz backfill (porta 1 para cada dispositivo existente) e tira `NOT NULL` + `UNIQUE` de `dispositivos.carregador_id`, **mas mantém a coluna** (depreciada, código novo não lê). O `16`, depois do firmware v2 (Chat 3), apaga a coluna.
- **v1:** requisição sem porta = porta 1; dispositivo v1 só recebe comandos da porta 1.
- **Offline:** dispositivo sem contato derruba todos os carregadores das suas portas.

**Rejeitado.** `carregadores.dispositivo_id + porta` (menos uma tabela). Motivo: `carregadores` é legível por qualquer logado (decisão do `11`) e o frontend faz `select *`; a topologia do hardware vazaria para o navegador. Tabela separada mantém isso fechado sem grant por coluna.

---

## D2. Protocolo v2 — autenticação por HMAC

**Problema.** HMAC exige que o servidor tenha o segredo. Se o banco guarda só o hash e a chave do HMAC for esse hash, **o hash vira a chave**: vazou o banco, forja-se qualquer placa. "Só hash no banco" e "HMAC" não convivem no sentido ingênuo.

**Decisão.** Chave por dispositivo **derivada**, nunca armazenada:

```
K = HMAC-SHA256(DEVICE_MASTER_KEY, "chargeops-v2|" + dispositivo_id + "|" + chave_versao)
```

- `DEVICE_MASTER_KEY` só no `backend/.env`. O banco guarda `dispositivo_id` e `chave_versao` (nada secreto).
- `provisionar.py chave-v2 --dispositivo <id>` imprime K **uma vez** para gravar no `segredos.h`. Rotação: `chave_versao + 1`.
- Vazou só o banco: não forja. Vazou o `.env`: forja tudo — mesmo nível do segredo JWT que já está lá; aceito e documentado.
- Cabeçalhos: `X-Device-Id`, `X-Boot`, `X-Seq`, `X-Ts`, `X-Sig`
  `X-Sig = hex(HMAC(K, método \n caminho \n boot \n seq \n ts \n sha256(corpo)))`
- Comparação em tempo constante (`hmac.compare_digest`).
- **Convivência:** `dispositivos.protocolo smallint default 1`. No primeiro handshake v2 válido: `protocolo = 2` e `token_hash = null`. A partir daí o v1 é recusado para aquela placa — **sem downgrade** para o protocolo mais fraco.

**Rejeitado.** Chave cifrada no Vault/pgsodium (mais infra e a chave-mestra continua no env); mTLS (gestão de certificado no ESP32 não cabe no prazo); manter bearer token (sem integridade, replay trivial).

---

## D3. Anti-replay — timestamp **e** sequência

- **Janela:** `|X-Ts − agora| ≤ 120 s`. Relógio da placa: `GET /hardware/v2/hora` (pública, hora não é segredo) ou NTP; o firmware guarda o offset.
- **Sequência:** `boot` = u32 aleatório a cada ligada; `seq` começa em 1 e cresce a **cada requisição assinada** (todas as rotas v2 — um RFID repetido também inicia recarga, não só telemetria). Boot novo só é aceito no handshake.
- **Por que os dois:** só timestamp deixa repetir dentro da janela; só seq deixa repetir um handshake antigo (boot novo = contador novo). Juntos: captura velha cai no ts, captura fresca cai no seq.
- **Onde cada um vive:** HMAC no Python (precisa do `.env`); ts + seq no Postgres, num `UPDATE ... WHERE seq_atual < p_seq` atômico (seguro com dois workers). Por isso o roteiro SQL consegue provar o critério (c).
- **Retry (para o Chat 3):** reenvio = requisição nova = seq novo. Telemetria é idempotente (Wh acumulado + guarda monotônica).

---

## D4. Telemetria em lote

```
POST /hardware/v2/telemetria
{ "t_envio_ms": 123456,
  "leituras": [ { "porta": 1, "t_ms": 121456, "potencia_w": 12.4, "energia_wh": 3.1,
                  "tensao_v": 5.02, "corrente_a": 2.47, "temperatura_c": 31.0,
                  "rele_ligado": true }, ... ] }      // até 30 leituras, corpo ≤ 8 KB
```

- `medido_em = recebido_em − (t_envio_ms − t_ms)`: ordem pelo relógio do servidor, sem confiar no da placa.
- **Uma RPC** `registrar_lote_telemetria` consome o seq **e** insere o lote na mesma transação (sem seq gasto com dado perdido).
- Regra de negócio (sessão, SoC, encerramento, custo) roda no Python **por porta**, com a última leitura de cada porta.
- Resposta: `{ "portas": [ { "porta", "deve_liberar", "motivo", "percentual", ... } ] }`.
- `leituras_hardware` ganha `porta`, `medido_em`, `origem`.

---

## D5. Views filtradas pelos favoritos

- Linha visível se **(condomínio do carregador ∈ favoritos de `auth.uid()`) OU (a linha é minha)**. O "é minha" mantém a própria recarga e a própria posição na fila visíveis mesmo num local não favoritado.
- Colunas iguais: `Dashboard.jsx` e `FilaPanel.jsx` **não mudam**.
- **Mudança de comportamento:** o `CondominioSelect` lista todos os locais (`/condominios`). Num local não favorito, os carregadores aparecem com status (política `true` em `carregadores`), mas sem detalhe de sessão nem fila. Fica para o chat de frontend: selecionar = favoritar, ou aviso na tela.
- `carregadores` continua legível por todos (catálogo/mapa, decisão do `11`).

---

## D6. Carteira com lastro — saldo = soma do extrato

- **Sinal por tipo:** `+` credito, estorno, bonus, ajuste · `−` pre_autorizacao, ajuste_debito. Tipos novos: `bonus`, `ajuste_debito`. Função `sinal_movimento(tipo)` imutável.
- `usuarios.saldo` default `100` → **`0`**.
- **RPC `cadastrar_usuario`** (só `service_role`), uma transação: usuário, credencial, veículo, favorito e `bonus` de R$ 100 com descrição "Crédito de boas-vindas (simulado)". O Argon2 continua no Python: a RPC recebe o hash, nunca a senha.
- **Nome único:** índice único em `lower(nome)`; a RPC converte `unique_violation` em `nome_em_uso` (→ 409). Some a corrida do "checa e depois insere". Se já houver duplicata no banco, a migration avisa e pula o índice em vez de falhar.
- **Backfill:** para cada usuário, `abertura = saldo − Σ extrato`. Se ≠ 0, um movimento datado em `usuarios.criado_em` com `saldo_apos = abertura` — `bonus` "(lançamento retroativo)" quando for 100; `ajuste`/`ajuste_debito` "Saldo de abertura (migração 15)" nos demais. Os `saldo_apos` existentes já embutem esse valor, então a cadeia fecha.
- **Guarda:** trigger `BEFORE UPDATE OF saldo` recusa a alteração se a GUC local `chargeops.carteira` não for `'rpc'` (as RPCs setam). `conferir_carteira()` devolve divergências (roteiro + `provisionar.py verificar`). `provisionar.py limpar` passa a usar ajuste.

**Rejeitado.** Apagar `usuarios.saldo` e calcular sempre pela soma: o `debitar_saldo` precisa de uma linha para travar (`WHERE saldo >= valor`), e saldo é lido em muitos lugares (chatbot inclusive). Coluna fica como cache, protegida pelo trigger.

---

## D7. Vocabulário Modbus HCA G2 (configuração simulada)

| Registrador | Significado no mapa | Coluna em `carregadores` |
|---|---|---|
| 10024 | Manter potência mínima de carga | `garantir_minimo boolean default false` |
| 10025 | Gestão dinâmica de carga (on/off) | `controle_dinamico boolean default false` |
| 10026 | Corrente nominal do disjuntor de entrada, 0–2000 A | `limite_disjuntor_a numeric null` |
| 10029 | Potência máxima de carga (faixa por modelo) | `potencia_maxima_kw` (existente) + nova `potencia_nominal_kw` ∈ {7, 11, 22} |
| 10032 | Modo: 0 rápido · 1 FV · 2 FV+bateria | `modo_carga smallint default 0` (valor do registrador; rótulo na API) |

- Check de 10029 por modelo, **só para `perfil = 'veicular'`** (a bancada USB fica de fora).
- **Correção de dados:** "GoodWe AC 7,4kW" / 7,4 → "GoodWe HCA G2 7kW", nominal 7, máximo 7; o de 22 kW → "GoodWe HCA G2 22kW". Tarifas intocadas. Na tela, 7,4 vira 7.
- `modo_carga` inteiro: quando houver Modbus de verdade, grava-se sem tradução.
- **Honestidade:** são parâmetros armazenados e simulados; o sistema **não** fala Modbus RS485 com um HCA G2. Pitch e UI dizem "parâmetros equivalentes ao mapa Modbus".
- Fora de escopo: 10027, 10028, 10030, 10031.

---

## D8. Solar simulado com origem rotulada

- Domínio: `medido | simulado | estimado` (check constraint).
- `condominios.fv_potencia_kwp numeric default 0` (FV instalada, simulada).
- Nova `geracao_solar (condominio_id, momento, potencia_kw, energia_kwh, origem default 'simulado')`, PK `(condominio_id, momento)`, escrita só pelo simulador, sem grant (gestor lê pela API).
- `leituras_hardware.origem default 'medido'`.
- `carregadores.origem` (`simulado | hardware`) **não muda**: diz de onde vem o equipamento, não o dado. Documentado para não confundir.

---

## D9. Revisão de RLS e grants

| Objeto | Hoje | Ação |
|---|---|---|
| `fila` | SELECT para `authenticated`, sem política | Revogar (só a view lê) |
| Funções em `public` | EXECUTE para `PUBLIC` por padrão | `alter default privileges ... revoke execute on functions from public`; revogar de `public, anon, authenticated` em todas; grant explícito a `service_role` |
| Tabelas novas | — | RLS ligado, sem grant |
| Views | SELECT para `authenticated` | Mantém, agora filtradas (D5) |
| `carregadores`, `condominios` | Leitura ampla | Mantém (catálogo); documentado |
| Realtime de `fila` | Provavelmente mudo desde o `13` | Não se resolve no schema sem abrir linhas; vai para o chat de frontend (broadcast pelo backend ou escutar `carregadores`) |

O roteiro lista toda tabela/view/função de `public` com RLS e privilégios de `anon`/`authenticated` e compara com o esperado.

---

## D10. Testes e roteiro

- **Pasta canônica:** `backend/testes/` (a mais nova). `testes/` da raiz sai.
- **Novos:** HMAC válido / assinatura errada / corpo adulterado; ts fora da janela; seq repetido; downgrade v1 após v2; lote com duas portas; cadastro atômico; saldo = extrato. `supabase_falso.py` ganha as RPCs novas.
- **`db/15_verificacao.sql`** (tudo em `begin … rollback`, impersonação por `set_config('request.jwt.claims', …)`):
  - (a) morador de A não vê sessões nem fila de B, e continua vendo as próprias;
  - (b) `cadastrar_usuario` → saldo 100 = soma do extrato; `conferir_carteira()` vazio;
  - (c) `registrar_lote_telemetria` com o mesmo seq duas vezes → segunda recusada; ts velho → recusado;
  - (d) na parte SQL: dispositivo v1 resolve para a porta 1 e recebe comando. O fluxo v1 completo é provado pelo `test_fluxo_esp32.py` + uma rodada do `simular_esp32.py`.

---

## 11. Impacto por arquivo

| Arquivo | Mudança |
|---|---|
| `db/15_multiporta_protocolo_v2.sql` | Novo, idempotente (D1–D9) |
| `db/15_verificacao.sql` | Novo (D10) |
| `seguranca.py` | Derivação de K, verificação HMAC |
| `dispositivos.py` | Busca por porta; `enfileirar(..., porta)`; offline por dispositivo |
| `hardware_api.py` | v1 intacto (porta 1, recusa se `protocolo = 2`); rotas `/hardware/v2/*` |
| `rotas_conta.py` | Cadastro vira uma chamada à RPC |
| `carteira.py` | Tipos novos; `conferir()` |
| `provisionar.py` | `chave-v2`, `ponto-fisico` com portas, `limpar` via ajuste, `verificar` com carteira e funções |
| `config.py` / `.env.example` | `DEVICE_MASTER_KEY`, `JANELA_REPLAY_S = 120` |
| `backend/testes/` | Novos testes + RPCs no falso |
| `Dashboard.jsx`, `FilaPanel.jsx` | Sem mudança (só conferir) |

**Ordem neste chat:** migration → roteiro SQL → backend → testes → conferência do frontend.
**Fora deste chat:** firmware v2 (Chat 3), migration 16 (contract), seletor de local e realtime da fila, interface.

---

## 12. Pontos aprovados (03/10/2026)

1. **D2** — chave derivada da `DEVICE_MASTER_KEY` no lugar de "HMAC com o hash do token".
2. **D7** — trocar 7,4 kW por 7 kW (modelo real HCA G2) e validar 10029 por modelo.
3. **D5** — local não favorito mostra status dos carregadores, mas não sessões nem fila (ajuste visual depois).
4. **D6** — trigger que bloqueia `update` direto de saldo (muda o `provisionar.py limpar`).
5. **D6** — índice único em `lower(nome)`.
6. **D10** — `backend/testes/` como pasta canônica e remoção de `testes/` da raiz.

---

## Ligação com o comentário da GoodWe

- **Gestão de demanda:** 10025/10026 são o recurso de gestão dinâmica do próprio HCA G2; o limite do condomínio é o mesmo raciocínio no nível do prédio, e a multiporta divide potência entre pontos de uma mesma placa.
- **Cobranças:** todo real na carteira tem uma linha no extrato, inclusive o bônus, rotulado como simulado.
- **Valor para empresa/gestor/usuário:** `origem` separa o que foi medido, simulado e estimado — o painel pode mostrar números sem misturar demonstração com medição.
- **Interface mais atrativa:** fora deste chat.
