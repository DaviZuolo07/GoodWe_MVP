-- ============================================================================
-- 21_taxa_ociosidade.sql  -  taxa por minuto de vaga ocupada depois da carga
-- ============================================================================
-- Rodar no SQL Editor DEPOIS do 20, uma vez. É idempotente.
--
-- A REGRA (só pontos SIMULADOS; o totem/bancada não muda)
--   Quando a recarga termina sozinha (bateria cheia, alvo atingido ou valor
--   reservado alcançado), a energia é cobrada e a sessão fecha - mas o carro
--   continua na vaga. A partir daí:
--     1. tolerância de `tolerancia_ociosidade_min` (padrão 15 min) sem custo;
--     2. depois, `taxa_ociosidade_min` por minuto (padrão R$ 0,50);
--     3. a taxa para de crescer em `teto_ociosidade` (padrão R$ 60,00);
--     4. o morador toca "Já retirei o carro" no app: a taxa é debitada da
--        carteira, a vaga volta a 'disponivel' e o primeiro da fila é avisado.
--   Referências de mercado: WeCharge R$ 0,50/min após 15 min; Volvo R$ 5/min
--   após 15 min; Tesla e Electrify America US$ 0,40/min (5 e 10 min).
--
-- O QUE CRIA
--   condominios      tolerancia_ociosidade_min, taxa_ociosidade_min, teto_ociosidade
--   sessoes_recarga  vaga_ocupada_desde, vaga_liberada_em, taxa_ociosidade,
--                    taxa_ociosidade_cobrada
--   carteira         tipo de movimento 'taxa_ociosidade' (sinal -1)
--
-- COMPATIBILIDADE: sem este arquivo o backend segue liberando a vaga na hora,
-- como antes (ele testa se a coluna existe).
-- ============================================================================

begin;

-- -----------------------------------------------------------------------------
-- 1. POLÍTICA POR LOCAL (o gestor de cada condomínio pode ter a sua)
-- -----------------------------------------------------------------------------
alter table public.condominios add column if not exists tolerancia_ociosidade_min integer       not null default 15;
alter table public.condominios add column if not exists taxa_ociosidade_min       numeric(10,2) not null default 0.50;
alter table public.condominios add column if not exists teto_ociosidade           numeric(10,2) not null default 60.00;

alter table public.condominios drop constraint if exists condominios_ociosidade_check;
alter table public.condominios add constraint condominios_ociosidade_check
    check (tolerancia_ociosidade_min between 0 and 240
           and taxa_ociosidade_min between 0 and 20
           and teto_ociosidade between 0 and 1000);

-- -----------------------------------------------------------------------------
-- 2. A VAGA DEPOIS DA CARGA
-- -----------------------------------------------------------------------------
alter table public.sessoes_recarga add column if not exists vaga_ocupada_desde      timestamptz;
alter table public.sessoes_recarga add column if not exists vaga_liberada_em        timestamptz;
alter table public.sessoes_recarga add column if not exists taxa_ociosidade         numeric(10,2) not null default 0;
alter table public.sessoes_recarga add column if not exists taxa_ociosidade_cobrada numeric(10,2) not null default 0;

create index if not exists idx_sessoes_vaga_ocupada on public.sessoes_recarga (carregador_id)
    where vaga_ocupada_desde is not null and vaga_liberada_em is null;

-- -----------------------------------------------------------------------------
-- 3. CARTEIRA: novo tipo de débito (a regra saldo = soma do extrato continua)
-- -----------------------------------------------------------------------------
alter table public.movimentacoes_carteira drop constraint if exists movimentacoes_carteira_tipo_check;
alter table public.movimentacoes_carteira add constraint movimentacoes_carteira_tipo_check
    check (tipo in ('credito', 'bonus', 'estorno', 'ajuste', 'pre_autorizacao', 'ajuste_debito',
                    'taxa_ociosidade'));

create or replace function public.sinal_movimento(p_tipo text) returns integer
language sql immutable
set search_path = public
as $$
    select case p_tipo
        when 'credito' then 1 when 'bonus' then 1 when 'estorno' then 1 when 'ajuste' then 1
        when 'pre_autorizacao' then -1 when 'ajuste_debito' then -1 when 'taxa_ociosidade' then -1
    end;
$$;

commit;

-- =============================================================================
-- CONFERÊNCIA (rodar separado)
--   select nome, tolerancia_ociosidade_min, taxa_ociosidade_min, teto_ociosidade from condominios;
--   select public.sinal_movimento('taxa_ociosidade');          -- deve dar -1
--   select * from public.conferir_carteira();                  -- deve vir vazio
-- =============================================================================
