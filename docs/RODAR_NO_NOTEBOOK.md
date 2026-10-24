# Rodar o ChargeOps no notebook do estande (Next, 24/10/2026)

Roteiro para levantar **tudo** num computador que não é o do Davi: app do usuário, painel do admin, as duas APIs e o Totem Next (ESP32), usando **o Supabase do Davi** e **a chave do Ollama do Davi**. Siga na ordem e marque `[x]`. Não pule a seção 1: cada item dela já custou tempo.

```
  app do usuário       frontend/   http://192.168.137.1:5173   (celulares no hotspot)
  painel do admin      admin/      http://localhost:5174       (só no notebook)
  API pública          backend/    http://192.168.137.1:8000   (app + ESP32)
  API administrativa   backend/    http://localhost:8001       (só o painel)
  banco                Supabase do Davi (nuvem, Canadá): o notebook PRECISA de internet
  totem                ESP32 no hotspot 2,4 GHz do notebook, falando com a :8000
```

> **DUAS VAGAS (24/10).** Cada vaga é `carregador 5 V → relé → porta USB`, e o relé
> **libera energia de verdade** depois de **tag vinculada + botão da vaga**. O banco e o
> firmware já vêm assim: `preparar_totem.py --next` cria duas vagas e `PORTAS = 2` em
> `firmware/totem_next/config.h`. Os dois números **têm de bater**. O relé da vaga 2 é o
> **GPIO 16** (não o 12 do sketch de validação). Contrato de integração:
> [docs/UMA_VAGA.md](UMA_VAGA.md).

---

## Cola: a ordem do dia

| # | Passo | Pronto quando |
|---|---|---|
| 1 | Relógio do Windows sincronizado | `w32tm` mostra diferença menor que 1 s (seção 1.1) |
| 2 | Internet no notebook + hotspot 2,4 GHz, economia de energia desligada | `ipconfig` mostra `192.168.137.1` (seção 1.2) |
| 3 | Firewall 8000/5173 liberado, regras de bloqueio do python/node desativadas | seção 1.3 |
| 4 | Os 4 terminais no ar | `http://localhost:8000/` e `:8001/` → `{"status":"ok"...}` (seção 5) |
| 5 | **Celular** no hotspot abre `http://192.168.137.1:8000/hardware/v2/hora` | volta JSON com `ts` e `iso` (seção 1.4) |
| 6 | `python preparar_totem.py --next` | termina em `Pronto (totem Next, 2 vaga(s))` (seção 8) |
| 7 | Gravar o ESP32 | serial: `handshake ok: 2 porta(s) no backend, 2 nesta placa` (seção 8.3) |
| 8 | Roteiro da banca | seção 9, com o número esperado em cada passo |

---

## 0. O que vai no zip e o que NÃO vai

| Vai no zip | NÃO vai no zip (passar por canal privado e colar à mão) |
|---|---|
| a pasta do projeto, **sem** `node_modules/`, `dist/`, `__pycache__/` | `backend/.env` (chave secreta do Supabase, chaves JWT, chave mestra do ESP32, chave do Ollama, chave do MFA) |
| `*.env.example` (modelos sem valor) | `frontend/.env`, `admin/.env` |
| | `firmware/totem_next/segredos.h` (senha do Wi-Fi + chave da placa) |
| | `totem_virtual/.env` |

O repositório é **público**. Um `.env` que passou por zip, e-mail ou grupo de WhatsApp é chave vazada: se aconteceu, rotacione (seção 3).

## 1. Notebook: rede, relógio, firewall (uma vez, ~30 min)

Programas:

- [ ] **Python 3.13+** (marcar "Add to PATH"). Da raiz: `pip install -r requirements.txt`
- [ ] **Node 22+**. Depois: `npm install` em `frontend/` e em `admin/`
- [ ] **Arduino IDE 2** com o que está na seção 8.1 (placa esp32 3.3.12 + 3 bibliotecas + driver USB)

### 1.1 Relógio

O ESP32 assina cada requisição com a hora. Notebook com relógio fora = `401 fora_da_janela` em todo handshake, e o código do autenticador do painel também não confere (já aconteceu: o PC estava 249 s atrasado).

- [ ] Configurações → Hora e idioma → Data e hora → **Definir hora automaticamente: ativado** → **Sincronizar agora**
- [ ] Conferir (PowerShell): `w32tm /stripchart /computer:time.windows.com /samples:3 /dataonly` → os três valores perto de `+00.0000000s` (menos de 1 s). Se der erro de serviço: PowerShell **como administrador** → `net start w32time` → `w32tm /resync`
- [ ] Mudou o relógio com o `uvicorn` rodando? **Reinicie o uvicorn.**

