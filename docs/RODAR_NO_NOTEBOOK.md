# Rodar o ChargeOps no notebook do estande (Next, 23/10/2026)

Roteiro para levantar **tudo** num computador que não é o do Davi: app do usuário, painel do admin, as duas APIs e o Totem Next (ESP32), usando **o Supabase do Davi** e **a chave do Ollama do Davi**. Siga na ordem e marque `[x]`.

```
  app do usuário       frontend/   http://<IP do notebook>:5173   (celulares na mesma rede)
  painel do admin      admin/      http://localhost:5174          (só no notebook)
  API pública          backend/    http://<IP do notebook>:8000   (app + ESP32)
  API administrativa   backend/    http://localhost:8001          (só o painel)
  banco                Supabase do Davi (nuvem, Canadá) - o MESMO de sempre
  totem                ESP32 na mesma rede Wi-Fi 2,4 GHz, falando com a :8000
```

> **UMA VAGA (23/10).** O totem montado tem **uma** vaga, e o relé dela **libera
> energia de verdade**. O banco e o firmware já vêm assim: `preparar_totem.py
> --next` cria uma vaga e `PORTAS = 1` em `firmware/totem_next/config.h`. Os dois
> números **têm de bater** - é a única coisa a mudar se amanhã forem quatro
> (`--vagas 4` e `PORTAS = 4`). Detalhes e contrato de integração:
> [docs/UMA_VAGA.md](UMA_VAGA.md).

---

## 0. O que vai no zip e o que NÃO vai

| Vai no zip | NÃO vai no zip (passar por canal privado e colar à mão) |
|---|---|
| a pasta do projeto, **sem** `node_modules/`, `dist/`, `__pycache__/` | `backend/.env` (chave secreta do Supabase, chaves JWT, chave mestra do ESP32, chave do Ollama, chave do MFA) |
| `*.env.example` (modelos sem valor) | `frontend/.env`, `admin/.env` |
| | `firmware/totem_next/segredos.h` (senha do Wi-Fi + chave da placa) |
| | `totem_virtual/.env` |

O repositório é **público**. Um `.env` que passou por zip, e-mail ou grupo de WhatsApp é chave vazada: se aconteceu, rotacione (seção 3).

## 1. Pré-requisitos no notebook (uma vez, ~30 min)

- [ ] **Python 3.13+** (marcar "Add to PATH"). Da raiz: `pip install -r requirements.txt`
- [ ] **Node 22+**. Depois: `npm install` em `frontend/` e em `admin/`
- [ ] **Arduino IDE 2** com a placa **esp32 (Espressif) 3.3.12** e as bibliotecas ArduinoJson 7.4.3, MFRC522 1.4.12 e LiquidCrystal I2C 1.1.2. Também o driver USB do ESP32 (CP210x ou CH340, conforme a placa)
- [ ] **Relógio do Windows sincronizado**: Configurações → Hora e idioma → Data e hora → **Sincronizar agora**. Sem isso, o ESP32 recebe `401 fora_da_janela` e o código do autenticador não confere (já aconteceu: o PC estava 249 s atrasado)
- [ ] Rede do estande em **2,4 GHz**: o ESP32 não enxerga 5 GHz. O notebook e o ESP32 precisam estar **na mesma rede**. Dois jeitos, nesta ordem de preferência:
  - **Hotspot do Windows (o que funcionou em 22/10).** O iPhone dá internet ao notebook e o notebook cria a rede: Configurações → Rede e Internet → **Hotspot móvel** → Editar → **Banda de rede: 2,4 GHz** → **Salvar**. Desligue **Economia de energia** (ela derruba o hotspot quando ninguém está conectado). O IP do notebook nessa rede é **192.168.137.1**. Se a banda voltar sozinha para "Qualquer um disponível", ligue o iPhone por **cabo USB** e compartilhe a conexão dele (o Wi-Fi fica livre para o 2,4 GHz)
  - **Hotspot do celular.** No iPhone, Ajustes → Acesso Pessoal → **Maximizar Compatibilidade** (sem isso ele fica só em 5 GHz)
