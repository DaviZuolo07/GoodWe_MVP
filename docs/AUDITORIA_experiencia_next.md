# Auditoria da experiência Next — 07/10/2026

- **Autor:** Davi (sessão de frontend/totem, com override do contrato v1 para esta rodada)
- **Escopo:** as 6 mudanças pedidas + validação da experiência do estande + revisão de segurança do admin.
- **Regra honrada:** frontend/admin só apresentam; a conta é sempre do backend. Toda mudança que caiu na pasta do Daniel (backend/db/admin) está registrada aqui e no commit.

> **Ação necessária antes da banca:** aplicar `db/19_condominio_perfil.sql` no Supabase e, dentro de `backend/`, rodar `python preparar_totem.py`. Sem o 19, o `preparar_totem` avisa e para; o app continua funcionando (o `/condominios` cai no formato antigo sozinho).

---

## 1. O que mudou, item a item

### Item 1 — Totem Next no cadastro esconde Bloco/Apto
- O ponto do Totem é um estande, não tem bloco/apto. Agora o condomínio carrega um `perfil` (`residencial` | `bancada`); quando o selecionado é `bancada`, o campo Bloco/Apto some do cadastro.
- **Onde:** `frontend/src/pages/Login.jsx`, `frontend/src/components/CondominioSelect.jsx` (`ehCondominioBancada`), `backend/rotas_conta.py` (`/condominios` passa a devolver `perfil`), `db/19_condominio_perfil.sql`, `backend/preparar_totem.py`.
- **Não quebra sem a migration:** o `/condominios` tenta `perfil` e, se a coluna não existir, volta ao formato antigo; o frontend então reconhece o Totem pelo nome (Estande/Totem).

### Item 2 — "Celular" ou "Carro Elétrico" para todos; Totem só celular
- O cadastro e "Meus Veículos" têm o par Celular / Carro Elétrico. No condomínio de bancada, trava em celular (lá não entra carro).
- **Onde:** `Login.jsx`, `VeiculosPage.jsx`.

### Item 3 — Celular pela base local; placa some; conta visível e, no admin, ao vivo
- "Celular (bancada ESP32)" virou só **Celular**. O celular **não pede placa**.
- Em vez de digitar o mAh (ninguém sabe o do próprio aparelho), escolhe-se o **modelo** e a energia vem de uma **base local embarcada** (`frontend/src/lib/celulares.js`, ~40 modelos; mAh × 3,85 V → kWh). "Outro" abre o campo manual de mAh. **Por que base local e não webhook:** o estande pode ficar sem internet na banca; uma API que falha travaria o cadastro. Funciona offline, sem chave.
- A energia estimada aparece na hora do cadastro, e a **previsão de recarga** (tempo/custo) continua vindo do backend (`/recargas/previa`), gravada no banco pelo simulador.
- **No painel do admin**, uma seção nova **"Recargas ao vivo"** mostra, por sessão em andamento: morador/bloco, veículo, % → alvo, potência, energia, tempo restante e **consumido** — tudo calculado pelo backend (`detalhar_custo`, a mesma conta do recibo). Atualiza a cada 10 s (o ritmo do alocador).
- **Onde:** `frontend/src/components/CamposCelular.jsx` (novo, compartilhado), `Login.jsx`, `VeiculosPage.jsx`, `backend/rotas_gestor.py` (`recargas_ao_vivo`), `admin/src/pages/PainelPage.jsx` (seção nova).
- **Limite respeitado:** o backend já valida celular ≤ 0,2 kWh / 0,2 kW; todos os modelos e o "Outro" (≤ 50.000 mAh) ficam abaixo.

### Item 4 — "Acompanhar pelo painel" agora leva ao painel
- **Causa:** o botão chamava `onSucesso`, que fazia `setSelectedCharger(null)` — ou seja, **fechava** o painel de detalhe. A pessoa tinha de clicar no carregador de novo.
- **Correção:** novo callback `onAcompanhar` que fecha só o modal, **mantém o ponto selecionado** (o painel segue aberto com o monitor ao vivo) e rola até ele no celular.
- A recarga simulada (carro, sem RFID) já funcionava para morador e visitante — não há trava por tipo de usuário no backend; confirmei lendo `recarga.py`/`rotas_recarga.py`. O que faltava era só a navegação.
- **Onde:** `frontend/src/components/PagamentoModal.jsx`, `frontend/src/pages/Dashboard.jsx`.

### Item 5 — Interface com mais vida/3D, sem sair do contrato GoodWe
- Mudança **só visual**, aditiva e reversível; nenhuma lógica tocada. Só luz branca tênue e o vermelho/flare da marca — **nada do roxo/azul** dos templates de referência.
- Novas camadas CSS (`frontend/src/index.css`): `.realce` (filete de luz no topo = vidro erguido), `.halo-carga` (brilho de energia atrás do carro quando carrega), `.aurora` (dois focos quentes que respiram, só na tela de entrada). Tudo com `pointer-events: none` e **desligado por `prefers-reduced-motion`** — mantém a rapidez.
- Aplicado em `ChargerCard`, `PainelCarregador`, card do login e nos cards "ao vivo" do admin.
- **Onde:** `frontend/src/index.css`, `admin/src/index.css`, `ChargerCard.jsx`, `Dashboard.jsx`, `Login.jsx`, `admin/.../PainelPage.jsx`.

