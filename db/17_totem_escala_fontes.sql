-- =============================================================================
-- 17_totem_escala_fontes.sql
-- =============================================================================
-- Rode DEPOIS do 16, no SQL Editor. Idempotente: rodar de novo não duplica,
-- não apaga e não desfaz ajuste feito depois. Decisões: docs/decisoes/ADR-017
-- (escala) e ADR-018 (Totem v2.1).
--
--  1. ESCALA       dispositivos.fator_escala; leitura guarda o bruto E o escalado
--  2. ORIGEM       dispositivos.virtual -> leituras do totem virtual = 'simulado'
--  3. FONTES       painel e bateria da vaga solar: leituras_fonte, porta_solar,
--                  SOC mínimo da bateria (Modbus 10030), geração por dispositivo
--  4. SESSÃO       aguardando_energia como sessão viva, % estimado, tag de início,
--                  modo da vaga solar; view do app enxerga a espera
--  5. SEGURANÇA    eventos_seguranca (só o backend grava e lê)
--  6. LOTE         registrar_lote_telemetria com fontes e escala, na mesma transação
--  7. GRANTS       tudo novo fechado ao navegador
--
-- ORDEM: rode ANTES de provisionar o Totem Central. Placa que já existe fica
-- com fator 1 (os carregadores e veículos dela foram cadastrados em unidades
-- de bancada); placa criada depois nasce com 1000.
--
-- COMPATIBILIDADE: o backend do 16 continua funcionando depois deste arquivo
-- (colunas novas têm default; a RPC nova aceita a chamada antiga por nome).
-- O backend do D1 PRECISA deste arquivo.
-- =============================================================================

begin;

-- =============================================================================
-- 1. ESCALA DE BANCADA (ADR-017)
-- =============================================================================
-- A placa manda W e Wh brutos. O backend multiplica pelo fator na ENTRADA da
-- telemetria e, dali para a frente, tudo é kW/kWh de produto (1:1000: 7,5 W
-- no celular = 7,5 kW no ponto). Placa existente: fator 1, nada muda para ela.
alter table public.dispositivos add column if not exists fator_escala numeric;
update public.dispositivos set fator_escala = 1 where fator_escala is null;
alter table public.dispositivos alter column fator_escala set default 1000;
alter table public.dispositivos alter column fator_escala set not null;
alter table public.dispositivos drop constraint if exists dispositivos_fator_escala_check;
alter table public.dispositivos add constraint dispositivos_fator_escala_check
    check (fator_escala > 0 and fator_escala <= 100000);
comment on column public.dispositivos.fator_escala is
    'ADR-017: multiplica W/Wh brutos da placa na entrada (1000 = maquete 1:1000). Só trocar sem sessão ativa.';

alter table public.leituras_hardware
    add column if not exists fator_escala         numeric,
    add column if not exists potencia_escalada_kw numeric,
    add column if not exists energia_escalada_kwh numeric;
comment on column public.leituras_hardware.potencia_w is 'BRUTO: W medido na bancada';
comment on column public.leituras_hardware.energia_wh is 'BRUTO: Wh acumulado na bancada';
comment on column public.leituras_hardware.potencia_escalada_kw is 'potencia_w x fator / 1000 (kW de produto)';
comment on column public.leituras_hardware.energia_escalada_kwh is 'energia_wh x fator / 1000 (kWh de produto)';


-- =============================================================================
-- 2. ORIGEM DO DADO (regra 5 / pedido do totem virtual P4)
-- =============================================================================
-- Placa virtual (gêmeo digital) grava 'simulado'; placa física, 'medido'.
alter table public.dispositivos add column if not exists virtual boolean not null default false;
comment on column public.dispositivos.virtual is
    'true = gêmeo digital: leituras e fontes gravadas com origem simulado';


-- =============================================================================
-- 3. FONTES DA VAGA SOLAR
-- =============================================================================
alter table public.dispositivos add column if not exists porta_solar smallint;
alter table public.dispositivos drop constraint if exists dispositivos_porta_solar_check;
alter table public.dispositivos add constraint dispositivos_porta_solar_check
    check (porta_solar is null or porta_solar between 1 and 8);
comment on column public.dispositivos.porta_solar is
    'Porta alimentada por painel/bateria (comutação, nunca em paralelo). Null = placa sem vaga solar';