- [ ] IP do notebook nessa rede: `ipconfig` → Adaptador Wi-Fi → **Endereço IPv4** (ex.: `192.168.137.1`). Anote; ele vai no `segredos.h` do ESP32
- [ ] Firewall: libere as portas para a rede local (PowerShell **como administrador**):
  ```powershell
  New-NetFirewallRule -DisplayName "ChargeOps API 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private,Public
  New-NetFirewallRule -DisplayName "ChargeOps app 5173" -Direction Inbound -Protocol TCP -LocalPort 5173 -Action Allow -Profile Private,Public
  ```
  Cancelar o aviso do Windows na primeira vez que o Python abre a porta cria uma regra de **bloqueio**, e bloqueio vence liberação. Confira e desative:
  ```powershell
  Get-NetFirewallRule -Action Block -Enabled True | ? DisplayName -match "python|node" | Disable-NetFirewallRule
  ```
- [ ] Teste a rede **antes de ligar o ESP32**: num celular na mesma rede, abra `http://<IP do notebook>:8000/hardware/v2/hora`. Tem de voltar um JSON com `ts` e `iso`. Se não voltar, o ESP32 também não vai conectar

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
| `FRONTEND_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173,http://<IP do notebook>:5173` |
| `AMBIENTE=desenvolvimento`, `MODO_DEMO=0`, `FUSO_HORARIO=America/Sao_Paulo` | como está |

**Não** escreva `ADMIN_MFA=opcional`: essa opção não existe mais. Se aparecer no `.env`, apague. O segundo fator agora é sempre obrigatório.

**`frontend/.env`**: `VITE_SUPABASE_URL` e `VITE_SUPABASE_KEY` (chave **publicável**). Sem `VITE_API_URL`, o app deduz a API do endereço que abriu a página, e é isso que faz funcionar no celular.

**`admin/.env`**: vazio serve (fala com `localhost:8001`). Para o Google, acrescente `VITE_GOOGLE_CLIENT_ID=<o mesmo do backend>`.

Conferência rápida (de `backend/`): `python provisionar.py testar-llm` → **PASSOU** (com 401, gere outra chave em ollama.com/settings/keys).

## 3. Chaves: o que rotacionar para amanhã

Rotacionar = gerar uma nova e invalidar a velha. A ordem abaixo é do mais urgente para o que só se troca se vazou.

| Chave | Rotacionar amanhã? | Como | Efeito colateral |
|---|---|---|---|
| `SUPABASE_KEY` (secreta, `sb_secret_`) | **Sim, se o `.env` viajou** em zip ou mensagem. Ela dá acesso total ao banco | Supabase → Settings → API Keys → **Create new secret key**, cole no `.env` dos dois computadores, depois **revogue** a antiga | nenhum, se trocar nos dois `.env` |
| `JWT_PRIVATE_JWK` | **Sim, se o `.env` viajou**: com ela se forja login de qualquer morador | `python provisionar.py chave-jwt` → cole a privada no `.env` → Supabase → Settings → **JWT Keys** → importe a pública como *standby* → **Rotate** | todo morador precisa entrar de novo (a sessão já vive só na aba). **Sem importar a pública no Supabase, o Realtime do app para** (o painel ao vivo congela) |
| `ADMIN_JWT_PRIVATE_JWK` | Recomendado: separa o token do painel do token do app | `python provisionar.py chave-jwt-admin` → `.env` | quem estiver no painel entra de novo. Não vai para o Supabase |
| `OLLAMA_API_KEY` | Se vazou | ollama.com/settings/keys → nova → `.env` → reiniciar a API | nenhum |
| `DEVICE_MASTER_KEY` | **Só se vazou.** Trocar invalida a chave do ESP32 | `python provisionar.py chave-mestra` → `.env` → `python preparar_totem.py --next` → novo `segredos.h` → **gravar o ESP32 de novo** | o ESP32 recebe 401 até ser regravado |
| `ADMIN_MFA_KEY` | **Não.** Trocar quebra o autenticador de todo gestor | se precisar: nova chave e depois `python provisionar.py gestor-mfa --nome "Davi Admin" --remover`; no próximo login o painel pede o QR de novo | todo gestor recadastra o app autenticador |
| `SUPABASE_ANON_KEY` / `VITE_SUPABASE_KEY` | Não: é pública por definição (vai no navegador) | — | — |
| `GOOGLE_CLIENT_ID` | Não: é público | — | — |
| Senha das contas de teste (`TotemNext#2026`) | **Sim**: está escrita no repositório público | `python preparar_totem.py --next --senha "<outra forte>"` | — |