### Item 6 — Segurança do admin: revisão estática (seção 3 abaixo)

---

## 2. Validação

| Verificação | Resultado |
|---|---|
| `backend` — `pytest testes` | **76 verdes** (nada em backend/db quebrou) |
| `frontend` — `npm run lint` | 0 erros (3 warnings pré-existentes de fast-refresh) |
| `frontend` — `npm run build` + isolamento | **ok**: 51 arquivos conferidos, nenhuma referência ao painel do gestor nem a segredo |
| `admin` — `npm run build` | **ok** |
| Diagnósticos do editor (arquivos backend alterados) | limpos |

**Caminhos revisados à mão (experiência Next):**
- Cadastro no Totem → sem bloco/apto, trava em celular, modelo preenche a energia → `/cadastro` aceita (celular ≤ 0,2 kWh).
- Iniciar recarga simulada (visitante **e** morador) → `preparar` sem `aguardando_cartao` → MONITOR → **Acompanhar pelo painel** mantém o ponto e mostra o monitor ao vivo.
- Fluxo com RFID (hardware) → AGUARDANDO (aproxime cartão) → MONITOR → mesmo botão.
- Admin → "Recargas ao vivo" lê `recargas_ao_vivo` (backend) e mostra a conta por sessão.

**Não validado em runtime nesta sessão** (sem subir a stack contra o Supabase real, para não criar dado de teste no banco de vocês): a renderização visual ao vivo e o fluxo ponta a ponta no navegador. O build e os testes cobrem a corretude; posso subir a stack e tirar prints **se você autorizar** rodar contra o Supabase real (vai criar usuários/recargas de teste).

---

## 3. Revisão de segurança do admin (item 6, estática)

Tentei "entrar" como quem não deveria, só lendo o repositório e a config. **Postura sólida; nenhum achado crítico.**

| Frente | O que achei |
|---|---|
| Segredos no git | Só `*.env.example` rastreados, todos com placeholders (`...`, `64_caracteres_hexadecimais`). `.gitignore` cobre `.env`, `.env.*`, `segredos.h`. **Nenhuma chave real** no histórico de arquivos rastreados. |
| `service_role` / JWT no bundle | **Nenhuma** ocorrência em `frontend/src` nem `admin/src`. O front usa só a chave **pública** (anon), e o RLS fecha o resto. |
| Separação do admin | O painel do gestor é **outra aplicação** (`backend/main_admin.py`, porta 8001, ADR-023). Na API pública as rotas `/gestor` e `/admin` **não existem** (dão 404). O frontend do morador não referencia `/gestor`, `/admin`, `8001` nem `main_admin` (o `verificar-isolamento` reforça isso no build). |
| Login do admin | Senha + conta de gestor + **código do autenticador (MFA)**; token de **audiência própria** (o token do morador é recusado); CORS restrito a `ADMIN_ORIGINS`; login/recusa/alteração em `auditoria_admin`. |
| "Não deve ser localizada" | `admin/public/robots.txt` = `Disallow: /`; `_headers` com `X-Robots-Tag: noindex, nofollow`, `X-Frame-Options: DENY`, CSP `frame-ancestors 'none'`, HSTS, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`. Tokens do admin só em memória (nunca localStorage/cookie). |
| Bypass de auth | Nenhum `TODO/FIXME` desligando auth; nada suspeito em `main_admin.py`. |

**Recomendações (não bloqueiam):**
1. Confirmar que, **em produção**, `ADMIN_MFA=obrigatorio` (no `.env.example` está comentado; o padrão de produção deve ser obrigatório).
2. Garantir que a API administrativa (8001) **não** fique no mesmo host/porta público da API do morador, e que `ADMIN_ORIGINS` aponte só para o domínio do painel.
3. Varredura ativa do deploy (gobuster na URL publicada) ficou **de fora** — ela precisa da sua autorização e da URL real do host. Se quiser, me passe a URL e eu faço a sondagem de caminhos.

---

## 4. Mudanças na pasta do Daniel (para revisão dele)

- **`db/19_condominio_perfil.sql`** (novo): coluna `condominios.perfil` (`residencial`|`bancada`, default `residencial`, idempotente) e marca o estande como `bancada`.
- **`backend/rotas_conta.py`**: `/condominios` e `/me/locais` devolvem `perfil` via helper tolerante (`_condominios_ordenados`) — cai no formato antigo se a coluna não existir.
- **`backend/rotas_gestor.py`**: `/gestor/painel` ganha `recargas_ao_vivo` (lista por sessão ativa, custo por `detalhar_custo`).
- **`backend/preparar_totem.py`**: marca o estande com `perfil='bancada'` e passa a exigir a migration 19 no `checar_banco`.
- Nada em `demanda.py`, `recarga.py`, `fisica.py`, `simulador.py` ou nas RPCs foi tocado.

Se preferir outra abordagem para o `perfil` (ex.: derivar do perfil dos carregadores em vez de coluna no condomínio), é só dizer — o frontend já tem o fallback por nome e não depende disso para não quebrar.
