-- =============================================================================
-- 16_fontes_e_cobranca.sql
-- =============================================================================
-- Rode DEPOIS do 15, no SQL Editor. Idempotente: rodar de novo não duplica,
-- não apaga e não desfaz ajuste que o síndico tenha feito depois.
-- Decisões: docs/decisoes/ADR-016.
--
--  1. SOLAR        preço ao morador e custo de geração (premissas do condomínio)
--  2. REDE         preço ao morador -> 1,15 (P1 - valores simulados)
--  3. MODBUS 10025 controle dinâmico ligado por padrão (P2)
--  4. SESSÃO       energia solar, origem e preço solar congelado
--  5. CURVA        consumo_horario separa rede x sol; registrar_consumo novo
--  6. GERAÇÃO      soma da geração solar no banco (o painel não pagina 8 mil linhas)
--  7. GRANTS       funções novas só para o backend
--
-- COMPATIBILIDADE: o backend antigo continua funcionando depois deste arquivo
-- (colunas novas têm default; a função nova aceita a chamada antiga de 5
-- parâmetros por nome). O backend novo PRECISA deste arquivo.
-- =============================================================================

begin;

-- =============================================================================
-- 1. SOLAR: PREÇO E CUSTO (premissas configuráveis pelo síndico)
-- =============================================================================
-- custo_solar_kwh: quanto custa ao condomínio gerar 1 kWh (amortização + O&M).
-- preco_solar_kwh: quanto o morador paga pelo kWh solar.
-- Valores SIMULADOS. Ficam legíveis pelo anon como as demais premissas de
-- tarifa (decisão do 14): tabela de preço, não dado pessoal.
alter table public.condominios
    add column if not exists custo_solar_kwh numeric not null default 0.35,
    add column if not exists preco_solar_kwh numeric not null default 0.75;

alter table public.condominios drop constraint if exists condominios_solar_precos_check;
alter table public.condominios add constraint condominios_solar_precos_check
    check (custo_solar_kwh > 0 and preco_solar_kwh > 0);

comment on column public.condominios.custo_solar_kwh is 'Custo de gerar 1 kWh solar (premissa SIMULADA)';
comment on column public.condominios.preco_solar_kwh is 'Preço do kWh solar ao morador (premissa SIMULADA)';


-- =============================================================================
-- 2. PREÇO DA REDE AO MORADOR (P1)
-- =============================================================================
-- Com 2,10 a margem da rede (1,15/kWh) supera a solar (0,40/kWh) e o condomínio
-- ganharia menos quando o sol brilha. 1,15 alinha o incentivo (ADR-016 D6).
-- Os seeds do 07 usavam 1,95 / 2,25 / 2,35 - todos invertidos do mesmo jeito,
-- e todos simulados (até aqui não havia tela para o síndico mudar tarifa).
-- Na PRIMEIRA execução (o default antigo da coluna é o marcador), todo preço
-- acima de 1,15 vira 1,15. Depois disso o síndico ajusta pelo painel e uma
-- nova execução não mexe no que ele definiu.
do $$
begin
    if (select column_default from information_schema.columns
         where table_schema = 'public' and table_name = 'carregadores'
           and column_name = 'tarifa_kwh') like '2.1%' then
        update public.carregadores set tarifa_kwh = 1.15 where tarifa_kwh > 1.15;
    end if;
end $$;
alter table public.carregadores alter column tarifa_kwh set default 1.15;


-- =============================================================================
-- 3. MODBUS 10025 - CONTROLE DINÂMICO LIGADO (P2)
-- =============================================================================
-- A partir do 16, 10025 desligado = carga fixa (não modulada). Os carregadores
-- veiculares existentes eram todos modulados: ligam o 10025 para manter o
-- comportamento. Mesmo marcador de primeira execução do item 2.
do $$
begin
    if (select column_default from information_schema.columns
         where table_schema = 'public' and table_name = 'carregadores'
           and column_name = 'controle_dinamico') = 'false' then
        update public.carregadores set controle_dinamico = true
         where perfil = 'veicular' and controle_dinamico = false;
    end if;
end $$;
alter table public.carregadores alter column controle_dinamico set default true;


-- =============================================================================
-- 4. SESSÃO: ENERGIA POR FONTE
-- =============================================================================
-- energia_entregue = solar + rede fora da ponta + rede na ponta.
-- energia_ponta_kwh passa a contar SÓ rede (ponta é tarifa da distribuidora).
-- origem_solar: de onde veio o número do sol (rótulo de auditoria).
alter table public.sessoes_recarga
    add column if not exists energia_solar_kwh         numeric not null default 0,
    add column if not exists origem_solar              text,
    add column if not exists tarifa_solar_kwh          numeric,
    add column if not exists potencia_alocada_solar_kw numeric;

