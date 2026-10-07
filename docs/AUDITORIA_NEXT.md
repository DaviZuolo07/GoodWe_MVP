# Auditoria para o Next — 07/10/2026

Escopo: validar o que entrou nos chats V1/V2 (totem virtual, ADR-021, ADR-022,
firmware C++), mapear o que falta para o app rodar publicado na semana do Next
e revisar a segurança, com foco no isolamento do painel do gestor (ADM).

Feita sobre uma cópia do repositório, em Linux / Python 3.13 / Node. Nada foi
alterado no projeto além deste arquivo. Os `.env` e `segredos.h` não foram lidos.

> **Atualização, mesmo dia (Chat V3).** Depois desta auditoria, parte dos
> achados foi corrigida. A seção 8, no fim, diz o estado de cada item. As
> seções 1 a 7 ficam como retrato de ANTES das correções.

---

## 1. O que foi rodado e o resultado

| Verificação | Resultado |
|---|---|
| `backend`: `python -m pytest testes -q` | **61 passam** |
| `totem_virtual`: `python -m pytest totem_virtual/testes -q` | **56 passam** (3 min 21 s) |
| `python -m totem_virtual roteiro --bolso` | **14 passam, 3 falham** (`desplugado`, `vaga_sem_celular`, `celular_cheio`) — os três que dependem do D2, como esperado |
| `frontend`: `npm run build` | compila; **um único JS de 571 kB** (157 kB gzip) |
| `frontend`: `npm run lint` | **13 erros**, todos `react-hooks/set-state-in-effect` (não quebram o build) |
| `frontend`: `npm audit --omit=dev` | 0 vulnerabilidades |
| Constantes `firmware/totem_central/config.h` × `totem_virtual/config.py` | tempos, limites de lote e limiares da bateria conferem um a um |
| Tela de login em 390 px e 1280 px | sem rolagem horizontal |

Não verificado aqui: o firmware C++ (não recompilei nem rodei em placa), o
backend contra o Supabase real, o app logado no celular (precisa das chaves) e
se o repositório no GitHub é público.

## 2. O que as implementações novas fazem (resumo para a equipe)

- **Laço de 401** — a causa era relógio do PC atrasado: `/hardware/v2/hora`
  devolve `time.time()` do servidor e o banco confere a janela de 120 s com o
  relógio dele. Num servidor na nuvem (NTP) o sintoma some sozinho; no notebook
  do estande ele volta. O pedido ao Daniel (`/hora` pelo relógio do banco)
  continua valendo.
- **ADR-021** — 3 recusas seguidas: o totem para, mostra o que fazer e tenta
  1×/min; recusa conta para a trava offline (relés abrem em 120 s).
- **ADR-022** — hardware real: 5 INA219 (o 5º no `Wire1`), reversor solar/rede
  na vaga 4 com 30 s de permanência mínima, LCD 16x2 paginado.
- **Firmware** — tradução de `firmware.py`; só compilado.

## 3. Segurança — o que já está bom

- Identidade só pelo JWT ES256 do backend; nenhum corpo aceita `usuario_id`.
- Todas as rotas `/gestor/*` e `/hardware/status|ping` passam por `gestor_logado`
  (confere `tipo_usuario` no banco a cada chamada). Gestor não se cadastra pela
  tela pública.
- Banco: RLS em tudo, `revoke` de escrita para o navegador, tabelas sensíveis
  sem `SELECT`, RPCs só para `service_role`.
- Senha Argon2id, resposta de login em tempo constante, limite de tentativas.
- Totem v2: HMAC com chave derivada, anti-replay, corpo limitado a 8 kB.
- Sem `eval`/`exec`/`subprocess`/`pickle` no Python; sem `dangerouslySetInnerHTML`,
  `innerHTML` ou `eval` no frontend; token só em memória.
- Backend recusa subir com a chave publicável; rotas `/debug` só com `MODO_DEMO=1`.

## 4. Segurança — o que falta antes de publicar

Ordenado por gravidade para um deploy público.

| # | Achado | Onde | Por que importa | Correção |
|---|---|---|---|---|
| S1 | **Tela do gestor vai no mesmo bundle do morador** | `Dashboard.jsx` importa `GestorPage` | Os dados estão protegidos (403 no backend), mas todo visitante baixa o código do painel ADM: rotas, campos, textos. É o oposto do que você pediu | App do gestor separado: outro build, outro endereço, outro login |
| S2 | **Token do gestor é igual ao do morador** | `seguranca.emitir_token` | Mesmo formato, mesma validade (120 min), mesma API | Claim própria para gestor, validade curta, origem CORS só do painel ADM |
| S3 | **`/docs` e `/openapi.json` abertos** | `main.py` (padrão do FastAPI) | Publica o mapa completo da API, inclusive `/gestor` e `/hardware` | Desligar em produção |
| S4 | **Limite por IP quebra atrás de proxy** | `rotas_conta._ip` usa `request.client.host` | Na hospedagem todo mundo chega com o IP do proxy: 5 cadastros em 10 min ou 20 senhas erradas **bloqueiam o estande inteiro** | Ler o IP real só do proxy confiável |
| S5 | **Cadastro aberto + crédito grátis + chatbot pago** | `/cadastro`, `/me/carteira/creditar`, `/chatbot` | Em endereço público qualquer um cria contas e gasta a cota do Ollama (20 msg/min por conta) | Código de acesso do evento no cadastro, ou `CHAT_MODO=regras` como teto |
| S6 | **CORS só aceita rede local** | `config.FRONTEND_ORIGIN_REGEX` | O domínio publicado é recusado; e a regex de IP privado não deve valer em produção | `FRONTEND_ORIGINS` com o domínio e regex vazia em produção |
| S7 | **Sem cabeçalhos de segurança** | hospedagem do frontend | Sem CSP, `frame-ancestors`, HSTS, `nosniff` | Configurar na hospedagem |
| S8 | **Totem fala HTTP puro** | `enlace.cpp`, `segredos.exemplo.h` | Com backend em HTTPS o firmware precisa de TLS; hoje o UID da tag trafega em claro (a assinatura protege contra adulteração, não contra leitura) | TLS no firmware, ou totem e backend na mesma rede local no estande |
| S9 | **Token antigo do ESP32 no histórico do git** | já apontado na `AUDITORIA.md` de 24/09 | Vale enquanto não for trocado | Confirmar que foi regerado; se o repositório for público, conferir o histórico |
| S10 | `GET /` devolve `modo_demo` | `main.py` | Informação de operação para anônimo | Devolver só `status` |
| S11 | Limitadores em memória | `seguranca.LimitadorTentativas` | Zeram a cada reinício e não valem com mais de um processo | Rodar com um processo só (suficiente para o Next) |

