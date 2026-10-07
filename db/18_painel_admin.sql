-- =============================================================================
-- 18_painel_admin.sql - Painel do gestor separado: segundo fator e auditoria
-- =============================================================================
-- ADR-023. Rodar no SQL Editor DEPOIS do 17, uma vez. É idempotente.
--
-- O QUE CRIA
--   1. gestor_mfa        segredo do app autenticador (TOTP) de cada gestor,
--                        CIFRADO pelo backend com a ADMIN_MFA_KEY. Quem ler só
--                        o banco não gera código.
--   2. auditoria_admin   quem entrou no painel, de onde, quem foi recusado e
--                        cada alteração feita por lá.
--
-- QUEM ACESSA: só o backend (service_role). As duas nascem com RLS ligado e
-- sem nenhum privilégio para anon/authenticated - o navegador não lê nem com
-- o token de um gestor.
--
-- COMPATIBILIDADE: o backend antigo ignora estas tabelas. A API
-- administrativa nova (backend/main_admin.py) PRECISA deste arquivo: sem ele
-- o login do gestor funciona só com ADMIN_MFA=opcional e a auditoria não grava
-- (o backend avisa no log, não quebra).
-- =============================================================================

begin;

-- -----------------------------------------------------------------------------
-- 1. SEGUNDO FATOR
-- -----------------------------------------------------------------------------
create table if not exists public.gestor_mfa (
    usuario_id      uuid primary key references public.usuarios(id) on delete cascade,
    segredo_cifrado text not null,          -- Fernet(ADMIN_MFA_KEY), nunca o segredo puro
    ativado_em      timestamptz,            -- null = cadastro iniciado e ainda não confirmado
    ultimo_passo    bigint,                 -- último código aceito: cada código vale UMA vez
    ultimo_uso      timestamptz,
    criado_em       timestamptz not null default now()
);

-- -----------------------------------------------------------------------------
-- 2. AUDITORIA
-- -----------------------------------------------------------------------------
create table if not exists public.auditoria_admin (
    id            uuid primary key default gen_random_uuid(),
    criado_em     timestamptz not null default now(),
    acao          text not null,            -- login, login_recusado, alteracao, mfa_iniciado, mfa_ativado
    usuario_id    uuid references public.usuarios(id) on delete set null,
    condominio_id uuid references public.condominios(id) on delete set null,
    ip            text,
    detalhe       text
);
alter table public.auditoria_admin drop constraint if exists auditoria_admin_tamanhos_check;
alter table public.auditoria_admin add constraint auditoria_admin_tamanhos_check
    check (length(acao) <= 60 and coalesce(length(ip), 0) <= 64
           and coalesce(length(detalhe), 0) <= 200);
create index if not exists idx_auditoria_admin_recentes
    on public.auditoria_admin (condominio_id, criado_em desc);

-- -----------------------------------------------------------------------------
-- 3. FECHADAS AO NAVEGADOR (duas camadas, como no 11)
-- -----------------------------------------------------------------------------
alter table public.gestor_mfa      enable row level security;
alter table public.auditoria_admin enable row level security;
revoke all on public.gestor_mfa, public.auditoria_admin from public, anon, authenticated;
grant  all on public.gestor_mfa, public.auditoria_admin to service_role;

commit;

-- =============================================================================
-- CONFERÊNCIA (rodar separado). As duas devem dar "permission denied":
--   begin; set local role authenticated; select * from gestor_mfa limit 1; rollback;
--   begin; set local role anon;          select * from auditoria_admin limit 1; rollback;
-- =============================================================================
