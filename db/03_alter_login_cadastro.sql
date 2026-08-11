-- =============================================================
-- GoodWe ChargeOps AI Assistant - Alteração de schema (login/cadastro)
-- =============================================================
-- Rodar isso DEPOIS do 01_schema.sql e 02_seed.sql já executados.
-- Adiciona os campos necessários para o cadastro (morador/visitante
-- e potência do carro) que não estavam no schema original.
-- =============================================================

-- Tipo de usuário: distingue morador de visitante no cadastro
alter table usuarios
    add column if not exists tipo_usuario text not null default 'morador';
    -- valores esperados: 'morador' | 'visitante'

-- Potência máxima que o carro aceita (kW) - usado no cálculo da simulação de recarga
alter table veiculos
    add column if not exists potencia_carro_kw numeric not null default 7.4;

-- Atualiza os veículos do seed com valores de exemplo coerentes
update veiculos set potencia_carro_kw = 7.4 where modelo = 'BYD Dolphin Mini';
update veiculos set potencia_carro_kw = 11 where modelo = 'GWM Ora 03';
