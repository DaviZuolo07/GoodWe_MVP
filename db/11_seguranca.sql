-- =============================================================
-- 11_seguranca.sql - Banco privado + identidade real
-- =============================================================
-- Rodar no SQL Editor DEPOIS do 10, uma vez só. É idempotente: rodar de
-- novo não duplica nada.
--
-- O QUE MUDA
--   1. Senhas em tabela própria, que nenhum cliente consegue ler.
--   2. Token do ESP32 guardado como hash; o texto puro some do banco.
--   3. RLS ligado em TODAS as tabelas (inclusive as que ninguém lembrou).
--   4. Duas camadas: privilégio (GRANT/REVOKE) e linha (RLS). Uma falha na
--      política não abre a tabela se o privilégio já estava fechado.
--   5. Políticas mínimas para o que o frontend realmente lê.
--   6. View que mostra recargas dos vizinhos SEM custo, placa ou identidade.
--
-- QUEM IGNORA TUDO ISSO: o backend, que usa a service_role. As regras de
-- negócio continuam no backend; o RLS protege o caminho navegador -> banco.
-- =============================================================

begin;

-- -------------------------------------------------------------
-- 1. CREDENCIAIS
-- -------------------------------------------------------------
-- Separada de `usuarios` de propósito. Se um dia alguém liberar leitura em
-- `usuarios` para mostrar nome na fila, o hash não vai junto.
create table if not exists public.credenciais_usuario (
    usuario_id    uuid primary key references public.usuarios(id) on delete cascade,
    senha_hash    text not null,                  -- $argon2id$...
    atualizado_em timestamptz not null default now()
);

-- -------------------------------------------------------------
-- 2. TOKEN DO DISPOSITIVO: texto puro -> hash
-- -------------------------------------------------------------
-- Depois deste bloco o ESP32 fica sem autenticar até rodar:
--   python provisionar.py token-esp --carregador <uuid>
-- É intencional: o token antigo estava escrito no 09 e no repositório.
alter table public.dispositivos add column if not exists token_hash text;
alter table public.dispositivos drop column if exists token;   -- leva o índice junto
create unique index if not exists idx_dispositivos_token_hash
    on public.dispositivos (token_hash);

-- -------------------------------------------------------------
-- 3. RLS EM TODAS AS TABELAS DE public
-- -------------------------------------------------------------
-- Laço em vez de lista: pega também tabela criada por alguém numa migration
-- que não está neste arquivo. Sem política, RLS ligado = ninguém lê.
do $$
declare t record;
begin
    for t in select tablename from pg_tables where schemaname = 'public' loop
        execute format('alter table public.%I enable row level security', t.tablename);
    end loop;
end $$;

-- -------------------------------------------------------------
-- 4. PRIVILÉGIOS - a camada de baixo
-- -------------------------------------------------------------
-- Navegador nunca escreve direto (exceto marcar notificação como lida).
revoke insert, update, delete, truncate, references, trigger
    on all tables in schema public from anon, authenticated;

-- Visitante sem login: só o catálogo de condomínios da tela de cadastro.
revoke select on all tables in schema public from anon;
grant  select on public.condominios to anon;

-- Tabelas que só o backend toca. Sem SELECT, nem uma política errada abre.
revoke select on
    public.usuarios,
    public.credenciais_usuario,
    public.dispositivos,
    public.comandos_dispositivo,
    public.chat_mensagens,
    public.condominios_favoritos
from authenticated;

-- A única escrita do frontend: a coluna `lida`, e nenhuma outra.
grant update (lida) on public.notificacoes to authenticated;

-- Tabela nova criada no SQL Editor nasce fechada para os clientes. Quem
-- criar precisa dar GRANT explícito - esquecer vira "não aparece", nunca
-- "vazou".
alter default privileges in schema public
    revoke all on tables from anon, authenticated;

-- -------------------------------------------------------------
-- 5. POLÍTICAS - a camada de cima
-- -------------------------------------------------------------
-- `(select auth.uid())` e não `auth.uid()`: o Postgres avalia uma vez por
-- consulta em vez de uma vez por linha (recomendação do Supabase).

-- Catálogo: nome e endereço de condomínio não são dado pessoal.
drop policy if exists condominios_leitura on public.condominios;
create policy condominios_leitura on public.condominios
    for select to anon, authenticated using (true);

-- Carregadores: status, potência e tarifa são informação de serviço, como
-- um mapa de eletropostos. Qualquer morador logado vê.
drop policy if exists carregadores_leitura on public.carregadores;
create policy carregadores_leitura on public.carregadores
    for select to authenticated using (true);

drop policy if exists veiculos_proprios on public.veiculos;
create policy veiculos_proprios on public.veiculos
    for select to authenticated
    using (usuario_id = (select auth.uid()));

