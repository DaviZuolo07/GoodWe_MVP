# Auditoria final — experiência Next — 08/10/2026

- **Autor:** Davi (sessão com override do contrato v1, autorizado por Davi; mudanças na pasta do Daniel registradas na seção 12).
- **Escopo:** segurança do repositório, painel administrativo, mapa, chatbot, totem virtual, multi-carregamento e demanda, celular, Docker e deploy.
- **Como foi validado:** testes automatizados **e** execução real contra o Supabase de produção (contas de teste `Auditoria *`, apagadas no fim), com prints de um navegador de verdade (Edge) em tamanho de celular.

> **Este repositório é PÚBLICO** (o GitHub responde sem login). Nenhuma senha está neste arquivo. As senhas novas foram entregues ao Davi fora do repositório.

---

## 0. Veredito

**Pronto para o Next, com três ações antes da banca** (seção 11): cadastrar o segundo fator da conta de administrador, decidir onde o backend roda (latência — seção 7.3) e trocar as senhas das contas de demonstração do totem.

| Frente | Situação |
|---|---|
| Cadastro, login, carteira, recarga, recibo | ✅ ponta a ponta contra o banco real |
| Multi-carregamento e gestão de demanda | ✅ duas recargas simultâneas, alocador dividindo, painel ao vivo |
| Painel admin com visão de tudo | ✅ novo: Visão geral (cadastros, pagamentos, recargas, notificações, chamados) |
| Chamados de suporte | ✅ novo: usuário abre, admin responde, resposta chega no sino |
| Mapa dos pontos | ✅ novo: OpenStreetMap, 3 locais reais, "como chegar" no Google Maps |
| Chatbot fecha ao clicar fora | ✅ corrigido e conferido no navegador |
| Celular | ✅ 390 px sem rolagem lateral, mapa e suporte conferidos por print |
| Totem virtual | ✅ 14/17 em memória · 13/17 contra o banco real (3 lacunas conhecidas do backend) |
| Segurança do git | ⚠️ nenhuma chave vazada; **senhas de demonstração vazadas abriam o painel** — corrigido |
| Docker | ⚠️ sem Docker nesta máquina; imagem reproduzida num ambiente limpo, guardas de produção conferidas |
| Deploy | 📋 recomendação com custo na seção 10 |

---

## 1. Segurança — varredura de todo o histórico do git

**Método:** script que lê **todas as versões de todos os arquivos** de todos os commits (444 blobs únicos, 30 commits) procurando JWT, `sb_secret_`, chave privada JWK (`"d"`), PEM, chaves Google/OpenAI/GitHub, hex de 64, URL de Postgres com senha **e os valores reais** de cada variável dos `.env` locais. O script nunca imprime o valor, só onde está.

| Achado | Gravidade | Situação |
|---|---|---|
| Chaves reais (Supabase service_role, JWK do JWT, `DEVICE_MASTER_KEY`, Ollama, chave da placa do totem) | — | **Nunca entraram no git.** Só `*.env.example` com placeholders. Nada a rotacionar. |
| Token de placa `gw_dev_…` no `segredos.exemplo.h` antigo (commit `2000b9a`) | baixa | Conferido no banco: **o token está morto** (hash não existe; o backend responde 401). Nada a fazer. |
| **Senha de demonstração `SenhaDemo#2026` nos testes = senha real das contas de gestor** | **alta** | Com ela, **"Sindico FIAP" entrava no painel admin** (local, onde o MFA é opcional). **Corrigido:** senhas dos dois síndicos trocadas por aleatórias de 20 caracteres; a antiga agora dá "Credenciais inválidas". Em produção o MFA obrigatório já barrava. |
| Senha `TotemNext#2026` (padrão do `preparar_totem.py`) abre "Ana/Bia/Caio Totem" | média | Contas simuladas, mas com saldo. **Ação:** `python preparar_totem.py --senha "<nova>"` antes do Next (seção 11). |
| `SenhaDemo#2026` também abre "Gus Bancada" (morador de bancada) | média | **Ação:** trocar (seção 11). |
| Em produção, a resposta "falta segundo fator" só aparece com senha certa | baixa | Revela que a senha de um gestor está correta. Sugestão ao Daniel: mesma resposta genérica. |
| Produção com origem `http://` em `FRONTEND_ORIGINS` só **avisa** | baixa | Sugestão ao Daniel: recusar subir. |

**Corrigido também:** `provisionar.py limpar --contas` apagava **toda conta fora de uma lista fixa** — inclusive a do administrador. Agora poupa gestores e administradores globais.

**A auditoria do painel funciona:** o "Registro de acesso" mostrou o login de teste feito com a senha vazada, com hora e IP.

