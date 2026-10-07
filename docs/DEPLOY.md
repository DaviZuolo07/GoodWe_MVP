# Publicar o ChargeOps

O projeto está PREPARADO para publicar; nada foi publicado. Este guia leva do
repositório a quatro endereços no ar. Tempo estimado: uma tarde.

```
  app do morador      site estático   frontend/   → https://<app>
  painel do gestor    site estático   admin/      → https://<painel>
  API pública         contêiner       backend/    → https://<api>         (sempre ligada)
  API administrativa  contêiner       backend/    → https://<api-admin>   (sempre ligada)
```

Os dois sites podem usar o endereço grátis da hospedagem (ex.: `*.vercel.app`).
O que **não** pode ser grátis-que-dorme é a API pública: o laço que avança as
recargas e a conversa com o totem vivem dentro dela. Se ela dorme, a recarga
congela e o totem abre os relés em 120 s.

---

## 0. Antes de tudo (uma vez)

1. **Supabase → SQL Editor:** rode `db/18_painel_admin.sql` (e os 15–17, se
   ainda não rodaram neste banco).
2. **Segredos novos** (de dentro de `backend/`):
   ```
   python provisionar.py chave-mfa                       → ADMIN_MFA_KEY
   python provisionar.py gestor-mfa --nome "Nome do Gestor"   (um por gestor)
   ```
   O segundo comando mostra, uma vez, a chave para o app autenticador.
3. **Rotacione o que já circulou.** A auditoria de 24/09 registra um token de
   ESP32 no histórico do git. Se o `.env` já foi mandado em zip ou grupo, gere
   de novo `JWT_PRIVATE_JWK`, `DEVICE_MASTER_KEY` e a chave secreta do Supabase.
4. **Escolha um código de convite** para o cadastro (`CODIGO_CADASTRO`).
5. **Apague do app do morador** os três arquivos que foram para `admin/`
   (o build reprova enquanto existirem):
   ```
   frontend/src/pages/GestorPage.jsx
   frontend/src/components/GraficoDemanda.jsx
   frontend/src/components/SimuladorDemanda.jsx
   ```

## 1. Backend (as duas APIs)

Qualquer hospedagem que rode Docker serve. Com o Render, o arquivo
`render.yaml` na raiz cria os dois serviços (New → Blueprint) e pede os
segredos no painel. Em outra hospedagem, crie dois serviços a partir do mesmo
`backend/Dockerfile` (contexto = raiz do repositório):

| Variável | API pública | API administrativa |
|---|---|---|
| `SERVICO` | `publico` | `admin` |
| `AMBIENTE` | `producao` | `producao` |
| `PROXIES_CONFIAVEIS` | `1` | `1` |
| `SUPABASE_URL`, `SUPABASE_KEY` (secreta) | ✔ | ✔ |
| `JWT_PRIVATE_JWK` | ✔ | ✔ |
| `DEVICE_MASTER_KEY` | ✔ | — |
| `FRONTEND_ORIGINS` | `https://<app>` | — |
| `ADMIN_ORIGINS` | — | `https://<painel>` |
| `ADMIN_MFA_KEY`, `ADMIN_MFA=obrigatorio` | — | ✔ |
| `CODIGO_CADASTRO` | ✔ | — |
| `CHAT_MODO`, `OLLAMA_*` | ✔ | — |
| `MODO_DEMO` | `0` | — |

Regras que não são opcionais:

- **Uma instância, um processo** por serviço. Sem `--workers`, sem autoscaling.
- **Plano sempre ligado** na API pública.
- `PROXIES_CONFIAVEIS=1` quando há um proxy da hospedagem na frente (o normal).
  Com `0`, o limite de tentativas por IP vira um limite para todo mundo junto.
  Com um número maior que o real, o IP passa a poder ser forjado.
- `FRONTEND_ORIGINS` e `ADMIN_ORIGINS` com `https://`, sem barra no fim, e sem
  origem repetida entre as duas (o backend recusa subir).

Conferência: `https://<api>/` responde `{"status":"ok"}`; `https://<api>/docs`
responde 404; `https://<api>/gestor/painel` responde 404;
`https://<api-admin>/admin/me` responde 401.

## 2. App do morador (`frontend/`)

Site estático. Na Vercel: New Project → pasta raiz `frontend` (o `vercel.json`
já traz build, rotas e cabeçalhos). Netlify e Cloudflare Pages usam
`public/_headers` e `public/_redirects`.

Variáveis de build:

```
VITE_API_URL=https://<api>
VITE_SUPABASE_URL=https://<projeto>.supabase.co
VITE_SUPABASE_KEY=<chave PUBLICÁVEL>
```

O build roda `scripts/verificar-isolamento.mjs` no fim e falha se houver
referência ao painel ou segredo no pacote. Para ele conferir também os
endereços, defina no ambiente do build `ENDERECO_DO_PAINEL` e
`ENDERECO_DA_API_ADMIN` (opcional).

## 3. Painel do gestor (`admin/`)

Outro projeto na hospedagem, pasta raiz `admin`. Uma variável de build:

```
VITE_ADMIN_API_URL=https://<api-admin>
```

Camada extra recomendada: pôr o endereço do painel atrás de um controle de
acesso da própria hospedagem (Vercel Deployment Protection, Cloudflare Access)
restrito aos e-mails dos gestores. O login com segundo fator continua valendo
por baixo.

## 4. Supabase

- Settings → API → confirme que a chave do frontend é a **publicável**.
- A chave pública do JWT do backend continua importada em JWT Keys.
- `python provisionar.py verificar` contra o banco de produção.

## 5. Totem

O firmware fala HTTP puro (`BACKEND_URL "http://..."`). Com a API em HTTPS há
dois caminhos:

- **No estande, rede local:** rode a API pública num notebook na mesma rede do
  totem (como hoje) e use a nuvem só para o app. Mais simples e é o que já foi testado.
- **Totem falando com a nuvem:** exige TLS no firmware (`WiFiClientSecure` com
  o certificado raiz da hospedagem). Não implementado nem testado.

## 6. Roteiro da semana de teste

1. Celular (4G, fora do Wi-Fi): abrir `https://<app>`, criar conta com o código
   de convite, adicionar à tela inicial, iniciar e encerrar uma recarga simulada.
2. Painel: entrar com senha + código, mudar o limite de potência, conferir a
   linha em "Acesso e segurança".
3. Tentar entrar no painel com uma conta de morador → "Credenciais inválidas".
4. Errar a senha do painel 5 vezes → bloqueio de 15 min só para aquele nome.
5. `python -m totem_virtual roteiro` com `BACKEND_URL=https://<api>`.
6. Deixar 24 h ligado e conferir que a recarga em andamento não congelou.

## 7. O que este preparo NÃO verificou

- A imagem Docker não foi construída aqui (sem Docker disponível na sessão).
- Nenhuma hospedagem foi configurada; `vercel.json` e `render.yaml` seguem a
  documentação das plataformas, mas não rodaram de verdade.
- O app publicado contra o Supabase real (Realtime incluído).
