-- ============================================================================
-- 22_cargo_next.sql  -  cargo "NEXT" para quem se cadastra no Estande Next
-- ============================================================================
-- Rodar no SQL Editor DEPOIS do 21, uma vez. É idempotente.
--
-- O Estande Next (condomínio de perfil 'bancada', db/19) não tem morador nem
-- visitante: é um ponto de feira. Quem se cadastra nele ganha o cargo 'next'.
--
-- A REGRA MORA NO BANCO (não só na tela):
--   local 'bancada'      -> o cargo é SEMPRE 'next', venha o que vier do app
--   local 'residencial'  -> só 'morador' ou 'visitante'; 'next' é recusado
-- Gestor continua nascendo só pelo provisionar.py.
-- ============================================================================

begin;

alter table public.usuarios drop constraint if exists usuarios_tipo_check;
alter table public.usuarios add constraint usuarios_tipo_check
    check (tipo_usuario in ('morador', 'visitante', 'gestor', 'next'));

-- Quem já estava cadastrado no estande como morador/visitante vira 'next'.
update public.usuarios u
   set tipo_usuario = 'next'
  from public.condominios c
 where c.id = u.condominio_id and c.perfil = 'bancada'
   and u.tipo_usuario in ('morador', 'visitante');

-- Mesma função do db/15, com o cargo decidido pelo perfil do local.
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
    v_perfil text;
    v_tipo text;
begin
    if p_senha_hash is null or p_senha_hash not like '$argon2%' then raise exception 'hash_invalido'; end if;
    if p_bonus < 0 then raise exception 'valor_negativo'; end if;
    select perfil into v_perfil from condominios where id = p_condominio;
    if not found then
        raise exception 'condominio_invalido';
    end if;
    if v_perfil = 'bancada' then
        v_tipo := 'next';
    elsif p_tipo in ('morador', 'visitante') then
        v_tipo := p_tipo;
    else
        raise exception 'tipo_invalido';
    end if;
    if p_veiculo is null or coalesce(trim(p_veiculo->>'modelo'), '') = '' then
        raise exception 'veiculo_invalido';
    end if;
    if exists (select 1 from usuarios where lower(nome) = lower(trim(p_nome))) then
        raise exception 'nome_em_uso';
    end if;

    begin
        insert into usuarios (nome, tipo_usuario, condominio_id, bloco_apto)
        values (trim(p_nome), v_tipo, p_condominio,
                case when v_perfil = 'bancada' then null else p_bloco end)
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

commit;

-- =============================================================================
-- CONFERÊNCIA (rodar separado)
--   select c.nome, c.perfil, u.tipo_usuario, count(*) from usuarios u
--     join condominios c on c.id = u.condominio_id group by 1, 2, 3 order by 1;
--   -- nenhuma linha 'bancada' com morador/visitante, nenhuma 'residencial' com next
-- =============================================================================