-- Modbus 10030: abaixo deste SOC a bateria não descarrega mais para o ponto.
alter table public.carregadores add column if not exists bateria_soc_minimo smallint not null default 20;
alter table public.carregadores drop constraint if exists carregadores_bateria_soc_minimo_check;
alter table public.carregadores add constraint carregadores_bateria_soc_minimo_check
    check (bateria_soc_minimo between 0 and 100);
comment on column public.carregadores.bateria_soc_minimo is
    'Modbus 10030 - SOC de descarga da bateria (0-100). Valor SIMULADO, ajustável pelo admin';

create table if not exists public.leituras_fonte (
    id                   uuid primary key default gen_random_uuid(),
    dispositivo_id       uuid not null references public.dispositivos(id) on delete cascade,
    fonte                text not null check (fonte in ('painel', 'bateria')),
    medido_em            timestamptz not null default now(),
    potencia_w           numeric,
    tensao_v             numeric,
    corrente_a           numeric,
    fator_escala         numeric not null default 1,
    potencia_escalada_kw numeric,
    soc_estimado         numeric check (soc_estimado is null or soc_estimado between 0 and 100),
    origem               text not null default 'medido' check (origem in ('medido', 'simulado', 'estimado')),
    criado_em            timestamptz not null default now()
);
create index if not exists idx_leituras_fonte_recentes
    on public.leituras_fonte (dispositivo_id, fonte, medido_em desc);
comment on table public.leituras_fonte is
    'Painel e bateria da vaga solar. potencia_w = fornecida pela fonte (bruto). soc_estimado vem da tensão (ESTIMADO)';

-- Quem escreveu a linha de geração: null = simulador; preenchido = placa
-- (real ou virtual). Linha de placa recente cala o simulador (fallback).
alter table public.geracao_solar
    add column if not exists dispositivo_id uuid references public.dispositivos(id) on delete set null;


-- =============================================================================
-- 4. SESSÃO
-- =============================================================================
-- aguardando_energia: tag aceita e saldo reservado, relé DESLIGADO até o
-- alocador ter orçamento (ADR-018). É sessão VIVA: ocupa a vaga e o veículo.
alter table public.sessoes_recarga
    add column if not exists percentual_origem text not null default 'informado',
    add column if not exists uid_inicio        text,
    add column if not exists modo_vaga_solar   text;
alter table public.sessoes_recarga drop constraint if exists sessoes_percentual_origem_check;
alter table public.sessoes_recarga add constraint sessoes_percentual_origem_check
    check (percentual_origem in ('informado', 'estimado'));
alter table public.sessoes_recarga drop constraint if exists sessoes_modo_vaga_solar_check;
alter table public.sessoes_recarga add constraint sessoes_modo_vaga_solar_check
    check (modo_vaga_solar is null or modo_vaga_solar in ('solar', 'rede', 'pausada'));
comment on column public.sessoes_recarga.percentual_origem is
    'informado = morador digitou no app; estimado = tag-primeiro (último % conhecido do veículo)';
comment on column public.sessoes_recarga.uid_inicio is 'UID da tag que iniciou/confirmou: a MESMA tag encerra';
comment on column public.sessoes_recarga.modo_vaga_solar is
    'Vaga solar: solar | rede (10024 ligado) | pausada (bateria abaixo do 10030)';

-- Os índices de unicidade passam a contar aguardando_energia. Drop + create
-- é idempotente e barato (só linhas vivas entram no índice parcial).
drop index if exists public.uq_sessao_viva_por_carregador;
create unique index uq_sessao_viva_por_carregador
    on public.sessoes_recarga (carregador_id)
    where status in ('aguardando_rfid', 'carregando', 'aguardando_energia');

drop index if exists public.uq_sessao_viva_por_veiculo;
create unique index uq_sessao_viva_por_veiculo
    on public.sessoes_recarga (veiculo_id)
    where status in ('aguardando_rfid', 'carregando', 'aguardando_energia');

create index if not exists idx_sessoes_aguardando_energia
    on public.sessoes_recarga (criado_em)
    where status = 'aguardando_energia';

