-- =============================================================================
-- 15_multiporta_protocolo_v2.sql
-- =============================================================================
-- Rode DEPOIS do 14, no SQL Editor. Idempotente: rodar de novo não duplica,
-- não apaga e não quebra nada. Decisões: docs/decisoes/ADR-015.
--
--  1. FUNÇÕES      nascem fechadas ao navegador (o 11 só fechou as tabelas)
--  2. MULTIPORTA   1 dispositivo -> N portas; cada porta -> 1 carregador
--  3. PROTOCOLO v2 boot + seq + janela de tempo contra replay; lote de leituras
--  4. VIEWS        sessões e fila só dos locais favoritos (ou as minhas)
--  5. CARTEIRA     saldo = soma do extrato; cadastro atômico com bônus rotulado
--  6. MODBUS       vocabulário do HCA G2 (10024/25/26/29/32), configuração simulada
--  7. SOLAR        geração simulada, com a origem de cada número rotulada
--  8. GRANTS       revisão final de privilégios
--
-- COMPATIBILIDADE: o backend atual continua funcionando depois deste arquivo.
-- A única diferença visível antes do backend novo: cadastro feito pelo código
-- antigo nasce com saldo 0 (o bônus passa a sair da RPC cadastrar_usuario).
-- =============================================================================

begin;

-- =============================================================================
-- 1. FUNÇÕES NASCEM FECHADAS
-- =============================================================================
-- O Postgres dá EXECUTE a PUBLIC em toda função nova. Sem isto, uma RPC criada
-- amanhã seria chamável do navegador com a anon key. A varredura final (seção 8)
-- fecha também as que já existem.
alter default privileges in schema public
    revoke execute on functions from public, anon, authenticated;


-- =============================================================================
-- 2. MULTIPORTA
-- =============================================================================
-- Tabela própria, fechada: `carregadores` é legível por qualquer logado e a
-- topologia do hardware não precisa chegar ao navegador.
create table if not exists public.portas_dispositivo (
    id             uuid primary key default gen_random_uuid(),
    dispositivo_id uuid not null references public.dispositivos(id) on delete cascade,
    numero         smallint not null check (numero between 1 and 8),
    carregador_id  uuid not null unique references public.carregadores(id) on delete cascade,
    criado_em      timestamptz not null default now(),
    unique (dispositivo_id, numero)
);

-- Backfill: toda placa que já existe vira "placa de uma porta só".
insert into public.portas_dispositivo (dispositivo_id, numero, carregador_id)
select d.id, 1, d.carregador_id
from public.dispositivos d
where d.carregador_id is not null
on conflict do nothing;

-- Expand/contract: a coluna antiga fica (o backend atual ainda lê), mas deixa
-- de ser obrigatória e única. O 16, depois do firmware v2, apaga.
alter table public.dispositivos drop constraint if exists dispositivos_carregador_id_key;
alter table public.dispositivos alter column carregador_id drop not null;
comment on column public.dispositivos.carregador_id is
    'DEPRECIADA (migration 15). Fonte da verdade: portas_dispositivo. Sai no 16.';

alter table public.comandos_dispositivo
    add column if not exists porta smallint not null default 1;
alter table public.comandos_dispositivo drop constraint if exists comandos_dispositivo_porta_check;
alter table public.comandos_dispositivo add constraint comandos_dispositivo_porta_check
    check (porta between 1 and 8);

-- Leitura: porta, instante da MEDIÇÃO (não da chegada) e origem do dado.
alter table public.leituras_hardware
    add column if not exists porta smallint not null default 1,
    add column if not exists medido_em timestamptz,
    add column if not exists origem text not null default 'medido';
update public.leituras_hardware set medido_em = criado_em where medido_em is null;
alter table public.leituras_hardware alter column medido_em set default now();
alter table public.leituras_hardware alter column medido_em set not null;
alter table public.leituras_hardware drop constraint if exists leituras_hardware_porta_check;
alter table public.leituras_hardware add constraint leituras_hardware_porta_check
    check (porta between 1 and 8);