---

## 2. Como entrar no painel administrativo

O painel é **outro aplicativo**, com **outra API** (ADR-023). O app do morador não sabe que ele existe.

| | Local | Porta |
|---|---|---|
| API administrativa | `cd backend` → `uvicorn main_admin:app --host 127.0.0.1 --port 8001` | 8001 |
| Painel (tela) | `cd admin` → `npm run dev` | http://localhost:5174 |

**Conta:** `Davi Admin` — gestor **e administrador global** (vê todos os locais). Criada com `python provisionar.py admin-global --nome "Davi Admin"`; a senha foi gerada aleatória e mostrada uma vez, fora do git.

**Primeiro login (faça agora):**
1. Abra http://localhost:5174, entre com `Davi Admin` e a senha.
2. O painel abre em **Acesso e segurança** → **Cadastrar app autenticador** → leia o QR com Google Authenticator / Microsoft Authenticator → digite o código de 6 dígitos.
3. A partir daí, todo login pede senha **e** código. Em produção (`ADMIN_MFA=obrigatorio`) sem o código ninguém entra.

O segredo do autenticador é cifrado com `ADMIN_MFA_KEY` (já gerada no `backend/.env`, que é ignorado pelo git). Em produção, ela vai nas variáveis da hospedagem — **não** troque depois de cadastrar o MFA, senão o código deixa de valer.

**Só você tem acesso:** os síndicos "Sindico FIAP" e "Sindico Portal" ganharam senhas novas (entregues a você) e veem só o próprio condomínio; a **Visão geral** é exclusiva de quem está na tabela `admins_globais` — hoje, só você. Para dar acesso a outra pessoa: `python provisionar.py admin-global --nome "Fulano"`.

---

## 3. Painel admin — o que ele controla agora

| Aba | O que mostra / faz | Origem |
|---|---|---|
| **Visão geral → Resumo** | recargas agora e potência em uso, cadastros (por tipo, novos no mês), faturamento, créditos de carteira, energia (ponta/solar), recusas, chamados abertos, carregadores por status — **total e por local** | `GET /gestor/geral/resumo` |
| **Chamados** | lista com filtro; responder (marca resolvido e avisa o usuário no sino), marcar em andamento, reabrir | `/gestor/geral/chamados` |
| **Recargas** | todas, de todos os locais: usuário, ponto, status, bateria, energia, valor | `/gestor/geral/recargas` |
| **Cadastros** | todos os usuários: tipo, local, veículos, nº de recargas, saldo; busca | `/gestor/geral/usuarios` |
| **Pagamentos** | todo movimento de carteira: crédito, pré-autorização, estorno, bônus, saldo depois | `/gestor/geral/pagamentos` |
| **Notificações** | histórico (lida ou não) e **envio** para todos, um local ou uma pessoa (gestores não recebem) | `/gestor/geral/notificacoes` |
| **Operação** (já existia) | demanda do condomínio, curva do dia, recargas ao vivo, energia por fonte, Modbus, simulador | `/gestor/painel` |
| **Acesso e segurança** (já existia) | segundo fator e registro de acesso | `/admin/*` |

**Tempo real:** o painel admin **atualiza a cada 10 s** (o ritmo do alocador de demanda). O app do morador usa **Supabase Realtime** (indicador "Tempo real" no topo). Toda escrita do painel vira linha na auditoria.

**Validado ao vivo:** login → Visão geral com 20 cadastros, 19 pontos, faturamento do mês → chamado aberto pelo app apareceu na aba → resposta chegou no Suporte do usuário → notificação enviada para uma pessoa.

---

## 4. Mapa de pontos (app do morador)

- Menu **Mapa de pontos** (no celular: **Mais → Mapa de pontos**).
- **Leaflet + azulejos oficiais do OpenStreetMap**: sem chave, sem cartão. (A CARTO, testada primeiro, passou a exigir chave — trocada.)
- 3 locais reais com coordenada (geocodificadas no OpenStreetMap a partir do endereço): Melville (Santana de Parnaíba), Portal dos Bandeirantes (Pirituba), Parque das Nações (Vila Leopoldina). **O estande do Next fica fora** (sem coordenada, perfil `bancada`).
- Pino com o nº de pontos livres agora (cinza quando não há vaga); lista ao lado com "X de Y pontos livres".
- **Usar minha localização**: ordena por distância e enquadra você + os pontos. Exige **https** (ou localhost) — regra do navegador; no endereço publicado funciona, no `http://192.168…` do celular, não.
- **Como chegar** abre a rota no Google Maps; **Ver carregadores** troca o local do painel e volta ao início.
- Tema escuro: filtro CSS sobre o mesmo mapa. CSP do build libera só `https://tile.openstreetmap.org`.

