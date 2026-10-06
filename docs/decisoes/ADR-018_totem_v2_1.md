# ADR-018 — Totem v2.1 no servidor: tag primeiro, fila de energia, fontes da vaga solar e eventos de segurança

- **Status:** ACEITO em 06/10/2026 para a interface congelada do contrato; pontos da seção 10 aguardam o Daniel
- **Chat:** D1 — Totem v2.1 no servidor
- **Entrega:** `db/17_totem_escala_fontes.sql` + `db/17_verificacao.sql`, `recarga.py`, `cartoes.py`, `demanda.py`, `hardware_api.py`, `dispositivos.py`, `simulador.py`, `fisica.py`, `testes/test_totem_v21.py`, `testes/supabase_falso.py`, `docs/contratos/totem_v2_1.md`
- **Fora:** fim de sessão pelo INA219, estados `completa_*` e taxa de ocupação (D2, ADR-019); painel do admin (D3)
- **Responde:** ADR-020 seção 9 (P1–P6) e `pedidos/2026-10-06_totem_virtual_backend.md`

---

## 0. Estado verificado

| # | Item | Verificado em | Consequência |
|---|------|---------------|--------------|
| 1 | Tag em vaga livre → `sem_recarga_preparada` | `recarga.processar_cartao` | Fluxo tag-primeiro inexistente |
| 2 | Falta de potência ao aproximar o cartão cancela a recarga (`limite_de_potencia`) | `recarga.confirmar` | Contrato pede `aguardando_energia` com relé desligado e religação depois |
| 3 | Hardware entra no alocador como **carga fixa** | `demanda.item_de` | O relé liga/desliga, não modula: gerenciar = admitir ou fazer esperar |
| 4 | `geracao_solar` aceita `medido`, só o simulador grava | `simulador.gravar_geracao_solar` | Falta o produtor real |
| 5 | Resposta do `/v2/rfid` tem `continuar_aguardando`, `uid`, `saldo_atual`, `valor_reservado`... | `processar_cartao` | Mudança só aditiva: esses campos continuam |
| 6 | Sessão encerrada 30 s depois de a placa sumir | `simulador.ciclo` | Briga com a trava offline de 120 s do totem (ADR-020 P2) |

## D1. Ordem de decisão do `/v2/rfid` (`recarga.processar_tag`)

```
uid inválido                         -> uid_invalido
vaga ocupada (carregando ou esperando energia)
   mesma tag que iniciou (uid_inicio) -> encerrada, desligar
   qualquer outra tag                 -> vaga_ocupada + evento tag_alheia
recarga do app esperando tag na vaga  -> fluxo do app: confirmada_app/ligar | aguardando_energia | recusas antigas
cartão desconhecido                  -> cartao_nao_cadastrado
cartão compartilhado                  -> cartao_de_outro_condominio | sem_recarga_preparada (ver P2)
cartão pessoal                        -> tag-primeiro (D2)
```

Resposta: `autorizado, motivo, acao, tela, mensagem, sessao_id, fila_posicao` + os campos antigos. `acao` é idempotente: o `ligar` também vai como `liberar` em `/v2/comandos`.

**Rejeitado:** tag alheia derrubar a sessão ("quem estiver com a tag manda"). Qualquer UID copiado encerraria a recarga do vizinho.

## D2. Tag-primeiro

- Só **cartão pessoal** inicia: o compartilhado não diz quem paga.
- Morador do mesmo condomínio do ponto (`usuarios.condominio_id`), sem outra sessão viva (`ja_carregando_em_outra_vaga`).
- Veículo: o **primeiro compatível** do morador (bancada → celular). Nenhum → `sem_veiculo`.
- **% inicial = último conhecido do veículo** (`veiculos.percentual_bateria`; 20% se nunca houve), alvo 100%, `percentual_origem = 'estimado'`.
- **% estimado não encerra a recarga.** Quem encerra: a medição (D2), a mesma tag ou o teto da reserva.
- **Reserva no pior caso (bateria vazia):** com o % só estimado, reservar até 100% a partir dele faria a recarga parar no teto se o celular estivesse mais descarregado. A diferença volta inteira no estorno. Celular 1:1000 de 15 kWh a R$ 1,15: reserva R$ 18,75.
- Saldo menor que a reserva → `saldo_insuficiente`, **sem criar sessão**.

**Rejeitado:** pedir o % no totem (4 botões, sem teclado) e usar 0% como % exibido (o morador veria um número sabidamente falso).

## D3. `aguardando_energia` — gestão de demanda visível na bancada

- Novo status de sessão **viva**: ocupa vaga e veículo (índices únicos do 17), saldo já reservado, relé **desligado** (`deve_liberar: false`, `rele_esperado: false`).
- Entra quando o alocador recusa a admissão (rede, sem contar sol) **ou** quando já há fila no condomínio (ordem de chegada).
- `promover_aguardando_energia()` roda no fim de cada recarga, no cancelamento de uma espera e no laço de 10 s; liga por ordem de chegada e **para no primeiro que não cabe**. Ligar = `carregando` + comando `liberar` + notificação.
- A mesma tag (ou o app) cancela a espera com **estorno integral**.
- Vale também para a recarga do app confirmada no totem (antes cancelava com `limite_de_potencia`).

**Rejeitado:** pausar dentro de `carregando` (o alocador contaria a demanda de quem não está puxando) e reservar só na promoção (o saldo podia ter sido gasto na espera).

