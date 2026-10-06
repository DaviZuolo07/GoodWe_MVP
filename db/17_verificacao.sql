-- =============================================================================
-- 17_verificacao.sql - Prova dos critérios de pronto da migration 17
-- =============================================================================
-- Rode no SQL Editor DEPOIS do 17. NÃO deixa rastro: tudo roda dentro de um
-- bloco que é desfeito no final. Só o resultado sobrevive.
--
-- Saída: uma tabela (teste | ok | detalhe). Pronto = todas as linhas ok = true.
--
--   a) colunas, defaults e checks novos
--   b) lote com escala e fontes (inclusive só fontes), origem pela placa
--   c) aguardando_energia é sessão viva (ocupa vaga e veículo)
--   d) tabelas e função novas fechadas ao navegador; assinatura antiga apagada
-- =============================================================================

create or replace function pg_temp.j(p_teste text, p_ok boolean, p_detalhe text)
returns jsonb language sql immutable as $$
    select jsonb_build_object('teste', p_teste, 'ok', coalesce(p_ok, false), 'detalhe', p_detalhe);
$$;

create or replace function pg_temp.verificar_17()
returns table (teste text, ok boolean, detalhe text)
language plpgsql as $$
declare
    res   jsonb := '[]';
    cond  uuid; c1 uuid; c2 uuid; virt uuid; fisica uuid; usr uuid; vei uuid;
    n int; txt text; b boolean; x numeric; y numeric; seq_antes bigint;
    nova_sig text := 'public.registrar_lote_telemetria(uuid,bigint,bigint,timestamptz,bigint,jsonb,integer,jsonb)';
