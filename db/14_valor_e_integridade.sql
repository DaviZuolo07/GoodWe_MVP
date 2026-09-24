-- =============================================================================
-- 14_valor_e_integridade.sql
-- =============================================================================
-- Rode DEPOIS do 13. Idempotente: pode rodar de novo sem estragar nada.
--
-- 1. INTEGRIDADE  Uma recarga viva por ponto e por veículo, garantido pelo
--                 banco. O backend já checava, mas "checar e depois inserir"
--                 tem uma janela: dois cliques no mesmo segundo criavam duas
--                 esperas no mesmo carregador.
-- 2. DEMANDA      A curva horária passa a guardar DOIS picos: o que o prédio
--                 puxou (com gestão) e o que teria puxado sem gestão. A
--                 diferença é a prova do valor do alocador.
-- 3. RECUSAS      Recarga barrada pelo limite vira evento contável.
-- 4. CUSTO        Premissas de tarifa da distribuidora (o que o condomínio
--                 paga), para o painel mostrar receita x custo x margem.
-- =============================================================================

begin;

-- --- 1. Integridade ----------------------------------------------------------
-- Se algum destes falhar com "could not create unique index", existe sessão
-- duplicada viva: rode o 99_limpeza.sql e depois este arquivo de novo.
create unique index if not exists uq_sessao_viva_por_carregador
    on public.sessoes_recarga (carregador_id)
    where status in ('aguardando_rfid', 'carregando');

create unique index if not exists uq_sessao_viva_por_veiculo
    on public.sessoes_recarga (veiculo_id)
    where status in ('aguardando_rfid', 'carregando');

create unique index if not exists uq_fila_usuario_carregador
    on public.fila (carregador_id, usuario_id);

-- --- 2. Pico sem gestão na curva horária -------------------------------------
alter table public.consumo_horario
    add column if not exists demanda_kw numeric not null default 0;

-- A assinatura muda (parâmetro novo): derruba a antiga para o PostgREST não
-- ficar em dúvida entre duas versões com os mesmos nomes de parâmetro.
drop function if exists public.registrar_consumo(uuid, numeric, boolean, numeric);

create or replace function public.registrar_consumo(
    p_cond uuid, p_kwh numeric, p_ponta boolean, p_carga_kw numeric, p_demanda_kw numeric default 0
) returns void
language sql
set search_path = public
as $$
    insert into consumo_horario (condominio_id, hora, energia_kwh, energia_ponta_kwh, pico_kw, demanda_kw)
    values (p_cond, date_trunc('hour', now()), greatest(p_kwh, 0),
            case when p_ponta then greatest(p_kwh, 0) else 0 end,
            greatest(p_carga_kw, 0), greatest(p_demanda_kw, p_carga_kw, 0))
    on conflict (condominio_id, hora) do update set
        energia_kwh       = consumo_horario.energia_kwh + excluded.energia_kwh,
        energia_ponta_kwh = consumo_horario.energia_ponta_kwh + excluded.energia_ponta_kwh,
        pico_kw           = greatest(consumo_horario.pico_kw, excluded.pico_kw),
        demanda_kw        = greatest(consumo_horario.demanda_kw, excluded.demanda_kw);
$$;

revoke all on function public.registrar_consumo(uuid, numeric, boolean, numeric, numeric)
    from public, anon, authenticated;
grant execute on function public.registrar_consumo(uuid, numeric, boolean, numeric, numeric)
    to service_role;

-- --- 3. Eventos de demanda ---------------------------------------------------
create table if not exists public.eventos_demanda (
    id            uuid primary key default gen_random_uuid(),
    condominio_id uuid not null references public.condominios(id) on delete cascade,
    usuario_id    uuid references public.usuarios(id) on delete set null,
    carregador_id uuid references public.carregadores(id) on delete set null,
    tipo          text not null check (tipo in ('recusa_limite')),
    etapa         text check (etapa in ('preparar', 'cartao')),
    limite_kw     numeric,
    em_ponta      boolean,
    criado_em     timestamptz not null default now()
);
create index if not exists idx_eventos_demanda_cond
    on public.eventos_demanda (condominio_id, criado_em desc);

-- Só o backend (service_role) lê e escreve. Nada exposto ao navegador.
alter table public.eventos_demanda enable row level security;
revoke all on public.eventos_demanda from anon, authenticated;

-- --- 4. Premissas de custo da energia ----------------------------------------
-- Valores padrão ILUSTRATIVOS. O síndico ajusta com a conta real em
-- Gestão do condomínio (PATCH /gestor/condominio).
alter table public.condominios
    add column if not exists custo_energia_kwh numeric not null default 0.95,
    add column if not exists custo_energia_ponta_kwh numeric not null default 1.45;

alter table public.condominios drop constraint if exists condominios_custo_energia_check;
alter table public.condominios add constraint condominios_custo_energia_check
    check (custo_energia_kwh > 0 and custo_energia_ponta_kwh > 0);

-- Observação honesta: `condominios` é legível pelo anon (tela de cadastro),
-- então estas duas colunas também ficam. São premissas de tarifa, não dado
-- pessoal nem segredo - o mesmo nível de uma tabela de preços.

commit;
