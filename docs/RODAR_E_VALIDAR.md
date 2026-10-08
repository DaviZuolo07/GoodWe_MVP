# Rodar e validar o ChargeOps — do zero ao "Next antes do Next"

Roteiro para subir o projeto inteiro, zerar o banco e conferir **cada fluxo**
antes do deploy. Faça na ordem; cada item tem o que fazer e o que deve
acontecer. Marque `[x]` conforme passar.

```
  app do morador      frontend/   dev: http://localhost:5173   docker: http://localhost:8080
  painel do gestor    admin/      dev: http://localhost:5174   docker: http://localhost:8081
  API pública         backend/    http://localhost:8000   (main:app)
  API administrativa  backend/    http://localhost:8001   (main_admin:app)
  banco               Supabase real (nuvem) — o mesmo nos dois modos
```

Dois jeitos de rodar:

| Modo | Para quê | Diferença |
|---|---|---|
| **Desenvolvimento** (uvicorn + `npm run dev`) | mexer no código, ver erro na hora | `/docs` aberto, 2º fator opcional, CORS aceita a rede local |
| **Docker** (`docker compose up`) | ensaiar o Next/publicação | `AMBIENTE=producao`, build de produção dos sites, 2º fator obrigatório, mesmos cabeçalhos da Vercel |

---

## 0. Pré-requisitos (uma vez)

- [ ] Python 3.13+ e `pip install -r requirements.txt` (da raiz)
- [ ] Node 22+ e `npm install` em `frontend/` e em `admin/`
- [ ] `backend/.env` e `frontend/.env` preenchidos (modelos nos `.env.example`)
- [ ] **Relógio do Windows sincronizado.** O código do autenticador e a
      anti-replay do totem dependem disso (já tivemos o PC 249 s atrasado):
      Configurações → Hora e idioma → Data e hora → **Sincronizar agora**.
- [ ] Docker Desktop instalado (só para o modo Docker): <https://www.docker.com/products/docker-desktop/>
      — depois de instalar, abra o Docker Desktop e confira `docker compose version`.

## 1. "WinError 10013" ao rodar o uvicorn

No Windows, esse erro quase sempre quer dizer **a porta já está ocupada** —
não é falta de permissão. Em 08/10 o diagnóstico foi exatamente esse: já havia
um `uvicorn main:app` na 8000 e um `main_admin:app` na 8001 (abertos às 11:42,
sem `--reload`, ou seja, rodando o código daquela hora).

Descobrir quem ocupa e encerrar (PowerShell):

```powershell
Get-NetTCPConnection -LocalPort 8000,8001 -State Listen |
  Select-Object LocalPort, OwningProcess, @{n='Comando';e={(Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)").CommandLine}}

Stop-Process -Id <OwningProcess> -Force
```

Conferir se uma API está de pé: abra <http://localhost:8000/> → `{"status":"ok", ...}`.

Se depois de encerrar o erro continuar, a porta pode estar reservada pelo
Hyper-V/WSL: `netsh interface ipv4 show excludedportrange protocol=tcp`.
Se 8000 estiver numa faixa, use outra porta (`--port 8010`) ou rode
`net stop winnat` e `net start winnat` como administrador.

## 2. Banco: migrations novas e reset total

No **Supabase → SQL Editor**, nesta ordem:

1. [ ] `db/20_mapa_chamados_admin_global.sql` (se ainda não rodou) — coordenadas, chamados, admin global.
2. [ ] `db/21_taxa_ociosidade.sql` — taxa por minuto de carro esquecido na vaga.
3. [ ] `db/98_reset_total.sql` — **apaga todas as contas (inclusive admin e
       síndicos do seed) e todo o histórico/logs.** Mantém condomínios,
       carregadores, placas e cartões do condomínio. Não tem desfazer.

A sessão "que não fecha": o login é um token guardado **só na memória da aba**
(recarregar a página já sai) e toda rota confere se a conta existe. Apagando a
conta, qualquer token dela morre na chamada seguinte (401). Se o que estava
preso era uma **recarga em andamento**, o reset apaga a recarga e devolve o
ponto como `disponivel`.

Conferência (resultado esperado: contas, recargas, extrato e auditoria = 0):

```sql
select (select count(*) from usuarios) contas, (select count(*) from sessoes_recarga) recargas,
       (select count(*) from movimentacoes_carteira) extrato, (select count(*) from auditoria_admin) auditoria,
       (select count(*) from condominios) condominios, (select count(*) from carregadores) carregadores;
```

Depois do reset, **reinicie as duas APIs** (os limitadores de tentativa vivem
na memória do processo) e recrie o administrador (de dentro de `backend/`):

```powershell
python provisionar.py admin-global --nome "Davi Admin"
```

A senha é gerada e aparece **uma vez** no terminal: guarde direto no
gerenciador de senhas (nunca em arquivo do repositório). O segundo fator vem
no passo 3.

## 3. Google Authenticator no painel — como funciona

É o padrão **TOTP** (RFC 6238), o mesmo de bancos e do GitHub:

1. O servidor gera um **segredo** aleatório (160 bits) e o guarda **cifrado**
   no banco (`gestor_mfa`, cifra com a `ADMIN_MFA_KEY` do `.env`).