### 1.2 Rede do estande: hotspot do Windows em 2,4 GHz

O ESP32 **não enxerga 5 GHz**. O notebook, os celulares da demonstração e o ESP32 têm de estar **na mesma rede**, e o notebook precisa de **internet** (o banco é o Supabase na nuvem).

- [ ] Dê internet ao notebook: Wi-Fi do evento, cabo, ou — o que funcionou em 22/10 — **o celular por cabo USB** (iPhone: Acesso Pessoal; Android: Ancoragem USB). Por cabo, o Wi-Fi do notebook fica livre para o hotspot
- [ ] Configurações → Rede e Internet → **Hotspot móvel**:
  - **Compartilhar minha conexão de internet de:** a conexão do passo anterior
  - **Editar** → nome sem acento (ex.: `ChargeOps`), senha com 8+ caracteres, **Banda de rede: 2,4 GHz** → **Salvar**
  - **Economia de energia: desativada** (ela desliga o hotspot quando ninguém está conectado — o ESP32 reiniciando conta como "ninguém")
  - Ligue o hotspot
- [ ] `ipconfig` → o adaptador **"Conexão Local* NN"** (o do hotspot) tem **Endereço IPv4 192.168.137.1**. É esse IP que vai no `segredos.h` e nos celulares
- [ ] Se a banda voltar sozinha para "Qualquer um disponível", o adaptador Wi-Fi do notebook está preso ao canal da rede de internet: dê internet por **cabo** (USB do celular ou Ethernet), não por Wi-Fi
- Plano B: **hotspot do celular** com o notebook conectado nele. iPhone: Ajustes → Acesso Pessoal → **Maximizar Compatibilidade** (sem isso, só 5 GHz). O IP do notebook muda: veja no `ipconfig` e use esse no `segredos.h` e nos celulares

### 1.3 Firewall

PowerShell **como administrador**:

```powershell
New-NetFirewallRule -DisplayName "ChargeOps API 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Any
New-NetFirewallRule -DisplayName "ChargeOps app 5173" -Direction Inbound -Protocol TCP -LocalPort 5173 -Action Allow -Profile Any
```

Cancelar (ou não responder) o aviso do Windows na primeira vez que o Python ou o Node abrem uma porta cria uma regra de **BLOQUEIO** para o programa inteiro, e **bloqueio vence liberação**. Liste e desative:

```powershell
Get-NetFirewallRule -Action Block -Enabled True | ? DisplayName -match "python|node" | ft DisplayName, Profile
Get-NetFirewallRule -Action Block -Enabled True | ? DisplayName -match "python|node" | Disable-NetFirewallRule
```

- [ ] A primeira linha não lista mais nada depois da segunda
- [ ] Se aparecer de novo o aviso do Windows ao subir o uvicorn ou o vite: **Permitir acesso**, com **Redes privadas e públicas** marcadas

### 1.4 Prova da rede, antes de ligar a placa

Com o terminal 1 da seção 5 no ar:

- [ ] Num **celular conectado ao hotspot**, abra `http://192.168.137.1:8000/hardware/v2/hora` → JSON com `ts` e `iso`
- [ ] No mesmo celular, `http://192.168.137.1:5173` → abre o app

Se o celular não abre, o ESP32 também não vai conectar. Não grave a placa antes disto passar: volte à 1.3 (firewall) e confira que o uvicorn tem `--host 0.0.0.0`.

## 2. Os `.env` (com as contas do Davi)

Copie de cada `.env.example` e preencha **os mesmos valores do PC do Davi**: o banco é o mesmo, então as chaves são as mesmas. Se alguma for rotacionada hoje (seção 3), use a nova.

**`backend/.env`**, as linhas que importam:

| Variável | De onde vem |
|---|---|
| `SUPABASE_URL`, `SUPABASE_KEY` (`sb_secret_...`), `SUPABASE_ANON_KEY` | Supabase do Davi → Settings → API Keys |
| `JWT_PRIVATE_JWK` | a mesma do PC do Davi (a pública está importada no Supabase) |
| `ADMIN_MFA_KEY` | a mesma do PC do Davi: é ela que abre o segredo do autenticador gravado no banco |
| `DEVICE_MASTER_KEY` | a mesma do PC do Davi: a chave do ESP32 é derivada dela |
| `OLLAMA_API_KEY`, `OLLAMA_HOST=https://ollama.com`, `OLLAMA_MODEL`, `CHAT_MODO=llm` | conta Ollama do Davi |
| `GOOGLE_CLIENT_ID` | opcional: só para operadores entrarem com Google (seção 7) |
| `FRONTEND_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173,http://192.168.137.1:5173` |
| `AMBIENTE=desenvolvimento`, `MODO_DEMO=0`, `FUSO_HORARIO=America/Sao_Paulo` | como está |