---

## 5. Chatbot fechando ao clicar fora

**Causa:** abaixo de 1280 px o chat tem fundo escuro que fecha ao toque; **no desktop (xl) não havia fundo**, então clicar em outra aba, numa recarga ou em qualquer lugar deixava o chat aberto.
**Correção:** clique/toque fora do painel fecha em qualquer largura (`ChatPanel.jsx`).
**Conferido no navegador:** chat aberto → clique em "Histórico de Recargas" → chat fechado.

E o problema do cadastro anterior ("Sua sessão expirou" ao errar a senha): o 401 do `/login` era tratado como sessão vencida. Corrigido em `frontend/src/lib/api.js` — conferido: senha errada agora diz "Nome de usuário ou senha incorretos".

---

## 6. Multi-carregamento, demanda e horário de pico

**Como funciona (resumo; detalhes e números em `docs/como_o_chargeops_gere_demanda_e_cobra.md`):**
- O quadro elétrico de cada condomínio tem um **limite** (`limite_potencia_kw`). Um **alocador** roda a cada 10 s e a cada recarga que começa/termina e decide **quanto cada ponto pode puxar e de qual fonte** (rede ou sol).
- **Horário de ponta** (padrão 18h–21h, dias úteis): o limite cai (`ponta_fator_limite`, ex.: 60%) e o kWh fica mais caro (`ponta_multiplicador_tarifa`, ex.: 1,5×). O preço é **congelado** no início de cada recarga.
- Se a soma dos carros passa do limite, o alocador **divide** a potência em vez de deixar o disjuntor desarmar; ninguém fica abaixo do mínimo do carregador (quem não cabe pausa ou vai para a fila).
- Cobrança: reserva no pior caso (tudo pela rede), estorno da diferença no fim; recibo com uma linha por fonte.

**Validado contra o banco real (08/10):**
| Teste | Resultado |
|---|---|
| Duas recargas simultâneas no Melville (limite 80 kW) | cada uma recebeu **7,0 kW alocados**; demanda total 20,4 kW (com uma terceira já em curso); `limitando: false` |
| Painel → Recargas ao vivo | as duas apareceram com %, potência, energia e custo parcial |
| Simulador de pico: 12 carros × 7 kW na ponta | limite na ponta **48 kW**; sem gestão seriam **84 kW** (estouraria); com gestão **36 kW evitados**, 12 admitidos |
| Encerrar | recibos gerados; estorno de ~R$ 29,9 de cada reserva (recargas curtas) |

**Dados a partir de recarga:** cada recarga grava energia por fonte, potência, tempo e custo; isso alimenta o histórico do morador, o recibo, a curva por hora e o faturamento do gestor, e a Visão geral.

---

## 7. Totem — como funciona e como simular

### 7.1 Como funciona
O **Totem Central** é um ESP32 com 4 vagas (relé + sensor INA219 cada), leitor RFID, 4 botões, LCD 16×2 e a vaga 4 solar (bateria 18650 ou rede, por relé reversor). Ele fala o **protocolo v2** com o backend: acerta o relógio (`/hora`), faz **handshake assinado** (HMAC, anti-replay de 120 s), lê comandos (ligar/desligar vaga), envia telemetria em lotes e o RFID. Detalhes: ADR-020 a ADR-022 e `totem_virtual/README.md`.

O **totem virtual** é o gêmeo digital: mesma máquina de estados que o firmware copia, com hardware de mentira.

### 7.2 Como simular (passo a passo)
```bash
# sem banco (tudo em memória) — o jeito mais rápido de ver funcionando
python -m totem_virtual painel --bolso      # abre http://127.0.0.1:8765

# contra o backend local + Supabase real
cd backend && python preparar_totem.py      # uma vez: vagas, placa, moradores de teste, totem_virtual/.env
uvicorn main:app                            # backend
cd .. && set TOTEM_HTTP_TIMEOUT_S=10        # PowerShell: $env:TOTEM_HTTP_TIMEOUT_S=10   (ver 7.3)
python -m totem_virtual painel
```
Na página: aproximar tag, apertar o botão de cada vaga, plugar/desplugar celular, mudar a luz do painel, derrubar o Wi-Fi, reiniciar a placa. No app, entre como "Ana Totem" no **Estande Next** e acompanhe a recarga ao vivo; no admin, a recarga aparece em Recargas ao vivo.

