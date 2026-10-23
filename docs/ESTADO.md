# Estado do projeto

Atualizado ao fim de cada chat: o que foi feito, o que quebrou, o que vem depois.

---

## 23/10/2026 — Davi · Chat V8 — Totem de UMA vaga, com o relé liberando energia

A montagem física que funcionou tem **uma** vaga (o Gustavo está com ela), e o relé
dela libera energia de verdade. O projeto passou a ser parametrizado pelo número de
vagas, em vez de supor quatro. Contrato de integração: `docs/UMA_VAGA.md`.

### Feito
1. **Firmware `firmware/totem_next/`:** `PORTAS` (config.h) manda em tudo — `1` por
   padrão, `4` volta ao totem de quatro vagas sem outra mudança. O handshake compara
   com o número de portas do backend e **avisa no serial** se diferirem.
2. **Bug corrigido:** a página do LCD com o quadro das vagas escrevia `3:` e `4:` fixos
   e lia além do fim do vetor quando `PORTAS < 4`. Agora monta as linhas por `PORTAS`.
3. **Comandos no monitor serial** (`t <UID>`, `b [vaga]`, `s`) e status automático a
   cada 5 s: plano B quando o leitor ou o botão falham, e o jeito de conduzir a
   demonstração sem tocar no totem. Passam pelo mesmo `POST /hardware/v2/rfid`.
4. **`USAR_RELE`** (bancada sem o módulo de relé) e **`ACELERAR`** (time-lapse de
   demonstração; `1.0` em operação, e acima disso a energia é declarada projeção).
5. **`preparar_totem.py --vagas N`** (1 a 4; padrão 1 com `--next`): limite do estande
   = 7,5 kW × vagas, e diminuir o número **apaga** as vagas que sobram, com as portas
   da placa. Se tiverem histórico, ficam offline e fora da placa em vez de apagadas.
   Sem `--next`, segue exigindo 4 (a vaga solar é a T4).
6. **Docs:** `docs/UMA_VAGA.md` (novo: integração, fiação, contrato das rotas, o que é
   real e o que é modelo), `docs/RODAR_NO_NOTEBOOK.md` (uma vaga, hotspot do Windows
   em 2,4 GHz, teste do `/hora` antes de ligar a placa, regra de bloqueio do firewall,
   roteiro de water-filling com uma vaga), README do firmware e README da raiz.

### Testado
- `pytest backend/testes` **124 verdes** (3 novos: uma vaga de ponta a ponta, diminuir
  vagas, e `--vagas` sem `--next` recusado); `totem_virtual/testes` **57 verdes**.
- `teste_carga.cpp` **TUDO PASSOU**, agora com 3 cenários de uma vaga.
- Firmware compila sem erro **nem aviso** com `PORTAS` em 1, 2, 3 e 4.

### NÃO testado
- O firmware desta versão numa placa (o de 22/10 chegou a fazer handshake e telemetria
  no notebook do estande; este mudou LCD, serial e `PORTAS`).
- Relé liberando energia para um celular de verdade ponta a ponta.

### Próximo
1. Gravar o `totem_next` na placa montada e seguir a seção 9 do `RODAR_NO_NOTEBOOK.md`.
2. Apagar do notebook os restos `backend/testes/test_maquina_de_estados.py` e
   `test_roteiro.py` (saíram do git; a versão atual mora em `totem_virtual/testes/`).
   São eles que quebram o `pytest` lá.
3. Apagar a pasta `firmware/totem_demo/` do notebook: era a tentativa de 22/10 e foi
   absorvida pelo `totem_next` (nunca entrou no git).

---

## 22/10/2026 — Davi · Chat V7 — Totem Next sem sensor, painel seguro, rodar no notebook

Pedido do Davi para a banca de 23/10 (backend, db, admin, frontend e firmware: registrado para o Daniel). Roteiro do dia: `docs/RODAR_NO_NOTEBOOK.md`.