-- View do app: mesmas colunas do 15, na mesma ordem, + percentual_origem no
-- fim (regra 5: o % do tag-primeiro aparece como estimado). Passa a mostrar
-- a sessão aguardando energia, que ainda não tem iniciado_em.
create or replace view public.v_sessoes_local
with (security_invoker = false) as
select
    s.id,
    s.carregador_id,
    s.status,
    s.origem,
    s.potencia_atual_kw,
    s.potencia_alocada_kw,
    s.energia_entregue_kwh,
    s.percentual_bateria_inicial,
    s.percentual_bateria_atual,
    s.alvo_percentual,
    s.tempo_estimado_min,
    s.iniciado_em,
    v.modelo as veiculo_modelo,
    v.tipo   as veiculo_tipo,
    case when s.usuario_id = (select auth.uid()) then s.usuario_id           end as usuario_id,
    case when s.usuario_id = (select auth.uid()) then s.veiculo_id           end as veiculo_id,
    case when s.usuario_id = (select auth.uid()) then v.placa                end as veiculo_placa,
    case when s.usuario_id = (select auth.uid()) then s.custo_estimado       end as custo_estimado,
    case when s.usuario_id = (select auth.uid()) then s.custo_final          end as custo_final,
    case when s.usuario_id = (select auth.uid()) then s.valor_pre_autorizado end as valor_pre_autorizado,
    s.percentual_origem
from public.sessoes_recarga s
join public.carregadores c on c.id = s.carregador_id
left join public.veiculos v on v.id = s.veiculo_id
where (s.status in ('carregando', 'aguardando_energia') or s.iniciado_em >= now() - interval '1 day')
  and (s.usuario_id = (select auth.uid())
       or exists (select 1 from public.condominios_favoritos f
                  where f.usuario_id = (select auth.uid())
                    and f.condominio_id = c.condominio_id));

revoke all    on public.v_sessoes_local from anon, authenticated;
grant  select on public.v_sessoes_local to authenticated;


-- =============================================================================
-- 5. EVENTOS DE SEGURANÇA
-- =============================================================================
-- Só o backend grava e lê (o painel do admin é o chat D3). Lista fechada:
-- tipo novo só via ADR. `uid` é o da tag que tentou; `ip` de quem assinou errado.
create table if not exists public.eventos_seguranca (
    id             uuid primary key default gen_random_uuid(),
    criado_em      timestamptz not null default now(),
    tipo           text not null,
    condominio_id  uuid references public.condominios(id) on delete set null,
    dispositivo_id uuid references public.dispositivos(id) on delete set null,
    carregador_id  uuid references public.carregadores(id) on delete set null,
    porta          smallint,
    uid            text,
    ip             text,
    detalhe        text
);
alter table public.eventos_seguranca drop constraint if exists eventos_seguranca_tipo_check;
alter table public.eventos_seguranca add constraint eventos_seguranca_tipo_check
    check (tipo in ('tag_alheia', 'replay', 'assinatura_invalida'));
alter table public.eventos_seguranca drop constraint if exists eventos_seguranca_tamanhos_check;
alter table public.eventos_seguranca add constraint eventos_seguranca_tamanhos_check
    check (coalesce(length(uid), 0) <= 64 and coalesce(length(ip), 0) <= 64
           and coalesce(length(detalhe), 0) <= 200);
create index if not exists idx_eventos_seguranca_recentes
    on public.eventos_seguranca (condominio_id, criado_em desc);


-- =============================================================================
-- 6. LOTE DE TELEMETRIA COM FONTES E ESCALA
-- =============================================================================
-- Mesma regra do 15 (consome o seq e grava na MESMA transação; leitura errada
-- = nada gravado e seq não gasto), mais:
--   - `leituras` pode vir vazia se `fontes` vier preenchida (1 a 30 + 0 a 20);
--   - fator e origem saem da linha do dispositivo, não do chamador;
--   - cada leitura guarda o bruto e o escalado.
--   p_fontes: [{"fonte":"painel","t_ms":12000,"potencia_w":7.41,"tensao_v":5.88,
--               "corrente_a":1.26,"soc_estimado":null}, ...]
drop function if exists public.registrar_lote_telemetria(uuid, bigint, bigint, timestamptz, bigint, jsonb, integer);

create or replace function public.registrar_lote_telemetria(
    p_dispositivo uuid, p_boot bigint, p_seq bigint, p_ts timestamptz,
    p_t_envio_ms bigint, p_leituras jsonb, p_janela_s integer default 120,
    p_fontes jsonb default null
) returns integer
language plpgsql
set search_path = public
as $$
declare
    n        integer;
    v_fator  numeric;
    v_origem text;
