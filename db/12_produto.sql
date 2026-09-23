-- =============================================================
-- 12_produto.sql - Blocos 2 a 5: identidade, demanda, cobrança,
--                  auditoria do chat e fluxo do ESP32
-- =============================================================
-- Rodar no SQL Editor DEPOIS do 11_seguranca.sql, uma vez só.
-- É idempotente: rodar de novo não duplica nada nem quebra nada.
--
-- O QUE ENTRA
--   1. Condomínio: limite de POTÊNCIA (kW), horário de ponta e tarifa de ponta
--   2. Carregador: perfil (veicular | bancada) - o ponto do ESP32 vira bancada USB
--   3. Veículo: tipo (carro | celular) - o celular de ~15 Wh do Gus
--   4. Sessão: potência alocada, energia em ponta, pré-autorização, estorno,
--      motivo de encerramento, potência média medida, tentativas de cartão
--   5. Carteira: extrato (livro-razão) + funções ATÔMICAS de débito e crédito
--   6. Consumo por hora do condomínio (curva de carga do painel do gestor)
--   7. Fila de comandos do ESP32 com payload (solicitar_cartao, cancelar_cartao)
--   8. Auditoria do chatbot em colunas (camada, intenção, modelo, latência)
--   9. Gestores (síndicos) e usuário de bancada para a demonstração
--  10. View do painel refeita e Realtime nas tabelas novas
-- =============================================================

begin;

-- -------------------------------------------------------------
-- 1. CONDOMÍNIO: potência, não energia
-- -------------------------------------------------------------
-- A coluna sempre guardou kW (potência), mas se chamava "energia". Com a
-- gestão de demanda ela vira o número central do sistema, então o nome
-- precisa dizer a verdade.
do $$
begin
    if exists (select 1 from information_schema.columns
               where table_schema = 'public' and table_name = 'condominios'
                 and column_name = 'limite_energia_kw') then
        alter table public.condominios rename column limite_energia_kw to limite_potencia_kw;
    end if;
end $$;

alter table public.condominios
    add column if not exists limite_potencia_kw numeric not null default 80;

-- Horário de ponta (tarifa branca da distribuidora): dias úteis, 18h às 21h.
-- Dentro dele o condomínio libera só uma FRAÇÃO do limite para recarga e a
-- energia custa mais. É o que faz o morador preferir carregar fora da ponta.
alter table public.condominios
    add column if not exists ponta_inicio time not null default '18:00',
    add column if not exists ponta_fim time not null default '21:00',
    add column if not exists ponta_fator_limite numeric not null default 0.6,
    add column if not exists ponta_multiplicador_tarifa numeric not null default 1.5;

alter table public.condominios drop constraint if exists condominios_ponta_fator_check;
alter table public.condominios add constraint condominios_ponta_fator_check
    check (ponta_fator_limite > 0 and ponta_fator_limite <= 1);
alter table public.condominios drop constraint if exists condominios_ponta_mult_check;
alter table public.condominios add constraint condominios_ponta_mult_check
    check (ponta_multiplicador_tarifa >= 1 and ponta_multiplicador_tarifa <= 5);
alter table public.condominios drop constraint if exists condominios_limite_check;
alter table public.condominios add constraint condominios_limite_check
    check (limite_potencia_kw > 0);

-- -------------------------------------------------------------
-- 2. CARREGADOR: perfil
-- -------------------------------------------------------------
-- 'veicular' = wallbox de verdade (simulado). 'bancada' = o ESP32 do Gus,
-- que liga uma porta USB de celular. Um carro de 40 kWh numa porta de 25 W
-- levaria dias, então o backend não deixa misturar.
alter table public.carregadores
    add column if not exists perfil text not null default 'veicular';
alter table public.carregadores drop constraint if exists carregadores_perfil_check;
alter table public.carregadores add constraint carregadores_perfil_check
    check (perfil in ('veicular', 'bancada'));