**Não** escreva `ADMIN_MFA=opcional`: essa opção não existe mais. Se aparecer no `.env`, apague. O segundo fator agora é sempre obrigatório.

**`frontend/.env`**: `VITE_SUPABASE_URL` e `VITE_SUPABASE_KEY` (chave **publicável**). Sem `VITE_API_URL`, o app deduz a API do endereço que abriu a página, e é isso que faz funcionar no celular.

**`admin/.env`**: vazio serve (fala com `localhost:8001`). Para o Google, acrescente `VITE_GOOGLE_CLIENT_ID=<o mesmo do backend>`.

Conferência rápida (de `backend/`): `python provisionar.py testar-llm` → **PASSOU** (com 401, gere outra chave em ollama.com/settings/keys).

## 3. Chaves: o que rotacionar

Rotacionar = gerar uma nova e invalidar a velha. A ordem abaixo é do mais urgente para o que só se troca se vazou. **No dia da banca, não rotacione nada que obrigue a regravar a placa.**

| Chave | Rotacionar? | Como | Efeito colateral |
|---|---|---|---|
| `SUPABASE_KEY` (secreta, `sb_secret_`) | **Sim, se o `.env` viajou** em zip ou mensagem. Ela dá acesso total ao banco | Supabase → Settings → API Keys → **Create new secret key**, cole no `.env` dos dois computadores, depois **revogue** a antiga | nenhum, se trocar nos dois `.env` |
| `JWT_PRIVATE_JWK` | **Sim, se o `.env` viajou**: com ela se forja login de qualquer morador | `python provisionar.py chave-jwt` → cole a privada no `.env` → Supabase → Settings → **JWT Keys** → importe a pública como *standby* → **Rotate** | todo morador precisa entrar de novo. **Sem importar a pública no Supabase, o Realtime do app para** (o painel ao vivo congela) |
| `ADMIN_JWT_PRIVATE_JWK` | Recomendado: separa o token do painel do token do app | `python provisionar.py chave-jwt-admin` → `.env` | quem estiver no painel entra de novo. Não vai para o Supabase |
| `OLLAMA_API_KEY` | Se vazou | ollama.com/settings/keys → nova → `.env` → reiniciar a API | nenhum |
| `DEVICE_MASTER_KEY` | **Só se vazou.** Trocar invalida a chave do ESP32 | `python provisionar.py chave-mestra` → `.env` → `python preparar_totem.py --next` → novo `segredos.h` → **gravar o ESP32 de novo** | o ESP32 recebe 401 até ser regravado |
| `ADMIN_MFA_KEY` | **Não.** Trocar quebra o autenticador de todo gestor | se precisar: nova chave e depois `python provisionar.py gestor-mfa --nome "Davi Admin" --remover` | todo gestor recadastra o app autenticador |
| `SUPABASE_ANON_KEY` / `VITE_SUPABASE_KEY` | Não: é pública por definição (vai no navegador) | — | — |
| `GOOGLE_CLIENT_ID` | Não: é público | — | — |
| Senha das contas de teste (`TotemNext#2026`) | **Sim**: está escrita no repositório público | `python preparar_totem.py --next --senha "<outra forte>"` | — |

Regra para o dia: **um** `.env` de referência (o do notebook). O do PC do Davi recebe as mesmas chaves novas, ou fica desligado. Duas APIs com chaves diferentes no mesmo banco = ESP32 e painel recusados.

## 4. Banco: nada a rodar

As migrations moram **no Supabase**, não no computador. Trocar de notebook **não exige rodar nada de novo**: o banco do Davi já tem de 01 a 23.

| # | O que faz | Situação |
|---|---|---|
| 01–08 | esquema, seed (3 condomínios), login, multi-condomínio, favoritos | aplicadas. **Não rode de novo**: o 02 e o 07 re-inserem seed |
| 09–22 | ESP32, RFID, segurança, produto, cartões, protocolo v2, fontes/cobrança, escala, MFA, perfil, admin global, ociosidade, cargo NEXT | aplicadas |
| 23 | `operadores_google`, `leituras_sessao` (gráfico de toda recarga), `percentual_origem = 'celular'` | **confira** com a consulta abaixo; se faltar, rode uma vez no SQL Editor (idempotente) |
| 98 `reset_total` | **apaga todas as contas e todo o histórico** | **NÃO rodar.** Ferramenta, não migration |
| 99 `limpeza` | apaga recargas, extrato, leituras | **NÃO rodar** sem querer zerar a demonstração |

Conferência do 23 (resultado esperado: 2 linhas):