begin
    p_leituras := coalesce(p_leituras, '[]'::jsonb);
    p_fontes   := coalesce(p_fontes, '[]'::jsonb);
    if jsonb_typeof(p_leituras) <> 'array' or jsonb_typeof(p_fontes) <> 'array'
       or jsonb_array_length(p_leituras) > 30 or jsonb_array_length(p_fontes) > 20
       or jsonb_array_length(p_leituras) + jsonb_array_length(p_fontes) = 0 then
        raise exception 'lote_invalido';
    end if;

    perform consumir_seq(p_dispositivo, p_boot, p_seq, p_ts, false, p_janela_s);

    select d.fator_escala, case when d.virtual then 'simulado' else 'medido' end
      into v_fator, v_origem
      from dispositivos d where d.id = p_dispositivo;

    if exists (
        select 1 from jsonb_to_recordset(p_leituras) as l(porta smallint)
        where not exists (select 1 from portas_dispositivo pd
                          where pd.dispositivo_id = p_dispositivo and pd.numero = l.porta)
    ) then
        raise exception 'porta_inexistente';
    end if;
    if exists (
        select 1 from jsonb_to_recordset(p_fontes) as f(fonte text)
        where f.fonte is null or f.fonte not in ('painel', 'bateria')
    ) then
        raise exception 'lote_invalido';
    end if;

    insert into leituras_hardware (dispositivo_id, porta, sessao_id, potencia_w, energia_wh,
                                   tensao_v, corrente_a, temperatura_c, rele_ligado,
                                   medido_em, origem, fator_escala,
                                   potencia_escalada_kw, energia_escalada_kwh)
    select p_dispositivo, l.porta, s.id, l.potencia_w, l.energia_wh,
           l.tensao_v, l.corrente_a, l.temperatura_c, l.rele_ligado,
           now() - make_interval(secs => greatest(0, least(600000,
                       coalesce(p_t_envio_ms, 0) - coalesce(l.t_ms, p_t_envio_ms, 0))) / 1000.0),
           v_origem, v_fator,
           l.potencia_w * v_fator / 1000.0,
           l.energia_wh * v_fator / 1000.0
    from jsonb_to_recordset(p_leituras) as l(
             porta smallint, t_ms bigint, potencia_w numeric, energia_wh numeric,
             tensao_v numeric, corrente_a numeric, temperatura_c numeric, rele_ligado boolean)
    join portas_dispositivo pd on pd.dispositivo_id = p_dispositivo and pd.numero = l.porta
    left join lateral (
        select sr.id from sessoes_recarga sr
        where sr.carregador_id = pd.carregador_id and sr.status = 'carregando'
        order by sr.iniciado_em desc nulls last
        limit 1
    ) s on true;
    get diagnostics n = row_count;

    insert into leituras_fonte (dispositivo_id, fonte, medido_em, potencia_w, tensao_v, corrente_a,
                                fator_escala, potencia_escalada_kw, soc_estimado, origem)
    select p_dispositivo, f.fonte,
           now() - make_interval(secs => greatest(0, least(600000,
                       coalesce(p_t_envio_ms, 0) - coalesce(f.t_ms, p_t_envio_ms, 0))) / 1000.0),
           f.potencia_w, f.tensao_v, f.corrente_a,
           v_fator, f.potencia_w * v_fator / 1000.0,
           least(100, greatest(0, f.soc_estimado)), v_origem
    from jsonb_to_recordset(p_fontes) as f(
             fonte text, t_ms bigint, potencia_w numeric, tensao_v numeric,
             corrente_a numeric, soc_estimado numeric);

    return n;
end $$;


-- =============================================================================
-- 7. GRANTS
-- =============================================================================
alter table public.leituras_fonte    enable row level security;
alter table public.eventos_seguranca enable row level security;
revoke all on public.leituras_fonte, public.eventos_seguranca from anon, authenticated;

revoke all on function public.registrar_lote_telemetria(uuid, bigint, bigint, timestamptz, bigint, jsonb, integer, jsonb)
    from public, anon, authenticated;
grant execute on function public.registrar_lote_telemetria(uuid, bigint, bigint, timestamptz, bigint, jsonb, integer, jsonb)
    to service_role;

commit;

-- =============================================================================
-- DEPOIS DE RODAR
-- =============================================================================
-- 1. Rode db/17_verificacao.sql (tudo em transação desfeita no final).
-- 2. Provisione o totem (backend/): python provisionar.py placa-v2 --carregadores
--    <v1>,<v2>,<v3>,<v4> --nome "Totem Central" --perfil bancada
-- 3. Marque a vaga solar e, se for o gêmeo digital, a origem:
--      update dispositivos set porta_solar = 4 where id = '<id do totem>';
--      update dispositivos set virtual = true  where id = '<id do totem virtual>';
-- 4. Conferência rápida:
--      select nome, fator_escala, virtual, porta_solar from dispositivos;
-- =============================================================================
