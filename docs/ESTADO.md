# Estado do projeto

Atualizado ao fim de cada chat: o que foi feito, o que quebrou, o que vem depois.

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