```sql
select table_name from information_schema.tables
 where table_schema = 'public' and table_name in ('operadores_google', 'leituras_sessao');
```

Teste de invasão contra o banco real (de `backend/`): `python provisionar.py verificar` → tudo **PASSOU**.

## 5. Subir (4 terminais)

Abra **quatro** janelas do PowerShell, cada uma na pasta indicada, nesta ordem:

```powershell
# 1 - API pública: 0.0.0.0 porque o ESP32 e os celulares vêm pela rede   (de backend/)
uvicorn main:app --host 0.0.0.0 --port 8000
# 2 - API do painel: SÓ no notebook                                        (de backend/)
uvicorn main_admin:app --host 127.0.0.1 --port 8001
# 3 - app do usuário, aberto para os celulares                             (de frontend/)
npm run dev -- --host
# 4 - painel do admin                                                      (de admin/)
npm run dev
```

- [ ] <http://localhost:8000/> e <http://localhost:8001/> → `{"status":"ok"...}`
- [ ] O terminal 3 mostra `Network: http://192.168.137.1:5173/`
- [ ] A API do painel **não sobe** sem `ADMIN_MFA_KEY` (de propósito)
- [ ] "WinError 10013" = porta ocupada: veja a seção 1 do `RODAR_E_VALIDAR.md`
- [ ] **Não feche o terminal 1**: o laço de 10 s que reparte a energia, promove a fila e encerra esperas vencidas roda dentro dele

## 6. Admin da plataforma (Davi)

A conta `Davi Admin` já existe no banco do Davi. Basta entrar em <http://localhost:5174>.

- **Primeira vez, ou a conta foi apagada:** `python provisionar.py admin-global --nome "Davi Admin"`. A senha é **gerada** e aparece **uma vez**.
- **Login:** nome + senha → se o autenticador ainda não está cadastrado, o painel mostra **só** a tela do QR code. Escaneie, confirme com um código e o painel abre.
- **Daí em diante:** nome + senha + código de 6 dígitos, sempre.
- **Perdeu o celular:** `python provisionar.py gestor-mfa --nome "Davi Admin" --remover`.

## 7. Operadores dos condomínios (Google + sua aprovação)

1. Google Cloud Console → Credenciais → **ID do cliente OAuth** "Aplicativo da Web" → origem `http://localhost:5174`. Client ID em `GOOGLE_CLIENT_ID` (backend) e `VITE_GOOGLE_CLIENT_ID` (admin); reinicie os dois.
2. O operador → **Entrar com Google** → escolhe o condomínio → "Pedido enviado".
3. Você → aba **Operadores** → **Aprovar**. Nasce uma conta de gestor presa àquele condomínio, sem senha.
4. **Revogar** corta na hora.

Sem o Client ID, o botão do Google não aparece e o resto funciona normalmente.

## 8. Totem Next: banco, segredos e gravação

### 8.1 Arduino IDE (uma vez por computador)

| O quê | Onde | Versão |
|---|---|---|
| Placa **esp32** (Espressif Systems) | Ferramentas → Placa → Gerenciador de Placas → "esp32" | **3.3.12** |
| **ArduinoJson** (Benoit Blanchon) | Ferramentas → Gerenciar Bibliotecas | **7.4.3** |
| **MFRC522** (GithubCommunity) | Gerenciar Bibliotecas | **1.4.12** |
| **LiquidCrystal I2C** (Frank de Brabander) | Gerenciar Bibliotecas | **1.1.2** |
| Driver USB | CP210x (Silicon Labs) ou CH340 (WCH), conforme o chip ao lado do conector da placa | — |

Ao plugar a placa, uma porta **COM** nova aparece em Ferramentas → Porta. Se não aparecer: cabo só de carga (troque) ou falta o driver.

### 8.2 Banco e segredos

```powershell
# de backend/   (duas vagas: o padrão. --vagas 1 ou --vagas 4 para outra montagem)
python preparar_totem.py --next
```

O comando cria ou ajusta o estande (limite **15 kW = 2 × 7,5 kW** na escala 1:1000, ponta = metade), as vagas **T1 e T2** com **divisão por tempo ligada**, a placa (sem porta solar, rotulada `simulado`) e 3 contas de teste com tag (`Ana Totem` AA000001 e `Bia Totem` BB000002 com R$ 100; `Caio Totem` CC000003 com R$ 0). Rodar de novo é seguro: a chave da placa não muda. Ele imprime o bloco do `segredos.h` e termina com:

```
Pronto (totem Next, 2 vaga(s)). ...
  4. Monitor serial a 115200: "handshake ok: 2 porta(s) no backend, 2 nesta placa".
  Limite do estande: 15 kW. ...
```

