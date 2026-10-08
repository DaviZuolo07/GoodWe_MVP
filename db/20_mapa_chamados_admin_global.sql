-- ============================================================================
-- 20_mapa_chamados_admin_global.sql  -  mapa, chamados e visão geral do admin
-- ============================================================================
-- Rodar no SQL Editor DEPOIS do 19, uma vez. É idempotente.
--
-- O QUE CRIA
--   1. condominios.latitude / longitude   pino de cada local no mapa do app.
--      Endereço de condomínio já é público no /condominios; a coordenada não
--      revela nada além dele.
--   2. chamados                           dúvida/problema aberto pelo morador
--      no Suporte e respondido pelo painel do gestor.
--   3. admins_globais                     quem enxerga TODOS os locais no
--      painel ("Visão geral"). Ser gestor continua valendo só para o próprio
--      condomínio; estar aqui é o que abre a visão de todos.
--
-- QUEM ACESSA chamados e admins_globais: só o backend (service_role). As duas
-- nascem com RLS ligado e sem privilégio para anon/authenticated, como o 18.
--
-- COMPATIBILIDADE: o backend lê as três coisas com tolerância. Sem este
-- arquivo o mapa mostra "local sem coordenada", o Suporte avisa que chamados
-- não estão disponíveis e a "Visão geral" do painel não aparece.
-- ============================================================================

begin;

-- -----------------------------------------------------------------------------
-- 1. COORDENADAS (geocodificadas pelo OpenStreetMap a partir do endereço)
-- -----------------------------------------------------------------------------
alter table public.condominios add column if not exists latitude  double precision;
alter table public.condominios add column if not exists longitude double precision;

alter table public.condominios drop constraint if exists condominios_coordenada_check;
alter table public.condominios add constraint condominios_coordenada_check
    check ((latitude is null and longitude is null)
           or (latitude between -90 and 90 and longitude between -180 and 180));

update public.condominios set latitude = -23.4785044, longitude = -46.8554637
 where id = '11111111-1111-1111-1111-111111111111' and latitude is null;   -- Melville
update public.condominios set latitude = -23.5044229, longitude = -46.7176165
 where id = 'c0000000-0000-0000-0000-000000000002' and latitude is null;   -- Portal dos Bandeirantes
update public.condominios set latitude = -23.5229052, longitude = -46.7412394
 where id = 'c0000000-0000-0000-0000-000000000003' and latitude is null;   -- Parque das Nações
-- O estande do Next (perfil 'bancada') fica SEM coordenada: não aparece no mapa.

-- -----------------------------------------------------------------------------
-- 2. CHAMADOS
-- -----------------------------------------------------------------------------
create table if not exists public.chamados (
    id             uuid primary key default gen_random_uuid(),
    usuario_id     uuid not null references public.usuarios(id) on delete cascade,
    condominio_id  uuid references public.condominios(id) on delete set null,
    assunto        text not null,
    mensagem       text not null,
    status         text not null default 'aberto',
    resposta       text,
    respondido_por uuid references public.usuarios(id) on delete set null,
    respondido_em  timestamptz,
    criado_em      timestamptz not null default now(),
    atualizado_em  timestamptz not null default now()
);
alter table public.chamados drop constraint if exists chamados_status_check;
alter table public.chamados add constraint chamados_status_check
    check (status in ('aberto', 'em_andamento', 'resolvido'));
alter table public.chamados drop constraint if exists chamados_tamanhos_check;
alter table public.chamados add constraint chamados_tamanhos_check
    check (length(assunto) between 3 and 120 and length(mensagem) between 5 and 2000
           and coalesce(length(resposta), 0) <= 2000);
create index if not exists idx_chamados_usuario on public.chamados (usuario_id, criado_em desc);
create index if not exists idx_chamados_status  on public.chamados (status, criado_em desc);

-- -----------------------------------------------------------------------------
-- 3. ADMINISTRADORES GLOBAIS
-- -----------------------------------------------------------------------------
create table if not exists public.admins_globais (
    usuario_id uuid primary key references public.usuarios(id) on delete cascade,
    criado_em  timestamptz not null default now()
);

-- -----------------------------------------------------------------------------
-- 4. FECHADAS AO NAVEGADOR (duas camadas, como no 11 e no 18)
-- -----------------------------------------------------------------------------
alter table public.chamados       enable row level security;
alter table public.admins_globais enable row level security;
revoke all on public.chamados, public.admins_globais from public, anon, authenticated;
grant  all on public.chamados, public.admins_globais to service_role;

commit;

-- =============================================================================
-- CONFERÊNCIA (rodar separado). As duas devem dar "permission denied":
--   begin; set local role authenticated; select * from chamados limit 1; rollback;
--   begin; set local role anon;          select * from admins_globais limit 1; rollback;
-- E esta deve listar 3 locais com coordenada (o estande fica de fora):
--   select nome, latitude, longitude from condominios where latitude is not null;
-- =============================================================================
