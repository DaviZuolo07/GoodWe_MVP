-- =============================================================
-- GoodWe ChargeOps AI Assistant - Hardware ESP32 por WiFi
-- =============================================================
-- Rodar DEPOIS do 08_locais_favoritos.sql.
--
-- O que muda em relação ao Arduino por cabo
-- -----------------------------------------
-- O Arduino falava por serial: o backend abria a porta COM e lia linhas.
-- Isso amarra o hardware ao PC que roda o backend. O ESP32 tem WiFi, então
-- ele deixa de ser periférico e vira CLIENTE HTTP do backend.
--
-- Direção da conexão: o ESP32 chama o backend, nunca o contrário.
-- Se o backend precisasse chamar o ESP32, seria necessário IP fixo, backend
-- e placa na mesma rede e firewall aberto - e WiFi de faculdade com
-- isolamento de cliente derruba isso na hora da gravação. Com o ESP32 como
-- cliente, funciona atrás de NAT, em hotspot de celular, em qualquer rede.
--
-- Como o backend manda ordens para um cliente que ele não pode chamar?
-- Fila de comandos. O backend enfileira "liberar" ou "bloquear"; o ESP32
-- pergunta a cada 2s se tem algo para ele. É polling, e é de propósito.
-- =============================================================

-- -------------------------------------------------------------
-- 1. DISPOSITIVOS - um ESP32 por carregador físico
-- -------------------------------------------------------------
create table if not exists dispositivos (
    id            uuid primary key default gen_random_uuid(),
    carregador_id uuid not null unique references carregadores(id) on delete cascade,
    nome          text not null,

    -- Credencial que o ESP32 manda no header X-Device-Token. É o que separa
    -- "meu carregador reportando" de "qualquer um postando telemetria".
    -- Em produção isto seria um hash; no MVP é texto puro para o Gus poder
    -- copiar direto para o firmware.
    token         text not null unique,

    mac           text,
    ip            text,
    firmware      text,

    -- Preenchido a cada requisição do dispositivo. É daqui que sai o
    -- "online/offline": sem contato há mais de 30s, o ponto cai.
    ultimo_contato timestamptz,
    online         boolean not null default false,

    -- O dispositivo lê estes valores no handshake. Mudar o ritmo de
    -- telemetria não exige regravar firmware.
    intervalo_telemetria_s integer not null default 5,
    intervalo_comandos_s   integer not null default 2,

    criado_em     timestamptz not null default now()
);

create index if not exists idx_dispositivos_token on dispositivos (token);

-- -------------------------------------------------------------
-- 2. COMANDOS - a caixa de saída do backend para o dispositivo
-- -------------------------------------------------------------
create table if not exists comandos_dispositivo (
    id             uuid primary key default gen_random_uuid(),
    dispositivo_id uuid not null references dispositivos(id) on delete cascade,
    sessao_id      uuid references sessoes_recarga(id) on delete set null,

    -- liberar  -> fecha o relé, energia passa
    -- bloquear -> abre o relé, corta a energia
    -- ping     -> só para testar a ponta sem mexer em relé
    acao           text not null check (acao in ('liberar', 'bloquear', 'ping')),

    -- pendente  -> na fila
    -- entregue  -> o ESP32 leu, mas ainda não confirmou que executou
    -- confirmado-> o relé mudou de estado de verdade
    -- falhou    -> o dispositivo reportou erro
    status         text not null default 'pendente'
                   check (status in ('pendente', 'entregue', 'confirmado', 'falhou')),

    erro           text,
    criado_em      timestamptz not null default now(),
    entregue_em    timestamptz,
    confirmado_em  timestamptz
);

-- A consulta quente é "comandos pendentes deste dispositivo", a cada 2s.
create index if not exists idx_comandos_pendentes
    on comandos_dispositivo (dispositivo_id, status, criado_em);

-- -------------------------------------------------------------
-- 3. LEITURAS - a série temporal medida pelo sensor
-- -------------------------------------------------------------
-- É isto que responde "energia monitorada por meio de dados": não é o modelo
-- físico estimando, é o medidor reportando. Vira gráfico de potência real na
-- apresentação, e prova que o número na tela veio de um sensor.
create table if not exists leituras_hardware (
    id             uuid primary key default gen_random_uuid(),
    dispositivo_id uuid not null references dispositivos(id) on delete cascade,
    sessao_id      uuid references sessoes_recarga(id) on delete set null,

    potencia_w     numeric,
    energia_wh     numeric,       -- acumulada na sessão
    tensao_v       numeric,
    corrente_a     numeric,
    temperatura_c  numeric,
    rele_ligado    boolean,

    criado_em      timestamptz not null default now()
);

create index if not exists idx_leituras_sessao
    on leituras_hardware (sessao_id, criado_em desc);

alter table dispositivos          disable row level security;
alter table comandos_dispositivo  disable row level security;
alter table leituras_hardware     disable row level security;

-- -------------------------------------------------------------
-- 4. Realtime: o painel precisa ver o ponto ficar online sozinho
-- -------------------------------------------------------------
do $$
begin
    alter publication supabase_realtime add table dispositivos;
exception when duplicate_object then null;
end $$;

-- -------------------------------------------------------------
-- 5. Cadastro do dispositivo do Gus
-- -------------------------------------------------------------
-- Marca o carregador 01 do Portal dos Bandeirantes como FÍSICO. A partir
-- daqui o simulador para de mexer nele: quem manda energia e temperatura
-- nesse ponto é o ESP32.
--
-- Troque o UUID abaixo se o hardware for plugado em outro carregador.
update carregadores
set origem = 'hardware', status = 'offline'
where id = 'b0000000-0000-0000-0000-000000000001';

insert into dispositivos (carregador_id, nome, token)
values (
    'b0000000-0000-0000-0000-000000000001',
    'ESP32 - Portal dos Bandeirantes - Ponto 01',
    'gw-esp32-portal-01-troque-este-token'
)
on conflict (carregador_id) do nothing;

-- -------------------------------------------------------------
-- Conferência
-- -------------------------------------------------------------
-- select c.numero, c.origem, c.status, d.nome, d.online, d.ultimo_contato
-- from carregadores c
-- left join dispositivos d on d.carregador_id = c.id
-- where c.origem = 'hardware';
