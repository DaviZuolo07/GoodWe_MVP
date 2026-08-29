# GoodWe ChargeOps AI Assistant

**Versão Beta 1.0 — build de apresentação**

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
12. [O fluxo do cartão RFID](#12-o-fluxo-do-cartão-rfid)
13. [Segurança](#13-segurança)
14. [Fluxos principais](#14-fluxos-principais)
15. [Testar sem o hardware](#15-testar-sem-o-hardware)
16. [Solução de problemas](#16-solução-de-problemas)
17. [Pendências conhecidas](#17-pendências-conhecidas)
18. [Roadmap e melhorias futuras](#18-roadmap-e-melhorias-futuras)

---

## 1. O que é o projeto

Condomínios que instalam carregadores de veículos elétricos enfrentam três problemas de uma vez: a rede do prédio não aguenta todo mundo carregando junto, não existe forma justa de cobrar de cada morador o que ele consumiu, e ninguém sabe quando um ponto vai ficar livre.

O **ChargeOps** resolve os três. Ele gerencia a fila, mede o consumo real por sessão, debita da carteira do morador e responde perguntas em linguagem natural sobre o estado do sistema.

O que torna isso mais que um CRUD:

- **A recarga é modelada com física real.** A potência não é constante: acima de 80% de bateria ela cai progressivamente, e acima de 35 °C o carregador reduz a entrega para se proteger. O tempo estimado sai da integração dessa curva, não de uma regra de três.
- **O assistente não inventa número.** Ele nunca escreve SQL, escolhe entre funções de leitura pré-aprovadas, e todo valor que aparece na resposta é conferido contra o que veio do banco antes de sair.
- **O hardware é real.** Um ESP32 por WiFi fecha o relé e reporta a energia medida por sensor. Quando ele está conectado, a energia deixa de ser calculada e passa a ser medida.
- **O cartão é quem autoriza.** A tela prepara a recarga; quem decide se ela começa é a aproximação do cartão físico no leitor, com a verificação de saldo acontecendo nesse instante.

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

**Três decisões de arquitetura que valem entender:**

**O frontend nunca faz polling.** Ele escuta `postgres_changes` do Supabase Realtime. Quando o simulador ou o ESP32 atualiza uma sessão, a barra de progresso na tela se move sozinha. O backend cuida apenas das **ações**.

**O ESP32 é cliente, não servidor.** Ele chama o backend; o backend nunca chama a placa. Isso parece invertido, mas é o que faz funcionar fora do laboratório: não exige IP fixo, não exige estar na mesma rede, não exige firewall aberto. Funciona atrás de NAT, em roteador doméstico ou em hotspot de celular. Como o backend manda ordem para alguém que não pode chamar? Fila de comandos — o backend enfileira, o dispositivo pergunta a cada 2 segundos.

**O banco é o canal de retorno para o usuário.** Quando o cartão é lido, o ESP32 conversa com o backend numa requisição onde o navegador do morador não está presente. Se a autorização falhar, o erro acontece num canal onde ele não está ouvindo. Por isso a decisão é **gravada na linha da sessão** e chega ao navegador pelo Realtime. Nenhuma informação importante viaja apenas numa resposta HTTP.

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
│   ├── 09_hardware_esp32.sql
│   └── 10_rfid_fluxo_real.sql
│
├── firmware/
│   └── chargeops_esp32.ino         Firmware do ESP32
│
├── frontend/
│   ├── src/
│   │   ├── components/             ChatPanel, ChargerCard, PagamentoModal, ...
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

Crie um projeto no Supabase. No **SQL Editor**, execute os arquivos de `db/` **na ordem numérica**, do `01` ao `10`, um de cada vez.

A ordem importa: cada migration assume o estado deixado pela anterior.

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

> `0.0.0.0` é uma instrução para o servidor, não um endereço navegável. Acesse sempre por `localhost:8000`.

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
3. Abra o assistente (botão flutuante) e pergunte *"qual o preço por kWh?"*
4. Confira o campo `"modelo"` na resposta pelo `/docs`: se vier `gpt-oss:120b`, a IA está na nuvem; se vier `regras`, caiu no fallback
5. Inicie uma recarga e veja a barra de progresso andar sozinha — é o Realtime funcionando

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

# --- Testes sem o ESP32 ---
MODO_DEMO=0                        # 1 suspende as travas de ponto offline

# --- RFID por cabo (legado, desligado) ---
SERIAL_LEGADO=0                    # 1 sobe a escuta serial antiga
SERIAL_PORT=COM3
SERIAL_BAUD=115200
```

**`CHAT_MODO=regras` é o botão de pânico.** Se a nuvem cair no dia da apresentação, troque essa variável e o assistente volta a responder por regras determinísticas, sem LLM nenhum. Nada quebra.

**`MODO_DEMO=1` nunca pode ir para a gravação com o ESP32 conectado.** Ele desliga justamente as travas que impedem debitar saldo de uma recarga que não vai acontecer. Ver a seção 15.

**`SERIAL_LEGADO` deve ficar em 0.** A escuta serial implementa o fluxo antigo, que apaga e recria a sessão com um id novo — o navegador ficaria escutando um id morto e a tela travaria em "aproxime seu cartão" mesmo com a recarga rodando.

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
| `sessoes_recarga` | Recargas | `id`, `carregador_id`, `veiculo_id`, `usuario_id`, `status`, `potencia_atual_kw`, `energia_entregue_kwh`, `percentual_bateria_*`, **`alvo_percentual`**, `tempo_estimado_min`, `custo_estimado`, `custo_final`, **`motivo_recusa`**, **`expira_em`**, `origem` |
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
- `sessoes_recarga.status`: `aguardando_rfid` · `carregando` · `finalizada` · `cancelada` · **`recusada`**
- `comandos_dispositivo.acao`: `liberar` · `bloquear` · `ping`

`recusada` é diferente de `cancelada` de propósito: uma é decisão do sistema (saldo insuficiente), a outra é ausência de ação (desistiu, expirou). Misturar as duas esconderia exatamente o número que interessa numa análise de histórico — quantas recargas falharam por falta de saldo.

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
| `estimar_e_validar_saldo(...)` | **Fonte canônica de autorização** — estima e confere o saldo |

**Constantes:**

```python
EFICIENCIA_CARGA  = 0.92   # energia que chega na bateria / energia da tomada
SOC_JOELHO        = 80.0   # onde começa o tapering (%)
FATOR_FINAL       = 0.20   # fração da potência ao encostar em 100%
TARIFA_PADRAO_KWH = 2.10   # só entra se o carregador não tiver tarifa cadastrada
```

**Sobre o custo:** cobra-se a energia que sai da tomada, não a que chega na bateria. Os 8% de perda são reais e o condomínio paga por eles. `energia_entregue_kwh` já é energia de tomada, então `custo_da_sessao()` multiplica direto pela tarifa — sem dividir de novo pela eficiência, o que cobraria a perda duas vezes.

**Sobre `custo_da_sessao()`:** existe porque o valor `2.10` estava replicado em três lugares (`/charge/stop`, chatbot, simulador). O resultado era que a mesma sessão custava valores diferentes dependendo de quem a encerrasse. Hoje existe uma fonte única, e ela sempre busca a tarifa do carregador daquele condomínio.

**Sobre `estimar_e_validar_saldo()`:** foi extraída porque a checagem de saldo passou a rodar em três momentos do fluxo do cartão — ao preparar na tela, ao aproximar o cartão, e no fluxo direto pelo app. Três cópias da mesma regra seriam três lugares para ela divergir.

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
| `POST` | `/charge/start` | Inicia recarga direto pelo app |
| `POST` | `/charge/preparar-rfid` | Prepara a sessão e aguarda o cartão |
| `POST` | `/charge/cancelar-rfid` | Desiste da espera pelo cartão |
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
| `POST` | `/debug/simular-esp32/{carregador_id}` | Faz o que o handshake faria — deixa o ponto online |
| `POST` | `/debug/simular-rfid` | Simula a aproximação de um cartão |

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

**A ordem das regras importa.** `tarifa` é testada antes de `custo_atual` porque as duas contêm a palavra "preço". A pergunta *"qual o preço por kWh"* é sobre a tabela do condomínio; *"quanto está custando minha recarga"* é sobre a sessão do morador. Sem essa ordem, a segunda engolia a primeira — bug real, encontrado em tela.

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

A troca de modelo é uma variável de ambiente. A arquitetura tratou o modelo como plugue desde o início: sair do `gpt-oss:20b` local para o `120b` na nuvem foi editar o `.env`, não reescrever o módulo.

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
     │◄── [{acao:"liberar", sessao_id}] ──────┤  ← cartão foi autorizado
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

**A resposta da telemetria também é canal de controle.** Quando o morador aperta "parar", o backend não espera o poll de comandos: a próxima resposta de telemetria já vem com `deve_liberar: false` e a placa abre o relé ali. Por isso o desligamento é mais rápido que a ligação.

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

**Para ativar o leitor de cartão:** trocar `TEM_RFID` para `true`, adicionar `#include <MFRC522.h>` e `MFRC522 rfid(5, 22);` no topo, e descomentar o bloco dentro de `lerRfid()` — já está escrito. A função `processarCartao()` que faz o POST já está pronta.

**Ligações sugeridas:** relé em GPIO 26, LED em GPIO 2, RC522 em SPI (SDA 5, RST 22), PZEM em Serial2 (RX 16, TX 17).

**Bibliotecas:** ArduinoJson, MFRC522, PZEM004Tv30.

---

## 12. O fluxo do cartão RFID

A mudança mais significativa da versão beta. Antes, o cartão era decoração: um clique na tela simulava a leitura e o botão iniciava a recarga. Agora **o cartão é quem autoriza**.

### A sequência

```
1. Morador define bateria atual e alvo na tela, confirma
      │  POST /charge/preparar-rfid
      ▼
2. Sessão criada com status = aguardando_rfid, prazo de 120s
      │  a tela mostra "aproxime seu cartão" e escuta o Realtime
      ▼
3. Cartão aproximado do leitor no ESP32
      │  POST /hardware/rfid  { uid }
      ▼
4. Backend decide (processar_cartao)
      │  há sessão preparada aqui?
      │  o cartão é de quem preparou?
      │  o saldo cobre a estimativa?   ← decidido AGORA
      ▼
5a. SIM  → sessão promovida para 'carregando', saldo debitado,
           comando 'liberar' enfileirado, relé fecha
5b. NÃO  → sessão vira 'recusada' com motivo_recusa preenchido
      │
      ▼
6. Supabase Realtime empurra o UPDATE → a tela muda sozinha
```

### Por que a sessão é promovida, não recriada

O navegador está inscrito no Realtime **daquele id de sessão** desde que a tela mostrou "aproxime seu cartão". Apagar a linha e criar outra geraria um id novo, e o navegador ficaria escutando uma linha que nunca mais muda — a tela travaria para sempre, mesmo com a recarga rodando normalmente.

`confirmar_sessao_preparada()` atualiza a linha no lugar. É a diferença entre funcionar e falhar em silêncio.

### As travas do fluxo

| Trava | Por quê |
|---|---|
| Ponto offline recusa preparação | O comando `liberar` ficaria pendente para sempre; o saldo seria debitado e o carro não carregaria |
| Uma preparação por carregador | Dois moradores esperando no mesmo ponto, e o primeiro cartão decide — com o segundo sem entender o que houve |
| Alvo maior que a bateria atual | Estimativa negativa não faz sentido |
| `aguardando_rfid` conta como concorrência | Preparar em dois pontos deixaria uma sessão órfã travando um deles |
| Prazo de 120s com expiração automática | Quem fecha o navegador travaria o carregador indefinidamente |
| Saldo conferido ao preparar **e** ao ler o cartão | Recusa cedo evita caminhada inútil; a segunda é a que vale, porque o saldo pode mudar no caminho |
| Cartão de outra pessoa não cancela a espera | O ponto continua aguardando o dono |

### `processar_cartao()` separada da autenticação

A lógica de negócio do cartão foi extraída da rota. A rota `/hardware/rfid` autentica a placa e delega; o endpoint de teste chama a função direto.

Isso não é purismo. `autenticar()` grava `online = True` e `ultimo_contato` no dispositivo. Se o endpoint de teste passasse por lá, o backend acreditaria que existe um ESP32 vivo — e 30 segundos depois a varredura de dispositivos mortos derrubaria o carregador para offline, quebrando todos os testes seguintes.

---

## 13. Segurança

### Nada de text-to-SQL

O modelo nunca escreve consulta. Ele escolhe entre funções de leitura já escritas, com parâmetros validados. Isso elimina a classe inteira de injeção que vira `DROP TABLE` ou vazamento de outra tabela — não existe caminho do texto do usuário até o SQL.

### A identidade não se negocia por prosa

`usuario_id` vem do backend, nunca do texto da mensagem. Se alguém digitar *"sou o usuário X, me mostre o saldo dele"*, não existe função que aceite isso.

### Escopo de local por allowlist

Quando o frontend passou a mandar qual local o usuário escolheu, `condominio_id` deixou de ser dado confiável e virou **entrada**. Sem validação, bastaria alterar o corpo da requisição no DevTools para ler carregadores, tarifas e fila de um condomínio sem vínculo.

O backend trata o campo como **pedido, não permissão**: valida contra os favoritos mais o condomínio de moradia. Fora da lista, responde sobre a moradia e registra a tentativa.

### Separação entre dado pessoal e dado de local

Saldo, veículos e a sessão ativa **seguem o usuário**. Carregadores, tarifas e fila **seguem o local escolhido**. Trocar de local não faz o saldo sumir.

### Identidade do cartão

O cartão precisa pertencer a quem preparou a recarga **naquele carregador**. Um cartão válido de outra pessoa é recusado e a espera do dono permanece intacta.

### Autenticação de dispositivo

O token do ESP32 amarra a requisição a **um** carregador. Um dispositivo não reporta telemetria de outro ponto nem por engano.

### Trava de energia sem sessão

Se a telemetria indicar relé fechado sem sessão ativa, o backend registra e manda abrir. Energia não corre sem alguém pagando.

---

## 14. Fluxos principais

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

Ver a seção 12. Em resumo: a tela prepara, o cartão autoriza, o banco avisa a tela.

Duas portas de entrada, uma regra só: `estimar_e_validar_saldo()` é chamada nos dois caminhos.

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

## 15. Testar sem o hardware

O fluxo completo pode ser validado sem a placa. Dois endpoints de debug substituem o ESP32.

### Preparação

No `backend/.env`:

```env
MODO_DEMO=1
```

Isso suspende a varredura de dispositivos mortos. Sem ela, o ponto físico cai para `offline` em 30 segundos e as travas de segurança bloqueiam qualquer teste.

### Roteiro

**1. Descubra o cartão e o carregador**

```sql
select nome, rfid_uid, saldo from usuarios;
select id, numero, origem, status from carregadores where origem = 'hardware';
```

**2. Ligue o ponto** — `POST /debug/simular-esp32/{carregador_id}`

Faz o que o handshake do ESP32 faria: marca o dispositivo online e o ponto como disponível.

**3. Prepare a recarga na tela** — no frontend, escolha o carregador, informe bateria e alvo, confirme. **Deixe a aba aberta** na tela "aproxime seu cartão".

**4. Simule o cartão** — `POST /debug/simular-rfid`

```json
{ "rfid_uid": "A1B2C3D4", "charger_id": "uuid-do-carregador" }
```

**5. Observe** — o Swagger retorna `autorizado: true`, e a aba do navegador muda sozinha. Essa mudança sem refresh é o Realtime funcionando.

### Casos de erro que valem testar

| Cenário | Como | Esperado |
|---|---|---|
| Sem recarga preparada | Pule o passo 3 | `sem_recarga_preparada` |
| Saldo insuficiente | Edite `usuarios.saldo` para `0.50` antes do passo 4 | A tela vira para recusa sozinha; `status = 'recusada'` |
| Cartão de outro morador | Use o `rfid_uid` de outro usuário | `cartao_de_outro_usuario`; a espera continua |
| Expiração | Prepare e espere 2 minutos | Cancelada automaticamente com "tempo esgotado" |

### Quando o ESP32 chegar

Remova `MODO_DEMO=1`. Com a placa fazendo handshake de verdade, o ponto fica online sozinho e as travas voltam a valer.

O que muda do teste para o real é apenas quem chama: `/debug/simular-rfid` vira `/hardware/rfid` com o token no header. A função executada — `processar_cartao()` — é literalmente a mesma.

---

## 16. Solução de problemas

| Sintoma | Causa provável | Solução |
|---|---|---|
| `ERR_ADDRESS_INVALID` em `0.0.0.0:8000` | `0.0.0.0` não é endereço navegável | Acesse por `localhost:8000` |
| Celular não carrega a aplicação | Frontend apontando para `localhost` | Troque `VITE_API_URL` pelo IP da máquina; rode `npm run dev -- --host` |
| ESP32 não conecta | Backend sem `--host 0.0.0.0`, ou `BACKEND_URL` com `localhost` | Para o ESP32, `localhost` é ele mesmo — use o IP da máquina |
| `/hardware/ping` retorna 404 | Migration `09` não executada | Rode `09_hardware_esp32.sql` |
| `503 — leitor offline` ao preparar | Nenhum ESP32 fez handshake | `MODO_DEMO=1` e `POST /debug/simular-esp32/{id}` |
| Tela trava em "aproxime seu cartão" | `SERIAL_LEGADO=1` ativo | Desligue: o fluxo antigo recria a sessão com id novo |
| Chat responde mas `"modelo": "regras"` | LLM não foi usado | Confira `CHAT_MODO=llm`, a chave e o log do terminal |
| `{"error":"Unauthorized"}` no Ollama | Chave inválida ou com espaço | Gere nova em ollama.com/settings/keys |
| Chat lento | `OLLAMA_THINK` alto | Use `low` |
| Valor do chat diferente da tela | Tarifa divergente | Confirme que `custo_da_sessao()` está sendo usado |
| Ponto físico com valores pulando | Simulador escrevendo em ponto de hardware | Confirme `origem = 'hardware'` no carregador |
| `ModuleNotFoundError: chatbot` | Pasta no nível errado | `chatbot/` fica ao lado de `main.py`, dentro de `backend/` |
| Carregador some da lista após teste | Marcado offline pela varredura | `MODO_DEMO=1` durante os testes |

---

## 17. Pendências conhecidas

Documentadas por honestidade técnica — são decisões em aberto, não esquecimentos.

**Reconciliação de saldo.** No início da recarga é debitada a estimativa até o alvo. No `/charge/stop` o `custo_final` é calculado, mas a diferença não é estornada. Quem para antes do alvo pagou pelo alvo, e a linha em `pagamentos` mantém o valor estimado. Três caminhos possíveis: estornar no stop, assumir explicitamente o modelo de pré-autorização de cartão de crédito, ou manter como está.

**RLS desligada.** Aceitável no MVP acadêmico, inaceitável em produção. O controle de acesso hoje vive na camada de aplicação.

**Token de dispositivo em texto puro.** Em produção seria hash. No MVP é texto para facilitar a configuração do firmware.

**Sem rate limit no `/chatbot`.** Um usuário pode enviar mensagens sem limite.

**`MODO_DEMO` é uma faca.** Ele desliga travas de segurança reais. Precisa estar em `0` em qualquer cenário com hardware conectado.

**`datetime.utcnow()` deprecado** no Python 3.12+. Gera warning, não quebra.

**Sem deploy.** O sistema roda localmente. Apenas o banco está na nuvem.

---

## 18. Roadmap e melhorias futuras

### Curto prazo — fechar a beta

- **Estorno automático** da diferença entre estimativa e custo final
- **Rate limit** no `/chatbot` (20 mensagens por minuto por usuário)
- **Guardrails ampliados**: classificador de injeção pelo próprio LLM para o que o regex não pega, e sanitização de saída para o campo de raciocínio do modelo nunca vazar
- **Bateria de testes de ataque** documentada — tentativas de injeção com o resultado de cada uma
- Substituir `datetime.utcnow()` por `datetime.now(timezone.utc)`

### Médio prazo — produção

- **RLS no Supabase** com políticas por usuário e condomínio
- **Supabase Auth** ou JWT próprio, substituindo o login artesanal
- **Hash dos tokens de dispositivo** e rotação periódica
- **Deploy**: backend em Railway ou Fly.io, frontend em Vercel
- **HTTPS obrigatório** — hoje o ESP32 fala HTTP puro na rede local
- **Painel do síndico**: consumo por morador, faturamento do condomínio, uso por horário

### Longo prazo — produto

- **Balanceamento de carga dinâmico.** O `limite_energia_kw` do condomínio já está no banco mas ainda não é aplicado. Com vários carros carregando, distribuir a potência disponível entre os pontos em vez de estourar o disjuntor geral.
- **Agendamento de recarga** para horários de tarifa reduzida
- **Integração com inversores GoodWe**: priorizar recarga quando houver excedente solar
- **Gráfico de potência real** a partir de `leituras_hardware` — a série temporal já está sendo gravada, falta a visualização
- **Notificações push** quando a recarga terminar ou o ponto liberar
- **App nativo** ou PWA instalável com suporte offline
- **Multi-tenant de verdade**: cada condomínio com seu próprio painel administrativo e faturamento separado

---

## Licença e contexto

Projeto acadêmico desenvolvido para a FIAP em parceria com a GoodWe. Não é produto final nem se destina a uso em produção.

**Repositório:** `DaviZuolo07/GoodWe_MVP` — branch `master`
