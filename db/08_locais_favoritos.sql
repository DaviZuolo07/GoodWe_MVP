-- =============================================================
-- GoodWe ChargeOps AI Assistant - Locais favoritos
-- =============================================================
-- Rodar DEPOIS do 07_multi_condominio.sql.
--
-- Por que uma tabela nova
-- -----------------------
-- `usuarios.condominio_id` guarda UM local: onde a pessoa mora. Isso não
-- resolve o caso real — alguém mora no Portal dos Bandeirantes, trabalha
-- perto do Parque das Nações e carrega nos dois. É uma relação N:N, e
-- relação N:N não cabe em coluna.
--
-- Esta tabela é também a ALLOWLIST de segurança do assistente. A partir do
-- momento em que o frontend passa a mandar qual local o usuário escolheu, o
-- backend precisa de uma lista fechada contra a qual validar — senão bastaria
-- mandar um UUID qualquer para ler carregadores, tarifas e fila de um
-- condomínio onde a pessoa não tem nenhum vínculo.
--
-- Regra: um usuário só enxerga locais que ele favoritou, mais o próprio
-- condomínio de moradia (que é favorito implícito e não pode ser removido).
-- =============================================================

create table if not exists condominios_favoritos (
    id           uuid primary key default gen_random_uuid(),
    usuario_id   uuid not null references usuarios(id)     on delete cascade,
    condominio_id uuid not null references condominios(id) on delete cascade,
    criado_em    timestamptz not null default now(),

    -- Favoritar duas vezes o mesmo lugar não faz sentido: o par é único.
    -- É isso que deixa o POST ser idempotente lá no backend.
    unique (usuario_id, condominio_id)
);

-- O acesso mais frequente é "os favoritos DESTE usuário", então o índice
-- acompanha essa consulta.
create index if not exists idx_favoritos_usuario
    on condominios_favoritos (usuario_id);

alter table condominios_favoritos disable row level security;

-- -------------------------------------------------------------
-- Seed: todo usuário já começa com o próprio condomínio favoritado.
-- -------------------------------------------------------------
-- Sem isso, o seletor do chat abriria vazio no primeiro acesso — e num vídeo
-- de 3 minutos não existe "primeiro acesso", existe a tela funcionando.
insert into condominios_favoritos (usuario_id, condominio_id)
select u.id, u.condominio_id
from usuarios u
where u.condominio_id is not null
on conflict (usuario_id, condominio_id) do nothing;

-- -------------------------------------------------------------
-- Seed de demonstração: dá um segundo local a quem mora no Portal dos
-- Bandeirantes, para o seletor abrir com mais de uma opção na gravação.
-- Remova este bloco se preferir que cada conta comece com um só.
-- -------------------------------------------------------------
insert into condominios_favoritos (usuario_id, condominio_id)
select u.id, 'c0000000-0000-0000-0000-000000000003'
from usuarios u
where u.condominio_id = 'c0000000-0000-0000-0000-000000000002'
on conflict (usuario_id, condominio_id) do nothing;

-- -------------------------------------------------------------
-- Conferência
-- -------------------------------------------------------------
-- select u.nome as usuario, c.nome as local_favorito
-- from condominios_favoritos f
-- join usuarios u     on u.id = f.usuario_id
-- join condominios c  on c.id = f.condominio_id
-- order by u.nome, c.nome;