Regra para o dia: **um** `.env` de referência (o do notebook). O do PC do Davi recebe as mesmas chaves novas, ou fica desligado. Duas APIs com chaves diferentes no mesmo banco = ESP32 e painel recusados.

## 4. Banco: auditoria das migrations (nada foi alterado nas 22 existentes)

As migrations moram **no Supabase**, não no computador. Trocar de notebook **não exige rodar nada de novo**: o banco do Davi já tem de 01 a 22. Conferência de 22/10:

| # | O que faz | Situação |
|---|---|---|
| 01–08 | esquema, seed (3 condomínios), login, multi-condomínio, favoritos | aplicadas. **Não rode de novo**: o 02 e o 07 re-inserem seed |
| 09 | ESP32 (dispositivos, comandos, leituras) | aplicada. Desliga o RLS de 3 tabelas, mas **o 11 religa** o RLS em todas as tabelas do `public` (conferido) |
| 10–14 | RFID, segurança (RLS + revoke), produto, cartões, integridade | aplicadas, idempotentes |
| 15, 16, 17 | protocolo v2, fontes/cobrança, escala do totem | aplicadas. Os `*_verificacao.sql` são **conferências**, não migrations: rodam dentro de transação e podem rodar a qualquer hora |
| 18 | `gestor_mfa`, `auditoria_admin` | aplicada |
| 19, 20, 21, 22 | perfil do condomínio, mapa/chamados/admin global, ociosidade, cargo NEXT | aplicadas |
| **23 (nova)** | `operadores_google` (pedido de acesso pelo Google), `leituras_sessao` (gráfico de toda recarga), `percentual_origem = 'celular'` | **rodar uma vez** no SQL Editor. Só acrescenta; idempotente; RLS ligado e fechado ao navegador. Sem ela: sem Google, sem gráfico da recarga simulada (o do totem cai para `leituras_hardware`), sem % do celular. Nada quebra |
| 98 `reset_total` | **apaga todas as contas e todo o histórico** | **NÃO rodar amanhã.** Ferramenta, não migration |
| 99 `limpeza` | apaga recargas, extrato, leituras | **NÃO rodar amanhã** sem querer zerar a demonstração |

Ordem certa para um banco NOVO (não é o caso de amanhã): 01 → 23 em ordem numérica, pulando 98/99. Os `*_verificacao.sql` vão logo depois do respectivo número.

Conferência depois do 23 (resultado esperado: 2 linhas):

```sql
select table_name from information_schema.tables
 where table_schema = 'public' and table_name in ('operadores_google', 'leituras_sessao');
```

E o teste de invasão contra o banco real (de `backend/`): `python provisionar.py verificar` → tudo **PASSOU**.

## 5. Subir (4 terminais)

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
- [ ] A API do painel **não sobe** sem `ADMIN_MFA_KEY` (de propósito: sem ela ninguém cadastra o autenticador)
- [ ] "WinError 10013" = porta ocupada: veja a seção 1 do `RODAR_E_VALIDAR.md`

## 6. Admin da plataforma (Davi)

A conta `Davi Admin` já existe no banco do Davi. Basta entrar.

- **Primeira vez, ou a conta foi apagada:** `python provisionar.py admin-global --nome "Davi Admin"`. Só o nome: a senha é **gerada** e aparece **uma vez**. Não há opção para escolher senha nem comando para trocar senha de gestor. Se a conta já existe, o comando recusa.
- **Login:** nome + senha → se o app autenticador ainda não está cadastrado, o painel mostra **só** a tela do QR code. Nenhuma aba, nenhum dado e nenhuma rota respondem antes (o backend recusa com `mfa_pendente`). Escaneie, confirme com um código e o painel abre.
- **Daí em diante:** nome + senha + código de 6 dígitos, sempre.
- **Perdeu o celular:** `python provisionar.py gestor-mfa --nome "Davi Admin" --remover`. No próximo login o painel pede o QR de novo.

O que mudou em 22/10: antes, `ADMIN_MFA=opcional` (o padrão fora do Docker) deixava **nome + senha abrirem o painel inteiro**. Era a falha que você viu. Agora o token sem código só serve para cadastrar o autenticador, e vale 10 min.