alter table public.leituras_hardware drop constraint if exists leituras_hardware_origem_check;
alter table public.leituras_hardware add constraint leituras_hardware_origem_check
    check (origem in ('medido', 'simulado', 'estimado'));


-- =============================================================================
-- 3. PROTOCOLO v2
-- =============================================================================
-- A chave do HMAC é DERIVADA no backend (DEVICE_MASTER_KEY + id + versão) e
-- nunca é gravada. Aqui fica só o que não é segredo: versão da chave e o
-- estado anti-replay.
alter table public.dispositivos
    add column if not exists protocolo    smallint not null default 1,
    add column if not exists chave_versao integer  not null default 1,
    add column if not exists boot_atual   bigint,
    add column if not exists seq_atual    bigint   not null default 0;
alter table public.dispositivos drop constraint if exists dispositivos_protocolo_check;
alter table public.dispositivos add constraint dispositivos_protocolo_check
    check (protocolo in (1, 2));

-- Boots já vistos. Sem isto, um handshake capturado de um boot ANTERIOR seria
-- aceito como "placa reiniciou" (boot diferente = contador novo).
create table if not exists public.dispositivo_boots (
    dispositivo_id uuid   not null references public.dispositivos(id) on delete cascade,
    boot           bigint not null,
    visto_em       timestamptz not null default now(),
    primary key (dispositivo_id, boot)
);

-- Consome UMA requisição assinada. A verificação do HMAC fica no Python (só
-- ele tem a chave-mestra); janela de tempo e sequência ficam aqui porque
-- precisam ser atômicas: um UPDATE com "seq_atual < p_seq" no WHERE resolve
-- até dois workers recebendo a mesma requisição ao mesmo tempo.
--
-- Erros (o backend traduz): fora_da_janela, seq_invalido, dispositivo_inexistente,
-- boot_desconhecido (placa precisa refazer o handshake), replay.
create or replace function public.consumir_seq(
    p_dispositivo uuid, p_boot bigint, p_seq bigint, p_ts timestamptz,
    p_handshake boolean default false, p_janela_s integer default 120
) returns void
language plpgsql
set search_path = public
as $$
declare v_boot bigint;
begin
    if p_ts is null or abs(extract(epoch from (now() - p_ts))) > p_janela_s then
        raise exception 'fora_da_janela';
    end if;
    if p_boot is null or p_seq is null or p_seq < 1 then
        raise exception 'seq_invalido';
    end if;
    if not exists (select 1 from dispositivos where id = p_dispositivo) then
        raise exception 'dispositivo_inexistente';
    end if;

    if p_handshake then
        insert into dispositivo_boots (dispositivo_id, boot)
        values (p_dispositivo, p_boot)
        on conflict do nothing;

        if found then
            -- Boot inédito: placa ligou agora. Primeiro handshake v2 também
            -- aposenta o token v1 (sem downgrade para o protocolo mais fraco).
            update dispositivos
            set boot_atual = p_boot, seq_atual = p_seq, protocolo = 2, token_hash = null
            where id = p_dispositivo;
            delete from dispositivo_boots
            where dispositivo_id = p_dispositivo and visto_em < now() - interval '1 day';
            return;
        end if;

        -- Boot já visto: só vale se for o atual e a sequência andar
        -- (re-handshake sem reiniciar). Boot antigo = replay.
        update dispositivos set seq_atual = p_seq
        where id = p_dispositivo and boot_atual = p_boot and seq_atual < p_seq;
        if not found then
            raise exception 'replay';
        end if;
        return;
    end if;

    update dispositivos set seq_atual = p_seq
    where id = p_dispositivo and boot_atual = p_boot and seq_atual < p_seq;
    if not found then
        select boot_atual into v_boot from dispositivos where id = p_dispositivo;
        if v_boot is distinct from p_boot then
            raise exception 'boot_desconhecido';
        end if;
        raise exception 'replay';
    end if;
end $$;

