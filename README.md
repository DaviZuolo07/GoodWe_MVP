# GoodWe ChargeOps AI Assistant

Plataforma de gestão de carregadores de veículos elétricos em condomínios residenciais, com assistente de IA, hardware embarcado e simulação física de recarga.

Projeto acadêmico desenvolvido na **FIAP** em parceria com a **GoodWe**.

---

## Equipe

| Nome | RM |
|---|---|
| Davi Q. Zuolo | 571669 |
| Daniel V. Mana | 571632 |
| Gustavo Zagatto | 569420 |
| Kayo Henderson | 570706 |

---

## Índice

1. [O que é o projeto](#1-o-que-é-o-projeto)
2. [Arquitetura](#2-arquitetura)
3. [Stack](#3-stack)
4. [Estrutura de pastas](#4-estrutura-de-pastas)
5. [Como rodar](#5-como-rodar)
6. [Variáveis de ambiente](#6-variáveis-de-ambiente)
7. [Banco de dados](#7-banco-de-dados)
8. [O modelo físico da recarga](#8-o-modelo-físico-da-recarga)
9. [API — endpoints](#9-api--endpoints)
10. [O assistente de IA](#10-o-assistente-de-ia)
11. [Hardware ESP32](#11-hardware-esp32)
12. [Segurança](#12-segurança)
13. [Fluxos principais](#13-fluxos-principais)
14. [Solução de problemas](#14-solução-de-problemas)
15. [Pendências conhecidas](#15-pendências-conhecidas)

---

## 1. O que é o projeto

Condomínios que instalam carregadores de veículos elétricos enfrentam três problemas de uma vez: a rede do prédio não aguenta todo mundo carregando junto, não existe forma justa de cobrar de cada morador o que ele consumiu, e ninguém sabe quando um ponto vai ficar livre.

O **ChargeOps** resolve os três. Ele gerencia a fila, mede o consumo real por sessão, debita da carteira do morador e responde perguntas em linguagem natural sobre o estado do sistema.

O que torna isso mais que um CRUD:

- **A recarga é modelada com física real.** A potência não é constante: acima de 80% de bateria ela cai progressivamente, e acima de 35 °C o carregador reduz a entrega para se proteger. O tempo estimado sai da integração dessa curva, não de uma regra de três.
- **O assistente não inventa número.** Ele nunca escreve SQL, escolhe entre funções de leitura pré-aprovadas, e todo valor que aparece na resposta é conferido contra o que veio do banco antes de sair.
- **O hardware é real.** Um ESP32 por WiFi fecha o relé e reporta a energia medida por sensor. Quando ele está conectado, a energia deixa de ser calculada e passa a ser medida.

O sistema atende **três condomínios** simultaneamente, cada um com seus próprios carregadores e tarifas.

---

## 2. Arquitetura

```
┌──────────────────────────────────────────────────────────┐
│  FRONTEND  React + Vite + Tailwind v4                    │
│  Dashboard · Carteira · Veículos · Histórico · Chat      │
└────────────┬──────────────────────────────┬──────────────┘
             │ escuta (Realtime)            │ age (REST)
             ▼                              ▼
┌────────────────────────┐   ┌──────────────────────────────┐
│  SUPABASE              │◄──│  BACKEND  FastAPI / Python   │
│  Postgres + Realtime   │   │                              │
└────────────────────────┘   │  ├── chatbot/   assistente   │
             ▲               │  ├── hardware_api.py  ESP32  │
             │               │  └── simulador (loop 10s)    │
             │ escreve       └──────────┬───────────────────┘
             │                          │ HTTP
             │               ┌──────────▼───────────────────┐
             └───────────────│  ESP32 (WiFi)                │
                             │  relé · medidor · RFID       │
                             └──────────────────────────────┘
```

**Duas decisões de arquitetura que valem entender:**

**O frontend nunca faz polling.** Ele escuta `postgres_changes` do Supabase Realtime. Quando o simulador ou o ESP32 atualiza uma sessão, a barra de progresso na tela se move sozinha. O backend cuida apenas das **ações** (login, iniciar/parar recarga, fila, saldo, chatbot).

**O ESP32 é cliente, não servidor.** Ele chama o backend; o backend nunca chama a placa. Isso parece invertido, mas é o que faz funcionar fora do laboratório: não exige IP fixo, não exige estar na mesma rede, não exige firewall aberto. Funciona atrás de NAT, em roteador doméstico ou em hotspot de celular. Como o backend manda ordem para alguém que não pode chamar? Fila de comandos — o backend enfileira, o dispositivo pergunta a cada 2 segundos.

---

## 3. Stack

| Camada | Tecnologia |
|---|---|
| Frontend | React 18, Vite, Tailwind CSS v4, `@supabase/supabase-js` |
| Backend | Python 3.10+, FastAPI, Uvicorn, Pydantic, `supabase-py`, httpx |
| Banco | Supabase (PostgreSQL + Realtime) |
| IA | Ollama Cloud — `gpt-oss:120b` |
| Hardware | ESP32 (Arduino IDE), ArduinoJson, PZEM-004T v3, MFRC522 |
| Serial (legado) | pyserial |

---

## 4. Estrutura de pastas

```
GoodWe_MVP/
├── backend/
│   ├── chatbot/                    Pacote do assistente de IA
│   │   ├── __init__.py             API pública (2 funções)
│   │   ├── contexto.py             Injeção de dependências do main.py
│   │   ├── dados.py                Funções de leitura whitelisted
│   │   ├── router.py               Classificação de intenção
│   │   ├── respostas.py            Redator determinístico (fallback)
│   │   ├── llm.py                  Cliente Ollama (local ou nuvem)
│   │   ├── verificador.py          Anti-alucinação numérica
│   │   ├── loader.py               Carregador de prompts versionados
│   │   ├── servico.py              Orquestrador do fluxo
│   │   └── prompts/
│   │       ├── system.md           Identidade, tom, regras do redator
│   │       ├── router.md           Instrução do classificador
│   │       └── few_shot.json       Exemplos, incluindo recusas
│   ├── hardware_api.py             Rotas HTTP do ESP32
│   ├── hardware_serial.py          Leitor RFID por cabo (legado)
│   ├── main.py                     API, física, simulador
│   └── .env                        Credenciais (NÃO versionar)
│
├── db/                             Migrations, na ordem
│   ├── 01_schema.sql
│   ├── 02_seed.sql
│   ├── 03_alter_login_cadastro.sql
│   ├── 04_fix_percentual_bateria.sql
│   ├── 05_saldo_billing.sql
│   ├── 06_rfid_e_temperatura.sql
│   ├── 07_multi_condominio.sql
│   ├── 08_locais_favoritos.sql
│   └── 09_hardware_esp32.sql
│
├── firmware/
│   └── chargeops_esp32.ino         Firmware do ESP32
│
├── frontend/
│   ├── src/
│   │   ├── components/             ChatPanel, ChargerCard, FilaPanel, ...
│   │   ├── pages/                  Dashboard, Login, Carteira, ...
│   │   ├── lib/                    midia.js, tema.js
│   │   ├── config.js               API_URL e condomínio padrão
│   │   ├── supabaseClient.js
│   │   └── index.css               Design tokens
│   └── .env                        VITE_* (NÃO versionar)
│
└── requirements.txt                Dependências Python
```

---

## 5. Como rodar

### Pré-requisitos

- Python 3.10 ou superior
- Node.js 18 ou superior
- Conta no [Supabase](https://supabase.com) (grátis)
- Conta no [Ollama](https://ollama.com) para a chave de API (grátis, sem cartão)

### Passo 1 — Banco de dados

Crie um projeto no Supabase. No **SQL Editor**, execute os arquivos de `db/` **na ordem numérica**, do `01` ao `09`, um de cada vez.

A ordem importa: cada migration assume o estado deixada pela anterior.

Depois, em **Settings → API**, copie a `URL` e a `anon key`.

### Passo 2 — Backend

```bash
# na raiz do projeto
pip install -r requirements.txt

cd backend
# crie o arquivo .env (ver seção 6)

uvicorn main:app --reload --host 0.0.0.0
```

O `--host 0.0.0.0` é obrigatório se você for testar no celular ou conectar o ESP32. Sem ele, o servidor só aceita conexão da própria máquina.

Documentação interativa da API: **http://localhost:8000/docs**

### Passo 3 — Frontend

```bash
cd frontend
npm install
# crie o arquivo .env (ver seção 6)

npm run dev -- --host
```

Aplicação: **http://localhost:5173**

O `--host` expõe na rede local. O terminal mostra um segundo endereço (`http://192.168.x.x:5173`) que funciona no celular, desde que esteja no mesmo WiFi.

### Passo 4 — Verificação

1. Faça login com uma conta do seed
2. O Dashboard deve mostrar os carregadores do condomínio
3. Abra o assistente (botão flutuante) e pergunte *"quais carregadores estão disponíveis?"*
4. Inicie uma recarga e veja a barra de progresso andar sozinha — é o Realtime funcionando

---

## 6. Variáveis de ambiente

### `backend/.env`

```env
# --- Supabase ---
SUPABASE_URL=https://seu-projeto.supabase.co
SUPABASE_KEY=sua_anon_key

# --- Assistente de IA (Ollama Cloud) ---
CHAT_MODO=llm                      # llm | regras
OLLAMA_HOST=https://ollama.com
OLLAMA_API_KEY=sua_chave_ollama
OLLAMA_MODEL=gpt-oss:120b
OLLAMA_TIMEOUT_S=30
OLLAMA_THINK=low                   # low | medium | high | none
OLLAMA_DEV=1                       # hot-reload dos prompts .md

# --- RFID por cabo (opcional, legado) ---
SERIAL_PORT=COM3
SERIAL_BAUD=115200
```

**`CHAT_MODO=regras` é o botão de pânico.** Se a nuvem cair no dia da apresentação, troque essa variável e o assistente volta a responder por regras determinísticas, sem LLM nenhum. Nada quebra.

Para rodar o modelo localmente em vez da nuvem:

```env
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=gpt-oss:20b
OLLAMA_TIMEOUT_S=8
# OLLAMA_API_KEY fica vazio
```

### `frontend/.env`

```env
VITE_API_URL=http://localhost:8000
VITE_SUPABASE_URL=https://seu-projeto.supabase.co
VITE_SUPABASE_KEY=sua_anon_key
```

Para acessar do celular, troque `localhost` pelo IP da máquina na rede:

```env
VITE_API_URL=http://192.168.0.100:8000
```

> **Atenção:** variáveis `VITE_*` vão para o bundle e ficam visíveis no navegador. Nunca coloque a chave do Ollama nem a `service_role` do Supabase aqui.

---

## 7. Banco de dados

Todas as tabelas em `public`. RLS desligada no MVP.

| Tabela | Papel | Colunas principais |
|---|---|---|
| `condominios` | Locais atendidos | `id`, `nome`, `endereco`, `limite_energia_kw` |
| `usuarios` | Moradores e síndicos | `id`, `nome`, `tipo_usuario`, `condominio_id`, `bloco_apto`, `saldo`, `rfid_uid` |
| `veiculos` | Carros cadastrados | `id`, `usuario_id`, `modelo`, `placa`, `capacidade_bateria_kwh`, `potencia_carro_kw`, `percentual_bateria` |
| `carregadores` | Pontos de recarga | `id`, `condominio_id`, `numero`, `tipo`, `potencia_maxima_kw`, `tarifa_kwh`, `status`, `temperatura_c`, `origem` |
| `sessoes_recarga` | Recargas | `id`, `carregador_id`, `veiculo_id`, `usuario_id`, `status`, `potencia_atual_kw`, `energia_entregue_kwh`, `percentual_bateria_*`, `tempo_estimado_min`, `custo_estimado`, `custo_final`, `origem` |
| `fila` | Espera por ponto | `id`, `carregador_id`, `usuario_id`, `posicao` |
| `pagamentos` | Débitos | `id`, `sessao_id`, `valor`, `metodo`, `status` |
| `notificacoes` | Avisos ao morador | `id`, `usuario_id`, `mensagem`, `lida` |
| `chat_mensagens` | Auditoria do chat | `id`, `usuario_id`, `carregador_id`, `remetente`, `mensagem` |
| `condominios_favoritos` | Locais favoritos + **allowlist** | `usuario_id`, `condominio_id` |
| `dispositivos` | ESP32 cadastrados | `id`, `carregador_id`, `token`, `online`, `ultimo_contato` |
| `comandos_dispositivo` | Fila de ordens ao ESP32 | `id`, `dispositivo_id`, `acao`, `status` |
| `leituras_hardware` | Série temporal medida | `potencia_w`, `energia_wh`, `tensao_v`, `corrente_a`, `temperatura_c` |

**Valores de enumeração:**

- `carregadores.status`: `disponivel` · `em_uso` · `fila` · `offline`
- `carregadores.origem`: `simulado` · `hardware`
- `sessoes_recarga.status`: `carregando` · `finalizada` · `cancelada` · `aguardando_rfid`
- `comandos_dispositivo.acao`: `liberar` · `bloquear` · `ping`

### A armadilha do schema

`sessoes_recarga` e `fila` **não têm coluna de condomínio**. Elas apontam para um carregador, e é o carregador que pertence a um local.

Para responder *"quantos carros estão na fila aqui"*, o caminho é: buscar os `carregadores.id` do condomínio, depois filtrar `fila` por esses IDs. Consultar `fila` diretamente mistura os três condomínios num número só.

Isso está implementado corretamente em `chatbot/dados.py::fila()`.

---

## 8. O modelo físico da recarga

Implementado em `backend/main.py`. É o diferencial técnico do projeto — e a razão pela qual o assistente **nunca recalcula nada por conta própria**, sempre chama estas funções. Duas contas divergentes é pior que nenhuma.

| Função | O que faz |
|---|---|
| `fator_termico(temp_c)` | Derating térmico: acima de 35 °C a potência cai até 30% |
| `potencia_no_soc(p_max, soc)` | Curva CC/CV: potência cheia até 80%, depois cai progressivamente |
| `tempo_de_carga_min(cap, soc_ini, soc_fim, p_max)` | Integra a curva em passos de 1% |
| `calcular_estimativa(charger, veiculo, soc, alvo)` | Energia, tempo, custo e potência instantânea |
| `custo_da_sessao(sessao)` | **Fonte canônica de custo** — sempre pela tarifa do carregador |

**Constantes:**

```python
EFICIENCIA_CARGA  = 0.92   # energia que chega na bateria / energia da tomada
SOC_JOELHO        = 80.0   # onde começa o tapering (%)
FATOR_FINAL       = 0.20   # fração da potência ao encostar em 100%
TARIFA_PADRAO_KWH = 2.10   # só entra se o carregador não tiver tarifa cadastrada
```

**Sobre o custo:** cobra-se a energia que sai da tomada, não a que chega na bateria. Os 8% de perda são reais e o condomínio paga por eles. `energia_entregue_kwh` já é energia de tomada, então `custo_da_sessao()` multiplica direto pela tarifa — sem dividir de novo pela eficiência, o que cobraria a perda duas vezes.

**Sobre `custo_da_sessao()`:** existe porque o valor `2.10` estava replicado em três lugares (`/charge/stop`, chatbot, simulador). O resultado era que a mesma sessão custava valores diferentes dependendo de quem a encerrasse. Hoje existe uma fonte única, e ela sempre busca a tarifa do carregador daquele condomínio.

---

## 9. API — endpoints

### Autenticação e cadastro

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/cadastro` | Cria morador |
| `POST` | `/login` | Autentica |
| `POST` | `/usuarios/{id}/vincular-rfid` | Associa cartão ao morador |

### Locais

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/condominios` | Todos os locais da rede |
| `GET` | `/usuarios/{id}/locais` | Favoritos + lista completa + condomínio de moradia |
| `POST` | `/usuarios/{id}/favoritos` | Favorita um local (idempotente) |
| `DELETE` | `/usuarios/{id}/favoritos/{condominio_id}` | Remove favorito |

### Recarga

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/chargers` | Carregadores de um condomínio |
| `POST` | `/charge/preview` | Estimativa sem iniciar |
| `POST` | `/charge/start` | Inicia recarga pelo app |
| `POST` | `/charge/preparar-rfid` | Prepara sessão para autorização por cartão |
| `POST` | `/charge/stop` | Encerra e calcula o custo final |

### Fila

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/fila/{charger_id}` | Fila de um ponto |
| `POST` | `/fila/entrar` | Entra na fila |
| `POST` | `/fila/sair` | Sai da fila |

### Veículos e carteira

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/usuarios/{id}/veiculos` | Veículos do morador |
| `POST` | `/veiculos` | Cadastra veículo |
| `POST` | `/usuarios/{id}/recarregar-saldo` | Adiciona crédito |

### Assistente

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/chatbot` | Pergunta ao assistente |

**Contrato congelado.** Os campos `reply` e `timestamp` nunca mudam de nome nem somem — o frontend depende deles.

```jsonc
// requisição
{
  "message": "quanto falta?",
  "usuario_id": "uuid",
  "charger_id": "uuid | null",
  "condominio_id": "uuid | null"    // local escolhido no seletor
}

// resposta
{
  "reply": "Faltam cerca de 2h15 para completar...",
  "timestamp": "2026-08-25T13:07:00",
  // campos aditivos (o frontend ignora o que não usa)
  "intencao": "tempo_restante",
  "fonte": ["sessoes_recarga", "carregadores"],
  "condominio_id": "uuid",
  "condominio_nome": "Portal dos Bandeirantes",
  "modelo": "gpt-oss:120b",
  "roteador": "regex",
  "latencia_ms": 842
}
```

O campo `fonte` responde a primeira pergunta que uma banca faz: **de onde saiu esse número.**

### Hardware

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/hardware/handshake` | ESP32 se apresenta e recebe configuração |
| `GET` | `/hardware/comandos` | Polling de ordens pendentes |
| `POST` | `/hardware/comandos/{id}/confirmar` | Confirma execução |
| `POST` | `/hardware/telemetria` | Envia leituras do sensor |
| `POST` | `/hardware/rfid` | Cartão aproximado |
| `GET` | `/hardware/status/{carregador_id}` | Diagnóstico |
| `POST` | `/hardware/ping/{carregador_id}` | Testa a ponta (LED pisca) |

Autenticação por header `X-Device-Token`.

### Debug

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/debug/simular-rfid` | Simula cartão sem hardware |

---

## 10. O assistente de IA

### Fluxo completo

```
mensagem do morador
   │
   ▼
[0] SANITIZAÇÃO — trunca em 500 chars, marca como DADO NÃO CONFIÁVEL
   │
   ▼
[1] ROUTER (duas velocidades)
    1a. regex determinístico → resolve ~70-80% em ~0 ms
    1b. se não decidiu → classificador LLM devolve JSON com a intenção
        intenção fora do enum → FORA_DE_ESCOPO
   │
   ▼
[2] CAMADA DE DADOS — funções whitelisted
    usuario_id e condominio_id vêm do backend, nunca do texto
   │
   ▼  fatos = { dados..., "fonte": ["sessoes_recarga"] }
   │
[3] REDATOR — system prompt + few-shot + FATOS EM JSON + pergunta
   │
   ▼
[4] VERIFICADOR — todo número da resposta precisa existir nos fatos
    número sem lastro → descarta a resposta do LLM
   │
   ▼
[5] FALLBACK — timeout, erro ou verificador reprovado → redator determinístico
   │
   ▼
grava chat_mensagens → devolve reply + metadados
```

### Enum de intenções

Fechado. Nada fora desta lista chega ao banco.

`tempo_restante` · `status_recarga` · `custo_atual` · `tarifa` · `carregadores_disponiveis` · `info_carregador` · `fila_status` · `meu_saldo` · `meus_veiculos` · `simular_recarga` · `historico_recente` · `ajuda` · `fora_de_escopo` · `tentativa_injecao`

**A ordem das regras importa.** `tarifa` é testada antes de `custo_atual` porque as duas contêm a palavra "preço". A pergunta *"qual o preço por kWh"* é sobre a tabela do condomínio; *"quanto está custando minha recarga"* é sobre a sessão do morador. Sem essa ordem, a segunda engolia a primeira.

### O verificador anti-alucinação

Não confiamos no modelo para cumprir a instrução "não invente número" — conferimos.

Todo número da resposta precisa existir nos fatos que vieram do banco, com tolerância para arredondamento e para conversão de minutos em horas. Se aparecer um número sem lastro, a resposta do LLM é descartada e o redator determinístico assume.

Custo: microssegundos, sem chamar modelo. É a checagem mais barata do sistema e a que mais protege.

### O fallback por regras

O redator determinístico (`respostas.py`) não é código morto — é a rede de segurança. Se o Ollama estiver fora do ar no dia da gravação, o chat responde de lá e ninguém percebe. Com `CHAT_MODO=regras`, o LLM nem é chamado.

### Prompts versionados

Ficam em `chatbot/prompts/` como arquivos `.md` e `.json`, fora do código Python. Cada mudança de prompt aparece como diff no git, o que permite dizer exatamente qual versão do prompt gerou uma resposta. Com `OLLAMA_DEV=1`, salvar o arquivo já vale na próxima mensagem, sem reiniciar o servidor.

### Escolha do modelo

`gpt-oss:120b` via Ollama Cloud. O critério não foi "conversa bem" — o caso de uso é obediência a contrato, não criatividade. Pesaram: saída estruturada confiável, bom português, e o fato de rodar na nuvem sem consumir a GPU da máquina de apresentação.

A troca de modelo é uma variável de ambiente. A arquitetura tratou o modelo como plugue desde o início.

---

## 11. Hardware ESP32

### Protocolo

```
ESP32 (cliente)                        Backend (servidor)
     │                                        │
     ├── POST /hardware/handshake ───────────►│  "cheguei, quem sou eu?"
     │◄── carregador, tarifa, intervalos ─────┤
     │                                        │
     ├── GET /hardware/comandos (2s) ────────►│  "tem ordem pra mim?"
     │◄── [{acao:"liberar", sessao_id}] ──────┤  ← app apertou iniciar
     │    FECHA O RELÉ                        │
     ├── POST .../confirmar ─────────────────►│  "relé fechou"
     │                                        │
     ├── POST /hardware/telemetria (5s) ─────►│  W, Wh, V, A, °C
     │◄── {deve_liberar, percentual} ─────────┤
     │                                        │
     ├── POST /hardware/rfid ────────────────►│  cartão aproximado
     │◄── {autorizado, mensagem} ─────────────┤
```

### Decisões que evitam problemas reais

**Energia acumulada, não delta.** O ESP32 manda o total de Wh da sessão. Se um POST se perder no WiFi, o próximo já corrige sozinho. Com delta, um pacote perdido sumiria da conta para sempre.

**Guarda contra reset.** Se o ESP32 reiniciar no meio da recarga, o contador dele zera. O backend nunca deixa a energia da sessão andar para trás — senão o morador ganharia recarga de graça por causa de um reboot.

**Relé aberto por padrão.** Ao ligar, ao perder WiFi, ao não saber o que fazer: abre. Ponto morto é melhor que ponto entregando energia sem sessão registrada.

**O simulador ignora pontos físicos.** Carregador com `origem = 'hardware'` tem um ESP32 escrevendo temperatura e energia a partir do sensor. Se o simulador também escrevesse, os dois brigariam pela mesma linha a cada 10 segundos e o valor na tela ficaria pulando entre o medido e o modelado. Um dono por linha.

### Configuração do firmware

No `firmware/chargeops_esp32.ino`, só o bloco `CONFIGURAÇÃO`:

```cpp
const char* WIFI_SSID    = "sua_rede";
const char* WIFI_SENHA   = "sua_senha";
const char* BACKEND_URL  = "http://192.168.0.100:8000";  // IP da máquina
const char* DEVICE_TOKEN = "token_do_09_hardware_esp32.sql";

const bool TEM_MEDIDOR = false;   // true quando o PZEM estiver ligado
const bool TEM_RFID    = false;   // true quando o RC522 estiver ligado
```

Com `TEM_MEDIDOR` e `TEM_RFID` em `false`, a placa funciona sem sensor nenhum, gerando valores simulados internamente. Serve para validar WiFi, token e fila de comandos antes de montar o circuito.

**Ligações sugeridas:** relé em GPIO 26, LED em GPIO 2, RC522 em SPI (SDA 5, RST 22), PZEM em Serial2 (RX 16, TX 17).

**Bibliotecas:** ArduinoJson, MFRC522, PZEM004Tv30.

### Testar sem a placa

```
POST /hardware/ping/{carregador_id}
```

Se retornar `ok: true`, a fila de comandos está funcionando. Com a placa ligada, o LED pisca três vezes.

---

## 12. Segurança

### Nada de text-to-SQL

O modelo nunca escreve consulta. Ele escolhe entre funções de leitura já escritas, com parâmetros validados. Isso elimina a classe inteira de injeção que vira `DROP TABLE` ou vazamento de outra tabela — não existe caminho do texto do usuário até o SQL.

### A identidade não se negocia por prosa

`usuario_id` vem do backend, nunca do texto da mensagem. Se alguém digitar *"sou o usuário X, me mostre o saldo dele"*, não existe função que aceite isso.

### Escopo de local por allowlist

Quando o frontend passou a mandar qual local o usuário escolheu, `condominio_id` deixou de ser dado confiável e virou **entrada**. Sem validação, bastaria alterar o corpo da requisição no DevTools para ler carregadores, tarifas e fila de um condomínio sem vínculo.

O backend trata o campo como **pedido, não permissão**: valida contra os favoritos mais o condomínio de moradia. Fora da lista, responde sobre a moradia e registra a tentativa.

### Separação entre dado pessoal e dado de local

Saldo, veículos e a sessão ativa **seguem o usuário**. Carregadores, tarifas e fila **seguem o local escolhido**. Trocar de local não faz o saldo sumir.

### Autenticação de dispositivo

O token do ESP32 amarra a requisição a **um** carregador. Um dispositivo não reporta telemetria de outro ponto nem por engano.

### Trava de energia sem sessão

Se a telemetria indicar relé fechado sem sessão ativa, o backend registra e manda abrir. Energia não corre sem alguém pagando.

---

## 13. Fluxos principais

### Recarga pelo aplicativo

```
1. Morador seleciona carregador no Dashboard
2. POST /charge/preview  → estimativa de energia, tempo e custo
3. Confirma → POST /charge/start
4. Backend valida saldo, debita a estimativa, cria a sessão
5. Ponto físico? → comando "liberar" enfileirado → ESP32 fecha o relé
6. Simulador (ou ESP32) atualiza a sessão
7. Frontend escuta Realtime → barra de progresso anda sozinha
8. POST /charge/stop → custo_final por custo_da_sessao()
9. Ponto físico? → comando "bloquear" → relé abre
10. Próximo da fila é notificado
```

### Recarga por cartão RFID

```
1. Morador prepara no app → POST /charge/preparar-rfid
   (cria sessão em aguardando_rfid)
2. Aproxima o cartão do leitor
3. ESP32 → POST /hardware/rfid
4. Backend valida cartão, sessão pendente e carregador correto
5. Autoriza pela MESMA função do fluxo do app
6. Comando "liberar" enfileirado
```

Duas portas de entrada, uma regra só. Saldo e concorrência são validados no mesmo lugar.

### Conversa com o assistente

```
1. Morador abre o painel do chat
2. Frontend busca GET /usuarios/{id}/locais
3. Seletor mostra os favoritos; morador escolhe onde está
4. Pergunta → POST /chatbot com o condominio_id escolhido
5. Backend valida o local, roteia a intenção, consulta o banco
6. Redige (LLM ou template), verifica os números, responde
```

Trocar de local zera a conversa: respostas de dois condomínios na mesma thread confundem.

---

## 14. Solução de problemas

| Sintoma | Causa provável | Solução |
|---|---|---|
| `ERR_ADDRESS_INVALID` em `0.0.0.0:8000` | `0.0.0.0` não é endereço navegável | Acesse por `localhost:8000` |
| Celular não carrega a aplicação | Frontend apontando para `localhost` | Troque `VITE_API_URL` pelo IP da máquina; rode `npm run dev -- --host` |
| ESP32 não conecta | Backend sem `--host 0.0.0.0`, ou `BACKEND_URL` com `localhost` | Para o ESP32, `localhost` é ele mesmo — use o IP da máquina |
| `/hardware/ping` retorna 404 | Migration `09` não executada | Rode `09_hardware_esp32.sql` |
| Chat responde mas `"modelo": "regras"` | LLM não foi usado | Confira `CHAT_MODO=llm`, a chave e o log do terminal |
| `{"error":"Unauthorized"}` no Ollama | Chave inválida ou com espaço | Gere nova em ollama.com/settings/keys |
| Chat lento | `OLLAMA_THINK` alto | Use `low` |
| Valor do chat diferente da tela | Tarifa divergente | Confirme que `custo_da_sessao()` está sendo usado nos três pontos |
| Ponto físico com valores pulando | Simulador escrevendo em ponto de hardware | Confirme `origem = 'hardware'` no carregador |
| `ModuleNotFoundError: chatbot` | Pasta no nível errado | `chatbot/` fica ao lado de `main.py`, dentro de `backend/` |

---

## 15. Pendências conhecidas

Documentadas por honestidade técnica — são decisões em aberto, não esquecimentos.

**Reconciliação de saldo.** No início da recarga é debitada a estimativa até 100%. No `/charge/stop` o `custo_final` é calculado, mas a diferença não é estornada. Quem para em 60% pagou pelos 100%, e a linha em `pagamentos` mantém o valor estimado. Três caminhos possíveis: estornar no stop, assumir explicitamente o modelo de pré-autorização de cartão de crédito, ou manter como está.

**RLS desligada.** Aceitável no MVP acadêmico, inaceitável em produção. O controle de acesso hoje vive na camada de aplicação.

**Token de dispositivo em texto puro.** Em produção seria hash. No MVP é texto para facilitar a configuração do firmware.

**Sem rate limit no `/chatbot`.** Um usuário pode enviar mensagens sem limite.

**`datetime.utcnow()` deprecado** no Python 3.12+. Gera warning, não quebra.

---

## Licença e contexto

Projeto acadêmico desenvolvido para a FIAP em parceria com a GoodWe. Não é produto final nem se destina a uso em produção.

**Repositório:** `DaviZuolo07/GoodWe_MVP` — branch `master`