- [ ] `firmware/totem_next/config.h` tem `constexpr uint8_t PORTAS = 2;`
- [ ] Copie `firmware/totem_next/segredos.exemplo.h` para `segredos.h` e preencha: `WIFI_SSID` (nome **exato** do hotspot), `WIFI_SENHA`, `BACKEND_URL "http://192.168.137.1:8000"` e as duas linhas `DEVICE_ID` / `DEVICE_KEY_HEX` que o comando imprimiu

### 8.3 Gravar

1. Fiação conferida: relé da vaga 2 no **GPIO 16** (não no 12); botões 32 e 33; MFRC522 em **3,3 V**
2. Arduino IDE → Arquivo → Abrir → `firmware/totem_next/totem_next.ino` (abre a pasta inteira, com as abas)
3. Ferramentas → Placa **ESP32 Dev Module**; Porta: a COM da placa
4. **Verificar** (✓) → termina em "Compilação concluída" sem erro
5. **Carregar** (→). Se parar em `Connecting........`, segure o botão **BOOT** da placa até aparecer `Writing at ...`
6. Ferramentas → Monitor Serial → **115200** e **Nova linha**

Partida boa (os `ms`, o `boot` e o IP mudam; a ordem e os textos são estes):

```
placa ligou: reles abertos (boot ..., firmware totem-next-1.2, sem sensor: modelo de carga)
2 vaga(s) neste firmware
LCD 16x2 em 0x27                                  <- ou: LCD nao encontrado (...): seguindo sem tela
monitor serial (Nova linha): t <UID> = tag | b [vaga] = botao | s = status
Wi-Fi caiu                                        <- normal na partida: ainda conectando
status: sem Wi-Fi
Wi-Fi voltou (192.168.137.xx)
servidor voltou a responder
handshake ok: 2 porta(s) no backend, 2 nesta placa
status: vaga 1 livre
status: vaga 2 livre
```

- [ ] **Nenhum relé fica fechado** depois de ligar a placa
- [ ] O LED azul da placa acende depois do `handshake ok`
- [ ] Sem `ATENCAO:` abaixo do handshake

Se algo der errado aqui: tabela "Se der errado" de [`firmware/totem_next/README.md`](../firmware/totem_next/README.md) e seção 11 abaixo.

### 8.4 Plano B pelo monitor serial

Sem leitor ou sem botão, o monitor serial faz as duas coisas pelo mesmo caminho da tag de verdade:

| Digite | Faz |
|---|---|
| `t D3F5BFD9` | aproxima a tag com esse UID |
| `b` / `b 2` | aperta o botão da vaga 1 / da vaga 2 |
| `s` | imprime o estado das vagas: %, W, Wh, tempo fechado e previsão de fim |

É também o jeito de ter uma **segunda tag** sem segundo cartão: `t BB000002` + `b 2` = Bia Totem na vaga 2.

## 9. Roteiro da banca (duas vagas), com o número esperado em cada passo

Antes de começar: dois celulares para carregar, um celular com o app (pode ser um dos dois), o painel aberto em <http://localhost:5174> na aba **Sala Next**, o monitor serial visível. Limite do estande em **15 kW** e **sem pico** (Sala Next → Demanda do estande → `Encerrar pico`, se estiver ligado).

**Contas.** Vaga 1: uma conta criada **ao vivo** no app, com a tag física `D3F5BFD9`. Vaga 2: `Bia Totem` (tag `BB000002`, R$ 100) — por um segundo cartão vinculado a ela, ou pelo serial (`t BB000002`, `b 2`). Uma conta carrega **uma** vaga por vez: a mesma tag na outra vaga dá `Voce ja esta carregando em outra vaga`.

### 9.1 Cadastro, tag e pagamento por RFID