## 7. Operadores dos condomínios (Google + sua aprovação)

1. Google Cloud Console → APIs e serviços → Credenciais → **Criar ID do cliente OAuth** → "Aplicativo da Web" → Origens JavaScript autorizadas: `http://localhost:5174` (e o endereço publicado, se houver). Copie o Client ID para `GOOGLE_CLIENT_ID` (backend) e `VITE_GOOGLE_CLIENT_ID` (admin) e reinicie os dois.
2. O operador abre o painel → **Entrar com Google** → escolhe o condomínio → "Pedido enviado". Nenhuma conta é criada.
3. Você → aba **Operadores** → **Aprovar**. Nasce uma conta de gestor **presa àquele condomínio**, **sem senha** (só entra pelo Google).
4. O operador entra com o Google de novo → cadastra o autenticador → vê **só** o condomínio dele (sessões, Operação e Sala Next, se for o estande). Visão geral e Operadores ficam fechadas.
5. **Revogar** corta na hora: o token aberto morre na chamada seguinte.

Sem o Client ID, o botão do Google não aparece e o resto funciona normalmente.

## 8. Totem Next (ESP32 sem INA219 e sem solar)

```powershell
# de backend/   (uma vaga: o padrão. Para o totem de quatro, --vagas 4)
python preparar_totem.py --next
```

O comando cria ou ajusta o estande (limite **7,5 kW = 1 × 7,5 kW** na escala 1:1000, ponta = metade), a vaga **T1** com **divisão por tempo ligada**, a placa (sem porta solar, rotulada `simulado`) e 3 contas de teste com tag. Também imprime o bloco do `segredos.h`. Diminuir o número de vagas **apaga** as que sobram, para o painel não mostrar vaga que nenhum relé atende.

- [ ] Confira que `firmware/totem_next/config.h` tem `constexpr uint8_t PORTAS = 1;` — o mesmo número do `--vagas`
- [ ] Grave a placa e abra o monitor serial a 115200. A linha a procurar é **`handshake ok: 1 porta(s) no backend, 1 nesta placa`**. Se os números diferirem, o próprio firmware avisa e diz o que corrigir

Depois: `firmware/totem_next/README.md` (copiar o `segredos.h`, gravar e seguir a "primeira ligação"). O sketch antigo do Gustavo (1 tag fixa, 1 relé por vez, `delay`) foi descartado: ele não falava com o backend.

**Tags reais:** a tag que ninguém cadastrou mostra o UID no LCD (`Tag D3F5BFD9`). A pessoa vincula esse UID no app (Configurações → cartão RFID) e passa de novo.

**Sem leitor ou sem botão?** O monitor serial (115200, com **Nova linha**) faz as duas coisas, e passa exatamente pelo mesmo caminho da tag de verdade:

| Digite | Faz |
|---|---|
| `t D3F5BFD9` | aproxima a tag com esse UID |
| `b` | aperta o botão da vaga 1 (`b 2` para a vaga 2, quando houver) |
| `s` | imprime o estado da vaga: %, W, Wh, tempo fechado e previsão de fim |

## 9. Validar os dois pontos principais (roteiro da banca)

### 9.1 Controle de energia e telemetria em tempo real

- [ ] App no celular → cadastro no **Estande Next** (cargo NEXT, só celular) → escolher o modelo do celular (a bateria e os watts vêm de `celulares.js`)
- [ ] Vincular a tag → tag no totem + botão → saldo **reservado** na Carteira → **relé fecha e o celular começa a carregar de verdade**
- [ ] No app, o monitor mostra o %, a potência, **"Termina em X (por volta das HH:MM)"** e os **dois gráficos** (potência e bateria) andando a cada 5 s. O mesmo vale para uma recarga num **eletroposto simulado** de carro
- [ ] Celular Android com o app aberto no Chrome: aparece **"lido do seu celular"** no % (o modelo se corrige pela bateria real). Precisa de HTTPS ou localhost: por IP, ative `chrome://flags` → *Insecure origins treated as secure* → `http://<IP>:5173`
- [ ] Painel → **Sessões** → clicar na sessão → condomínio, usuário, celular, demanda, energia (entregue, na bateria, **da tomada**), conta, **de onde vêm os números** e os gráficos
- [ ] Painel → **Sala Next** → cadastros, celulares, recargas e a vaga ao vivo, em W e Wh reais
- [ ] A mesma tag de novo → encerra → recibo e **estorno** da diferença na Carteira