-- O ponto 01 do Portal dos Bandeirantes é o do ESP32 (ver 09_hardware_esp32).
update public.carregadores
set perfil = 'bancada',
    modelo = 'Bancada USB · ESP32',
    tipo = 'DC',
    potencia_maxima_kw = 0.025,     -- 25 W: carregador de celular
    conector = 'USB',
    tensao_v = 5,
    corrente_maxima_a = 3
where id = 'b0000000-0000-0000-0000-000000000001';

-- -------------------------------------------------------------
-- 3. VEÍCULO: tipo
-- -------------------------------------------------------------
alter table public.veiculos
    add column if not exists tipo text not null default 'carro';
alter table public.veiculos drop constraint if exists veiculos_tipo_check;
alter table public.veiculos add constraint veiculos_tipo_check
    check (tipo in ('carro', 'celular'));

-- -------------------------------------------------------------
-- 4. SESSÃO DE RECARGA
-- -------------------------------------------------------------
alter table public.sessoes_recarga
    -- quanto o alocador liberou para esta sessão agora (kW)
    add column if not exists potencia_alocada_kw numeric,
    -- média móvel da potência MEDIDA (base da previsão de término no ESP32)
    add column if not exists potencia_media_kw numeric,
    -- parte da energia que caiu no horário de ponta (cobrada com multiplicador)
    add column if not exists energia_ponta_kwh numeric not null default 0,
    -- tarifa base congelada no início: mudar a tabela depois não muda a conta
    add column if not exists tarifa_kwh numeric,
    add column if not exists multiplicador_ponta numeric,
    -- cobrança: quanto foi reservado no cartão e quanto voltou no fim
    add column if not exists valor_pre_autorizado numeric,
    add column if not exists valor_estornado numeric,
    -- quem ou o que encerrou (usuario | alvo_atingido | dispositivo_carregado |
    -- limite_pre_autorizado | bateria_cheia | dispositivo_offline | sistema)
    add column if not exists encerrado_por text,
    -- cartão com saldo insuficiente não mata a espera: o morador põe saldo e
    -- aproxima de novo. Este contador impede tentativa infinita.
    add column if not exists tentativas_cartao integer not null default 0,
    -- desde quando o celular praticamente parou de puxar corrente
    add column if not exists baixa_potencia_desde timestamptz;

-- -------------------------------------------------------------
-- 5. CARTEIRA: extrato + operações atômicas
-- -------------------------------------------------------------
-- Antes o backend fazia "lê saldo -> subtrai -> grava". Duas requisições ao
-- mesmo tempo liam o mesmo saldo e uma das duas cobranças sumia. Agora a
-- conta acontece DENTRO do Postgres, numa instrução só, com a trava
-- "saldo >= valor" na própria cláusula WHERE.
create table if not exists public.movimentacoes_carteira (
    id          uuid primary key default gen_random_uuid(),
    usuario_id  uuid not null references public.usuarios(id) on delete cascade,
    sessao_id   uuid references public.sessoes_recarga(id) on delete set null,
    -- credito | pre_autorizacao | estorno | ajuste
    tipo        text not null check (tipo in ('credito', 'pre_autorizacao', 'estorno', 'ajuste')),
    valor       numeric not null check (valor >= 0),
    saldo_apos  numeric not null,
    descricao   text,
    criado_em   timestamptz not null default now()
);
create index if not exists idx_mov_usuario on public.movimentacoes_carteira (usuario_id, criado_em desc);

create or replace function public.debitar_saldo(
    p_usuario uuid, p_valor numeric, p_tipo text, p_descricao text, p_sessao uuid default null
) returns numeric
language plpgsql
set search_path = public
as $$
declare novo numeric;
begin
    if p_valor < 0 then raise exception 'valor_negativo'; end if;
    update usuarios set saldo = round(saldo - p_valor, 2)
    where id = p_usuario and saldo >= p_valor
    returning saldo into novo;
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
    update usuarios set saldo = round(saldo + p_valor, 2)
    where id = p_usuario
    returning saldo into novo;
    if novo is null then raise exception 'usuario_inexistente'; end if;
    insert into movimentacoes_carteira (usuario_id, sessao_id, tipo, valor, saldo_apos, descricao)
    values (p_usuario, p_sessao, p_tipo, p_valor, novo, p_descricao);
    return novo;