| # | Faça | Número esperado |
|---|---|---|
| 1 | Celular no hotspot → `http://192.168.137.1:5173` → **Criar conta** no **Estande Next** (cargo NEXT, só celular) → escolher o modelo do celular | Carteira com **R$ 100,00** (bônus de boas-vindas, `config.BONUS_BOAS_VINDAS`). O celular escolhido define a bateria (Wh) e os watts do modelo |
| 2 | Aproxime a tag `D3F5BFD9` e aperte o botão 1 **antes** de vincular | LCD `Tag nao` / `cadastrada`, depois `Cadastre no app` / `Tag D3F5BFD9`. Serial `rfid vaga 1: cartao_nao_cadastrado / nenhuma`. **Nenhum relé fecha** |
| 3 | App → Configurações → cartão RFID → `D3F5BFD9` | tag vinculada à conta |
| 4 | Aperte o botão 2 **sem** tag | LCD `Aproxime o` / `cartao primeiro`; nada fecha |
| 5 | Tag + **botão 1** | LCD `Vaga 1 liberada` / `Boa recarga, <nome>!`. Serial `vaga 1 LIBERADA (rfid)` e `divisao por tempo (janela 30s): 1:100% 2:0%`. **Clique do relé 1, o celular 1 começa a carregar.** No app, saldo **reservado**: o valor estimado da recarga até 100% sai do saldo disponível e aparece como reservado (com a conta de teste e o celular padrão de 15 Wh partindo de 20%: **R$ 18,75**, saldo 100,00 → 81,25) |
| 6 | Bia na **vaga 2** (cartão, ou `t BB000002` + `b 2`) | `vaga 2 LIBERADA (rfid)`; serial `1:100% 2:100%`; **os dois relés fechados, os dois celulares carregando: recarga simultânea.** Bia: R$ 18,75 reservados |
| 7 | (opcional) `t CC000003` + `b 2` com a vaga 2 livre | LCD `Saldo insuficiente` / `Precisa R$ 18,75` / `Recarregue no app`; nada fecha |

### 9.2 Telemetria e gráficos ao vivo

| # | Onde | Número esperado |
|---|---|---|
| 8 | Serial (a cada 5 s) ou `s` | `status: vaga N carregando \| xx.x% de 100% \| 7.50 W (rele fechado) \| ... \| tempo fechado 100%` — com o celular padrão, o % sobe ~**0,77 ponto por minuto** (7,5 W × 92% ÷ 15 Wh) |
| 9 | App → recarga em andamento | potência **7,5 kW** (escala 1:1000 de 7,5 W), %, "Termina em ...", gráficos de potência e bateria andando a cada ~6 s (um lote de telemetria) |
| 10 | Painel → **Sala Next** | as duas vagas ao vivo, "Tempo fechado 100%"; Sessões → clicar na sessão → energia, conta e **de onde vêm os números** (`modelo`) |
| 11 | Custo | fora da ponta, vaga cheia: **R$ 0,14 por minuto** (7,5 W × 1 min = 0,125 Wh = 0,125 kWh na escala × R$ 1,15). Cada **1 Wh real = R$ 1,15** |
| 12 | Celular Android com o app aberto no Chrome | "lido do seu celular" no % (o modelo se corrige pela bateria real). Por IP precisa de `chrome://flags` → *Insecure origins treated as secure* → `http://192.168.137.1:5173` |

### 9.3 Water-filling: o limite do estande vira tempo de relé

Painel → **Sala Next → Demanda do estande** → digite o limite → **Aplicar limite**. O backend refaz a divisão em **até 10 s** e o ESP32 refaz o rodízio na resposta seguinte (até ~6 s). Os dois celulares abaixo de 80%:

| # | Limite | Serial do ESP32 | O que se **vê e ouve** | Sala Next / app |
|---|---|---|---|---|
| 13 | **15 kW** | `1:100% 2:100%` | os dois relés fechados, silêncio | Tempo fechado 100% / 100% |
| 14 | **7,5 kW** | `1:50% 2:50%` | **um clique a cada 15 s**: a vaga 1 carrega de 0 a 15 s, a vaga 2 de 15 a 30 s. **Nunca as duas juntas** — a fonte de 5 V alimenta um celular por vez | 50% / 50%; o gráfico vira um "pente"; a previsão de término **dobra** |
| 15 | **5 kW** | `1:33% 2:33%` | 10 s cada, depois 10 s os dois abertos | 33% / 33%; previsão × 3 |
| 16 | **3 kW** | `1:20% 2:20%` | 6 s cada, 18 s os dois abertos | 20% / 20% (o mínimo: 20% de 7,5 kW = 1,5 kW) |
| 17 | **2,5 kW** | `1:33% 2:0%` | só o relé 1 clica (10 s de 30); o relé 2 fica **aberto** | a vaga 2 pausa **sem encerrar**: sessão viva, saldo reservado. Quem chegou por último pausa primeiro |
| 18 | volte a **15 kW** | `1:100% 2:100%` | os dois fecham | as duas voltam, nada encerrado |

Frase para a banca: *"o relé só liga e desliga; o water-filling do backend vira tempo de relé fechado numa janela de 30 s, com as vagas uma depois da outra. A qualquer instante, o que está fechado cabe no limite."*

### 9.4 Horário de pico e tarifa

