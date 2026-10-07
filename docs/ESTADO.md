# Estado do projeto

Atualizado ao fim de cada chat: o que foi feito, o que quebrou, o que vem depois.

---

## 07/10/2026 — Davi · Chat V3 — Auditoria para o Next, painel do gestor separado, visual e deploy (ADR-023)

### Feito

- `docs/AUDITORIA_NEXT.md`: o que foi rodado, o que já tem, o que falta, achados de segurança.
- **ADR-023:** painel do gestor virou aplicativo separado — `admin/` (frontend) e `backend/main_admin.py` (API na porta 8001), com login próprio, segundo fator (TOTP), token de audiência própria, CORS próprio e auditoria. A API pública não tem mais nenhuma rota `/gestor`.
- Endurecimento para publicar: `AMBIENTE=producao` (sem `/docs`, sem CORS de rede local, HSTS), IP real atrás de proxy, código de convite no cadastro, cabeçalhos de segurança, CSP gerada no build.
- App do morador: diagrama de energia vivo, barra inferior no celular (com Sair, que não existia), indicadores em 2 colunas, páginas sob demanda (JS inicial caiu de 571 kB num arquivo para ~113 kB + bibliotecas em cache), fontes servidas pelo app, ícone e manifesto.
- Deploy preparado, **não publicado**: `backend/Dockerfile`, `render.yaml`, `vercel.json` e `_headers` nos dois sites, `docs/DEPLOY.md`.
- `db/18_painel_admin.sql`.

### Testado

- `backend/testes`: 76 verdes (61 + 15 novos). `totem_virtual/testes`: 56 verdes.
- `npm run build` + verificação de isolamento nos dois apps; `eslint` sem erros.
- No navegador (390 px e 1366 px, tema claro e escuro), contra o backend real com banco em memória: login, todas as páginas, recarga simulada, painel do gestor, cadastro do segundo fator e login com código.

### NÃO testado

- Contra o Supabase real (Realtime, RLS das tabelas novas, migration 18).
- Build da imagem Docker e qualquer hospedagem de verdade.
- Em celular físico (só em tela emulada).

### Quebrou / atenção

- **Apagar à mão** em `frontend/src`: `pages/GestorPage.jsx`, `components/GraficoDemanda.jsx`, `components/SimuladorDemanda.jsx` (foram para `admin/`; o build do morador reprova enquanto existirem).
- Gestor não entra mais pelo app do morador. O painel abre em `http://127.0.0.1:5174` e precisa de `uvicorn main_admin:app --port 8001`.
- `npm install` de novo em `frontend/` (fontes) e pela primeira vez em `admin/`.

### Próximo

1. Davi: rodar o `db/18`, `provisionar.py chave-mfa` e `gestor-mfa`; escolher a hospedagem e seguir `docs/DEPLOY.md`.
2. Daniel: revisar a seção 7 do ADR-023.
3. Pendências que continuam: D2 do backend (3 cenários do roteiro), TLS no firmware, firmware em placa.

---

## 06/10/2026 — Davi · Chat V2 — Laço de 401, totem físico e firmware (ADR-021, ADR-022)

### Feito

- **Laço de 401 diagnosticado:** o relógio deste PC estava 249 s atrasado (Windows sem sincronizar). `/v2/hora` devolve o relógio do PC, o banco confere com o dele → `401 fora_da_janela` em todo handshake. Chave, `DEVICE_ID`, `chave_versao` e projeto Supabase conferidos: certos.
- ADR-021: 3 recusas seguidas → o totem para, imprime diagnóstico acionável (terminal, página, LCD) e tenta 1×/min. Recusa conta para a trava offline. O roteiro distingue "não respondeu" de "recusou".
- ADR-022: hardware real — 5 INA219 (o 5º no `Wire1`), relé reversor SPDT na vaga 4 (solar ↔ rede, `fonte: "rede"` implementado), LCD 16x2 com paginação, pinos. Contrato da máquina de estados, totem virtual e testes atualizados.
- Ajustes do Daniel nos testes revisados; fila de energia ganhou teste contra o backend D1.
- `firmware/totem_central/`: tradução C++ da máquina de estados (millis, HMAC v2, lote com fontes, reconciliação, travas). Compila para ESP32 (core 3.3.12).
- Pedido ao backend: `docs/decisoes/pedidos/2026-10-06_totem_para_backend_v2.md`.

