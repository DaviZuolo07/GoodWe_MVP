-- =============================================================================
-- 23_operadores_e_series.sql - operadores pelo Google e série de cada recarga
-- =============================================================================
-- Rodar no SQL Editor DEPOIS do 22, uma vez. É idempotente e só ACRESCENTA:
-- nenhuma tabela, coluna ou dado existente é apagado.
--
-- O QUE CRIA
--   1. operadores_google   pedido de acesso de um operador de condomínio que
--                          entrou com a conta Google. Nasce PENDENTE; só o
--                          admin da plataforma (admins_globais) aprova. Aprovado,
--                          vira uma conta de gestor PRESA ao condomínio pedido,
--                          sem senha (entra só pelo Google) e com o app
--                          autenticador obrigatório antes de ver qualquer dado.
--   2. leituras_sessao     a série de TODA recarga (simulada ou do totem):
--                          potência, energia, %, potência liberada e previsão,
--                          gravada a cada atualização. É o gráfico do app e do
--                          painel, e é o que o admin abre ao clicar na sessão.
--   3. percentual_origem   ganha 'celular': o % veio da bateria do próprio
--                          celular (app aberto no Chrome do Android), e não da
--                          conta pela energia.
--
-- QUEM ACESSA as tabelas novas: só o backend (service_role). As duas nascem com
-- RLS ligado e sem privilégio para anon/authenticated, como o 18 e o 20.
--
-- COMPATIBILIDADE: sem este arquivo o backend continua de pé. O botão "Entrar
-- com Google" responde "rode o db/23", o gráfico de recarga simulada fica vazio
-- (o do totem cai para leituras_hardware) e o % do celular é ignorado.
-- =============================================================================

begin;

-- -----------------------------------------------------------------------------
-- 1. OPERADORES PELO GOOGLE (pedido + aprovação)
-- -----------------------------------------------------------------------------
create table if not exists public.operadores_google (
    id             uuid primary key default gen_random_uuid(),
    -- `sub` é o identificador estável da conta Google (o e-mail pode mudar).
    google_sub     text not null unique,
    email          text not null,
    nome_google    text,
    condominio_id  uuid not null references public.condominios(id) on delete cascade,
    status         text not null default 'pendente',
    usuario_id     uuid references public.usuarios(id) on delete set null,
    decidido_por   uuid references public.usuarios(id) on delete set null,
    decidido_em    timestamptz,
    criado_em      timestamptz not null default now()
);
alter table public.operadores_google drop constraint if exists operadores_google_status_check;
alter table public.operadores_google add constraint operadores_google_status_check
    check (status in ('pendente', 'aprovado', 'recusado', 'revogado'));
alter table public.operadores_google drop constraint if exists operadores_google_tamanhos_check;
alter table public.operadores_google add constraint operadores_google_tamanhos_check
    check (length(google_sub) <= 64 and length(email) <= 254 and coalesce(length(nome_google), 0) <= 120);
create index if not exists idx_operadores_google_status
    on public.operadores_google (status, criado_em desc);

-- -----------------------------------------------------------------------------
-- 2. SÉRIE DE CADA RECARGA
-- -----------------------------------------------------------------------------
-- Unidades de PRODUTO (kW, kWh), as mesmas de sessoes_recarga. No estande a
-- escala é 1:1000 (dispositivos.fator_escala): 7,5 kW aqui = 7,5 W no USB.
create table if not exists public.leituras_sessao (
    id                 bigint generated always as identity primary key,
    sessao_id          uuid not null references public.sessoes_recarga(id) on delete cascade,
    momento            timestamptz not null default now(),
    potencia_kw        numeric not null,
    energia_kwh        numeric not null,      -- acumulada na sessão
    percentual         numeric,
    alocado_kw         numeric,               -- o que o water-filling liberou
    tempo_restante_min integer,
    origem             text not null default 'simulado'
);
alter table public.leituras_sessao drop constraint if exists leituras_sessao_origem_check;
alter table public.leituras_sessao add constraint leituras_sessao_origem_check
    check (origem in ('medido', 'simulado', 'estimado'));
create index if not exists idx_leituras_sessao_sessao
    on public.leituras_sessao (sessao_id, momento);

-- -----------------------------------------------------------------------------
-- 3. % LIDO DO CELULAR
-- -----------------------------------------------------------------------------
alter table public.sessoes_recarga drop constraint if exists sessoes_percentual_origem_check;
alter table public.sessoes_recarga add constraint sessoes_percentual_origem_check
    check (percentual_origem in ('informado', 'estimado', 'celular'));

-- -----------------------------------------------------------------------------
-- 4. FECHADAS AO NAVEGADOR (duas camadas, como no 11, 18 e 20)
-- -----------------------------------------------------------------------------
alter table public.operadores_google enable row level security;
alter table public.leituras_sessao   enable row level security;
revoke all on public.operadores_google, public.leituras_sessao from public, anon, authenticated;
grant  all on public.operadores_google, public.leituras_sessao to service_role;

commit;

-- =============================================================================
-- CONFERÊNCIA (rodar separado). As duas devem dar "permission denied":
--   begin; set local role authenticated; select * from operadores_google limit 1; rollback;
--   begin; set local role anon;          select * from leituras_sessao limit 1; rollback;
-- E esta deve devolver as 2 tabelas:
--   select table_name from information_schema.tables
--    where table_schema = 'public' and table_name in ('operadores_google', 'leituras_sessao');
-- =============================================================================