| # | Faça | Número esperado |
|---|---|---|
| 19 | Limite em 15 kW, as duas carregando → **Simular pico agora (2 h)** | o botão vira `Encerrar pico`; o limite efetivo cai para **7,5 kW** (× 0,5); serial `1:50% 2:50%`; relés alternando como no passo 14. **Vale no sábado**: no estande (perfil bancada) o pico ligado pelo painel ignora a regra de dia útil |
| 20 | Tarifa | a energia gasta durante o pico entra no balde **ponta**: R$ 1,15 × `ponta_multiplicador_tarifa` (padrão **1,5** → **R$ 1,725/kWh**). Por vaga, na ponta a 50%: **R$ 0,11 por minuto** (metade da energia, 1,5× o preço) contra R$ 0,14 fora dela |
| 21 | **Encerrar pico** | limite volta a 15 kW, `1:100% 2:100%` |

### 9.5 Fila de energia (quando não cabe mais ninguém)

| # | Faça | Número esperado |
|---|---|---|
| 22 | Encerre a Bia (a mesma tag/serial na vaga 2). Limite em **2,5 kW** com só a vaga 1 carregando | vaga 1: `1:33%` (2,5 de 7,5 kW) |
| 23 | Bia na vaga 2 de novo | LCD `Vaga 2 na espera` / `Sem energia`, depois `agora` / `Fila: 1`, depois `Liga sozinha depois`. Serial `rfid vaga 2: aguardando_energia / nenhuma`. **R$ 18,75 reservados** (saldo da Bia cai) e o relé 2 **não** fecha: 1,25 kW para cada seria menos que o mínimo de 1,5 kW |
| 24 | Limite de volta a **15 kW** | em **até 10 s** a fila anda sozinha: serial `comando liberar na vaga 2` e `vaga 2 LIBERADA (comando)`, depois `1:100% 2:100%` |

### 9.6 Recibo com estorno

| # | Faça | Número esperado |
|---|---|---|
| 25 | A mesma tag na mesma vaga (tag física + botão 1) | LCD `Vaga 1 encerrada` / `Custo R$ x,xx` / `Retire o celular`. Serial `rfid vaga 1: encerrada / desligar` e `vaga 1 CORTADA (rfid)`. Relé abre na hora |
| 26 | App → recibo / Carteira | **custo = energia × tarifa** (fora da ponta, R$ 1,15 por Wh real; o que caiu no pico, R$ 1,725) e **estorno = reservado − custo**. Exemplo conferido no teste: 1,0 Wh entregue → custo **R$ 1,15**, estorno **R$ 17,60** de R$ 18,75 |

### 9.7 O que é medido e o que é modelo (diga isto)

- **Real:** a tag, o botão, o relé (o clique que se ouve é o contato abrindo e fechando a energia do celular), o tempo de relé fechado, o saldo, a reserva, a cobrança e o estorno. O celular **recebe energia de verdade**.
- **Modelo:** os **números** de potência e energia. Não há sensor de corrente (INA219) nesta montagem: o ESP32 calcula pela física do celular cadastrado (curva CC-CV: cheia até 80%, caindo até 100%) e só integra energia com o relé **fechado**. Tudo é gravado com origem **`simulado`**, nunca `medido`, e o painel diz isso em cada sessão.
- **Escala 1:1000:** 7,5 W da porta USB aparecem como 7,5 kW, para o estande se comportar como um eletroposto de condomínio. O backend aplica a escala; a placa fala em W.
- **O que o modelo não sabe:** se o celular foi desplugado ou se a fonte não deu conta. A vaga segue contando até a tag encerrar. É por isso que o projeto completo tem um INA219 por vaga (ADR-022).
- **Uma fonte para duas portas:** com as duas vagas cheias, o carregador de 5 V reparte a corrente e cada celular recebe menos que os 7,5 W do modelo. Com o limite em 7,5 kW, o escalonamento nunca fecha as duas ao mesmo tempo — é o mesmo mecanismo que protege o quadro de um condomínio.

## 10. Como a demanda funciona (para responder a banca)

**Limite contratado por condomínio.** Cada local tem `limite_potencia_kw`. Na **janela de ponta** (dias úteis, ex.: 18h–21h; no estande, quando o painel liga), o limite efetivo é `limite × ponta_fator_limite` e o kWh da rede custa `tarifa × ponta_multiplicador_tarifa`.

**Um alocador só** (`backend/demanda.py`, `distribuir_fontes`), a cada 10 s e a cada recarga que começa ou termina:

1. **Cargas fixas** (relé sem divisão) levam o que pedem.
2. **Sol** (quando o local tem FV): primeiro para quem está em modo FV, depois para o rápido.
3. **Rede restante: água no balde (water-filling).** Quem pede menos que a parte igual leva o que pede, e a sobra é redividida. Ninguém recebe mais do que a bateria aceita.
4. **Mínimo do carregador** (HCA G2: 6 A = 1,4 kW mono). Quem não alcança o mínimo **pausa**, começando por quem chegou por último. No totem, o mínimo é **20% da vaga** (1,5 kW na escala).
5. **Admissão.** Uma recarga nova é simulada **só com a rede**. Se empurrasse alguém para baixo do mínimo, vai para a **fila de energia** com o saldo reservado e liga sozinha quando sobrar potência.