### 7.3 Resultado do roteiro de aceitação e achado de latência
| Onde | Resultado |
|---|---|
| Backend em memória (`--bolso`) | **14/17** |
| Backend local + Supabase real | **13/17** (com `TOTEM_HTTP_TIMEOUT_S=10`) · **0/17 com o padrão de 3 s** |

- Os 3 que falham nos dois (`desplugado`, `vaga_sem_celular`, `celular_cheio`) são lacunas **conhecidas** do backend: encerrar a sessão pela medição (corrente zero / celular cheio) — já listadas no README do totem.
- **Achado:** o banco Supabase está na **AWS ca-central-1 (Canadá)**. Daqui, cada consulta leva ~164 ms e o handshake faz ~30 consultas em série → **4,9 s**. O totem (virtual **e o firmware**) desiste em **3 s**. Com o backend num notebook no Brasil, **o totem físico não conecta**. Por isso o `timeout_escolha` também falhou contra o banco real (passa em memória).
- **Correções possíveis (escolher uma antes do Next):**
  1. **Recomendado:** publicar o backend na América do Norte, perto do banco (seção 10) → ~15–20 ms por consulta, handshake < 1 s, firmware intocado.
  2. Subir `HTTP_TIMEOUT_MS` do firmware para 8 s (`firmware/totem_central/config.h`) — muda o contrato do laço; precisa de decisão.
  3. Daniel: reduzir as consultas do handshake (em lote).
- O totem virtual ganhou `TOTEM_HTTP_TIMEOUT_S` (padrão continua 3 s, igual ao firmware).

---

## 8. Rodando no celular

Prints reais (Edge, 390×844, toque):
- **Login, Dashboard, Mapa, Suporte:** página com **390 px de largura — sem rolagem lateral**; barra inferior (Início, Carteira, Assistente, Histórico, Mais); mapa com 3 pinos e azulejos carregados; nenhum erro de JavaScript.
- Pelo celular na mesma rede: `http://<ip-do-pc>:5173` (a API é deduzida do endereço; o backend precisa subir com `--host 0.0.0.0`). Localização só em https.

---

## 9. Docker

- **Docker e WSL não estão instalados nesta máquina** — o `docker build` não pôde rodar.
- **Reprodução equivalente:** ambiente Python limpo só com o `requirements.txt` da raiz, `backend/` copiado sem `.env`, `testes`, `evals` (o que o `.dockerignore` e o `Dockerfile` fazem), e os dois serviços em `AMBIENTE=producao`:

| Conferência | Resultado |
|---|---|
| Instalação limpa das dependências | ✅ |
| API pública em produção | ✅ `/` 200, **`/docs` 404**, `/gestor/*` 404, CORS recusa origem estranha, HSTS + `X-Frame-Options: DENY` + `nosniff` |
| API admin em produção **sem** `ADMIN_MFA_KEY` | ✅ **recusa subir** |
| API admin em produção com MFA, senha vazada antiga | ✅ recusada (MFA obrigatório) |
| `.dockerignore` | ✅ exclui `.env`, `segredos.h`, `node_modules`, frontends |
| Origem `http://` em produção | ⚠️ só avisa (seção 1) |

Para testar a imagem de verdade: instalar Docker Desktop e rodar os dois comandos do cabeçalho do `backend/Dockerfile`.

---

## 10. Deploy — melhor custo para o Next

**Fato que decide:** o Supabase está em **ca-central-1 (Canadá)**. O backend tem de rodar **perto dele** (leste da América do Norte), senão cada tela e o totem pagam ~165 ms por consulta.

| Peça | Recomendação | Custo/mês | Por quê |
|---|---|---|---|
| API pública (`chargeops-api`) | **Render Starter**, região **Virginia** ou **Ohio** | **US$ 7** | sempre ligada (o plano grátis dorme e congela as recargas), Docker pronto (`render.yaml` já existe) |
| API admin (`chargeops-admin-api`) | Render **Free**, mesma região | **US$ 0** | não roda o simulador; dormir 15 min só atrasa o primeiro login do painel |
| App do morador + painel | **Cloudflare Pages** (dois projetos, dois domínios) | **US$ 0** | banda ilimitada, uso comercial permitido; `public/_headers` já serve. (Vercel Hobby também serve — `vercel.json` existe —, mas é só não comercial) |
| Banco | Supabase (já existe) | US$ 0 | **atenção:** projeto grátis **pausa após 7 dias sem uso** — acesse na véspera |
| **Total** | | **≈ US$ 7/mês** (US$ 14 se a API admin também ficar sempre ligada) | |

**Alternativa mais barata:** Fly.io, região Toronto (`yyz`): duas máquinas pequenas ≈ US$ 4–7/mês, mas exige `fly.toml` e CLI (ainda não preparados). **Railway** (US$ 5/mês com US$ 5 de crédito) também funciona; o custo depende do uso.