-- Sessão completa (custo, veículo) só do dono. Vizinhos: ver a view abaixo.
drop policy if exists sessoes_proprias on public.sessoes_recarga;
create policy sessoes_proprias on public.sessoes_recarga
    for select to authenticated
    using (usuario_id = (select auth.uid()));

-- `pagamentos` não tem usuario_id: o dono é quem é dono da sessão.
drop policy if exists pagamentos_proprios on public.pagamentos;
create policy pagamentos_proprios on public.pagamentos
    for select to authenticated
    using (exists (
        select 1 from public.sessoes_recarga s
        where s.id = pagamentos.sessao_id
          and s.usuario_id = (select auth.uid())
    ));

drop policy if exists notificacoes_leitura on public.notificacoes;
create policy notificacoes_leitura on public.notificacoes
    for select to authenticated
    using (usuario_id = (select auth.uid()));

-- `with check` impede mudar o dono da linha; o GRANT acima já limita a
-- coluna. As duas juntas: só dá para marcar como lida a própria notificação.
drop policy if exists notificacoes_marcar_lida on public.notificacoes;
create policy notificacoes_marcar_lida on public.notificacoes
    for update to authenticated
    using (usuario_id = (select auth.uid()))
    with check (usuario_id = (select auth.uid()));

-- Fila: posição e carregador. O usuario_id é um identificador opaco e deixa
-- de ser explorável no Bloco 2, quando nenhum endpoint aceita mais
-- usuario_id vindo do cliente. O NOME não sai daqui: `usuarios` é fechada.
drop policy if exists fila_leitura on public.fila;
create policy fila_leitura on public.fila
    for select to authenticated using (true);

-- Leituras do medidor: só as da própria recarga (base do gráfico ao vivo).
drop policy if exists leituras_da_propria_sessao on public.leituras_hardware;
create policy leituras_da_propria_sessao on public.leituras_hardware
    for select to authenticated
    using (exists (
        select 1 from public.sessoes_recarga s
        where s.id = leituras_hardware.sessao_id
          and s.usuario_id = (select auth.uid())
    ));

-- -------------------------------------------------------------
-- 6. VIEW: recargas do local, com o que é privado mascarado
-- -------------------------------------------------------------
-- O dashboard precisa saber que o ponto 03 está em 64% e libera em 40 min,
-- mesmo quando a recarga é do vizinho. Não precisa saber quem é, quanto ele
-- paga, nem a placa dele.
--
-- A view roda com o privilégio do dono (security_invoker = false) para
-- enxergar as sessões dos outros - e por isso escolhe coluna por coluna o
-- que sai. O painel do Supabase vai marcar como "security definer view":
-- aqui é a decisão de projeto, não um descuido.
--
-- Os campos privados voltam preenchidos quando a sessão é de quem pergunta,
-- então `sessao.usuario_id === meuId` no frontend continua funcionando.
create or replace view public.v_sessoes_local
with (security_invoker = false) as
select
    s.id,
    s.carregador_id,
    s.status,
    s.origem,
    s.potencia_atual_kw,
    s.energia_entregue_kwh,
    s.percentual_bateria_inicial,
    s.percentual_bateria_atual,
    s.alvo_percentual,
    s.tempo_estimado_min,
    s.iniciado_em,
    v.modelo as veiculo_modelo,
    case when s.usuario_id = (select auth.uid()) then s.usuario_id     end as usuario_id,
    case when s.usuario_id = (select auth.uid()) then s.veiculo_id     end as veiculo_id,
    case when s.usuario_id = (select auth.uid()) then v.placa          end as veiculo_placa,
    case when s.usuario_id = (select auth.uid()) then s.custo_estimado end as custo_estimado,
    case when s.usuario_id = (select auth.uid()) then s.custo_final    end as custo_final
from public.sessoes_recarga s
left join public.veiculos v on v.id = s.veiculo_id
where s.status = 'carregando'
   or s.iniciado_em >= now() - interval '1 day';

revoke all    on public.v_sessoes_local from anon, authenticated;
grant  select on public.v_sessoes_local to authenticated;

commit;

-- =============================================================
-- CONFERÊNCIA RÁPIDA (rodar cada bloco separado no SQL Editor)
-- =============================================================
-- RLS ligado em tudo? Deve voltar zero linhas:
--   select tablename from pg_tables
--   where schemaname = 'public' and not rowsecurity;
--
-- Simulando o visitante sem login. Deve dar "permission denied":
--   begin;
--   set local role anon;
--   select * from usuarios limit 1;
--   rollback;
--
-- Simulando um morador logado (troque o uuid). Deve ver só as dele:
--   begin;
--   set local role authenticated;
--   select set_config('request.jwt.claims',
--          '{"sub":"<uuid-do-morador>","role":"authenticated"}', true);
--   select usuario_id, count(*) from notificacoes group by 1;
--   rollback;
