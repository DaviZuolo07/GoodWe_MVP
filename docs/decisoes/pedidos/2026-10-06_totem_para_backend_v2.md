# Pedido ao backend — laço de 401, totem físico e respostas ao D1

- **De:** Davi · **Para:** Daniel · **Data:** 06/10/2026
- **Origem:** ADR-021 (recusa de autenticação) e ADR-022 (totem físico)
- **Bloqueia o gate de 11/10?** Não. O laço tinha causa local (relógio do PC) e o totem já para de insistir. O item 1 evita que o mesmo problema derrube o ESP32 no Next.

## 1. `/v2/hora` deveria devolver o relógio do banco (ADR-021 P1) — prioridade

Causa do laço de hoje: o PC estava **249 s atrasado** (Windows sem sincronizar). `/v2/hora` devolve `time.time()` do processo; `consumir_seq` confere a janela com o `now()` do Postgres. Diferença > 120 s → todo handshake vira **401 `fora_da_janela`** (não `replay`: só replay e boot_desconhecido são 409). O totem acertava a hora pelo mesmo relógio errado e tentava de novo, para sempre.

Chave, `DEVICE_ID`, `chave_versao` e o projeto Supabase foram conferidos: tudo certo (derivei a chave localmente e ela bate com a versão 1).

Proposta: `/v2/hora` devolver o `now()` do Postgres (uma RPC pequena, ou guardar o `ts` do banco), com `time.time()` como reserva. No estande, o backend roda num notebook; se o relógio dele escorregar, o ESP32 cai do mesmo jeito.

## 2. `preparar_totem.py` conferir o relógio (ADR-021 P2)

Comparar o relógio local com o cabeçalho `Date` do Supabase e avisar acima de metade da `JANELA_REPLAY_S`. Teria achado o problema em um segundo.

## 3. Hardware real do Totem Central (ADR-022)

| # | O que muda para o backend | Pedido |
|---|---|---|
| P1 | `fontes` traz **só `bateria`**, com sinal (+ descarregando, − carregando). O painel não tem sensor | Nada a mudar (o modelo já aceita). Confirmar que sem `painel` o simulador segue como fallback rotulado. O exemplo do `docs/contratos/totem_v2_1.md` §3 ainda mostra `painel` |
| P2 | A vaga 4 **tem caminho de rede**: relé reversor (SPDT) bateria ↔ fonte de 5 V | **Manter** `fonte: "rede"`. Implementado e testado no totem |
| P3 | Na rede, a bateria descansa, a tensão sobe e o SOC estimado pula acima de 10030 + 5 → volta para solar → sob carga cai → rede... | Medir o SOC só com a bateria descarregando, ou exigir tempo mínimo em `rede`. O totem segura 30 s (`FONTE_MIN_MS`) para poupar o relé |
| P4 | LCD **16x2** | O totem re-quebra a `tela` em 16 colunas e pagina de 2 em 2. Se der, linhas de até 16 e no máximo 2. O formato atual continua aceito |
| P5 | Corte local da bateria (< 3,30 V) vai para a **rede**, mesmo com o 10024 desligado | É proteção de hardware, bem abaixo dos 20% do 10030. Se preferir pausa, o handshake precisa mandar o 10024 |

## 4. Sobre os três testes ajustados na minha pasta

Rodei `totem_virtual/testes` na minha cópia: verde. Concordo com a direção dos três ajustes; corrigi dois detalhes:

- `test_tag_e_botao...`: o comentário dizia que o relé fecha pelo comando `liberar`. No v2.1 fecha na hora, pelo `acao: "ligar"` do RFID. Agora o teste afirma isso (`motivo_rele == "rfid"`) e que a vaga segue ligada depois que a tela volta.
- `test_duas_vagas_carregam_juntas...`: aceitava `acao in ("ligar", "confirmada_app")`, mas `confirmada_app` é **motivo**, não ação. Agora: `(autorizado, motivo, acao) == (True, "confirmada_app", "ligar")`.
- O ajuste tirou a única asserção de que `autorizado: true` **não** fecha o relé. Acrescentei `test_fila_de_energia_autorizado_sem_ligar_e_liga_sozinha_depois`, contra o backend D1 em memória: limite baixo → `aguardando_energia`/`nenhuma`, relé aberto, LCD `1:FILA`; limite sobe → `simulador.ciclo()` → `liberar` → liga na **mesma** sessão.
- `test_roteiro...`: a docstring atribuía as 3 falhas a "espera de 15 s"; a causa é o D2 (fim de sessão pela medição). Corrigido. Os três cenários do D2 seguem FALHOU contra o backend real até o D2 entrar.

## 5. Arquivos na tua pasta que vi no `git status`

`backend/testes/test_maquina_de_estados.py` e `backend/testes/test_roteiro.py` aparecem **apagados** (não staged); eram cópias dos testes do totem que entraram em `backend/testes` no commit `c77c49b`. Não mexi. Se a ideia era tirá-los de lá, confirma no teu PR.