Variáveis obrigatórias em produção (lista completa em `docs/DEPLOY.md`): API pública — `SUPABASE_URL`, `SUPABASE_KEY`, `JWT_PRIVATE_JWK`, `DEVICE_MASTER_KEY`, `FRONTEND_ORIGINS=https://…`; API admin — as mesmas + `ADMIN_MFA_KEY`, `ADMIN_ORIGINS=https://…`, `ADMIN_MFA=obrigatorio`. Os builds do front leem `VITE_API_URL` e `VITE_SUPABASE_URL` (a CSP é gerada com eles).

---

## 11. Antes da banca — checklist

1. **Cadastrar o segundo fator** da conta `Davi Admin` (seção 2).
2. **Trocar as senhas de demonstração vazadas:** `cd backend && python preparar_totem.py --senha "<nova senha forte>"` (contas Totem). Para "Gus Bancada", gere uma nova senha pelo `provisionar.py` (o comando `senha-gestor` vale só para gestor — pedir ao Daniel um equivalente para morador, ou recriar a conta).
3. **Decidir onde o backend roda no dia** (seção 7.3): publicado na América do Norte (recomendado) ou firmware com timeout maior.
4. Publicar conforme a seção 10 e acessar o Supabase na véspera (pausa por inatividade).
5. Recarga presa: há uma recarga de **"Daniel Crepe" (Melville, ponto 04)** em `carregando` desde 07/10 15:49 UTC — conferir se é de verdade ou encerrar.

---

## 12. Mudanças na pasta do Daniel (para revisão)

- **`db/20_mapa_chamados_admin_global.sql`** (novo, **já aplicado** no Supabase): `condominios.latitude/longitude` (+ 3 coordenadas), tabela `chamados`, tabela `admins_globais`. As duas tabelas novas: RLS ligado, sem privilégio para `anon`/`authenticated`.
- **`backend/rotas_geral.py`** (novo, só na API admin): Visão geral — `resumo`, `usuarios`, `pagamentos`, `recargas`, `notificacoes` (GET/POST), `chamados` (GET/PATCH). Acesso: gestor **e** linha em `admins_globais`; tabela ausente = ninguém é global.
- **`backend/rotas_suporte.py`** (novo, API pública): `GET/POST /me/chamados`, identidade pelo token, máx. 5 chamados em aberto por pessoa.
- **`backend/rotas_conta.py`**: `/condominios` devolve `latitude/longitude`; o fallback por formato agora tenta de novo a cada 60 s (aplicar migration com o backend no ar passa a valer sem reiniciar).
- **`backend/rotas_admin.py`**: `/admin/login` e `/admin/me` devolvem `global`.
- **`backend/main.py` / `main_admin.py`**: montam os routers novos.
- **`backend/provisionar.py`**: comandos `admin-global` e `senha-gestor` (senha aleatória mostrada uma vez); `limpar --contas` deixa de apagar gestor e admin global.
- **`backend/testes/test_visao_geral.py`**: 9 testes novos. Total **85 verdes**.
- **`admin/`**: `VisaoGeralPage.jsx` (novo) e aba no `App.jsx` (só aparece para admin global).
- Nada em `demanda.py`, `recarga.py`, `fisica.py`, `simulador.py`, RPCs ou RLS existente foi tocado.

**Sugestões ao Daniel:** handshake v2 com menos consultas (7.3); mesma resposta genérica quando falta o segundo fator (seção 1); recusar subir com origem `http://` em produção; um `provisionar.py senha-usuario` para contas de morador.

---

## 13. Validação desta rodada

| Verificação | Resultado |
|---|---|
| `backend` — `pytest testes` | **85 verdes** (76 + 9 novos) |
| `frontend` — lint / build / isolamento | 0 erros (3 avisos antigos) / ok / ok (55 arquivos) |
| `admin` — lint / build | 0 erros / ok |
| Ponta a ponta contra o banco real | 20 checagens, todas ok (cadastro, mapa, 2 recargas simultâneas, painel ao vivo, simulador de pico, recibo, chamado, notificação, isolamento) |
| Navegador real (Edge) | celular sem rolagem lateral; mapa com 3 pinos; chat fecha ao clicar fora; painel admin renderiza; nenhum erro de página |
| Totem virtual | `pytest totem_virtual/testes`: **56 verdes**; roteiro 14/17 em memória, 13/17 contra o banco real |
| Dados de teste | contas `Auditoria *` e `teste6271` **apagadas** com tudo que pendia delas |
