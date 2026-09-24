-- =============================================================
-- 99_limpeza.sql - Zera a operação, mantém a estrutura
-- =============================================================
-- Mesmo efeito de `python provisionar.py limpar --sim`, para quando for mais
-- fácil rodar no SQL Editor do Supabase.
--
-- APAGA: recargas, fila, pagamentos, extrato da carteira, notificações,
--        leituras do ESP32, comandos, histórico do chat, consumo por hora.
-- MANTÉM: condomínios, carregadores, dispositivos (o token da placa segue
--         valendo), cartões cadastrados e as contas das migrations.
--
-- Este arquivo NÃO faz parte da sequência 01->13. É uma ferramenta: rode
-- quando quiser voltar ao estado "recém-instalado" para testar ou gravar.
-- =============================================================

begin;

-- -------------------------------------------------------------
-- 1. O que aconteceu (histórico e operação)
-- -------------------------------------------------------------
delete from public.comandos_dispositivo;
delete from public.leituras_hardware;
delete from public.movimentacoes_carteira;
delete from public.pagamentos;
delete from public.fila;
delete from public.notificacoes;
delete from public.chat_mensagens;
delete from public.sessoes_recarga;      -- por último: as outras referenciam
delete from public.consumo_horario;

-- -------------------------------------------------------------
-- 2. Destravar os carregadores
-- -------------------------------------------------------------
-- Ponto que ficou 'em_uso' por causa de uma sessão que não existe mais.
-- O físico volta para 'offline' até a placa fazer handshake de novo - é o
-- estado honesto: sem placa falando, não há ponto disponível.
update public.carregadores
set status = case when origem = 'hardware' then 'offline' else 'disponivel' end,
    temperatura_c = 25;

update public.dispositivos set online = false;

-- -------------------------------------------------------------
-- 3. Cadastros de teste (OPCIONAL - descomente para apagar)
-- -------------------------------------------------------------
-- Remove qualquer conta que não venha das migrations. O CASCADE leva junto
-- veículos, credenciais, cartões pessoais e favoritos dessas contas.
--
-- Confira ANTES quem vai sumir:
--     select id, nome, tipo_usuario from usuarios
--     where id not in (
--         '22222222-2222-2222-2222-222222222222',   -- Davi Zuolo
--         'e0000000-0000-0000-0000-000000000001',   -- Sindico Portal
--         'e0000000-0000-0000-0000-000000000002',   -- Sindico FIAP
--         'e0000000-0000-0000-0000-000000000003'    -- Gus Bancada
--     );
--
-- delete from public.usuarios
-- where id not in (
--     '22222222-2222-2222-2222-222222222222',
--     'e0000000-0000-0000-0000-000000000001',
--     'e0000000-0000-0000-0000-000000000002',
--     'e0000000-0000-0000-0000-000000000003'
-- );

-- -------------------------------------------------------------
-- 4. Saldo (OPCIONAL)
-- -------------------------------------------------------------
-- Gus Bancada precisa começar com ZERO para a demonstração do cartão
-- recusado por saldo funcionar.
update public.usuarios set saldo = 0
where id = 'e0000000-0000-0000-0000-000000000003';

-- update public.usuarios set saldo = 0;   -- todas as contas

commit;

-- =============================================================
-- CONFERÊNCIA
-- =============================================================
-- select status, count(*) from carregadores group by status;
-- select count(*) from sessoes_recarga;
-- select nome, tipo_usuario, saldo from usuarios order by nome;
-- select uid, escopo, apelido from cartoes_rfid;
