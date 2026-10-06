-- =============================================================================
-- 16_verificacao.sql - Prova dos critérios de pronto da migration 16
-- =============================================================================
-- Rode no SQL Editor DEPOIS do 16. NÃO deixa rastro: tudo roda dentro de um
-- bloco que é desfeito no final. Só o resultado sobrevive.
--
-- Saída: uma tabela (teste | ok | detalhe). Pronto = todas as linhas ok = true.
--
--   a) colunas, defaults e checks novos
--   b) dados convertidos na primeira execução (tarifa 1,15 e 10025 ligado)
--   c) registrar_consumo separa rede x sol e não põe sol na ponta
--   d) somar_geracao_solar soma por origem
--   e) funções novas fechadas ao navegador; versão antiga apagada
--   f) premissas alinham o incentivo solar em todo condomínio
-- =============================================================================

create or replace function pg_temp.j(p_teste text, p_ok boolean, p_detalhe text)
returns jsonb language sql immutable as $$
    select jsonb_build_object('teste', p_teste, 'ok', coalesce(p_ok, false), 'detalhe', p_detalhe);
$$;

create or replace function pg_temp.verificar_16()
returns table (teste text, ok boolean, detalhe text)
language plpgsql as $$
declare
    res  jsonb := '[]';
    cond uuid;
    n int; txt text; b boolean;
    e numeric; ep numeric; es numeric; pk numeric; pr numeric;
    nova_sig text := 'public.registrar_consumo(uuid,numeric,boolean,numeric,numeric,numeric,numeric)';