-- Lote de telemetria: consome o seq E grava as leituras na mesma transação.
-- Se qualquer leitura estiver errada, nada é gravado e o seq não é gasto.
--   p_leituras: [{"porta":1,"t_ms":121456,"potencia_w":12.4,"energia_wh":3.1,
--                 "tensao_v":5.02,"corrente_a":2.47,"temperatura_c":31,
--                 "rele_ligado":true}, ...]   (1 a 30 itens)
-- medido_em = agora - (t_envio_ms - t_ms): a ORDEM vem do relógio do servidor.
create or replace function public.registrar_lote_telemetria(
    p_dispositivo uuid, p_boot bigint, p_seq bigint, p_ts timestamptz,
    p_t_envio_ms bigint, p_leituras jsonb, p_janela_s integer default 120
) returns integer
language plpgsql
set search_path = public
as $$
declare n integer;
begin
    if p_leituras is null or jsonb_typeof(p_leituras) <> 'array'
       or jsonb_array_length(p_leituras) not between 1 and 30 then
        raise exception 'lote_invalido';
    end if;

    perform consumir_seq(p_dispositivo, p_boot, p_seq, p_ts, false, p_janela_s);

    if exists (
        select 1 from jsonb_to_recordset(p_leituras) as l(porta smallint)
        where not exists (select 1 from portas_dispositivo pd
                          where pd.dispositivo_id = p_dispositivo and pd.numero = l.porta)
    ) then
        raise exception 'porta_inexistente';
    end if;

    insert into leituras_hardware (dispositivo_id, porta, sessao_id, potencia_w, energia_wh,
                                   tensao_v, corrente_a, temperatura_c, rele_ligado,
                                   medido_em, origem)
    select p_dispositivo, l.porta, s.id, l.potencia_w, l.energia_wh,
           l.tensao_v, l.corrente_a, l.temperatura_c, l.rele_ligado,
           now() - make_interval(secs => greatest(0, least(600000,
                       coalesce(p_t_envio_ms, 0) - coalesce(l.t_ms, p_t_envio_ms, 0))) / 1000.0),
           'medido'
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
    return n;
end $$;


-- =============================================================================
-- 4. VIEWS FILTRADAS PELOS FAVORITOS
-- =============================================================================
-- Visível se o carregador é de um local favorito de quem pergunta, OU se a
-- linha é dele (a própria recarga e a própria posição nunca somem da tela).
-- Mesmas colunas, mesma ordem: o frontend não muda.
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
    case when s.usuario_id = (select auth.uid()) then s.valor_pre_autorizado end as valor_pre_autorizado
from public.sessoes_recarga s
join public.carregadores c on c.id = s.carregador_id
left join public.veiculos v on v.id = s.veiculo_id
where (s.status = 'carregando' or s.iniciado_em >= now() - interval '1 day')
  and (s.usuario_id = (select auth.uid())
       or exists (select 1 from public.condominios_favoritos f
                  where f.usuario_id = (select auth.uid())
                    and f.condominio_id = c.condominio_id));

create or replace view public.v_fila_local
with (security_invoker = false) as
select
    f.id,
    f.carregador_id,
    f.posicao,
    f.criado_em,
    (f.usuario_id = (select auth.uid())) as eh_meu
from public.fila f
join public.carregadores c on c.id = f.carregador_id
where f.usuario_id = (select auth.uid())
   or exists (select 1 from public.condominios_favoritos fav
              where fav.usuario_id = (select auth.uid())
                and fav.condominio_id = c.condominio_id);

revoke all    on public.v_sessoes_local, public.v_fila_local from anon, authenticated;
grant  select on public.v_sessoes_local, public.v_fila_local to authenticated;


-- =============================================================================
-- 5. CARTEIRA: SALDO = SOMA DO EXTRATO
-- =============================================================================
alter table public.movimentacoes_carteira drop constraint if exists movimentacoes_carteira_tipo_check;
alter table public.movimentacoes_carteira add constraint movimentacoes_carteira_tipo_check
    check (tipo in ('credito', 'bonus', 'estorno', 'ajuste', 'pre_autorizacao', 'ajuste_debito'));

