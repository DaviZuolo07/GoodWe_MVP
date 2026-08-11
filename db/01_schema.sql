-- =============================================================
-- GoodWe ChargeOps AI Assistant - Schema (Supabase / Postgres)
-- =============================================================
-- Rodar isso no SQL Editor do Supabase (Project > SQL Editor > New query)
-- Cria toda a estrutura de dados do MVP virtual.
-- =============================================================

-- Extensão para gerar UUIDs
create extension if not exists "pgcrypto";

-- -------------------------------------------------------------
-- CONDOMINIOS
-- -------------------------------------------------------------
create table condominios (
    id uuid primary key default gen_random_uuid(),
    nome text not null,
    endereco text,
    limite_energia_kw numeric not null default 80,
    criado_em timestamptz not null default now()
);

-- -------------------------------------------------------------
-- USUARIOS
-- -------------------------------------------------------------
create table usuarios (
    id uuid primary key default gen_random_uuid(),
    nome text not null,
    papel text default 'Morador',              -- ex: Revendedor/Instalador, Morador
    condominio_id uuid references condominios(id) on delete set null,
    bloco_apto text,
    criado_em timestamptz not null default now()
);

-- -------------------------------------------------------------
-- VEICULOS
-- -------------------------------------------------------------
create table veiculos (
    id uuid primary key default gen_random_uuid(),
    usuario_id uuid references usuarios(id) on delete cascade,
    modelo text not null,                      -- "BYD Dolphin Mini"
    placa text,
    capacidade_bateria_kwh numeric not null default 40,
    percentual_bateria numeric not null default 50,  -- 0 a 100
    criado_em timestamptz not null default now()
);

-- -------------------------------------------------------------
-- CARREGADORES
-- -------------------------------------------------------------
create table carregadores (
    id uuid primary key default gen_random_uuid(),
    condominio_id uuid references condominios(id) on delete cascade,
    numero text not null,                      -- "01", "02"...
    modelo text not null default 'GoodWe AC 7,4kW',
    tipo text not null default 'AC',            -- AC | DC
    potencia_maxima_kw numeric not null default 7.4,
    conector text not null default 'Tipo 2',
    tensao_v numeric default 230,
    corrente_maxima_a numeric default 32,
    tarifa_kwh numeric not null default 2.10,
    status text not null default 'disponivel',  -- disponivel | em_uso | fila | offline
    origem text not null default 'simulado',    -- simulado | hardware  <- chave pro next
    atualizado_em timestamptz not null default now(),
    criado_em timestamptz not null default now()
);

-- -------------------------------------------------------------
-- SESSOES DE RECARGA (o coração da simulação em tempo real)
-- -------------------------------------------------------------
create table sessoes_recarga (
    id uuid primary key default gen_random_uuid(),
    carregador_id uuid references carregadores(id) on delete cascade,
    veiculo_id uuid references veiculos(id) on delete set null,
    usuario_id uuid references usuarios(id) on delete set null,
    status text not null default 'aguardando',  -- aguardando | carregando | finalizada | cancelada
    potencia_atual_kw numeric not null default 0,
    energia_entregue_kwh numeric not null default 0,
    percentual_bateria_inicial numeric,
    percentual_bateria_atual numeric,
    tempo_estimado_min integer,
    custo_estimado numeric,
    custo_final numeric,
    origem text not null default 'simulado',    -- simulado | hardware
    iniciado_em timestamptz,
    finalizado_em timestamptz,
    criado_em timestamptz not null default now()
);

-- -------------------------------------------------------------
-- FILA (veículos aguardando um carregador ocupado)
-- -------------------------------------------------------------
create table fila (
    id uuid primary key default gen_random_uuid(),
    carregador_id uuid references carregadores(id) on delete cascade,
    usuario_id uuid references usuarios(id) on delete cascade,
    posicao integer not null default 1,
    criado_em timestamptz not null default now()
);

-- -------------------------------------------------------------
-- PAGAMENTOS
-- -------------------------------------------------------------
create table pagamentos (
    id uuid primary key default gen_random_uuid(),
    sessao_id uuid references sessoes_recarga(id) on delete cascade,
    valor numeric not null,
    metodo text not null default 'rfid_simulado',
    status text not null default 'aprovado',    -- aprovado | recusado | pendente
    criado_em timestamptz not null default now()
);

-- -------------------------------------------------------------
-- NOTIFICACOES
-- -------------------------------------------------------------
create table notificacoes (
    id uuid primary key default gen_random_uuid(),
    usuario_id uuid references usuarios(id) on delete cascade,
    mensagem text not null,
    lida boolean not null default false,
    criado_em timestamptz not null default now()
);

-- -------------------------------------------------------------
-- CHAT (log opcional do chatbot)
-- -------------------------------------------------------------
create table chat_mensagens (
    id uuid primary key default gen_random_uuid(),
    usuario_id uuid references usuarios(id) on delete cascade,
    carregador_id uuid references carregadores(id) on delete set null,
    remetente text not null,                    -- usuario | bot
    mensagem text not null,
    criado_em timestamptz not null default now()
);

-- =============================================================
-- REALTIME: habilita as tabelas que o dashboard precisa
-- escutar em tempo real (carregadores e sessões mudam sozinhos
-- durante a simulação)
-- =============================================================
alter publication supabase_realtime add table carregadores;
alter publication supabase_realtime add table sessoes_recarga;
alter publication supabase_realtime add table fila;
alter publication supabase_realtime add table notificacoes;

-- =============================================================
-- RLS (Row Level Security) - desabilitado por enquanto pro MVP
-- Todo o time acessa com a chave "anon" do Supabase, sem login
-- real de banco. Reabilitar antes de virar produto de verdade.
-- =============================================================
alter table condominios disable row level security;
alter table usuarios disable row level security;
alter table veiculos disable row level security;
alter table carregadores disable row level security;
alter table sessoes_recarga disable row level security;
alter table fila disable row level security;
alter table pagamentos disable row level security;
alter table notificacoes disable row level security;
alter table chat_mensagens disable row level security;