begin
    begin   -- ===== tudo daqui até o fim do bloco é desfeito =====

    -- -------------------------------------------------------------------------
    -- (a) ESTRUTURA
    -- -------------------------------------------------------------------------
    select count(*) into n from information_schema.columns
     where table_schema = 'public'
       and (table_name, column_name) in (
            ('condominios', 'custo_solar_kwh'), ('condominios', 'preco_solar_kwh'),
            ('sessoes_recarga', 'energia_solar_kwh'), ('sessoes_recarga', 'origem_solar'),
            ('sessoes_recarga', 'tarifa_solar_kwh'), ('sessoes_recarga', 'potencia_alocada_solar_kw'),
            ('consumo_horario', 'energia_solar_kwh'), ('consumo_horario', 'pico_rede_kw'));
    res := res || pg_temp.j('a1 as 8 colunas novas existem', n = 8, format('%s de 8', n));

    select string_agg(table_name || '.' || column_name || '=' || column_default, ', ' order by table_name, column_name)
      into txt from information_schema.columns
     where table_schema = 'public'
       and (table_name, column_name) in (('condominios', 'custo_solar_kwh'), ('condominios', 'preco_solar_kwh'),
                                         ('carregadores', 'tarifa_kwh'), ('carregadores', 'controle_dinamico'));
    res := res || pg_temp.j('a2 defaults: solar 0,35/0,75, rede 1,15, 10025 ligado',
        txt = 'carregadores.controle_dinamico=true, carregadores.tarifa_kwh=1.15, '
              'condominios.custo_solar_kwh=0.35, condominios.preco_solar_kwh=0.75', txt);

    select count(*) into n from pg_constraint
     where conname in ('condominios_solar_precos_check', 'sessoes_origem_solar_check',
                       'sessoes_energia_solar_check', 'sessoes_fontes_fecham_check');
    res := res || pg_temp.j('a3 os 4 checks novos existem', n = 4, format('%s de 4', n));

    -- -------------------------------------------------------------------------
    -- (b) DADOS CONVERTIDOS (logo depois da migration; o síndico pode mudar depois)
    -- -------------------------------------------------------------------------
    select count(*) into n from public.carregadores where tarifa_kwh > 1.15;
    res := res || pg_temp.j('b1 nenhum carregador acima de R$ 1,15 (seeds convertidos)', n = 0,
                            format('%s acima', n));

    select count(*) into n from public.carregadores where perfil = 'veicular' and not controle_dinamico;
    res := res || pg_temp.j('b2 veiculares com 10025 ligado', n = 0, format('%s desligados', n));

    -- -------------------------------------------------------------------------
    -- (c) REGISTRAR_CONSUMO: REDE x SOL
    -- -------------------------------------------------------------------------
    insert into public.condominios (nome, endereco, limite_potencia_kw)
    values ('Teste16 ' || substr(md5(random()::text), 1, 6), 'roteiro', 10)
    returning id into cond;

    -- fora da ponta: 2 kWh, 0,5 do sol; carga 5 kW, rede 3 kW
    perform public.registrar_consumo(cond, 2, false, 5, 6, 0.5, 3);
    -- na ponta: 1 kWh, 0,25 do sol -> só 0,75 entra na ponta
    perform public.registrar_consumo(cond, 1, true, 4, 4, 0.25, 4);
    -- chamada antiga (5 parâmetros por nome) continua aceita
    perform public.registrar_consumo(p_cond => cond, p_kwh => 0, p_ponta => false,
                                     p_carga_kw => 2, p_demanda_kw => 2);

    select energia_kwh, energia_ponta_kwh, energia_solar_kwh, pico_kw, pico_rede_kw
      into e, ep, es, pk, pr
      from public.consumo_horario where condominio_id = cond;
    res := res || pg_temp.j('c1 energia 3, solar 0,75, ponta só rede 0,75',
        e = 3 and es = 0.75 and ep = 0.75, format('energia=%s solar=%s ponta=%s', e, es, ep));
    res := res || pg_temp.j('c2 pico da garagem 5, pico da rede 4',
        pk = 5 and pr = 4, format('pico=%s pico_rede=%s', pk, pr));

    -- -------------------------------------------------------------------------
    -- (d) SOMA DA GERAÇÃO
    -- -------------------------------------------------------------------------
    insert into public.geracao_solar (condominio_id, momento, potencia_kw, energia_kwh, origem) values
        (cond, now() - interval '20 minutes', 6, 0.5, 'simulado'),
        (cond, now() - interval '15 minutes', 7, 0.6, 'simulado'),
        (cond, now() - interval '3 days',     9, 9.0, 'simulado');
    select string_agg(origem || '=' || energia_kwh || '/' || pico_kw, ', ') into txt
      from public.somar_geracao_solar(cond, now() - interval '1 hour');
    res := res || pg_temp.j('d1 somar_geracao_solar respeita o período', txt = 'simulado=1.1/7', txt);

    -- -------------------------------------------------------------------------
    -- (e) GRANTS
    -- -------------------------------------------------------------------------
    select not has_function_privilege('anon', nova_sig, 'execute')
       and not has_function_privilege('authenticated', nova_sig, 'execute')
       and has_function_privilege('service_role', nova_sig, 'execute')
       and not has_function_privilege('authenticated', 'public.somar_geracao_solar(uuid,timestamptz)', 'execute')
       and has_function_privilege('service_role', 'public.somar_geracao_solar(uuid,timestamptz)', 'execute')
      into b;
    res := res || pg_temp.j('e1 funções novas só para service_role', b, null);

    select to_regprocedure('public.registrar_consumo(uuid,numeric,boolean,numeric,numeric)') is null into b;
    res := res || pg_temp.j('e2 assinatura antiga de registrar_consumo apagada', b, null);

    select count(*), string_agg(p.oid::regprocedure::text, ', ') into n, txt
      from pg_proc p join pg_namespace ns on ns.oid = p.pronamespace
     where ns.nspname = 'public'
       and not exists (select 1 from pg_depend d where d.objid = p.oid and d.deptype = 'e')
       and (has_function_privilege('anon', p.oid, 'execute')
            or has_function_privilege('authenticated', p.oid, 'execute'));
    res := res || pg_temp.j('e3 nenhuma função de public chamável pelo navegador', n = 0, txt);

    -- -------------------------------------------------------------------------
    -- (f) INCENTIVO SOLAR: margem solar >= margem da rede fora da ponta
    -- -------------------------------------------------------------------------
    select count(*), string_agg(c.nome, ', ') into n, txt
      from public.condominios c
     where c.nome not like 'Teste16 %'
       and (c.preco_solar_kwh - c.custo_solar_kwh) <
           (select coalesce(max(k.tarifa_kwh), 0) from public.carregadores k
             where k.condominio_id = c.id and k.perfil = 'veicular') - c.custo_energia_kwh;
    res := res || pg_temp.j('f1 incentivo solar alinhado em todo condomínio', n = 0, txt);

    raise exception 'desfazer_teste_16';
    exception when others then
        if sqlerrm <> 'desfazer_teste_16' then
            res := res || pg_temp.j('ERRO INESPERADO - roteiro interrompido', false, sqlerrm);
        end if;
    end;   -- ===== tudo acima foi desfeito =====

    return query select x.teste, x.ok, x.detalhe
                 from jsonb_to_recordset(res) as x(teste text, ok boolean, detalhe text);
end $$;

select * from pg_temp.verificar_16();