-- O sinal de cada tipo, num lugar só. `valor` continua sempre >= 0.
create or replace function public.sinal_movimento(p_tipo text) returns integer
language sql immutable
set search_path = public
as $$
    select case p_tipo
        when 'credito' then 1 when 'bonus' then 1 when 'estorno' then 1 when 'ajuste' then 1
        when 'pre_autorizacao' then -1 when 'ajuste_debito' then -1
    end;
$$;

-- Conta nova nasce zerada; o bônus vira linha no extrato.
alter table public.usuarios alter column saldo set default 0;

-- 5.1 Backfill ANTES da guarda. abertura = saldo - soma do extrato. Os
-- saldo_apos já gravados embutem esse valor, então a linha retroativa (datada
-- na criação da conta) fecha a cadeia. Rodar de novo: abertura = 0, não insere.
insert into public.movimentacoes_carteira (usuario_id, tipo, valor, saldo_apos, descricao, criado_em)
select a.id,
       case when a.abertura = 100 then 'bonus'
            when a.abertura > 0   then 'ajuste'
            else 'ajuste_debito' end,
       abs(a.abertura),
       a.abertura,
       case when a.abertura = 100 then 'Crédito de boas-vindas (simulado) — lançamento retroativo'
            else 'Saldo de abertura (migração 15)' end,
       a.criado_em
from (
    select u.id, u.criado_em,
           round(u.saldo - coalesce((select sum(public.sinal_movimento(m.tipo) * m.valor)
                                     from public.movimentacoes_carteira m
                                     where m.usuario_id = u.id), 0), 2) as abertura
    from public.usuarios u
) a
where a.abertura <> 0;

-- 5.2 Guarda: saldo só muda dentro das RPCs (que ligam a GUC local abaixo).
-- Um UPDATE direto - inclusive pela service_role - falha com saldo_so_por_rpc.
create or replace function public.proteger_saldo() returns trigger
language plpgsql
set search_path = public
as $$
begin
    if coalesce(current_setting('chargeops.carteira', true), '') <> 'rpc' then
        if tg_op = 'INSERT' and coalesce(new.saldo, 0) <> 0 then
            raise exception 'saldo_so_por_rpc';
        end if;
        if tg_op = 'UPDATE' and new.saldo is distinct from old.saldo then
            raise exception 'saldo_so_por_rpc';
        end if;
    end if;
    return new;
end $$;

drop trigger if exists trg_proteger_saldo on public.usuarios;
create trigger trg_proteger_saldo
    before insert or update of saldo on public.usuarios
    for each row execute function public.proteger_saldo();

-- 5.3 Débito e crédito: mesma assinatura e mesmo comportamento do 12, agora
-- abrindo e fechando a guarda.
create or replace function public.debitar_saldo(
    p_usuario uuid, p_valor numeric, p_tipo text, p_descricao text, p_sessao uuid default null
) returns numeric
language plpgsql
set search_path = public
as $$
declare novo numeric;
begin
    if p_valor < 0 then raise exception 'valor_negativo'; end if;
    if sinal_movimento(p_tipo) is distinct from -1 then raise exception 'tipo_invalido'; end if;
    perform set_config('chargeops.carteira', 'rpc', true);
    update usuarios set saldo = round(saldo - p_valor, 2)
    where id = p_usuario and saldo >= p_valor
    returning saldo into novo;
    perform set_config('chargeops.carteira', '', true);
    if novo is null then
        raise exception 'saldo_insuficiente';
    end if;
    insert into movimentacoes_carteira (usuario_id, sessao_id, tipo, valor, saldo_apos, descricao)
    values (p_usuario, p_sessao, p_tipo, p_valor, novo, p_descricao);
    return novo;
end $$;

