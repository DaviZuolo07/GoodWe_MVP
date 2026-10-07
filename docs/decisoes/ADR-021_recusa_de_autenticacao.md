# ADR-021 — Totem que o servidor recusa: parar de insistir e dizer por quê

- **Status:** ACEITO em 06/10/2026 (Davi) — pasta `totem_virtual/` e contrato da máquina de estados; P1 e P2 são pedidos ao Daniel
- **Chat:** V2 — laço de 401, totem físico e firmware
- **Entrega:** `totem_virtual/firmware.py`, `totem.py`, `roteiro.py`, `painel.py`, `config.py`, `testes/test_recusa.py`, `docs/contratos/maquina_de_estados_totem.md` §5 e §12
- **Pedido:** `docs/decisoes/pedidos/2026-10-06_totem_para_backend_v2.md`

---

## 0. Diagnóstico do laço (06/10, contra o Supabase real)

Sintoma: `GET /hardware/v2/hora 200` → `POST /hardware/v2/handshake 401`, repetindo sem parar; o roteiro falha com "backend não respondeu em 15 s".

| Hipótese do pedido | Verificação | Resultado |
|---|---|---|
| 1. `.env` do totem de outro provisionamento | `DEVICE_ID` é UUID válido; `DEVICE_KEY_HEX` tem 64 hexa; derivei `HMAC(DEVICE_MASTER_KEY, "chargeops-v2\|id\|v")` localmente | **Bate com a versão 1.** Descartada |
| 2. `preparar_totem.py` com outra chave-mestra | idem | Descartada |
| 3. Dispositivo em outro projeto Supabase | `select` no projeto do `backend/.env` | Existe: "Totem Central", fator 1000, porta solar 4, virtual, 4 portas |
| 4. `chave_versao` rotacionada | banco | `chave_versao = 1`. Descartada |
| 5. Relógio fora da janela | `Date` do Supabase, Google e Cloudflare contra o relógio do PC | **CAUSA.** O PC está **249 s atrasado**; `w32tm /query /status`: "não sincronizado, fonte: Local CMOS Clock" |

Por que o laço:

1. `GET /v2/hora` devolve `time.time()` **do processo do backend**, que roda no mesmo PC atrasado.
2. `consumir_seq` compara o `X-Ts` com `now()` **do Postgres do Supabase**. 249 s > `JANELA_REPLAY_S` (120) → `fora_da_janela`.
3. `fora_da_janela` é **401**, como `assinatura_invalida` (só `replay` e `boot_desconhecido` são 409). A premissa da hipótese 5 do pedido estava trocada.
4. O totem tratava `fora_da_janela` como "acerte a hora" — e a hora que ele acerta vem do mesmo relógio errado. Pior: `_tratar` chamava `_sucesso()`, que zerava a espera. Resultado: hora + handshake a cada volta do laço (~10 por segundo), para sempre.

O mesmo vale para o ESP32 no estande: ele também acerta a hora pelo `/hora` do notebook. **Um notebook com o relógio fora da hora derruba o totem físico do mesmo jeito.**

## D1. Recusa de autenticação conta e bloqueia

Ficam no grupo "recusa de autenticação" as respostas **401** `assinatura_invalida` e `fora_da_janela`.

- Cada recusa espera mais que a anterior (`RETENTATIVA_MIN_MS` dobrando até `RETENTATIVA_MAX_MS`). Recusa **não** chama `sucesso()`.
- `fora_da_janela` continua mandando acertar a hora de novo (o relógio da placa pode ter derivado de verdade).
- **3 recusas seguidas do mesmo tipo** (`RECUSAS_PARA_BLOQUEAR`) → `bloqueio`: um diagnóstico acionável vai para o terminal, para a página e para o LCD, e a próxima tentativa só sai depois de `BLOQUEIO_MS` (60 s).
- Qualquer resposta que não seja recusa (200, 409, 422...) zera a contagem e apaga o diagnóstico.

Diagnóstico, por código:

| Código | Texto (resumo) | Tela |
|---|---|---|
| `assinatura_invalida` | a chave do `.env` não bate com a `DEVICE_MASTER_KEY` do backend (ou o `DEVICE_ID` não existe no banco que o backend usa): rode `backend/preparar_totem.py` de novo | `Chave invalida` |
| `fora_da_janela` | recusou mesmo logo depois de acertar a hora: o relógio do PC do backend discorda do relógio do banco em mais que a janela; sincronize o relógio do Windows e reinicie o backend | `Relogio servidor` |

**Rejeitado — parar de vez (só volta reiniciando a placa).** No estande ninguém reinicia o ESP32 depois de acertar o relógio do notebook. Uma tentativa por minuto é silêncio para o servidor e se cura sozinha.

**Rejeitado — mais tentativas antes de bloquear.** Três já separam "relógio da placa derivou" (o primeiro `fora_da_janela` se resolve com a hora nova) de "relógio do servidor está errado" (repete mesmo com a hora nova).

## D2. Servidor que recusa conta como servidor ausente para a trava offline

Antes, um 401 marcava o servidor como presente (`offline_desde` vazio). Se a chave fosse rotacionada ou o relógio derivasse **com recarga em curso**, os relés ficavam fechados para sempre com o servidor sem aceitar nenhuma leitura.

Agora a recusa de autenticação **inicia** `offline_desde` (se ainda vazio). A trava de 120 s (ADR-020 P2) abre os relés, e a regra "ninguém carrega sem o servidor acompanhando" vale também aqui.

**Rejeitado — abrir os relés na primeira recusa.** Um `fora_da_janela` isolado se resolve em um segundo com a hora nova; derrubar a recarga por isso seria pior que esperar a trava.

## D3. O roteiro diz quem falhou

`conexao` deixa de esperar 15 s cegamente: termina assim que o totem fica `PRONTO` **ou** levanta o diagnóstico. A mensagem distingue:

- **recusou a autenticação** (com o código, quantas vezes e o diagnóstico);
- **respondeu outra coisa** ao handshake (status e código);
- **não respondeu** (só quando nenhuma troca voltou do servidor).

## Pontos para o Daniel

| # | Ponto | Proposta |
|---|---|---|
| P1 | `/v2/hora` devolve o relógio do processo; a janela é conferida pelo relógio do banco | `/v2/hora` devolver o `now()` do Postgres (uma RPC ou o `ts` do próprio `consumir_seq`), com `time.time()` como reserva. Assim o relógio do notebook deixa de importar, inclusive para o ESP32 no estande |
| P2 | `preparar_totem.py` não confere o relógio | Comparar o relógio local com o `Date` do Supabase e avisar se passar de metade da janela |

## Ação imediata (Davi, nesta máquina)

Sincronizar o relógio do Windows (Configurações → Hora e idioma → Data e hora → **Sincronizar agora**, ou `w32tm /resync` num terminal de administrador) e reiniciar o `uvicorn`. Não depende de nenhuma mudança de código.