end $$;

-- Só o backend (service_role) executa. Um morador chamando o RPC direto pelo
-- navegador para se dar crédito é exatamente o que isto impede.
revoke all on function public.debitar_saldo(uuid, numeric, text, text, uuid) from public, anon, authenticated;
revoke all on function public.creditar_saldo(uuid, numeric, text, text, uuid) from public, anon, authenticated;
grant execute on function public.debitar_saldo(uuid, numeric, text, text, uuid) to service_role;
grant execute on function public.creditar_saldo(uuid, numeric, text, text, uuid) to service_role;

-- -------------------------------------------------------------
-- 6. CONSUMO POR HORA - a curva de carga do condomínio
-- -------------------------------------------------------------
create table if not exists public.consumo_horario (
    condominio_id     uuid not null references public.condominios(id) on delete cascade,
    hora              timestamptz not null,       -- truncada na hora cheia
    energia_kwh       numeric not null default 0,
    energia_ponta_kwh numeric not null default 0,
    pico_kw           numeric not null default 0, -- maior carga vista na hora
    primary key (condominio_id, hora)
);

create or replace function public.registrar_consumo(
    p_cond uuid, p_kwh numeric, p_ponta boolean, p_carga_kw numeric
) returns void
language sql
set search_path = public
as $$
    insert into consumo_horario (condominio_id, hora, energia_kwh, energia_ponta_kwh, pico_kw)
    values (p_cond, date_trunc('hour', now()), greatest(p_kwh, 0),
            case when p_ponta then greatest(p_kwh, 0) else 0 end, greatest(p_carga_kw, 0))
    on conflict (condominio_id, hora) do update set
        energia_kwh       = consumo_horario.energia_kwh + excluded.energia_kwh,
        energia_ponta_kwh = consumo_horario.energia_ponta_kwh + excluded.energia_ponta_kwh,
        pico_kw           = greatest(consumo_horario.pico_kw, excluded.pico_kw);
$$;
revoke all on function public.registrar_consumo(uuid, numeric, boolean, numeric) from public, anon, authenticated;
grant execute on function public.registrar_consumo(uuid, numeric, boolean, numeric) to service_role;

-- -------------------------------------------------------------
-- 7. COMANDOS DO ESP32: payload e ações novas
-- -------------------------------------------------------------
alter table public.comandos_dispositivo add column if not exists payload jsonb;

alter table public.comandos_dispositivo drop constraint if exists comandos_dispositivo_acao_check;
alter table public.comandos_dispositivo add constraint comandos_dispositivo_acao_check
    check (acao in ('liberar', 'bloquear', 'ping', 'solicitar_cartao', 'cancelar_cartao'));

-- 'descartado': o comando perdeu o sentido antes de ser entregue (a sessão
-- expirou enquanto a placa estava fora do ar). Entregar um "aproxime o
-- cartão" de 10 minutos atrás confundiria quem está na frente do leitor.
alter table public.comandos_dispositivo drop constraint if exists comandos_dispositivo_status_check;
alter table public.comandos_dispositivo add constraint comandos_dispositivo_status_check
    check (status in ('pendente', 'entregue', 'confirmado', 'falhou', 'descartado'));

-- A placa do celular precisa de telemetria mais frequente que um carro.
update public.dispositivos set intervalo_telemetria_s = 2, intervalo_comandos_s = 2;

-- -------------------------------------------------------------
-- 8. AUDITORIA DO CHATBOT
-- -------------------------------------------------------------
alter table public.chat_mensagens
    add column if not exists intencao    text,
    add column if not exists camada      text,     -- entrada | contexto | redacao | saida
    add column if not exists bloqueado   boolean not null default false,
    add column if not exists motivo      text,
    add column if not exists modelo      text,
    add column if not exists latencia_ms integer;