### 9.2 Demanda no horário de pico e water-filling (o foco)

Com **uma vaga**, o water-filling aparece na própria vaga: o quadro do estande é do tamanho dela, e baixar o limite vira **tempo de relé fechado**.

- [ ] Celular carregando: limite **7,5 kW** → relé fechado direto, `fracao` 100%
- [ ] Painel → **Sala Next → Demanda do estande** → **3,75 kW (50%)**, ou **Simular pico agora (2 h)**: a ponta divide o limite por 2, e só existe em **dia útil**. A aba Operação mostra o condomínio-base da sua conta, não o estande. Em ≤ 10 s:
  - serial do ESP32: `divisao por tempo (janela 30s): 1:50%`
  - o relé **alterna**: 15 s fechado, 15 s aberto. **Dá para ouvir**
  - LCD: `50%` na página da vaga, no lugar dos watts, enquanto o relé está aberto
  - app: o gráfico de potência vira um "pente" e a linha tracejada mostra o liberado; a **previsão de término dobra** (50% do tempo = o dobro de minutos)
  - Sala Next: "Tempo fechado 50%" na vaga
- [ ] **1,5 kW** (o mínimo da vaga, 20% de 7,5) → `fracao` 20%: 6 s fechado a cada 30 s
- [ ] **1 kW** (abaixo do mínimo) → a vaga **pausa**; uma tag nova iria para a **fila de energia**. Volte para 7,5 kW: ela religa sozinha em ≤ 10 s, sem perder a sessão nem o saldo reservado
- [ ] Desligar **Divisão por tempo** na vaga (Sala Next) → ela vira carga fixa (só admissão); religar → volta a dividir

> Com quatro vagas (`--vagas 4` e `PORTAS = 4`) é o mesmo roteiro com os números em quádruplo: limite 30 kW → 22,5 kW dá 75% para cada e três relés fechados em rodízio; na ponta, 15 kW dá 50% e dois relés.

## 10. Como a demanda funciona (para responder a banca)

**Limite contratado por condomínio.** Cada local tem `limite_potencia_kw`, a potência que o quadro geral aguenta. Na **janela de ponta** (dias úteis, ex.: 18h–21h), o limite efetivo é `limite × ponta_fator_limite` e o kWh da rede custa `tarifa × ponta_multiplicador_tarifa`. Tudo é configurado por local no painel (Operação).

**Um alocador só** (`backend/demanda.py`, `distribuir_fontes`), a cada 10 s e a cada recarga que começa ou termina:

1. **Cargas fixas** (relé sem divisão) levam o que pedem.
2. **Sol** (quando o local tem FV): primeiro para quem está em modo FV, depois para o rápido.
3. **Rede restante: água no balde (water-filling).** Os pontos moduláveis são ordenados pelo que pedem. Quem pede menos que a parte igual leva o que pede, e a sobra é redividida entre os outros. Ninguém recebe mais do que a bateria aceita (curva CC-CV: cheia até 80%, caindo até 100%).
4. **Mínimo do carregador** (HCA G2: 6 A, ou seja 1,4 kW mono / 4,2 kW tri). Quem não alcança o mínimo é **pausado**, começando por quem chegou por último. No totem, o mínimo é **20% da vaga** (1,5 kW na escala, 1,5 W real): fatia de relé menor que isso não carrega e só faz o relé estalar.
5. **Admissão.** Uma recarga nova é simulada **só com a rede** (sol não é garantido). Se ela empurrasse alguém para baixo do mínimo, vai para a **fila de energia** com o saldo reservado e liga sozinha quando sobrar potência.

**No eletroposto simulado (carros):** o alocado vira a potência do carro (o 10029 do HCA G2). O carro puxa o menor entre a curva da bateria e o alocado, e o simulador avança energia, %, ponta/fora-ponta e custo a cada 10 s.