create or replace function public.creditar_saldo(
    p_usuario uuid, p_valor numeric, p_tipo text, p_descricao text, p_sessao uuid default null
) returns numeric
language plpgsql
set search_path = public
as $$
declare novo numeric;
begin
    if p_valor < 0 then raise exception 'valor_negativo'; end if;
    if sinal_movimento(p_tipo) is distinct from 1 then raise exception 'tipo_invalido'; end if;
    perform set_config('chargeops.carteira', 'rpc', true);
    update usuarios set saldo = round(saldo + p_valor, 2)
    where id = p_usuario
    returning saldo into novo;
    perform set_config('chargeops.carteira', '', true);
    if novo is null then raise exception 'usuario_inexistente'; end if;
    insert into movimentacoes_carteira (usuario_id, sessao_id, tipo, valor, saldo_apos, descricao)
    values (p_usuario, p_sessao, p_tipo, p_valor, novo, p_descricao);
    return novo;
end $$;

-- Leva o saldo a um valor-alvo lançando a diferença como ajuste. É o que o
-- `provisionar.py limpar` usa no lugar do UPDATE direto.
create or replace function public.ajustar_saldo(
    p_usuario uuid, p_saldo_alvo numeric, p_descricao text
) returns numeric
language plpgsql
set search_path = public
as $$
declare atual numeric; dif numeric;
begin
    if p_saldo_alvo < 0 then raise exception 'valor_negativo'; end if;
    select saldo into atual from usuarios where id = p_usuario for update;
    if atual is null then raise exception 'usuario_inexistente'; end if;
    dif := round(p_saldo_alvo - atual, 2);
    if dif > 0 then
        return creditar_saldo(p_usuario, dif, 'ajuste', p_descricao);
    elsif dif < 0 then
        return debitar_saldo(p_usuario, -dif, 'ajuste_debito', p_descricao);
    end if;
    return atual;
end $$;

-- Quem diverge da regra? Vazio = carteira íntegra.
create or replace function public.conferir_carteira()
returns table (usuario_id uuid, saldo numeric, soma_extrato numeric, diferenca numeric)
language sql stable
set search_path = public
as $$
    select u.id, u.saldo, coalesce(x.soma, 0), round(u.saldo - coalesce(x.soma, 0), 2)
    from usuarios u
    left join (select m.usuario_id, sum(sinal_movimento(m.tipo) * m.valor) as soma
               from movimentacoes_carteira m group by m.usuario_id) x on x.usuario_id = u.id
    where round(u.saldo - coalesce(x.soma, 0), 2) <> 0;
$$;

-- 5.4 Nome único sem depender de maiúscula. Se já houver duplicata no banco,
-- avisa e segue: a RPC abaixo ainda checa antes de inserir.
do $$
begin
    if exists (select 1 from public.usuarios group by lower(nome) having count(*) > 1) then
        raise notice 'uq_usuarios_nome_ci NÃO criado: há nomes duplicados (ignorando maiúsculas). Resolva e rode de novo.';
    else
        create unique index if not exists uq_usuarios_nome_ci on public.usuarios (lower(nome));
    end if;
end $$;

-- 5.5 Cadastro atômico. Tudo ou nada: usuário, senha, veículo, favorito e
-- bônus. O Argon2 roda no Python; aqui chega só o hash.
-- Erros: nome_em_uso, condominio_invalido, tipo_invalido, veiculo_invalido.
create or replace function public.cadastrar_usuario(
    p_nome text, p_senha_hash text, p_condominio uuid, p_tipo text,
    p_bloco text, p_veiculo jsonb, p_bonus numeric default 100
) returns uuid
language plpgsql
set search_path = public
as $$
declare
    v_id uuid;
    v_restricao text;
