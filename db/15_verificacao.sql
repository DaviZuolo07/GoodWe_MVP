-- =============================================================================
-- 15_verificacao.sql - Prova dos critérios de pronto da migration 15
-- =============================================================================
-- Rode no SQL Editor DEPOIS do 15. NÃO deixa rastro: os testes rodam dentro
-- de um bloco que é desfeito no final (subtransação). Só o resultado sobrevive.
--
-- Saída: uma tabela (teste | ok | detalhe). Pronto = todas as linhas com ok = true.
--
--   a) morador de A não vê sessões nem fila de B; vê as próprias
--   b) cadastro novo -> saldo 100 = soma do extrato; tudo-ou-nada; guarda do saldo
--   c) replay rejeitado (seq repetido, ts velho, boot antigo, porta inválida)
--   d) caminho v1 intacto (porta 1 implícita, token mantido)
--   e) grants: nada chamável/legível pelo navegador além do previsto
--
-- Impersonação: set local role + request.jwt.claims, como o PostgREST faz.
-- =============================================================================

create or replace function pg_temp.j(p_teste text, p_ok boolean, p_detalhe text)
returns jsonb language sql immutable as $$
    select jsonb_build_object('teste', p_teste, 'ok', coalesce(p_ok, false), 'detalhe', p_detalhe);
$$;

create or replace function pg_temp.verificar_15()
returns table (teste text, ok boolean, detalhe text)
language plpgsql as $$
declare
    res        jsonb := '[]';
    cond_a     uuid  := '11111111-1111-1111-1111-111111111111';
    cond_b     uuid  := 'c0000000-0000-0000-0000-000000000002';
    sufixo     text  := substr(md5(random()::text), 1, 6);
    hash_falso text  := '$argon2id$v=19$m=65536,t=3,p=4$dGVzdGU$dGVzdGU';
    u_a uuid; u_b uuid; v_b uuid; ch1 uuid; ch2 uuid; disp uuid; disp_v1 uuid;
    n int; n2 int; s numeric; s2 numeric; txt text; b boolean;