**No totem (relé liga/desliga):** a mesma fração `alocado ÷ pedido` vira **tempo de relé fechado** numa janela de 30 s, em rodízio (McNaughton). A média de potência de cada vaga é a fração × a potência cheia. A soma, em qualquer instante, cabe no limite. É o water-filling executado em hardware.

**Exemplo de conta — UMA vaga** (estande 7,5 kW, 1 celular de 7,5 kW):

| Situação | Limite | A vaga recebe | O relé, numa janela de 30 s |
|---|---|---|---|
| fora da ponta | 7,5 kW | 7,5 kW (100%) | fechado direto |
| limite 3,75 kW | 3,75 kW | 3,75 kW (50%) | 15 s fechado, 15 s aberto |
| ponta (× 0,5) | 3,75 kW | 3,75 kW (50%) | 15 s fechado, 15 s aberto |
| limite 1,5 kW (o mínimo) | 1,5 kW | 1,5 kW (20%) | 6 s fechado, 24 s aberto |
| limite 1 kW | 1 kW | 0 — **pausada** | aberto; tag nova vai para a fila |

**Com quatro vagas** (estande 30 kW, 4 celulares de 7,5 kW):

| Situação | Limite | Cada vaga | Relés fechados ao mesmo tempo |
|---|---|---|---|
| fora da ponta | 30 kW | 7,5 kW (100%) | 4 |
| limite 22,5 kW | 22,5 kW | 5,625 kW (75%) | 3, em rodízio |
| ponta (× 0,5) | 15 kW | 3,75 kW (50%) | 2, em rodízio |

**Cobrança:** cada kWh entra num de três baldes (solar, rede fora da ponta, rede na ponta), com o preço congelado no início da recarga. O saldo é reservado no início e a diferença é estornada no fim. No totem, o kWh é o do **modelo de carga** (rotulado `simulado`). Diga isso: sem sensor, a energia é calculada pela física do celular. O relé e o tempo são reais, a corrente não é medida.

## 11. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| ESP32 `Sem Wi-Fi` | rede 5 GHz, nome ou senha diferentes | hotspot em 2,4 GHz (seção 1); o `WIFI_SSID` tem de ser igual ao nome da rede, com maiúsculas e espaços |
| ESP32 `Conectando...` para sempre | IP errado no `BACKEND_URL`, firewall, uvicorn sem `--host 0.0.0.0` | `ipconfig`; regra de firewall da seção 1; abrir `http://<IP>:8000/hardware/v2/hora` no celular |
| Serial: `ATENCAO: o backend tem N porta(s) e este firmware tem PORTAS = M` | o `--vagas` e o `PORTAS` não batem | `python preparar_totem.py --next --vagas M`, ou mude o `PORTAS` em `config.h` e grave de novo |
| Arduino IDE: `ArduinoJson.h: No such file or directory` | biblioteca não instalada neste computador | Ferramentas → Gerenciar Bibliotecas → ArduinoJson, MFRC522, LiquidCrystal I2C |
| `pytest` falha com `ModuleNotFoundError: servidor_v21` | sobraram `backend/testes/test_maquina_de_estados.py` e `test_roteiro.py` de uma versão antiga (já saíram do git; a versão atual mora em `totem_virtual/testes/`) | apague os dois arquivos: `del backend\testes\test_maquina_de_estados.py backend\testes\test_roteiro.py` |
| LCD `Relogio servidor` | relógio do notebook fora | Sincronizar agora; reiniciar o uvicorn |
| LCD `Chave invalida` | `.env` com outra `DEVICE_MASTER_KEY` | `preparar_totem.py --next` de novo e regravar o `segredos.h` |
| Placa reinicia em laço com o relé ligado | GPIO 12 (pino de boot) | IN2 no GPIO 16 (README do firmware) |
| Painel: "mfa_pendente" | conta sem autenticador | cadastrar pelo QR que o painel mostra |
| Código do autenticador sempre inválido | relógio do celular ou do notebook | `python provisionar.py testar-mfa --nome "Davi Admin"` |
| App no celular não abre | firewall 5173 ou `FRONTEND_ORIGINS` sem o IP | seção 1 e 2 |
| Gráfico da recarga simulada vazio | db/23 não aplicado | rodar o 23 |
| Assistente responde só "regras" | chave Ollama revogada | `python provisionar.py testar-llm` |