## D4. Escala no motor

Com o ADR-017, a vaga entra no alocador como 7,5 kW. Num limite de 20 kW, duas vagas carregam e a terceira espera; quando uma sai, a terceira liga sozinha. É a demonstração física do que o HCA G2 faz com o controle dinâmico (manual 3.5: "reduz até pausar... reinicia automaticamente").

## D5. Campo `estado`

O D1 envia `livre | aguardando_energia | carregando | pausada` na telemetria (por porta) e no handshake. `completa_tolerancia | completa_taxa` são do D2. A recarga do app ainda esperando cartão aparece como `livre` (relé aberto) com o `pedido` no handshake, como hoje.

## D6. Fontes da vaga solar

- `dispositivos.porta_solar`: a porta alimentada por painel/bateria (comutação, nunca em paralelo).
- Lote com `fontes` (até 20) e `leituras` possivelmente vazia, gravado na mesma transação (`leituras_fonte`). Resposta: `fontes_gravadas`.
- **Painel → `geracao_solar`** do condomínio, balde de 5 min, energia = Σ P·Δt pelo `t_ms`, origem pela placa (`medido` / `simulado`), com `dispositivo_id`. Linha de placa recente **cala o simulador** (fallback rotulado).
- **Bateria → SOC estimado pela tensão** (curva 18650, a mesma do totem virtual). Sob carga a tensão cede e o SOC sai menor: erra para o lado que protege a bateria.
- **Fração solar da vaga solar é MEDIDA:** `(painel + bateria) / potência da vaga`, limitada a [0, 1]. Portas vizinhas da mesma placa entram no alocador com `so_rede` e não recebem sol atribuído — sem isso o mesmo kWh do painel seria vendido duas vezes.
- **Modbus 10030 (`carregadores.bateria_soc_minimo`, default 20) e 10024 (`garantir_minimo`)** — `demanda.decidir_vaga_solar()`:
  - bateria **descarregando na vaga** com SOC abaixo do 10030 → `pausada` (10024 desligado) ou `rede` (10024 ligado);
  - painel dando conta (bateria parada) → segue `solar`, mesmo com a bateria baixa;
  - volta a `solar` com SOC ≥ 10030 + 5 pontos (histerese);
  - sem leitura de bateria, não muda nada.
- Pausar: `bloquear` + `deve_liberar: false` + `estado: pausada` (a sessão continua viva). Retomar: `liberar`. Rede: `fonte: "rede"` na resposta da porta solar; o relé não muda (pedido ao totem).

**Rejeitado:** decidir só pelo SOC (pausaria com sol forte) e mandar o painel para o alocador como sol do condomínio inteiro (fisicamente ele só alimenta a vaga 4).

## D7. Eventos de segurança

`eventos_seguranca` (RLS ligado, nenhum grant ao navegador; lista fechada): `tag_alheia` (vaga ocupada), `replay`, `assinatura_invalida` (com o IP). O mesmo evento (tipo + placa + IP + uid) é segurado por 5–30 s em memória: martelar a API não enche a tabela. Gravar evento nunca derruba a resposta da placa.

## D8. Offline

A placa continua marcada offline aos 30 s, mas a recarga só é encerrada após **150 s** sem contato (`simulador.SEGUNDOS_OFFLINE_ENCERRA`), acima da trava de 120 s do totem. Wi-Fi que volta antes reconcilia pelo handshake e a energia guardada é cobrada.

## 9. Respostas ao ADR-020 (Davi)

| # | Ponto | Resposta |
|---|---|---|
| P1 | Trava de sessão (`deve_liberar: false` abre o relé) | **Aprovada.** É também o mecanismo da pausa da vaga solar e da espera por energia |
| P2 | Trava offline de 120 s | **Aprovada.** O backend passa a encerrar só após 150 s (D8) |
| P3 | Sinal em `fontes` | Aceito ≥ 0 hoje (o backend não tem `ge=0`). Quando a vaga 4 tiver caminho de rede, a **bateria precisa vir com sinal** (negativa = carregando), senão painel carregando a bateria conta como sol entregue à vaga |
| P4 | Origem das leituras | **Feito:** `dispositivos.virtual = true` grava `simulado` |
| P5 | Confirmação das fontes | **Feito:** `fontes_gravadas` na resposta |
| P6 | Prazo de liberação de vaga vazia/desplugada/cheia | **D2.** Até lá, valem 30 s abaixo de 0,5 W com mais de 0,2 Wh |

## 10. Pontos para o Daniel

| # | Ponto | Padrão adotado |
|---|---|---|
| P1 | Encerrar sessão por placa offline só após 150 s | 150 s |
| P2 | Cartão compartilhado em vaga livre responde `sem_recarga_preparada` (motivo legado, fora da lista do v2.1; o totem já tem tela para ele) | Legado mantido |
| P3 | Tag-primeiro reserva no pior caso (bateria vazia) | Pior caso |
| P4 | SOC mínimo padrão (10030) e histerese | 20% e 5 pontos (SIMULADOS, ajustáveis) |

## 11. Não feito neste chat

- `taxa_pendente`: depende da taxa de ocupação (D2, ADR-019).
- Painel que lê `eventos_seguranca`: D3.
- Comando de troca de fonte para a rede: depende de hardware (pedido ao totem).