## 5. O que falta para publicar e rodar no celular

| # | Lacuna | Detalhe |
|---|---|---|
| D1 | **Backend precisa ficar ligado o tempo todo, num processo só** | O laço do simulador (10 s) e os limitadores vivem dentro do processo. Hospedagem que dorme (plano grátis) ou serverless **congela as recargas e derruba o totem** |
| D2 | `VITE_API_URL` | Sem ela o app procura a API na porta 8000 do mesmo endereço; publicado, precisa apontar para o backend |
| D3 | Recarregar a página pede login de novo | Decisão de segurança (token em memória). No celular, trocar de app e voltar pode derrubar a sessão no meio da demo |
| D4 | Bundle único de 571 kB | Dividir por página; o painel do gestor sai do bundle com o S1 |
| D5 | 13 erros de lint | Limpar antes de mexer no visual |
| D6 | Fontes vêm do Google Fonts por `@import` | Depende de rede externa no estande e precisa entrar na CSP (S7); servir as fontes junto do app resolve os dois |
| D7 | Três cenários do roteiro falham | Dependem do D2 do backend (desplugado, vaga vazia, celular cheio): em demo, a vaga não libera sozinha |
| D8 | Firmware nunca rodou em placa | Seguir a "primeira ligação" do README; calibrar limiares da 18650 |
| D9 | Migrations 15–17 no Supabase de produção | Rodar e conferir com os `*_verificacao.sql` e `provisionar.py verificar` |
| D10 | Sem HTTPS local, sem PWA | Publicado resolve o HTTPS; manifesto e ícone deixam "adicionar à tela inicial" |

## 6. O que já tem

Login/cadastro, dashboard com pontos e fila, prévia com reserva, recibo por
fonte, carteira e extrato, histórico, notificações em tempo real, veículos,
configurações (tema claro/escuro), assistente, painel do gestor (demanda sem ×
com gestão, valor, simulador, Modbus, cartões), protocolo v2 do totem, totem
virtual com painel e roteiro, firmware compilável, tokens de cor GoodWe e
animações com `prefers-reduced-motion`.

## 7. Ordem sugerida

1. S3, S4, S6, S10 e D2 (pequenos, destravam o deploy).
2. S1 + S2: separar o painel do gestor.
3. Deploy em hospedagem sempre ligada + domínio; rodar a semana de teste.
4. S5 e S7.
5. Visual novo e D4/D5/D6 (não mudam contrato com o backend).
6. S8, D7, D8 com o Daniel e a bancada.

## 8. Estado depois das correções (Chat V3, ADR-023)

| Item | Estado | Onde |
|---|---|---|
| S1 painel no bundle do morador | **corrigido** | `admin/` é outro app; `frontend/scripts/verificar-isolamento.mjs` reprova o build se voltar |
| S2 token igual ao do morador | **corrigido** | audiência `chargeops-admin`, 30 min, segundo fator (TOTP) |
| S3 `/docs` aberto | **corrigido** | desligado com `AMBIENTE=producao` |
| S4 limite por IP atrás de proxy | **corrigido** | `PROXIES_CONFIAVEIS` + `seguranca.ip_do_cliente` |
| S5 cadastro aberto | **corrigido (opcional)** | `CODIGO_CADASTRO`; sem ele o cadastro segue aberto |
| S6 CORS | **corrigido** | listas separadas por app; rede local desligada em produção |
| S7 cabeçalhos | **corrigido** | API (`endurecimento.py`), sites (`vercel.json`, `_headers`), CSP no build |
| S8 totem em HTTP | aberto | ver `docs/DEPLOY.md` seção 5 |
| S9 token antigo no git | aberto | ação manual: regerar e conferir o repositório |
| S10 `modo_demo` em `/` | **corrigido** | só `status` em produção |
| S11 limitadores em memória | aceito | um processo por serviço (documentado) |
| D1 backend sempre ligado | preparado | `backend/Dockerfile`, `render.yaml`; falta contratar |
| D2 `VITE_API_URL` | documentado | `docs/DEPLOY.md` |
| D3 recarregar pede login | mantido | decisão de segurança; token segue só em memória |
| D4 bundle único | **corrigido** | páginas sob demanda, bibliotecas em arquivo próprio |
| D5 lint | **corrigido** | 0 erros (regra de efeito desligada com justificativa no `eslint.config.js`) |
| D6 fontes externas | **corrigido** | servidas pelo app (`@fontsource`) |
| D7 três cenários do roteiro | aberto | depende do D2 do backend |
| D8 firmware em placa | aberto | bancada |
| D9 migrations em produção | aberto | agora inclui o `db/18` |
| D10 PWA | **parcial** | manifesto e ícone; sem funcionamento offline |

Testes depois das correções: backend 76 verdes, totem virtual 56 verdes.