alter table public.sessoes_recarga drop constraint if exists sessoes_origem_solar_check;
alter table public.sessoes_recarga add constraint sessoes_origem_solar_check
    check (origem_solar is null or origem_solar in ('medido', 'simulado', 'estimado'));

alter table public.sessoes_recarga drop constraint if exists sessoes_energia_solar_check;
alter table public.sessoes_recarga add constraint sessoes_energia_solar_check
    check (energia_solar_kwh >= 0);

-- A soma das fontes não passa do total. NOT VALID: não reprova linha antiga;
-- vale para toda escrita nova. Tolerância de 10 mWh para arredondamento.
alter table public.sessoes_recarga drop constraint if exists sessoes_fontes_fecham_check;
alter table public.sessoes_recarga add constraint sessoes_fontes_fecham_check
    check (energia_solar_kwh + coalesce(energia_ponta_kwh, 0)
           <= coalesce(energia_entregue_kwh, 0) + 0.00001) not valid;

comment on column public.sessoes_recarga.energia_solar_kwh is 'kWh da sessão vindos do excedente solar';
comment on column public.sessoes_recarga.energia_ponta_kwh is 'kWh da REDE entregues no horário de ponta';
comment on column public.sessoes_recarga.tarifa_solar_kwh  is 'Preço solar congelado no início da sessão';


-- =============================================================================
-- 5. CURVA HORÁRIA: REDE x SOL
-- =============================================================================
-- pico_kw continua = carga da garagem (com gestão). pico_rede_kw = o que veio
-- da distribuidora. A diferença é o pico coberto pelo sol.
alter table public.consumo_horario
    add column if not exists energia_solar_kwh numeric not null default 0,
    add column if not exists pico_rede_kw      numeric not null default 0;

drop function if exists public.registrar_consumo(uuid, numeric, boolean, numeric, numeric);

create or replace function public.registrar_consumo(
    p_cond       uuid,
    p_kwh        numeric,
    p_ponta      boolean,
    p_carga_kw   numeric,
    p_demanda_kw numeric default 0,
    p_solar_kwh  numeric default 0,
    p_rede_kw    numeric default null
) returns void
language sql
set search_path = public
as $$
    insert into consumo_horario (condominio_id, hora, energia_kwh, energia_ponta_kwh, pico_kw,
                                 demanda_kw, energia_solar_kwh, pico_rede_kw)
    values (p_cond, date_trunc('hour', now()),
            greatest(p_kwh, 0),
            case when p_ponta then greatest(p_kwh - least(greatest(p_solar_kwh, 0), greatest(p_kwh, 0)), 0)
                 else 0 end,
            greatest(p_carga_kw, 0),
            greatest(p_demanda_kw, p_carga_kw, 0),
            least(greatest(p_solar_kwh, 0), greatest(p_kwh, 0)),
            greatest(coalesce(p_rede_kw, p_carga_kw), 0))
    on conflict (condominio_id, hora) do update set
        energia_kwh       = consumo_horario.energia_kwh + excluded.energia_kwh,
        energia_ponta_kwh = consumo_horario.energia_ponta_kwh + excluded.energia_ponta_kwh,
        energia_solar_kwh = consumo_horario.energia_solar_kwh + excluded.energia_solar_kwh,
        pico_kw           = greatest(consumo_horario.pico_kw, excluded.pico_kw),
        demanda_kw        = greatest(consumo_horario.demanda_kw, excluded.demanda_kw),
        pico_rede_kw      = greatest(consumo_horario.pico_rede_kw, excluded.pico_rede_kw);
$$;


-- =============================================================================
-- 6. SOMA DA GERAÇÃO SOLAR
-- =============================================================================
-- Baldes de 5 min = ~9 mil linhas por mês por condomínio; o PostgREST devolve
-- no máximo mil. A soma é feita aqui, por origem.
create or replace function public.somar_geracao_solar(p_cond uuid, p_desde timestamptz)
returns table (origem text, energia_kwh numeric, pico_kw numeric)
language sql
stable
set search_path = public
as $$
    select g.origem, coalesce(sum(g.energia_kwh), 0), coalesce(max(g.potencia_kw), 0)
      from geracao_solar g
     where g.condominio_id = p_cond and g.momento >= p_desde
     group by g.origem;
$$;


-- =============================================================================
-- 7. GRANTS
-- =============================================================================
revoke all on function public.registrar_consumo(uuid, numeric, boolean, numeric, numeric, numeric, numeric)
    from public, anon, authenticated;
grant execute on function public.registrar_consumo(uuid, numeric, boolean, numeric, numeric, numeric, numeric)
    to service_role;

revoke all on function public.somar_geracao_solar(uuid, timestamptz) from public, anon, authenticated;
grant execute on function public.somar_geracao_solar(uuid, timestamptz) to service_role;

commit;

-- =============================================================================
-- Conferência: rode db/16_verificacao.sql. Pronto = todas as linhas ok = true.
-- =============================================================================
