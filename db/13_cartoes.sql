-- =============================================================
-- 13_cartoes.sql - Cartão RFID compartilhado + limpeza de arestas
-- =============================================================
-- Rodar depois do 12. Idempotente.
--
-- O PROBLEMA QUE ISTO RESOLVE
-- ---------------------------
-- O modelo anterior guardava UM uid por usuário (`usuarios.rfid_uid`, com
-- índice único). Isso implica um cartão físico POR MORADOR. Na bancada de
-- demonstração existe UM cartão só: com o modelo antigo, o primeiro que
-- vinculasse travava o cartão para si e ninguém mais conseguia usar.
--
-- O MODELO NOVO: dois tipos de cartão
--   'pessoal'        pertence a um morador. Só autoriza a recarga DELE.
--                    É o modelo de produção, onde cada um tem o seu.
--   'compartilhado'  pertence ao CONDOMÍNIO, não a uma pessoa. Não identifica
--                    ninguém: serve como prova de PRESENÇA no ponto. Autoriza
--                    a recarga que está preparada ali, seja de quem for - e
--                    cobra de quem preparou, que é quem está logado no app.
--
-- Ou seja: Joaquim prepara no app e encosta o cartão -> debita do Joaquim.
-- Marcos prepara no app e encosta O MESMO cartão -> debita do Marcos. A placa
-- não sabe, não guarda e não precisa saber quem é qualquer um dos dois.
--
-- O QUE SE PERDE, DITO CLARAMENTE
-- -------------------------------
-- Cartão compartilhado prova presença, não identidade. Quem estiver com ele
-- na mão pode confirmar a recarga que estiver preparada naquele ponto. Como a
-- recarga só existe depois que alguém logado a preparou, e a cobrança é de
-- quem preparou, o estrago possível é "começar a recarga que o vizinho já
-- pediu" - não "carregar no nome do vizinho". Para exigir identidade de
-- verdade, basta o morador cadastrar um cartão pessoal: ele passa a valer
-- para ele, e o compartilhado continua atendendo os demais.
-- =============================================================

begin;

-- -------------------------------------------------------------
-- 1. Tabela de cartões
-- -------------------------------------------------------------
create table if not exists public.cartoes_rfid (
    uid           text primary key,
    escopo        text not null check (escopo in ('pessoal', 'compartilhado')),
    usuario_id    uuid references public.usuarios(id) on delete cascade,
    condominio_id uuid references public.condominios(id) on delete cascade,
    apelido       text,
    ativo         boolean not null default true,
    criado_em     timestamptz not null default now(),
    ultimo_uso    timestamptz,
    -- Pessoal exige dono; compartilhado exige condomínio. Sem meio-termo.
    constraint cartoes_escopo_coerente check (
        (escopo = 'pessoal' and usuario_id is not null) or
        (escopo = 'compartilhado' and condominio_id is not null)
    )
);

create index if not exists idx_cartoes_usuario on public.cartoes_rfid (usuario_id);
create index if not exists idx_cartoes_condominio on public.cartoes_rfid (condominio_id)
    where escopo = 'compartilhado';

-- -------------------------------------------------------------
-- 2. Migra o que já existia e aposenta a coluna antiga
-- -------------------------------------------------------------
do $$
begin
    if exists (select 1 from information_schema.columns
               where table_schema = 'public' and table_name = 'usuarios'
                 and column_name = 'rfid_uid') then

        insert into public.cartoes_rfid (uid, escopo, usuario_id, apelido)
        select upper(u.rfid_uid), 'pessoal', u.id, 'Cartão pessoal'
        from public.usuarios u
        where u.rfid_uid is not null and length(trim(u.rfid_uid)) > 0
        on conflict (uid) do nothing;

        -- Duas fontes para o mesmo fato é como bug nasce. A coluna sai.
        alter table public.usuarios drop column rfid_uid;
    end if;
end $$;

-- -------------------------------------------------------------
-- 3. Último cartão lido na sessão
-- -------------------------------------------------------------
-- Cartão desconhecido encostado numa espera: em vez de só recusar, guardamos
-- o uid na sessão. O app mostra "cartão A1B2C3D4 não cadastrado" com o botão
-- de cadastrar - ninguém precisa abrir o monitor serial para descobrir o uid.
alter table public.sessoes_recarga
    add column if not exists ultimo_uid_lido text;

-- -------------------------------------------------------------
-- 4. Fila sem expor o id dos vizinhos
-- -------------------------------------------------------------
-- A política da fila liberava a linha inteira para qualquer autenticado,
-- inclusive o usuario_id de quem está na frente. O id sozinho não permite
-- agir (toda escrita passa pelo backend com token), mas também não precisa
-- sair do banco. A view devolve só a posição e um "esse sou eu".
create or replace view public.v_fila_local
with (security_invoker = false) as
select
    f.id,
    f.carregador_id,
    f.posicao,
    f.criado_em,
    (f.usuario_id = (select auth.uid())) as eh_meu
from public.fila f;

revoke all    on public.v_fila_local from anon, authenticated;
grant  select on public.v_fila_local to authenticated;

drop policy if exists fila_leitura on public.fila;
-- Sem política de select na tabela: quem lê fila é a view (que roda como dono).

-- -------------------------------------------------------------
-- 5. Privilégios dos cartões
-- -------------------------------------------------------------
alter table public.cartoes_rfid enable row level security;

-- Nenhum GRANT para o navegador, de propósito: a tabela é lida pelo backend
-- (GET /me/cartoes e GET /gestor/cartoes), que já sabe quem está pedindo.
--
-- A tentação era criar uma política "vejo os meus e os compartilhados do meu
-- condomínio". Ela NÃO funcionaria: descobrir o condomínio do morador exige
-- consultar `usuarios`, e o 11_seguranca revogou o SELECT dessa tabela para
-- `authenticated` - a política inteira morreria com "permission denied".
-- Fechada, o uid dos cartões nem chega ao código-fonte da página.
revoke all on public.cartoes_rfid from anon, authenticated;

commit;

-- =============================================================
-- DEPOIS DE RODAR
-- =============================================================
-- Cadastrar o cartão da bancada como compartilhado (de dentro de backend/):
--   python provisionar.py cartao-compartilhado \
--     --uid A1B2C3D4 --condominio c0000000-0000-0000-0000-000000000002
--
-- Não sabe o uid? Encoste o cartão com uma recarga preparada: o app mostra o
-- uid na tela de "aproxime o cartão", com o botão para cadastrar.
--
-- Conferência:
--   select uid, escopo, apelido, ativo from cartoes_rfid;