2. Esse segredo vai para o celular **uma única vez**, por QR code (ou
   digitado). A partir daí celular e servidor têm o mesmo segredo.
3. A cada 30 s, os dois calculam sozinhos `HMAC-SHA1(segredo, hora atual)` →
   6 dígitos. **Não há internet envolvida**: o app funciona em modo avião.
   Por isso o relógio precisa estar certo (aceitamos ±30 s).
4. No login do painel: nome + senha → o servidor responde "falta o código" →
   você digita os 6 dígitos → ele confere. Cada código vale **uma vez só**.

Serve qualquer app TOTP: Google Authenticator, Microsoft Authenticator, Authy,
1Password. **É isso mesmo que o painel usa para logar** — e é só no painel do
gestor; o app do morador continua só com senha.

Dois jeitos de cadastrar:

- **Pelo painel (QR code)** — só no modo desenvolvimento (`ADMIN_MFA=opcional`):
  entre com nome + senha em <http://localhost:5174>, abra **Segurança**, escaneie
  o QR e confirme com um código.
- **Pela linha de comando** — vale sempre (e é o único jeito com
  `ADMIN_MFA=obrigatorio`, que é o caso do Docker e da produção):
  ```powershell
  python provisionar.py gestor-mfa --nome "Davi Admin"
  ```
  Mostra a chave e o endereço `otpauth://` uma vez. No app: **+** → **Inserir
  chave de configuração** → nome da conta, a chave, tipo **baseada em tempo**.

Perdeu o celular: `python provisionar.py gestor-mfa --nome "Davi Admin" --trocar`.
Trocar a `ADMIN_MFA_KEY` invalida o segundo fator de **todos** os gestores.

## 4. Rodar em modo desenvolvimento (4 terminais)

```powershell
# 1 - API pública            (de backend/)
uvicorn main:app --reload --port 8000
# 2 - API administrativa     (de backend/)
uvicorn main_admin:app --reload --port 8001
# 3 - app do morador         (de frontend/)
npm run dev
# 4 - painel do gestor       (de admin/)
npm run dev
```

- [ ] <http://localhost:8000/> e <http://localhost:8001/> respondem `{"status":"ok"...}`
- [ ] <http://localhost:8000/docs> abre (só em desenvolvimento)
- [ ] O log da API pública mostra o simulador rodando a cada 10 s, sem `[SIMULADOR] erro`

## 5. Rodar com Docker (ensaio do Next)

Pare tudo do passo 4 (mesmas portas 8000/8001) e, **da raiz**:

```powershell
docker compose up --build
```

Primeira vez leva alguns minutos. Endereços: app <http://localhost:8080>,
painel <http://localhost:8081>. Diferenças que você deve **ver**:

- [ ] <http://localhost:8000/> responde só `{"status":"ok"}` e `/docs` dá 404
- [ ] Login no painel **exige** o código do autenticador
- [ ] `docker compose logs -f api` mostra o simulador

Desligar: `docker compose down`. Depois de mudar código: `docker compose up --build` de novo.

## 6. Validação item por item

Faça no modo Docker (é o mais fiel). Onde diz "painel", use a conta `Davi Admin`.

### Contas e sessão
- [ ] **Cadastro**: no app, criar a conta `Morador Teste` (com o código de convite, se `CODIGO_CADASTRO` estiver definido). Entra direto e mostra o bônus de boas-vindas na Carteira.
- [ ] **Login/logout**: sair e entrar de novo.
- [ ] **Sessão só na aba**: recarregar a página (F5) → volta para a tela de login. É o esperado.
- [ ] **Conta apagada derruba sessão**: com o app aberto, apague a conta no Supabase (Table Editor → usuarios) → a próxima ação do app responde "Sessão inválida". (Recrie a conta depois.)
- [ ] **Senha errada 5 vezes no painel** → bloqueio de 15 min só para aquele nome.
- [ ] **Morador no painel**: tentar entrar no painel com `Morador Teste` → "Credenciais inválidas" (mesma mensagem de senha errada).

### Recarga simulada
- [ ] Cadastrar um veículo (Meus Veículos).
- [ ] Escolher um ponto livre → prévia de custo → iniciar. O ponto vira "em uso", potência e % sobem a cada ~10 s.
- [ ] Carteira: aparece a linha **Reservado para a recarga**.
- [ ] Encerrar pelo app → custo final, **Estorno da diferença** na Carteira, recibo abre com as linhas por fonte.
- [ ] **Fila**: com outra conta, entrar na fila de um ponto ocupado → quando ele libera, a primeira da fila recebe a notificação.