begin
    if p_tipo not in ('morador', 'visitante') then raise exception 'tipo_invalido'; end if;
    if p_senha_hash is null or p_senha_hash not like '$argon2%' then raise exception 'hash_invalido'; end if;
    if p_bonus < 0 then raise exception 'valor_negativo'; end if;
    if not exists (select 1 from condominios where id = p_condominio) then
        raise exception 'condominio_invalido';
    end if;
    if p_veiculo is null or coalesce(trim(p_veiculo->>'modelo'), '') = '' then
        raise exception 'veiculo_invalido';
    end if;
    if exists (select 1 from usuarios where lower(nome) = lower(trim(p_nome))) then
        raise exception 'nome_em_uso';
    end if;

    begin
        insert into usuarios (nome, tipo_usuario, condominio_id, bloco_apto)
        values (trim(p_nome), p_tipo, p_condominio, p_bloco)
        returning id into v_id;
    exception when unique_violation then
        get stacked diagnostics v_restricao = constraint_name;
        if v_restricao = 'uq_usuarios_nome_ci' then raise exception 'nome_em_uso'; end if;
        raise;
    end;

    insert into credenciais_usuario (usuario_id, senha_hash) values (v_id, p_senha_hash);

    insert into veiculos (usuario_id, modelo, placa, tipo, capacidade_bateria_kwh, potencia_carro_kw)
    values (v_id,
            trim(p_veiculo->>'modelo'),
            nullif(p_veiculo->>'placa', ''),
            coalesce(p_veiculo->>'tipo', 'carro'),
            coalesce((p_veiculo->>'capacidade_bateria_kwh')::numeric, 40),
            coalesce((p_veiculo->>'potencia_carro_kw')::numeric, 7.4));

    insert into condominios_favoritos (usuario_id, condominio_id)
    values (v_id, p_condominio)
    on conflict (usuario_id, condominio_id) do nothing;

    if p_bonus > 0 then
        perform creditar_saldo(v_id, p_bonus, 'bonus', 'Crédito de boas-vindas (simulado)');
    end if;

    return v_id;
end $$;


-- =============================================================================
-- 6. VOCABULÁRIO MODBUS HCA G2 (configuração simulada)
-- =============================================================================
-- Os nomes seguem o mapa Modbus do HCA G2. Os valores são guardados e
-- simulados: o sistema NÃO fala Modbus RS485 com um carregador real.
alter table public.carregadores
    add column if not exists potencia_nominal_kw numeric,
    add column if not exists garantir_minimo     boolean  not null default false,
    add column if not exists controle_dinamico   boolean  not null default false,
    add column if not exists limite_disjuntor_a  numeric,
    add column if not exists modo_carga          smallint not null default 0;

comment on column public.carregadores.garantir_minimo     is 'Modbus 10024 - manter potência mínima de carga (0 off / 1 on)';
comment on column public.carregadores.controle_dinamico   is 'Modbus 10025 - gestão dinâmica de carga (0 off / 1 on)';
comment on column public.carregadores.limite_disjuntor_a  is 'Modbus 10026 - corrente nominal do disjuntor de entrada, 0-2000 A';
comment on column public.carregadores.potencia_maxima_kw  is 'Modbus 10029 - potência máxima configurada; faixa depende do modelo';
comment on column public.carregadores.potencia_nominal_kw is 'Modelo HCA G2: 7 (monofásico), 11 ou 22 (trifásico). Null na bancada USB';
comment on column public.carregadores.modo_carga          is 'Modbus 10032 - 0 rápido / 1 FV / 2 FV + bateria (valor do registrador)';

-- Dados: 7,4 kW não existe na linha HCA G2. Só mexe em quem ainda não tem
-- nominal (idempotente) e só renomeia modelo que ainda é o nome genérico.
update public.carregadores c
set potencia_nominal_kw = x.nominal,
    potencia_maxima_kw  = least(greatest(c.potencia_maxima_kw,
                                         case when x.nominal = 7 then 1.4 else 4.2 end), x.nominal),
    modelo = case when c.modelo like 'GoodWe AC%'
                  then 'GoodWe HCA G2 ' || x.nominal || 'kW' else c.modelo end
from (
    select id, case when potencia_maxima_kw <= 7.4 then 7
                    when potencia_maxima_kw <= 11  then 11
                    else 22 end as nominal
    from public.carregadores
) x
where x.id = c.id and c.perfil = 'veicular' and c.potencia_nominal_kw is null;

update public.carregadores set potencia_nominal_kw = null where perfil = 'bancada';

