-- =============================================================
-- GoodWe ChargeOps AI Assistant - Seed de dados (demo)
-- =============================================================
-- Popula o banco com dados parecidos com o print de referência,
-- pra abrir o dashboard já com informação visualmente rica.
-- Rodar DEPOIS do 01_schema.sql.
-- =============================================================

-- Condomínio
insert into condominios (id, nome, endereco, limite_energia_kw)
values (
    '11111111-1111-1111-1111-111111111111',
    'LAB FIAP Eco Smart Home',
    'Av. Lins de Vasconcelos, 1222 - Cambuci, São Paulo - SP',
    80
);

-- Usuário principal (o que loga na demo)
insert into usuarios (id, nome, papel, condominio_id, bloco_apto)
values (
    '22222222-2222-2222-2222-222222222222',
    'Davi Zuolo',
    'Revendedor/Instalador',
    '11111111-1111-1111-1111-111111111111',
    'Bloco A - 101'
);

-- Veículo do usuário
insert into veiculos (id, usuario_id, modelo, placa, capacidade_bateria_kwh, percentual_bateria)
values (
    '33333333-3333-3333-3333-333333333333',
    '22222222-2222-2222-2222-222222222222',
    'BYD Dolphin Mini',
    'ABC1D23',
    30.08,
    64
);

-- Segundo veículo (usado no carregador 05 do exemplo)
insert into veiculos (id, usuario_id, modelo, placa, capacidade_bateria_kwh, percentual_bateria)
values (
    '44444444-4444-4444-4444-444444444444',
    '22222222-2222-2222-2222-222222222222',
    'GWM Ora 03',
    'XYZ9F87',
    45,
    36
);

-- 6 carregadores, replicando os status do print
insert into carregadores
    (id, condominio_id, numero, modelo, tipo, potencia_maxima_kw, conector, tensao_v, corrente_maxima_a, tarifa_kwh, status, origem)
values
    ('a0000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', '01', 'GoodWe AC 7,4kW', 'AC', 7.4, 'Tipo 2', 230, 32, 2.10, 'disponivel', 'simulado'),
    ('a0000000-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', '02', 'GoodWe AC 7,4kW', 'AC', 7.4, 'Tipo 2', 230, 32, 2.10, 'em_uso',     'simulado'),
    ('a0000000-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', '03', 'GoodWe AC 7,4kW', 'AC', 7.4, 'Tipo 2', 230, 32, 2.10, 'fila',       'simulado'),
    ('a0000000-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', '04', 'GoodWe AC 22kW',  'AC', 22,  'Tipo 2', 400, 32, 2.10, 'disponivel', 'simulado'),
    ('a0000000-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', '05', 'GoodWe AC 7,4kW', 'AC', 7.4, 'Tipo 2', 230, 32, 2.10, 'em_uso',     'simulado'),
    ('a0000000-0000-0000-0000-000000000006', '11111111-1111-1111-1111-111111111111', '06', 'GoodWe AC 7,4kW', 'AC', 7.4, 'Tipo 2', 230, 32, 2.10, 'disponivel', 'simulado');

-- Sessão ativa: carregador 02 (BYD Dolphin Mini, 64%)
insert into sessoes_recarga
    (carregador_id, veiculo_id, usuario_id, status, potencia_atual_kw, energia_entregue_kwh,
     percentual_bateria_inicial, percentual_bateria_atual, tempo_estimado_min, custo_estimado, origem, iniciado_em)
values (
    'a0000000-0000-0000-0000-000000000002',
    '33333333-3333-3333-3333-333333333333',
    '22222222-2222-2222-2222-222222222222',
    'carregando',
    6.8, 8.73,
    40, 64,
    72, 22.74,
    'simulado', now() - interval '38 minutes'
);

-- Sessão ativa: carregador 05 (GWM Ora 03, 36%)
insert into sessoes_recarga
    (carregador_id, veiculo_id, usuario_id, status, potencia_atual_kw, energia_entregue_kwh,
     percentual_bateria_inicial, percentual_bateria_atual, tempo_estimado_min, custo_estimado, origem, iniciado_em)
values (
    'a0000000-0000-0000-0000-000000000005',
    '44444444-4444-4444-4444-444444444444',
    '22222222-2222-2222-2222-222222222222',
    'carregando',
    7.1, 6.21,
    20, 36,
    58, 13.04,
    'simulado', now() - interval '15 minutes'
);

-- Fila no carregador 03 (2 pessoas aguardando)
insert into fila (carregador_id, usuario_id, posicao)
values
    ('a0000000-0000-0000-0000-000000000003', '22222222-2222-2222-2222-222222222222', 1);

-- Notificações de exemplo
insert into notificacoes (usuario_id, mensagem, lida)
values
    ('22222222-2222-2222-2222-222222222222', 'Sua recarga no Carregador 02 atingirá 80% em breve.', false),
    ('22222222-2222-2222-2222-222222222222', 'Novo carregador disponível no Bloco A.', false),
    ('22222222-2222-2222-2222-222222222222', 'Fatura de recarga do mês está disponível.', false);