### Feito
1. **Segurança do painel:** segundo fator SEMPRE obrigatório (`ADMIN_MFA=opcional` não existe mais; nome + senha abriam tudo). Sem o código, o token (10 min) só abre `/admin/me` e `/admin/mfa/*`. `provisionar.py admin-global` só recebe o nome (senha gerada uma vez, não recria nem promove conta); saíram `--senha`, `--nova-senha` e `senha-gestor`; `senhas-demo` não toca gestor.
2. **Operadores pelo Google** (`rotas_operadores.py`, db/23): pedido → aprovação do admin da plataforma → conta de gestor presa ao condomínio, sem senha, com MFA. Revogar corta na hora.
3. **Divisão por tempo (water-filling no relé):** porta de relé com o 10025 ligado é modulável (`demanda.por_tempo`); a `fracao` vai para a placa; mínimo de 20% da vaga; previsão de término usa a fração.
4. **Firmware `firmware/totem_next/`:** sem INA219/solar, pinos da fiação real, modelo de carga do celular (rótulo `simulado`), rodízio McNaughton numa janela de 30 s, LCD com fim previsto e tomada derivada. Compila (83% flash) e o modelo passa no teste de PC.
5. **Série de toda recarga** (`leituras_sessao`, db/23) + `/recargas/{id}/serie`; % real do celular (`/recargas/{id}/bateria`, Battery API do Android).
6. **Painel:** abas Sessões (detalhe com gráfico, local, usuário, demanda, energia da tomada), Sala Next (cadastros, celulares, recargas, vagas, limite e "pico agora"), Operadores.
7. `preparar_totem.py --next`. Auditoria das 22 migrations (nenhuma alterada) e quadro de chaves no roteiro.

### Testado
- pytest backend 121 e totem virtual 57 verdes; lint/build do app e do painel; firmware compila sem aviso nosso; `teste_carga.cpp` (zig c++) TUDO PASSOU.

### NÃO testado
- Firmware numa placa; Google com um Client ID real; db/23 no Supabase real; navegador (só build).

### Próximo
1. Davi: rodar o db/23; seguir `docs/RODAR_NO_NOTEBOOK.md`; rotacionar as chaves se o `.env` viajou.
2. Daniel: revisar `rotas_admin.py`, `rotas_operadores.py`, `rotas_sessoes.py`, `serie.py`, `demanda.por_tempo` e o db/23.

---

## 19/10/2026 — Davi · Chat V6 — Correções B1–B5 para o NEXT

Override do contrato v1 de novo (autorizado): backend mexido e registrado para o Daniel. Detalhes em `docs/CORRECOES_NEXT_B1_B5.md`; contrato em `docs/contratos/experiencia_next.md`; estudo em `docs/MAPA_DE_ESTUDO.md`.

### Feito
1. **B2/B4** no alocador: vaga solar na rede vira modo rápido e entra na divisão; zero com motivo (`sem_potencia_disponivel`).
2. **Achado:** porta do totem é carga fixa (relé) — o alocador não a divide. Vaga 4 no sol agora fica fora do barramento (antes ia 6,5 kW da 18650 para a conta da rede); pausada = 0; admissão continua contando a vaga 4 pela rede.
3. **B3:** 5 INA219 = 4 vagas + **painel**; 18650 pelo ADC (GPIO 35); potência da bateria deduzida. Totem virtual e firmware (ADR-022 revisto).
4. **B1:** roda no PC do Gustavo com o Supabase do Davi; `HTTP_TIMEOUT_MS` 8000; firewall/IP fixo/checklist no README.
5. `preparar_totem.py`: limite 30 kW (com 20 a 3ª vaga ia para a fila); T4 com 10032 = 1 e 10024 ligado.
6. **B5:** README (22 migrations, pytest, Totem Central, rede do estande, sem deploy).

### Testado
- pytest backend 108 e totem virtual 57 verdes; firmware compila (core 3.3.12, 83 % flash, 18 % RAM, sem avisos nossos).

### NÃO testado
- Firmware numa placa real; latência no hotspot; `preparar_totem.py` contra o banco real.

### Quebrou / atenção
- A troca solar → rede leva ~50 min com a 18650 cheia: ensaiar com ela em ~3,65 V.
- Decisão em aberto: dividir de verdade no totem exigiria ciclar o relé (não feito).