alter table public.carregadores alter column modelo              set default 'GoodWe HCA G2 7kW';
alter table public.carregadores alter column potencia_maxima_kw  set default 7;
alter table public.carregadores alter column potencia_nominal_kw set default 7;

alter table public.carregadores drop constraint if exists carregadores_hca_g2_potencia_check;
alter table public.carregadores add constraint carregadores_hca_g2_potencia_check check (
    perfil = 'bancada' or (
        potencia_nominal_kw in (7, 11, 22)
        and potencia_maxima_kw >= case when potencia_nominal_kw = 7 then 1.4 else 4.2 end
        and potencia_maxima_kw <= potencia_nominal_kw
    )
);
alter table public.carregadores drop constraint if exists carregadores_modo_carga_check;
alter table public.carregadores add constraint carregadores_modo_carga_check
    check (modo_carga in (0, 1, 2));
alter table public.carregadores drop constraint if exists carregadores_disjuntor_check;
alter table public.carregadores add constraint carregadores_disjuntor_check
    check (limite_disjuntor_a is null or limite_disjuntor_a between 0 and 2000);


-- =============================================================================
-- 7. SOLAR SIMULADO, ORIGEM ROTULADA
-- =============================================================================
-- medido = veio de sensor · simulado = gerado pelo simulador · estimado = conta
-- feita a partir de outro dado. `carregadores.origem` (simulado | hardware)
-- continua dizendo de onde vem o EQUIPAMENTO, não o dado.
alter table public.condominios
    add column if not exists fv_potencia_kwp numeric not null default 0;
alter table public.condominios drop constraint if exists condominios_fv_check;
alter table public.condominios add constraint condominios_fv_check check (fv_potencia_kwp >= 0);
comment on column public.condominios.fv_potencia_kwp is 'Potência FV instalada (SIMULADA nesta fase)';

create table if not exists public.geracao_solar (
    condominio_id uuid not null references public.condominios(id) on delete cascade,
    momento       timestamptz not null,
    potencia_kw   numeric not null default 0 check (potencia_kw >= 0),
    energia_kwh   numeric not null default 0 check (energia_kwh >= 0),
    origem        text not null default 'simulado'
                  check (origem in ('medido', 'simulado', 'estimado')),
    primary key (condominio_id, momento)
);


-- =============================================================================
-- 8. GRANTS - REVISÃO FINAL
-- =============================================================================
-- Tabelas novas: RLS ligado, nenhum grant. Só o backend (service_role) toca.
alter table public.portas_dispositivo enable row level security;
alter table public.dispositivo_boots  enable row level security;
alter table public.geracao_solar      enable row level security;
revoke all on public.portas_dispositivo, public.dispositivo_boots, public.geracao_solar
    from anon, authenticated;

-- `fila` ficou com SELECT sem política desde o 13. Quem lê é a view.
revoke select on public.fila from authenticated;

-- Varredura: toda função do schema public (menos as de extensão) fecha para
-- o navegador e abre só para o backend.
do $$
declare f record;
begin
    for f in
        select p.oid::regprocedure as assinatura
        from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public'
          and not exists (select 1 from pg_depend d where d.objid = p.oid and d.deptype = 'e')
    loop
        execute format('revoke all on function %s from public, anon, authenticated', f.assinatura);
        execute format('grant execute on function %s to service_role', f.assinatura);
    end loop;
end $$;

commit;

-- =============================================================================
-- DEPOIS DE RODAR
-- =============================================================================
-- 1. Rode db/15_verificacao.sql (tudo em transação desfeita no final).
-- 2. Conferências rápidas:
--      select * from public.conferir_carteira();          -- 0 linhas
--      select d.nome, p.numero, c.numero as ponto
--        from portas_dispositivo p
--        join dispositivos d on d.id = p.dispositivo_id
--        join carregadores c on c.id = p.carregador_id;    -- 1 linha por placa
--      select numero, modelo, potencia_nominal_kw, potencia_maxima_kw, modo_carga
--        from carregadores order by condominio_id, numero;
-- =============================================================================
