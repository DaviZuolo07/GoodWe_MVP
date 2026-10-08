-- ============================================================================
-- 98_reset_total.sql  -  APAGA TODAS AS CONTAS E TODO O HISTÓRICO
-- ============================================================================
-- Ferramenta, não migration. Rode no SQL Editor quando quiser o banco como
-- "recém-instalado" para testar tudo do zero (roteiro em docs/RODAR_E_VALIDAR.md).
--
-- APAGA
--   - TODAS as contas: moradores, visitantes, gestores, síndicos do seed e o
--     admin global. O CASCADE leva junto senhas (credenciais_usuario),
--     veículos, cartões PESSOAIS, favoritos, segundo fator (gestor_mfa) e
--     admins_globais.
--   - Todo o histórico: recargas, fila, pagamentos, extrato, notificações,
--     chat, chamados, consumo por hora, eventos de demanda e de segurança,
--     auditoria do painel, leituras e comandos do ESP32, boots, solar gravado.
--
-- MANTÉM
--   condomínios (com coordenadas e política de ociosidade), carregadores,
--   dispositivos e portas (token v1 e chave v2 das placas seguem valendo) e
--   cartões DO CONDOMÍNIO (usuario_id nulo).
--
-- SESSÃO QUE NÃO FECHA: o login é JWT próprio, guardado só na memória da
-- aba. Toda rota confere se a conta ainda existe, então apagar a conta
-- derruba qualquer token dela na chamada seguinte (401). A recarga presa é
-- apagada aqui e o ponto volta a 'disponivel'.
--
-- NÃO há desfazer. Se quiser guardar algo, exporte antes
-- (Table Editor -> tabela -> Export to CSV).
--
-- DEPOIS DE RODAR (de dentro de backend/):
--   1. reinicie as duas APIs (limitadores de tentativa vivem na memória)
--   2. python provisionar.py admin-global --nome "Davi Admin"
--   3. python provisionar.py gestor-mfa  --nome "Davi Admin"
--   4. crie as contas de teste pelo próprio app (cadastro)
-- ============================================================================

-- PASSO 0 (opcional, rodar separado): o que vai sumir
--   select tipo_usuario, count(*) from usuarios group by 1;
--   select status, count(*) from sessoes_recarga group by 1;

begin;

-- -----------------------------------------------------------------------------
-- 1. Histórico e logs. Tabela que não existe (migration não rodada) é pulada.
--    A ordem respeita as chaves estrangeiras: quem referencia sai primeiro.
-- -----------------------------------------------------------------------------
do $$
declare
    t text;
begin
    foreach t in array array[
        'comandos_dispositivo', 'leituras_hardware', 'leituras_fonte', 'dispositivo_boots',
        'movimentacoes_carteira', 'pagamentos', 'fila', 'notificacoes', 'chat_mensagens',
        'chamados', 'eventos_demanda', 'eventos_seguranca', 'auditoria_admin',
        'consumo_horario', 'geracao_solar', 'sessoes_recarga'
    ] loop
        if to_regclass('public.' || t) is not null then
            execute format('delete from public.%I', t);
            raise notice 'limpa: %', t;
        else
            raise notice 'não existe (pulada): %', t;
        end if;
    end loop;
end $$;

-- -----------------------------------------------------------------------------
-- 2. Todas as contas (cascade: senhas, veículos, cartões pessoais, favoritos,
--    gestor_mfa, admins_globais)
-- -----------------------------------------------------------------------------
delete from public.usuarios;

-- -----------------------------------------------------------------------------
-- 3. Destravar pontos e placas
-- -----------------------------------------------------------------------------
-- Físico volta a 'offline' até a placa fazer handshake de novo (estado honesto).
update public.carregadores
   set status = case when origem = 'hardware' then 'offline' else 'disponivel' end,
       temperatura_c = 25;
update public.dispositivos set online = false;

commit;

-- =============================================================================
-- CONFERÊNCIA (rodar separado). Tudo zero, exceto a estrutura:
--   select (select count(*) from usuarios)               as contas,
--          (select count(*) from sessoes_recarga)        as recargas,
--          (select count(*) from movimentacoes_carteira) as extrato,
--          (select count(*) from auditoria_admin)        as auditoria,
--          (select count(*) from condominios)            as condominios,
--          (select count(*) from carregadores)           as carregadores;
--   select status, origem, count(*) from carregadores group by 1, 2;
-- =============================================================================
