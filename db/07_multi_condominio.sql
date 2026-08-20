-- =============================================================
-- GoodWe ChargeOps AI Assistant - Multi-condomínio
-- =============================================================
-- Rodar DEPOIS do 06_rfid_e_temperatura.sql.
--
-- Até aqui o sistema tinha um condomínio só, com o UUID fixo no
-- backend e no frontend. Este arquivo adiciona mais dois locais,
-- cada um com seus próprios carregadores, para provar que a
-- plataforma atende uma rede de condomínios e não uma instalação
-- única.
--
-- Nenhuma coluna nova é necessária: `usuarios.condominio_id` e
-- `carregadores.condominio_id` já existem desde o 01_schema.sql.
-- O que muda é o backend parar de assumir um valor fixo.
-- =============================================================

-- -------------------------------------------------------------
-- Condomínio 2 - Portal dos Bandeirantes
-- -------------------------------------------------------------
insert into condominios (id, nome, endereco, limite_energia_kw)
values (
    'c0000000-0000-0000-0000-000000000002',
    'Portal dos Bandeirantes',
    'Av. Raimundo Pereira de Magalhães, 1720 - Jardim Íris, São Paulo - SP',
    60
)
on conflict (id) do nothing;

insert into carregadores
    (id, condominio_id, numero, modelo, tipo, potencia_maxima_kw, conector, tensao_v, corrente_maxima_a, tarifa_kwh, status, origem)
values
    ('b0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000002', '01', 'GoodWe AC 7,4kW', 'AC', 7.4, 'Tipo 2', 230, 32, 1.95, 'disponivel', 'simulado'),
    ('b0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000002', '02', 'GoodWe AC 7,4kW', 'AC', 7.4, 'Tipo 2', 230, 32, 1.95, 'disponivel', 'simulado'),
    ('b0000000-0000-0000-0000-000000000003', 'c0000000-0000-0000-0000-000000000002', '03', 'GoodWe AC 22kW',  'AC', 22,  'Tipo 2', 400, 32, 2.35, 'disponivel', 'simulado'),
    ('b0000000-0000-0000-0000-000000000004', 'c0000000-0000-0000-0000-000000000002', '04', 'GoodWe AC 7,4kW', 'AC', 7.4, 'Tipo 2', 230, 32, 1.95, 'offline',    'simulado')
on conflict (id) do nothing;

-- -------------------------------------------------------------
-- Condomínio 3 - Residencial Parque das Nações
-- -------------------------------------------------------------
insert into condominios (id, nome, endereco, limite_energia_kw)
values (
    'c0000000-0000-0000-0000-000000000003',
    'Residencial Parque das Nações',
    'Av. Dr. Gastão Vidigal, 1345 - Vila Leopoldina, São Paulo - SP',
    100
)
on conflict (id) do nothing;

insert into carregadores
    (id, condominio_id, numero, modelo, tipo, potencia_maxima_kw, conector, tensao_v, corrente_maxima_a, tarifa_kwh, status, origem)
values
    ('d0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000003', '01', 'GoodWe AC 22kW',  'AC', 22,  'Tipo 2', 400, 32, 2.25, 'disponivel', 'simulado'),
    ('d0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000003', '02', 'GoodWe AC 22kW',  'AC', 22,  'Tipo 2', 400, 32, 2.25, 'disponivel', 'simulado'),
    ('d0000000-0000-0000-0000-000000000003', 'c0000000-0000-0000-0000-000000000003', '03', 'GoodWe AC 7,4kW', 'AC', 7.4, 'Tipo 2', 230, 32, 2.25, 'disponivel', 'simulado'),
    ('d0000000-0000-0000-0000-000000000004', 'c0000000-0000-0000-0000-000000000003', '04', 'GoodWe AC 7,4kW', 'AC', 7.4, 'Tipo 2', 230, 32, 2.25, 'disponivel', 'simulado'),
    ('d0000000-0000-0000-0000-000000000005', 'c0000000-0000-0000-0000-000000000003', '05', 'GoodWe AC 7,4kW', 'AC', 7.4, 'Tipo 2', 230, 32, 2.25, 'disponivel', 'simulado')
on conflict (id) do nothing;

-- -------------------------------------------------------------
-- A fila precisa aparecer em tempo real na prévia de espera.
-- (Se já estiver publicada, o Postgres reclama - por isso o bloco.)
-- -------------------------------------------------------------
do $$
begin
    alter publication supabase_realtime add table fila;
exception
    when duplicate_object then null;
end $$;

-- -------------------------------------------------------------
-- Conferência
-- -------------------------------------------------------------
-- select c.nome, count(ch.id) as carregadores
-- from condominios c
-- left join carregadores ch on ch.condominio_id = c.id
-- group by c.nome order by c.nome;
