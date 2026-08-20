-- =============================================================
-- GoodWe ChargeOps AI Assistant - RFID físico + Temperatura
-- =============================================================
-- 1) rfid_uid: vincula um cartão RFID físico a um usuário, usado pelo
--    fluxo de hardware (leitor RFID real via Arduino).
-- 2) temperatura_c: temperatura simulada do carregador, atualizada pelo
--    backend a cada ciclo do simulador. Influencia o cálculo do tempo
--    estimado de recarga (derating térmico).
-- 3) status "aguardando_rfid" precisa ser aceito em sessoes_recarga -
--    como o campo é texto livre (não é um ENUM no schema original),
--    nenhuma alteração de constraint é necessária aqui.
-- =============================================================

alter table usuarios
    add column if not exists rfid_uid text;

-- Garante que cada cartão só pode estar vinculado a um usuário
-- (permite múltiplos usuários com rfid_uid NULL - Postgres trata NULLs
-- como distintos entre si numa constraint unique)
alter table usuarios
    add constraint usuarios_rfid_uid_key unique (rfid_uid);

alter table carregadores
    add column if not exists temperatura_c numeric not null default 25;
