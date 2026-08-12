-- =============================================================
-- GoodWe ChargeOps AI Assistant - Saldo (billing simulado)
-- =============================================================
-- Adiciona um saldo em R$ para cada usuário, usado para simular
-- o pagamento RFID de verdade (não é mais sempre aprovado).
-- Usuários novos E os que já existem recebem R$ 100,00 de crédito
-- de demonstração.
-- =============================================================

alter table usuarios
    add column if not exists saldo numeric not null default 100.00;