-- -------------------------------------------------------------
-- 9. PAPÉIS E DADOS DE DEMONSTRAÇÃO
-- -------------------------------------------------------------
-- tipo_usuario: morador | visitante | gestor. O cadastro público só aceita
-- os dois primeiros - gestor nasce por migration ou pelo provisionar.py.
alter table public.usuarios drop constraint if exists usuarios_tipo_check;
alter table public.usuarios add constraint usuarios_tipo_check
    check (tipo_usuario in ('morador', 'visitante', 'gestor'));

insert into public.usuarios (id, nome, papel, tipo_usuario, condominio_id, bloco_apto, saldo)
values
    ('e0000000-0000-0000-0000-000000000001', 'Sindico Portal', 'Síndico', 'gestor',
     'c0000000-0000-0000-0000-000000000002', 'Administração', 0),
    ('e0000000-0000-0000-0000-000000000002', 'Sindico FIAP', 'Síndico', 'gestor',
     '11111111-1111-1111-1111-111111111111', 'Administração', 0),
    -- Conta da bancada: começa SEM saldo de propósito. É o que permite gravar
    -- "cartão recusado -> põe saldo no app -> aproxima de novo -> carrega".
    ('e0000000-0000-0000-0000-000000000003', 'Gus Bancada', 'Morador', 'morador',
     'c0000000-0000-0000-0000-000000000002', 'Bancada ESP32', 0)
on conflict (id) do nothing;

insert into public.veiculos (id, usuario_id, modelo, placa, tipo, capacidade_bateria_kwh, potencia_carro_kw)
values ('f0000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-000000000003',
        'Celular (bancada ESP32)', null, 'celular', 0.015, 0.018)
on conflict (id) do nothing;

insert into public.condominios_favoritos (usuario_id, condominio_id)
select u.id, u.condominio_id from public.usuarios u
where u.id in ('e0000000-0000-0000-0000-000000000001',
               'e0000000-0000-0000-0000-000000000002',
               'e0000000-0000-0000-0000-000000000003')
on conflict (usuario_id, condominio_id) do nothing;

-- -------------------------------------------------------------
-- 10. PRIVILÉGIOS, RLS, VIEW E REALTIME
-- -------------------------------------------------------------
alter table public.movimentacoes_carteira enable row level security;
alter table public.consumo_horario enable row level security;

-- O 11 fez tabela nova nascer fechada. Abrimos só a leitura necessária.
grant select on public.movimentacoes_carteira to authenticated;
drop policy if exists movimentacoes_proprias on public.movimentacoes_carteira;
create policy movimentacoes_proprias on public.movimentacoes_carteira
    for select to authenticated
    using (usuario_id = (select auth.uid()));
-- consumo_horario: só o backend lê (painel do gestor passa pela API).

-- A view ganha colunas novas: recria (create or replace não reordena colunas).
drop view if exists public.v_sessoes_local;
create view public.v_sessoes_local
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
left join public.veiculos v on v.id = s.veiculo_id
where s.status = 'carregando'
   or s.iniciado_em >= now() - interval '1 day';

revoke all    on public.v_sessoes_local from anon, authenticated;
grant  select on public.v_sessoes_local to authenticated;

do $$
begin
    begin alter publication supabase_realtime add table public.leituras_hardware;
    exception when duplicate_object then null; end;
    begin alter publication supabase_realtime add table public.movimentacoes_carteira;
    exception when duplicate_object then null; end;
end $$;

commit;

-- =============================================================
-- DEPOIS DE RODAR
-- =============================================================
-- 1. Senha para as contas novas (gestores e bancada), de dentro de backend/:
--      python provisionar.py senhas-demo --senha "SuaSenhaDemo#2026"
-- 2. Conferência:
--      select nome, tipo_usuario, saldo from usuarios order by tipo_usuario, nome;
--      select numero, perfil, potencia_maxima_kw, origem from carregadores
--      where condominio_id = 'c0000000-0000-0000-0000-000000000002' order by numero;
-- 3. Teste de invasão (deve dar 13/13):
--      python provisionar.py verificar
