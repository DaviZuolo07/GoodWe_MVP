-- =============================================================
-- GoodWe ChargeOps AI Assistant - Fluxo real do cartão RFID
-- =============================================================
-- O QUE MUDA NO FLUXO
-- -------------------
-- Antes: o site perguntava o cartão primeiro (simulado, um clique), depois a
-- bateria, depois iniciava a recarga direto. O cartão era decoração.
--
-- Agora: o site define bateria e alvo, confirma, e ENTÃO fica aguardando o
-- cartão físico no ESP32. Quem decide se a recarga começa é a aproximação do
-- cartão — e a verificação de saldo acontece nesse instante, não antes.
--
-- Isso cria um estado que não existia: uma sessão parada, esperando um evento
-- do mundo físico que pode nunca acontecer. Três colunas nascem daí.
-- =============================================================

-- -------------------------------------------------------------
-- 1. alvo_percentual — até onde carregar
-- -------------------------------------------------------------
-- `calcular_estimativa()` sempre aceitou um parâmetro `alvo`, mas ninguém
-- nunca o passava: toda estimativa era até 100%. Agora que o morador define
-- isso na tela, o valor precisa sobreviver até o cartão ser lido — que pode
-- ser minutos depois, em outro processo, disparado pelo ESP32.
alter table sessoes_recarga
    add column if not exists alvo_percentual numeric not null default 100;

-- -------------------------------------------------------------
-- 2. motivo_recusa — por que não começou
-- -------------------------------------------------------------
-- ESTA É A COLUNA CENTRAL DA MUDANÇA.
--
-- Quando o saldo é insuficiente, quem descobre isso é o backend respondendo
-- ao ESP32 — não ao navegador. O morador está de pé no carregador, olhando o
-- celular, e o erro acontece num canal onde ele não está ouvindo.
--
-- A solução é não deixar a recusa morrer na resposta HTTP: ela é gravada na
-- própria linha da sessão. Como `sessoes_recarga` já está publicada no
-- Realtime, o navegador recebe o UPDATE e mostra a recusa na tela sozinho.
-- O canal de volta para o usuário é o banco, não a requisição.
alter table sessoes_recarga
    add column if not exists motivo_recusa text;

-- -------------------------------------------------------------
-- 3. expira_em — a espera não pode ser eterna
-- -------------------------------------------------------------
-- Uma sessão `aguardando_rfid` segura o carregador. Se o morador desistir e
-- fechar o navegador, ninguém desfaz esse estado e o ponto fica travado até
-- alguém mexer no banco. Numa demo isso significa um carregador morto no
-- meio da apresentação.
--
-- Com prazo, o laço do simulador (que já roda a cada 10s) cancela sozinho.
alter table sessoes_recarga
    add column if not exists expira_em timestamptz;

-- A varredura de expirados roda a cada 10s, então merece índice.
create index if not exists idx_sessoes_aguardando_rfid
    on sessoes_recarga (status, expira_em)
    where status = 'aguardando_rfid';

-- -------------------------------------------------------------
-- 4. Valores de status
-- -------------------------------------------------------------
-- A coluna é texto livre (sem check constraint), então nada quebra. Ficam
-- documentados os valores em uso:
--
--   aguardando_rfid -> preparada, esperando o cartão
--   carregando      -> em andamento
--   finalizada      -> terminou normalmente
--   cancelada       -> desistência ou prazo esgotado
--   recusada        -> NOVO: cartão lido mas a autorização falhou
--
-- `recusada` é diferente de `cancelada` de propósito: uma é decisão do
-- sistema (saldo), a outra é ausência de ação (desistiu, expirou). Numa
-- análise de histórico, misturar as duas esconderia exatamente o número que
-- interessa — quantas recargas falharam por falta de saldo.

comment on column sessoes_recarga.alvo_percentual is
    'Percentual de bateria desejado ao final. Definido na tela, honrado no cartão.';
comment on column sessoes_recarga.motivo_recusa is
    'Preenchido quando status = recusada. Chega ao navegador via Realtime.';
comment on column sessoes_recarga.expira_em is
    'Prazo para aproximar o cartão. Depois disso o laço do simulador cancela.';

-- -------------------------------------------------------------
-- 5. Limpeza de sessões órfãs de testes anteriores
-- -------------------------------------------------------------
update sessoes_recarga
set status = 'cancelada',
    motivo_recusa = 'limpeza_migration_10',
    finalizado_em = now()
where status = 'aguardando_rfid';

-- -------------------------------------------------------------
-- Conferência
-- -------------------------------------------------------------
-- select id, status, alvo_percentual, motivo_recusa, expira_em
-- from sessoes_recarga
-- order by criado_em desc limit 10;