### Testado

- `python -m pytest totem_virtual/testes -q`: 56 verdes. `backend/testes`: 61 verdes (nada alterado lá).
- `arduino-cli compile --fqbn esp32:esp32:esp32`: compila, nenhum aviso dos nossos arquivos.

### NÃO testado

- O firmware C++ **não rodou** em placa nenhuma (sem hardware) nem em simulador. Só compilação.
- Contra o Supabase real depois de sincronizar o relógio (depende da ação abaixo).
- Limiares da 18650 e corrente real dos celulares sem D+/D− (ADR-022 D5).

### Quebrou / atenção

- **Ação imediata (Davi):** sincronizar o relógio do Windows e reiniciar o `uvicorn`.
- Tela de espera do LCD agora alterna a cada 3 s (convite ↔ quadro das vagas).

### Próximo

1. Davi: sincronizar o relógio; rodar `python -m totem_virtual roteiro` contra o backend local.
2. Daniel: itens 1 e 3 do pedido (`/hora` pelo relógio do banco; histerese da vaga solar).
3. Bancada: montar conforme `firmware/totem_central/README.md` e seguir a "primeira ligação".

---

## 06/10/2026 — Davi · Chat V1 — Totem virtual (ADR-020)

Branch sugerido: `davi/v1-totem-virtual`.

### Feito

- `docs/decisoes/ADR-020_totem_virtual.md`: registro de decisão (proposto; seção 9 aguarda o Daniel).
- `totem_virtual/`: gêmeo digital do Totem Central — 4 vagas (relé, INA219 e celular virtuais), vaga 4 solar (painel com luz ajustável, bateria 18650, comutação sem paralelo), telemetria em lote em W brutos com `fontes`, LCD 20x4 sem acento, Wi-Fi caindo (guarda e reenvia), reboot (boot novo, relés abertos, handshake reconcilia).
- Página local em `127.0.0.1` (`python -m totem_virtual painel`) e modo roteiro (`python -m totem_virtual roteiro`), os dois com `--bolso` para rodar sem Supabase.
- `docs/contratos/maquina_de_estados_totem.md`: pseudocódigo, base do firmware.
- `docs/decisoes/pedidos/2026-10-06_totem_virtual_backend.md`: pedidos ao backend.
- Nada alterado em `backend/`, `db/` ou `placa_v2.py`.

### Testado

- `python -m pytest totem_virtual/testes -q`: 48 testes verdes. `backend/testes` segue com 42 verdes.
- Roteiro contra o backend de hoje (em memória e por HTTP com uvicorn): 5 passam, 0 falham, 12 aguardando backend.
- Roteiro contra o servidor v2.1 de referência (`totem_virtual/testes/servidor_v21.py`): 16 passam, 1 pulado.

### NÃO testado

- Contra o Supabase de verdade (RPCs reais `consumir_seq` / `registrar_lote_telemetria`): depende da chave do `provisionar.py placa-v2`.
- Contra o Totem v2.1 do Daniel: o lado v2.1 foi testado só contra a minha leitura do contrato.
- No Windows (desenvolvido e testado em Linux, Python 3.13; só biblioteca padrão + o que já está no `requirements.txt`).
- Limiares de tensão da vaga 4 em hardware real.

### Quebrou / atenção

- Nada quebrou. Atenção à **regra 5**: o backend grava as leituras do totem virtual como `origem = 'medido'` (pedido aberto).

### Próximo

1. Daniel: responder a seção 9 do ADR-020 e o pedido; mandar `DEVICE_ID`, `DEVICE_KEY_HEX` e as tags por canal privado.
2. Rodar `python -m totem_virtual roteiro` contra o backend local com o banco de verdade.
3. Quando o Totem v2.1 entrar: rodar o roteiro de novo — os "aguardando backend" têm de virar "passou". É o gate de 11/10.
4. Chat do firmware: traduzir `firmware.py` seguindo `maquina_de_estados_totem.md`.