begin
    begin   -- ===== tudo daqui até o fim do bloco é desfeito =====

    -- -------------------------------------------------------------------------
    -- (b) CADASTRO ATÔMICO E CARTEIRA COM LASTRO
    -- -------------------------------------------------------------------------
    u_a := public.cadastrar_usuario('Teste15 A ' || sufixo, hash_falso, cond_a, 'morador', '1A',
                                    '{"modelo":"Carro A","tipo":"carro"}'::jsonb);
    u_b := public.cadastrar_usuario('Teste15 B ' || sufixo, hash_falso, cond_b, 'visitante', '1B',
                                    '{"modelo":"Carro B","tipo":"carro"}'::jsonb);

    select u.saldo, coalesce(sum(public.sinal_movimento(m.tipo) * m.valor), 0)
      into s, s2
      from public.usuarios u left join public.movimentacoes_carteira m on m.usuario_id = u.id
     where u.id = u_a group by u.saldo;
    res := res || pg_temp.j('b1 cadastro: saldo = 100 = soma do extrato', s = 100 and s2 = 100,
                            format('saldo=%s extrato=%s', s, s2));

    select count(*) into n from public.movimentacoes_carteira
     where usuario_id = u_a and tipo = 'bonus' and descricao = 'Crédito de boas-vindas (simulado)';
    res := res || pg_temp.j('b2 bônus rotulado como simulado', n = 1, format('%s linha(s)', n));

    select (select count(*) from public.credenciais_usuario where usuario_id = u_a)
         + (select count(*) from public.veiculos where usuario_id = u_a)
         + (select count(*) from public.condominios_favoritos where usuario_id = u_a and condominio_id = cond_a)
      into n;
    res := res || pg_temp.j('b3 cadastro criou credencial, veículo e favorito', n = 3, format('%s/3', n));

    begin
        perform public.cadastrar_usuario(upper('Teste15 A ' || sufixo), hash_falso, cond_a, 'morador',
                                         null, '{"modelo":"X"}'::jsonb);
        res := res || pg_temp.j('b4 nome repetido (maiúsculas) recusado', false, 'aceitou');
    exception when others then
        res := res || pg_temp.j('b4 nome repetido (maiúsculas) recusado', sqlerrm = 'nome_em_uso', sqlerrm);
    end;

    begin
        perform public.cadastrar_usuario('Teste15 C ' || sufixo, hash_falso, cond_a, 'morador',
                                         null, '{"modelo":""}'::jsonb);
        res := res || pg_temp.j('b5 cadastro com veículo inválido não deixa nada', false, 'aceitou');
    exception when others then
        select count(*) into n from public.usuarios where nome = 'Teste15 C ' || sufixo;
        res := res || pg_temp.j('b5 cadastro com veículo inválido não deixa nada',
                                sqlerrm = 'veiculo_invalido' and n = 0, format('%s; usuários=%s', sqlerrm, n));
    end;

    begin
        perform public.cadastrar_usuario('Teste15 G ' || sufixo, hash_falso, cond_a, 'gestor',
                                         null, '{"modelo":"X"}'::jsonb);
        res := res || pg_temp.j('b6 cadastro público não cria gestor', false, 'aceitou');
    exception when others then
        res := res || pg_temp.j('b6 cadastro público não cria gestor', sqlerrm = 'tipo_invalido', sqlerrm);
    end;

    begin
        update public.usuarios set saldo = 9999 where id = u_a;
        res := res || pg_temp.j('b7 UPDATE direto no saldo bloqueado', false, 'aceitou');
    exception when others then
        res := res || pg_temp.j('b7 UPDATE direto no saldo bloqueado', sqlerrm = 'saldo_so_por_rpc', sqlerrm);
    end;

    s := public.debitar_saldo(u_a, 30, 'pre_autorizacao', 'teste');
    s := public.creditar_saldo(u_a, 12.5, 'estorno', 'teste');
    s := public.ajustar_saldo(u_a, 50, 'teste');
    select count(*) into n from public.conferir_carteira();
    res := res || pg_temp.j('b8 após débito/estorno/ajuste: saldo = extrato em todo o banco',
                            s = 50 and n = 0, format('saldo=%s divergentes=%s', s, n));

    -- -------------------------------------------------------------------------
    -- Cenário: B carregando num ponto do local B, B e A na fila de outro ponto B
    -- -------------------------------------------------------------------------
    select c.id into ch1 from public.carregadores c
     where c.condominio_id = cond_b and c.perfil = 'veicular'
       and not exists (select 1 from public.portas_dispositivo p where p.carregador_id = c.id)
       and not exists (select 1 from public.sessoes_recarga s
                       where s.carregador_id = c.id and s.status in ('aguardando_rfid', 'carregando'))
     order by c.numero limit 1;
    select c.id into ch2 from public.carregadores c
     where c.condominio_id = cond_b and c.id <> ch1
       and not exists (select 1 from public.portas_dispositivo p where p.carregador_id = c.id)
     order by c.numero limit 1;
    select id into v_b from public.veiculos where usuario_id = u_b;

    insert into public.sessoes_recarga (carregador_id, veiculo_id, usuario_id, status, iniciado_em, custo_estimado)
    values (ch1, v_b, u_b, 'carregando', now(), 10);
    insert into public.fila (carregador_id, usuario_id, posicao) values (ch2, u_b, 1), (ch2, u_a, 2);

    -- -------------------------------------------------------------------------
    -- (a) VIEWS FILTRADAS - impersonando A (favorito: só o local A)
    -- -------------------------------------------------------------------------
    perform set_config('request.jwt.claims', json_build_object('sub', u_a, 'role', 'authenticated')::text, true);
    execute 'set local role authenticated';
    select count(*) into n  from public.v_sessoes_local where carregador_id = ch1;
    select count(*) into n2 from public.v_fila_local where carregador_id = ch2 and not eh_meu;
    select count(*) into s  from public.v_fila_local where carregador_id = ch2 and eh_meu;
    execute 'reset role';
    res := res || pg_temp.j('a1 A não vê a sessão de B (local B)', n = 0, format('%s linha(s)', n));
    res := res || pg_temp.j('a2 A não vê a fila de B (local B)', n2 = 0, format('%s linha(s)', n2));
    res := res || pg_temp.j('a3 A vê a PRÓPRIA posição, mesmo fora dos favoritos', s = 1, format('%s linha(s)', s));

    execute 'set local role authenticated';
    begin
        select count(*) into n from public.fila;
        txt := format('leu %s linha(s)', n);
        b := false;
    exception when insufficient_privilege then
        txt := 'permission denied'; b := true;
    end;
    select count(*) into n2 from public.sessoes_recarga where usuario_id = u_b;
    execute 'reset role';
    res := res || pg_temp.j('a4 A não lê a tabela fila direto', b, txt);
    res := res || pg_temp.j('a5 A não lê sessoes_recarga de B direto', n2 = 0, format('%s linha(s)', n2));

    -- Impersonando B (favorito: local B): vê a própria sessão com custo
    perform set_config('request.jwt.claims', json_build_object('sub', u_b, 'role', 'authenticated')::text, true);
    execute 'set local role authenticated';
    select count(*), max(custo_estimado) into n, s from public.v_sessoes_local where carregador_id = ch1;
    select count(*) into n2 from public.v_fila_local where carregador_id = ch2;
    execute 'reset role';
    res := res || pg_temp.j('a6 B vê a própria sessão, com custo', n = 1 and s = 10, format('%s linha(s), custo=%s', n, s));
    res := res || pg_temp.j('a7 B vê a fila do local favorito inteira', n2 = 2, format('%s linha(s)', n2));

    -- -------------------------------------------------------------------------
    -- (c) PROTOCOLO v2: REPLAY
    -- -------------------------------------------------------------------------
    insert into public.dispositivos (nome, token_hash) values ('Teste15 placa v2', 'hash-v1-' || sufixo)
    returning id into disp;
    insert into public.portas_dispositivo (dispositivo_id, numero, carregador_id)
    values (disp, 1, ch1), (disp, 2, ch2);

    perform public.consumir_seq(disp, 111, 1, now(), true);
    select protocolo = 2 and token_hash is null into b from public.dispositivos where id = disp;
    res := res || pg_temp.j('c1 handshake v2 aposenta o token v1 (sem downgrade)', b, null);

    n := public.registrar_lote_telemetria(disp, 111, 2, now(), 5000,
        '[{"porta":1,"t_ms":3000,"potencia_w":12.4,"energia_wh":3.1,"rele_ligado":true},
          {"porta":2,"t_ms":4000,"potencia_w":0,"energia_wh":0,"rele_ligado":false}]'::jsonb);
    select count(*) into n2 from public.leituras_hardware l
     join public.sessoes_recarga s on s.id = l.sessao_id
     where l.dispositivo_id = disp and l.porta = 1 and s.carregador_id = ch1 and l.origem = 'medido';
    res := res || pg_temp.j('c2 lote com 2 portas gravado; porta 1 ligada à sessão', n = 2 and n2 = 1,
                            format('gravadas=%s ligadas=%s', n, n2));

    begin
        perform public.registrar_lote_telemetria(disp, 111, 2, now(), 5000,
            '[{"porta":1,"t_ms":3000,"potencia_w":12.4,"energia_wh":3.1}]'::jsonb);
        res := res || pg_temp.j('c3 telemetria repetida (mesmo seq) rejeitada', false, 'aceitou');
    exception when others then
        res := res || pg_temp.j('c3 telemetria repetida (mesmo seq) rejeitada', sqlerrm = 'replay', sqlerrm);
    end;

    begin
        perform public.registrar_lote_telemetria(disp, 111, 3, now() - interval '5 minutes', 5000,
            '[{"porta":1,"t_ms":3000,"potencia_w":1}]'::jsonb);
        res := res || pg_temp.j('c4 timestamp fora da janela rejeitado', false, 'aceitou');
    exception when others then
        res := res || pg_temp.j('c4 timestamp fora da janela rejeitado', sqlerrm = 'fora_da_janela', sqlerrm);
    end;

    begin
        perform public.consumir_seq(disp, 111, 1, now(), true);
        res := res || pg_temp.j('c5 handshake repetido rejeitado', false, 'aceitou');
    exception when others then
        res := res || pg_temp.j('c5 handshake repetido rejeitado', sqlerrm = 'replay', sqlerrm);
    end;

    perform public.consumir_seq(disp, 222, 1, now(), true);       -- placa reiniciou de verdade
    begin
        perform public.consumir_seq(disp, 111, 50, now(), true);  -- handshake do boot ANTIGO
        res := res || pg_temp.j('c6 handshake de boot antigo rejeitado', false, 'aceitou');
    exception when others then
        res := res || pg_temp.j('c6 handshake de boot antigo rejeitado', sqlerrm = 'replay', sqlerrm);
    end;

    begin
        perform public.registrar_lote_telemetria(disp, 111, 99, now(), 5000,
            '[{"porta":1,"t_ms":3000,"potencia_w":1}]'::jsonb);
        res := res || pg_temp.j('c7 requisição do boot antigo rejeitada', false, 'aceitou');
    exception when others then
        res := res || pg_temp.j('c7 requisição do boot antigo rejeitada', sqlerrm = 'boot_desconhecido', sqlerrm);
    end;

    begin
        perform public.registrar_lote_telemetria(disp, 222, 2, now(), 5000,
            '[{"porta":1,"t_ms":3000,"potencia_w":1},{"porta":7,"t_ms":3000,"potencia_w":1}]'::jsonb);
        res := res || pg_temp.j('c8 porta inexistente derruba o lote inteiro', false, 'aceitou');
    exception when others then
        select seq_atual into n from public.dispositivos where id = disp;
        res := res || pg_temp.j('c8 porta inexistente derruba o lote inteiro',
                                sqlerrm = 'porta_inexistente' and n = 1, format('%s; seq_atual=%s', sqlerrm, n));
    end;

    -- -------------------------------------------------------------------------
    -- (d) CAMINHO v1 INTACTO
    -- -------------------------------------------------------------------------
    select count(*) into n from public.dispositivos d
     where d.protocolo = 1 and d.carregador_id is not null
       and not exists (select 1 from public.portas_dispositivo p
                       where p.dispositivo_id = d.id and p.numero = 1 and p.carregador_id = d.carregador_id);
    res := res || pg_temp.j('d1 toda placa v1 existente ganhou a porta 1 (backfill)', n = 0,
                            format('%s sem porta', n));

    -- Mesmos INSERTs que o hardware_api.py v1 faz hoje: sem coluna porta.
    insert into public.dispositivos (nome, token_hash) values ('Teste15 placa v1', 'hash-v1b-' || sufixo)
    returning id into disp_v1;
    update public.portas_dispositivo set dispositivo_id = disp_v1 where dispositivo_id = disp and numero = 2;
    insert into public.comandos_dispositivo (dispositivo_id, acao, status) values (disp_v1, 'ping', 'pendente');
    insert into public.leituras_hardware (dispositivo_id, potencia_w, energia_wh, rele_ligado)
    values (disp_v1, 5, 1, true);
    select (select porta from public.comandos_dispositivo where dispositivo_id = disp_v1)
         + (select porta from public.leituras_hardware where dispositivo_id = disp_v1)
      into n;
    select protocolo = 1 and token_hash is not null into b from public.dispositivos where id = disp_v1;
    res := res || pg_temp.j('d2 comando e leitura v1 caem na porta 1; token v1 mantido', n = 2 and b,
                            format('soma das portas=%s', n));

    -- -------------------------------------------------------------------------
    -- (e) GRANTS
    -- -------------------------------------------------------------------------
    select count(*), string_agg(p.oid::regprocedure::text, ', ') into n, txt
      from pg_proc p join pg_namespace ns on ns.oid = p.pronamespace
     where ns.nspname = 'public'
       and not exists (select 1 from pg_depend d where d.objid = p.oid and d.deptype = 'e')
       and (has_function_privilege('anon', p.oid, 'execute')
            or has_function_privilege('authenticated', p.oid, 'execute'));
    res := res || pg_temp.j('e1 nenhuma função de public chamável pelo navegador', n = 0, txt);

    select count(*), string_agg(c.relname, ', ') into n, txt
      from pg_class c join pg_namespace ns on ns.oid = c.relnamespace
     where ns.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity;
    res := res || pg_temp.j('e2 RLS ligado em todas as tabelas', n = 0, txt);

    select string_agg(c.relname, ', ' order by c.relname) into txt
      from pg_class c join pg_namespace ns on ns.oid = c.relnamespace
     where ns.nspname = 'public' and c.relkind in ('r', 'v')
       and has_table_privilege('authenticated', c.oid, 'select');
    res := res || pg_temp.j('e3 authenticated lê exatamente o previsto',
        txt = 'carregadores, condominios, leituras_hardware, movimentacoes_carteira, notificacoes, '
              'pagamentos, sessoes_recarga, v_fila_local, v_sessoes_local, veiculos', txt);

    select string_agg(c.relname, ', ') into txt
      from pg_class c join pg_namespace ns on ns.oid = c.relnamespace
     where ns.nspname = 'public' and c.relkind in ('r', 'v')
       and has_table_privilege('anon', c.oid, 'select');
    res := res || pg_temp.j('e4 anon lê só condominios', txt = 'condominios', txt);

    select string_agg(c.relname || '.' || pr, ', ') into txt
      from pg_class c join pg_namespace ns on ns.oid = c.relnamespace
      cross join unnest(array['insert', 'update', 'delete']) pr
     where ns.nspname = 'public' and c.relkind = 'r'
       and has_table_privilege('authenticated', c.oid, pr);
    res := res || pg_temp.j('e5 authenticated não escreve em nada (exceto marcar lida)', txt is null, txt);

    raise exception 'desfazer_teste_15';
    exception when others then
        if sqlerrm <> 'desfazer_teste_15' then
            res := res || pg_temp.j('ERRO INESPERADO - roteiro interrompido', false, sqlerrm);
        end if;
    end;   -- ===== tudo acima foi desfeito =====

    return query select x.teste, x.ok, x.detalhe
                 from jsonb_to_recordset(res) as x(teste text, ok boolean, detalhe text);
end $$;

select * from pg_temp.verificar_15();