**No totem (relé liga/desliga):** a fração `alocado ÷ pedido` vira **tempo de relé fechado** numa janela de 30 s, com as vagas em sequência (McNaughton). A soma das fechadas, em qualquer instante, cabe no limite.

**Duas vagas** (estande 15 kW, 2 celulares de 7,5 kW abaixo de 80%):

| Situação | Limite | Cada vaga | Relés fechados ao mesmo tempo |
|---|---|---|---|
| fora da ponta | 15 kW | 7,5 kW (100%) | 2 |
| limite 7,5 kW, ou ponta (× 0,5) | 7,5 kW | 3,75 kW (50%) | 1, em rodízio |
| limite 5 kW | 5 kW | 1,667 kW (33%) | 1 |
| limite 3 kW | 3 kW | 1,5 kW (20%, o mínimo) | 1 |
| limite 2,5 kW | 2,5 kW | a primeira 2,5 kW (33%), a segunda **pausada** | 1; tag nova vai para a fila |

Acima de 80% o celular pede menos (curva CC-CV), e a fração dele sobe sozinha.

**Cobrança:** cada kWh entra num de três baldes (solar, rede fora da ponta, rede na ponta), com os preços congelados no início da recarga. O saldo é reservado no início e a diferença é estornada no fim. No totem, o kWh é o do **modelo de carga** (rotulado `simulado`).

## 11. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Celular não abre `http://192.168.137.1:8000/hardware/v2/hora` | firewall, regra de bloqueio do python, uvicorn sem `--host 0.0.0.0`, celular em outra rede | seção 1.3; terminal 1 da seção 5; conferir o Wi-Fi do celular |
| ESP32 `status: sem Wi-Fi` para sempre | hotspot em 5 GHz, nome ou senha diferentes, hotspot desligado pela economia de energia | seção 1.2; `WIFI_SSID` idêntico ao nome da rede |
| ESP32 `sem resposta do servidor` | IP errado no `BACKEND_URL`, firewall | o teste do celular (seção 1.4) tem de passar primeiro |
| `recusado (fora_da_janela)` / LCD `Relogio servidor` | relógio do notebook | seção 1.1; reiniciar o uvicorn |
| `recusado (assinatura_invalida)` / LCD `Chave invalida` | `.env` com outra `DEVICE_MASTER_KEY` | `preparar_totem.py --next` neste notebook e regravar o `segredos.h` |
| `ATENCAO: o backend tem N porta(s) e este firmware tem PORTAS = M` | `--vagas` ≠ `PORTAS` | `python preparar_totem.py --next --vagas M` e apertar EN na placa |
| Placa reinicia em laço / `flash read err` / gravação para em `Connecting...` | algo no GPIO 12, ou BOOT não pressionado | IN2 no **GPIO 16**; segurar **BOOT** na gravação |
| `LCD nao encontrado` | sem LCD, ou mal ligado | o totem funciona sem ele: o serial é a tela |
| Relé fica fechado depois de ligar a placa | módulo ativo em LOW | `RELE_ATIVO_EM_LOW 1` em `config.h` e regravar |
| Celular conecta e desconecta com as duas vagas fechadas | o carregador de 5 V não aguenta as duas | limite em 7,5 kW: uma vaga por vez (seção 9.3) |
| "Simular pico" não muda nada | backend antigo (antes de 24/10) num fim de semana | atualize (`git pull`) e reinicie o uvicorn |
| Arduino IDE: `ArduinoJson.h: No such file or directory` | biblioteca não instalada neste computador | seção 8.1 |
| `pytest` falha com `ModuleNotFoundError: servidor_v21` | sobraram `backend/testes/test_maquina_de_estados.py` e `test_roteiro.py` de uma cópia antiga | apague os dois (a versão atual mora em `totem_virtual/testes/`) |
| Painel: "mfa_pendente" | conta sem autenticador | cadastrar pelo QR que o painel mostra |
| Código do autenticador sempre inválido | relógio do celular ou do notebook | `python provisionar.py testar-mfa --nome "Davi Admin"` |
| App no celular não abre | firewall 5173 ou `FRONTEND_ORIGINS` sem `192.168.137.1` | seções 1.3 e 2 |
| Nada responde, app e painel com erro de banco | notebook sem internet (o Supabase é na nuvem) | seção 1.2: internet pelo celular por cabo USB |
| Assistente responde só "regras" | chave Ollama revogada | `python provisionar.py testar-llm` |
