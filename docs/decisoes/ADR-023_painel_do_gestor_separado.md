# ADR-023 — Painel do gestor como aplicativo separado

**Data:** 07/10/2026 · **Autor:** Davi · **Estado:** implementado, aguarda revisão do Daniel (seção 7)

## 1. Contexto

Até aqui o painel do gestor era uma página dentro do app do morador: mesmo
pacote JavaScript, mesmo endereço, mesmo login, mesma API. Os DADOS estavam
protegidos (toda rota `/gestor/*` conferia o papel no banco), mas:

- todo visitante baixava o código do painel — rotas, campos, textos;
- o token de um gestor tinha o mesmo formato e a mesma validade do de um morador;
- a tela decidia o que mostrar olhando `tipo_usuario` no navegador;
- publicar o app do morador publicava junto a superfície administrativa.

Para o Next o app vai para a internet. A decisão do Davi: o app do morador não
pode conhecer o painel.

## 2. Decisão

Dois aplicativos, separados em **código, build, endereço, API, login e token**.

```
  app do morador (frontend/)            painel do gestor (admin/)
  https://<app>                          https://<painel>
        │                                       │
        ▼                                       ▼
  API pública (backend/main.py)         API administrativa (backend/main_admin.py)
  porta 8000 · morador + totem          porta 8001 · só gestor
        └───────────────┬───────────────────────┘
                        ▼
                 Supabase (Postgres)
```

O backend continua UMA base de código (os módulos de regra são os mesmos), mas
sobe como DOIS processos, cada um montando só as suas rotas.

## 3. As camadas (cada uma segura sozinha)

| # | Camada | Como |
|---|---|---|
| 1 | Código | `frontend/` não tem nenhum arquivo, rota ou texto de configuração do painel. `scripts/verificar-isolamento.mjs` roda depois de todo `npm run build` e **quebra o build** se achar referência ao painel ou um segredo no código-fonte ou no pacote gerado |
| 2 | Rotas | `/gestor/*`, `/admin/*`, `/hardware/status`, `/hardware/ping` só existem na API administrativa. Na pública respondem 404 |
| 3 | Token | Audiência própria (`chargeops-admin`), validade de 30 min, sem `role` (não serve no Supabase). O token do morador dá 401 na API administrativa; o do gestor dá 401 na pública. Opcional: chave de assinatura separada (`ADMIN_JWT_PRIVATE_JWK`) |
| 4 | Login | `/admin/login`: senha (Argon2id) + conta de gestor + código TOTP. Resposta idêntica para nome inexistente, senha errada e conta de morador. 5 erros por nome / 10 por IP em 15 min |
| 5 | Segundo fator | TOTP (RFC 6238), compatível com Google/Microsoft Authenticator, Authy, 1Password. Segredo cifrado no banco com `ADMIN_MFA_KEY`. Cada código vale uma vez. Obrigatório em produção |
| 6 | Papel | `tipo_usuario = 'gestor'` relido do banco a cada chamada: rebaixou, perdeu o acesso na chamada seguinte |
| 7 | CORS | A API administrativa só aceita a origem do painel (`ADMIN_ORIGINS`). O backend recusa subir se a mesma origem estiver nas duas listas |
| 8 | Auditoria | `auditoria_admin`: entrada, recusa e toda alteração, com usuário, IP e horário. Visível no painel em "Acesso e segurança" |
| 9 | Navegador | CSP gerada no build: o painel só conversa com a API administrativa; o app do morador só com a API pública e o Supabase. Sem iframe, sem script de terceiro, fontes servidas pelo próprio app |

Conta de gestor **não entra** pelo app do morador (`/login` responde como senha
errada). Quem é síndico e também carrega o carro usa uma conta de morador para isso.

## 4. O que mudou no backend

| Arquivo | Mudança |
|---|---|
| `main.py` | deixou de montar `rotas_gestor`; `/docs` desligado e `/` enxuto em produção |
| `main_admin.py` | **novo** — API administrativa |
| `rotas_admin.py` | **novo** — login, segundo fator, auditoria |
| `endurecimento.py` | **novo** — cabeçalhos de segurança, comuns às duas APIs |
| `seguranca.py` | token administrativo, TOTP, cifra do segredo, `ip_do_cliente`, limitadores do painel |
| `identidade.py` | `gestor_logado` passa a exigir o token administrativo |
| `config.py` | `AMBIENTE`, `ADMIN_ORIGINS`, `CODIGO_CADASTRO`, `ADMIN_MFA`; CORS de rede local desligado em produção |
| `rotas_conta.py` | IP real atrás de proxy, código de convite, `/config-publica`, gestor barrado no `/login` |
| `hardware_api.py` | `status` e `ping` foram para `router_admin`; IP real nos eventos |
| `provisionar.py` | `chave-mfa`, `gestor-mfa`, `chave-jwt-admin` |
| `db/18_painel_admin.sql` | **novo** — `gestor_mfa` e `auditoria_admin`, fechadas ao navegador |

Regra de negócio (recarga, demanda, cobrança, protocolo do totem): **nada alterado**.

## 5. Testes

- `backend/testes/test_admin_isolamento.py` (15 testes novos): rotas de cada API,
  tokens cruzados, login, segundo fator, modo obrigatório, auditoria, CORS,
  cabeçalhos, `/docs` em produção, IP atrás de proxy, código de convite.
- `test_fluxo_esp32.py` e `test_demanda_fontes.py`: o gestor passou a entrar
  pela API administrativa; as verificações "morador não acessa" viraram 404
  (API pública) e 401 (API administrativa).
- Total do backend: 76 verdes. Totem virtual: 56 verdes, sem alteração.

## 6. O que NÃO foi feito (e por quê)

- **Banco separado / schema separado.** O banco continua um só; a separação é
  de privilégio (tabelas novas sem acesso para o navegador) e de aplicação.
- **WAF, VPN ou Zero Trust na frente do painel.** Depende da hospedagem. O
  `docs/DEPLOY.md` indica onde ligar (Cloudflare Access, por exemplo).
- **Revogação de token antes do vencimento.** O token do painel dura 30 min e
  o papel é relido do banco; não há lista de tokens revogados.
- **Limitadores em armazenamento compartilhado.** Seguem em memória: cada API
  roda em UM processo.

## 7. Para o Daniel revisar

1. Gestor não entra mais pelo `/login` do morador. Se a demo depende de o
   síndico usar o app com a mesma conta, é preciso uma conta de morador para ele.
2. As contas de gestor do seed precisam do segundo fator antes de publicar:
   `python provisionar.py chave-mfa` e `python provisionar.py gestor-mfa --nome "..."`.
3. `provisionar.py verificar` ainda não cobre as tabelas do `db/18`.
4. Quem chamava `/gestor/*` na porta 8000 (scripts, Postman) passa a chamar na 8001.