begin
    begin   -- ===== tudo daqui até o fim do bloco é desfeito =====

    -- -------------------------------------------------------------------------
    -- (a) ESTRUTURA
    -- -------------------------------------------------------------------------
    select count(*) into n from information_schema.columns
     where table_schema = 'public'
       and (table_name, column_name) in (
            ('dispositivos', 'fator_escala'), ('dispositivos', 'virtual'), ('dispositivos', 'porta_solar'),
            ('carregadores', 'bateria_soc_minimo'),
            ('leituras_hardware', 'fator_escala'), ('leituras_hardware', 'potencia_escalada_kw'),
            ('leituras_hardware', 'energia_escalada_kwh'),
            ('sessoes_recarga', 'percentual_origem'), ('sessoes_recarga', 'uid_inicio'),
            ('sessoes_recarga', 'modo_vaga_solar'), ('geracao_solar', 'dispositivo_id'),
            ('v_sessoes_local', 'percentual_origem'));
    res := res || pg_temp.j('a1 as 12 colunas novas existem', n = 12, format('%s de 12', n));

    select string_agg(table_name || '.' || column_name || '=' || column_default, ', ' order by table_name, column_name)
      into txt from information_schema.columns
     where table_schema = 'public'
       and (table_name, column_name) in (('dispositivos', 'fator_escala'), ('dispositivos', 'virtual'),
                                         ('carregadores', 'bateria_soc_minimo'),
                                         ('sessoes_recarga', 'percentual_origem'));
    res := res || pg_temp.j('a2 defaults: fator 1000, virtual false, 10030 = 20, % informado',
        txt = 'carregadores.bateria_soc_minimo=20, dispositivos.fator_escala=1000, '
              'dispositivos.virtual=false, sessoes_recarga.percentual_origem=''informado''::text', txt);

    select count(*) into n from public.dispositivos where fator_escala is null;
    res := res || pg_temp.j('a3 nenhuma placa sem fator', n = 0, format('%s sem fator', n));

    select count(*) into n from to_regclass('public.leituras_fonte') t where t is not null;
    select n + count(*) into n from to_regclass('public.eventos_seguranca') t where t is not null;
    res := res || pg_temp.j('a4 leituras_fonte e eventos_seguranca existem', n = 2, format('%s de 2', n));

    -- -------------------------------------------------------------------------
    -- (b) LOTE COM ESCALA E FONTES
    -- -------------------------------------------------------------------------
    insert into public.condominios (nome, endereco, limite_potencia_kw)
    values ('Teste17 ' || substr(md5(random()::text), 1, 6), 'roteiro', 20)
    returning id into cond;
    insert into public.carregadores (condominio_id, numero, modelo, tipo, potencia_maxima_kw, conector,
                                     tensao_v, corrente_maxima_a, origem, perfil)
    values (cond, 'T1', 'Totem', 'DC', 7.5, 'USB', 5, 3, 'hardware', 'bancada') returning id into c1;
    insert into public.carregadores (condominio_id, numero, modelo, tipo, potencia_maxima_kw, conector,
                                     tensao_v, corrente_maxima_a, origem, perfil)
    values (cond, 'T4', 'Totem', 'DC', 7.5, 'USB', 5, 3, 'hardware', 'bancada') returning id into c2;

    insert into public.dispositivos (nome, virtual, porta_solar) values ('Teste17 virtual', true, 2)
    returning id into virt;
    insert into public.dispositivos (nome) values ('Teste17 fisica') returning id into fisica;
    insert into public.portas_dispositivo (dispositivo_id, numero, carregador_id) values (virt, 1, c1), (virt, 2, c2);

    select fator_escala into x from public.dispositivos where id = virt;
    res := res || pg_temp.j('b1 placa nova nasce com fator 1000', x = 1000, format('fator=%s', x));

    perform public.consumir_seq(virt, 7, 1, now(), true, 120);

    -- só fontes: leituras vazia
    select public.registrar_lote_telemetria(virt, 7, 2, now(), 5000, '[]'::jsonb, 120,
        '[{"fonte":"painel","t_ms":4000,"potencia_w":7.4,"tensao_v":5.9,"corrente_a":1.25},
          {"fonte":"bateria","t_ms":4000,"potencia_w":0,"tensao_v":3.91,"corrente_a":0,"soc_estimado":68.8}]'::jsonb)
      into n;
    select count(*), min(origem), max(potencia_escalada_kw), max(soc_estimado)
      into n, txt, x, y from public.leituras_fonte where dispositivo_id = virt;
    res := res || pg_temp.j('b2 lote só com fontes: 2 linhas, simulado, 7,4 W -> 7,4 kW, SOC 68,8',
        n = 2 and txt = 'simulado' and x = 7.4 and y = 68.8,
        format('linhas=%s origem=%s kw=%s soc=%s', n, txt, x, y));

    -- leitura de vaga: bruto e escalado
    perform public.registrar_lote_telemetria(virt, 7, 3, now(), 9000,
        '[{"porta":1,"t_ms":9000,"potencia_w":7.5,"energia_wh":12,"rele_ligado":true}]'::jsonb, 120, null);
    select potencia_escalada_kw, energia_escalada_kwh, origem
      into y, x, txt from public.leituras_hardware where dispositivo_id = virt;
    res := res || pg_temp.j('b3 7,5 W / 12 Wh brutos -> 7,5 kW / 12 kWh, origem simulado',
        y = 7.5 and x = 12 and txt = 'simulado', format('kw=%s kwh=%s origem=%s', y, x, txt));

    -- lote vazio e fonte desconhecida: recusados sem gastar o seq
    select seq_atual into seq_antes from public.dispositivos where id = virt;
    begin
        perform public.registrar_lote_telemetria(virt, 7, 4, now(), 1, '[]'::jsonb, 120, '[]'::jsonb);
        txt := 'aceitou';
    exception when others then txt := sqlerrm;
    end;
    res := res || pg_temp.j('b4 lote vazio recusado', txt = 'lote_invalido', txt);
    begin
        perform public.registrar_lote_telemetria(virt, 7, 4, now(), 1, '[]'::jsonb, 120,
            '[{"fonte":"eolica","t_ms":1,"potencia_w":1}]'::jsonb);
        txt := 'aceitou';
    exception when others then txt := sqlerrm;
    end;
    select seq_atual into x from public.dispositivos where id = virt;
    res := res || pg_temp.j('b5 fonte fora da lista recusada e seq não gasto',
        txt = 'lote_invalido' and x = seq_antes, format('%s; seq %s -> %s', txt, seq_antes, x));

    -- placa física (virtual = false) grava medido
    perform public.consumir_seq(fisica, 9, 1, now(), true, 120);
    perform public.registrar_lote_telemetria(fisica, 9, 2, now(), 1000, '[]'::jsonb, 120,
        '[{"fonte":"painel","t_ms":1000,"potencia_w":2}]'::jsonb);
    select origem into txt from public.leituras_fonte where dispositivo_id = fisica;
    res := res || pg_temp.j('b6 placa física grava medido', txt = 'medido', txt);

    -- chamada antiga (7 parâmetros por nome) continua aceita
    perform public.registrar_lote_telemetria(p_dispositivo => virt, p_boot => 7, p_seq => 5,
        p_ts => now(), p_t_envio_ms => 1, p_leituras => '[{"porta":2,"t_ms":1,"potencia_w":0}]'::jsonb,
        p_janela_s => 120);
    select count(*) into n from public.leituras_hardware where dispositivo_id = virt;
    res := res || pg_temp.j('b7 chamada antiga por nome aceita', n = 2, format('%s leituras', n));

    -- -------------------------------------------------------------------------
    -- (c) AGUARDANDO_ENERGIA É SESSÃO VIVA
    -- -------------------------------------------------------------------------
    insert into public.usuarios (nome, tipo_usuario, condominio_id)
    values ('Teste17 ' || substr(md5(random()::text), 1, 6), 'morador', cond) returning id into usr;
    insert into public.veiculos (usuario_id, modelo, tipo, capacidade_bateria_kwh, potencia_carro_kw)
    values (usr, 'Celular 1:1000', 'celular', 15, 7.5) returning id into vei;
    insert into public.sessoes_recarga (carregador_id, veiculo_id, usuario_id, status, percentual_origem)
    values (c1, vei, usr, 'aguardando_energia', 'estimado');
    begin
        insert into public.sessoes_recarga (carregador_id, usuario_id, status) values (c1, usr, 'carregando');
        txt := 'aceitou';
    exception when unique_violation then txt := 'recusou';
    end;
    res := res || pg_temp.j('c1 vaga em aguardando_energia não aceita outra sessão', txt = 'recusou', txt);
    begin
        insert into public.sessoes_recarga (carregador_id, veiculo_id, usuario_id, status) values (c2, vei, usr, 'aguardando_rfid');
        txt := 'aceitou';
    exception when unique_violation then txt := 'recusou';
    end;
    res := res || pg_temp.j('c2 veículo em aguardando_energia não abre outra sessão', txt = 'recusou', txt);
    begin
        insert into public.sessoes_recarga (carregador_id, usuario_id, status, percentual_origem)
        values (c2, usr, 'carregando', 'chutado');
        txt := 'aceitou';
    exception when check_violation then txt := 'recusou';
    end;
    res := res || pg_temp.j('c3 percentual_origem é lista fechada', txt = 'recusou', txt);

    -- -------------------------------------------------------------------------
    -- (d) GRANTS E LISTA FECHADA DE EVENTOS
    -- -------------------------------------------------------------------------
    select not has_function_privilege('anon', nova_sig, 'execute')
       and not has_function_privilege('authenticated', nova_sig, 'execute')
       and has_function_privilege('service_role', nova_sig, 'execute')
      into b;
    res := res || pg_temp.j('d1 RPC nova só para service_role', b, null);

    select to_regprocedure('public.registrar_lote_telemetria(uuid,bigint,bigint,timestamptz,bigint,jsonb,integer)') is null
      into b;
    res := res || pg_temp.j('d2 assinatura antiga do lote apagada', b, null);

    select not (has_table_privilege('anon', 'public.leituras_fonte', 'select')
             or has_table_privilege('authenticated', 'public.leituras_fonte', 'select')
             or has_table_privilege('anon', 'public.eventos_seguranca', 'select')
             or has_table_privilege('authenticated', 'public.eventos_seguranca', 'select')
             or has_table_privilege('authenticated', 'public.eventos_seguranca', 'insert'))
      into b;
    res := res || pg_temp.j('d3 leituras_fonte e eventos_seguranca fechadas ao navegador', b, null);

    begin
        insert into public.eventos_seguranca (tipo) values ('qualquer_coisa');
        txt := 'aceitou';
    exception when check_violation then txt := 'recusou';
    end;
    res := res || pg_temp.j('d4 tipo de evento é lista fechada', txt = 'recusou', txt);

    select count(*), string_agg(p.oid::regprocedure::text, ', ') into n, txt
      from pg_proc p join pg_namespace ns on ns.oid = p.pronamespace
     where ns.nspname = 'public'
       and not exists (select 1 from pg_depend d where d.objid = p.oid and d.deptype = 'e')
       and (has_function_privilege('anon', p.oid, 'execute')
            or has_function_privilege('authenticated', p.oid, 'execute'));
    res := res || pg_temp.j('d5 nenhuma função de public chamável pelo navegador', n = 0, txt);

    raise exception 'desfazer_teste_17';
    exception when others then
        if sqlerrm <> 'desfazer_teste_17' then
            res := res || pg_temp.j('ERRO INESPERADO - roteiro interrompido', false, sqlerrm);
        end if;
    end;   -- ===== tudo acima foi desfeito =====

    return query select x.teste, x.ok, x.detalhe
                 from jsonb_to_recordset(res) as x(teste text, ok boolean, detalhe text);
end $$;

select * from pg_temp.verificar_17();