### Próximo
1. Gustavo: rodar `preparar_totem.py --fisico --sem-env`, montar painel/divisor, calibrar, gravar.
2. Daniel: revisar `demanda.py` (`fora_da_rede`) e `hardware_api.py` (`_aplicar_vaga_solar`).

---

## 08/10/2026 — Davi · Chat V5 — Auditoria final do Next

Override do contrato v1 de novo (autorizado por Davi): backend/db/admin mexidos e registrados para o Daniel. Detalhes em `docs/AUDITORIA_FINAL_next.md`.

### Feito
1. Varredura de todo o histórico do git: nenhuma chave real; senha de demo `SenhaDemo#2026` abria o painel como "Sindico FIAP" → senhas dos síndicos trocadas.
2. Conta `Davi Admin` (gestor + admin global) e `db/20` (coordenadas, `chamados`, `admins_globais`) — aplicado no Supabase.
3. Painel: aba **Visão geral** (resumo, chamados, recargas, cadastros, pagamentos, notificações) para todos os locais.
4. App: **Mapa de pontos** (Leaflet + OpenStreetMap), **chamados** no Suporte, chatbot fecha ao clicar fora.
5. Totem virtual: `TOTEM_HTTP_TIMEOUT_S` configurável.

### Testado
- pytest 85 verdes; lint/build front e admin ok; ponta a ponta contra o banco real; prints em Edge no tamanho de celular; roteiro do totem (14/17 em memória, 13/17 real).

### NÃO testado
- `docker build` (sem Docker na máquina; reproduzido em ambiente limpo).

### Quebrou / atenção
- **Banco no Canadá:** handshake do totem leva ~5 s a partir do Brasil; firmware desiste em 3 s. Publicar o backend na América do Norte ou subir o timeout.
- Cadastrar o MFA do `Davi Admin`; trocar senhas das contas Totem e Gus Bancada.

### Próximo
1. Daniel: revisar `rotas_geral.py`, `rotas_suporte.py`, `db/20` e as sugestões da seção 12 da auditoria.
2. Deploy conforme a seção 10 da auditoria.

---

## 07/10/2026 — Davi · Chat V4 — Experiência Next: cadastro, recarga, visual e segurança

Override do contrato v1 nesta rodada (autorizado): mexi em backend/db/admin e registrei tudo para o Daniel. Detalhes em `docs/AUDITORIA_experiencia_next.md`.

### Feito (6 itens)
1. Totem no cadastro esconde Bloco/Apto (novo `condominios.perfil`, `db/19`).
2. Celular/Carro em todos os cadastros; Totem trava em celular.
3. Celular: nome vira "Celular", sem placa, modelo preenche a energia por base local (`frontend/src/lib/celulares.js`); admin ganha "Recargas ao vivo" (`recargas_ao_vivo` em `/gestor/painel`).
4. "Acompanhar pelo painel" mantém o ponto selecionado e leva ao monitor (antes fechava tudo).
5. Visual com mais profundidade/3D (`.realce`, `.halo-carga`, `.aurora`), só marca GoodWe, reduced-motion aware; nenhuma lógica tocada.
6. Revisão estática de segurança do admin: postura sólida, sem achado crítico.

### Testado
- backend `pytest`: 76 verdes. frontend/admin `npm run build`: ok (isolamento ok). lint: 0 erros.

### NÃO testado
- Runtime contra o Supabase real (não subi a stack para não criar dado no banco de vocês). Build + testes cobrem a corretude.
- Varredura ativa do deploy do admin (precisa de URL + autorização).

### Quebrou / atenção
- **Aplicar `db/19_condominio_perfil.sql` e rodar `python preparar_totem.py`** antes da banca. Sem o 19, o app não quebra (há fallback), mas o Totem não é reconhecido pelo `perfil`.

### Próximo
1. Daniel: revisar `db/19`, `recargas_ao_vivo` e o helper `_condominios_ordenados`.
2. Se quiser, autorizar a sondagem ativa do admin publicado (gobuster) e os prints da experiência ao vivo.

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