### Taxa de ociosidade (novo — db/21)
Para não esperar 15 min, baixe a tolerância do local de teste para 1 min:
```sql
update condominios set tolerancia_ociosidade_min = 1 where nome ilike '%Portal%';
```
- [ ] Iniciar recarga com alvo baixo (ex.: 5 pontos acima do atual) e **não** encerrar: deixar terminar sozinha.
- [ ] Ao terminar: aviso amarelo "Carga completa no ponto X. Retire o carro." e o ponto continua **em uso**.
- [ ] Depois de 1 min: aviso vira vermelho com "Taxa de ociosidade: R$ 0,50", subindo R$ 0,50 por minuto; chega notificação "A tolerância acabou".
- [ ] Tocar **Já retirei o carro** → ponto volta a livre; Carteira mostra **Taxa de ociosidade** com o valor; a fila (se houver) é avisada.
- [ ] Encerrar pelo app (em vez de deixar terminar) **não** gera taxa.
- [ ] Voltar a tolerância: `update condominios set tolerancia_ociosidade_min = 15;`

Regra: tolerância 15 min → R$ 0,50 por minuto começado → teto R$ 60,00;
carro "esquecido" 6 h é liberado pelo sistema (cobrando o teto). Só pontos
simulados; o totem/bancada não mudou. Referências de mercado: WeCharge
R$ 0,50/min após 15 min; Volvo R$ 5/min após 15 min; Tesla e Electrify America
US$ 0,40/min. Cada condomínio pode ter valores próprios (colunas
`tolerancia_ociosidade_min`, `taxa_ociosidade_min`, `teto_ociosidade`).

### Mapa
- [ ] Mapa de pontos carrega o mapa escuro (sem os quadrados "Access blocked / 403").
- [ ] Três pinos com o número de pontos livres; o estande do Next **não** aparece.
- [ ] **Como chegar** abre o Google Maps no **endereço** do local (com número), não numa coordenada ao lado.
- [ ] **Usar minha localização** pede permissão e mostra a distância (em localhost e https).

Sobre o pino: no Brasil o OpenStreetMap quase não tem número de casa, então a
coordenada de alguns locais é o meio da rua (só o Portal, nº 1720, tem o prédio
mapeado). A rota já vai certa pelo endereço. Para o pino ficar em cima do
prédio: Google Maps → clique direito no prédio → clique nas coordenadas (copia) →
```sql
update condominios set latitude = <lat>, longitude = <lng> where nome ilike '%Melville%';
```

### Suporte e chamados
- [ ] App → Suporte → abrir chamado (assunto + mensagem). Aparece em "Meus chamados" como **aberto**.
- [ ] Painel → **Visão geral** → Chamados: o chamado está lá. (Só o admin global vê chamados.)
- [ ] Responder e marcar como resolvido → no app, o chamado mostra a resposta e o sino recebe a notificação.
- [ ] Visão geral → enviar notificação em massa para moradores → chega no sino do app; **não** chega para gestor.

### Painel do gestor
- [ ] Login com senha + código (Docker) ou senha e depois cadastro do QR (dev).
- [ ] Painel mostra os pontos do condomínio, a curva de demanda e as recargas em andamento em tempo real.
- [ ] Mudar o limite de potência → recargas em andamento se ajustam no ciclo seguinte.
- [ ] Segurança → a auditoria lista os logins e as alterações que você acabou de fazer.

### Segurança e integridade (automático)
De dentro de `backend/`:
- [ ] `python -m pytest testes -q` → **todos passam** (100 em 08/10).
- [ ] `python provisionar.py verificar` → teste de invasão contra o banco real: tudo **PASSOU**.
- [ ] No SQL Editor: `select * from conferir_carteira();` → **vazio** (saldo = soma do extrato).

### Totem
- [ ] `python -m totem_virtual roteiro` (com a API pública de pé e as 4 vagas livres) → roteiro de aceitação passa.
- [ ] Com a bancada física: handshake, tag no leitor, relé liga e desliga (ver `totem_virtual/README.md`).

### Celular
- [ ] Modo dev: no celular na mesma Wi-Fi, abrir `http://<IP do PC>:5173` → app funciona (a API é deduzida do endereço).

## 7. Deploy (depois que tudo acima passou)

O que vai para a **Vercel** são os **dois sites** (app do morador e painel).
As **duas APIs não podem ir para a Vercel**: lá o código roda como função que
acorda por requisição e morre em segundos, e a API pública precisa de um
processo **sempre ligado** (o laço de 10 s que avança recargas, a taxa de
ociosidade e a conversa com o totem). Elas vão para um host de contêiner
(Render pelo `render.yaml`, Railway ou Fly.io) usando o mesmo
`backend/Dockerfile` que o `docker compose` acabou de testar. Escolha uma
região no **leste dos EUA**: o Supabase está no Canadá e, do Brasil, a
conexão do totem estoura o tempo limite.

Passo a passo completo: [`docs/DEPLOY.md`](DEPLOY.md). Resumo:

1. Backend (2 serviços) no host de contêiner, com as variáveis da tabela do DEPLOY.md
   e `FRONTEND_ORIGINS` / `ADMIN_ORIGINS` = endereços `https://` da Vercel.
2. Vercel → New Project → pasta raiz `frontend`, variáveis `VITE_API_URL`,
   `VITE_SUPABASE_URL`, `VITE_SUPABASE_KEY` (chave publicável).
3. Vercel → outro projeto → pasta raiz `admin`, variável `VITE_ADMIN_API_URL`.
4. Repetir a seção 6 contra os endereços publicados, pelo celular em 4G.
