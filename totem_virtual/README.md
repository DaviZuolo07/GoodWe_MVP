# Totem virtual

Gêmeo digital do ESP32 "Totem Central": 4 vagas com relé e INA219, leitor RFID, 4 botões, LCD 20x4 e a vaga 4 solar (painel ou bateria 18650). Fala o protocolo v2 com o backend, assinando com a `PlacaV2` de `backend/testes/placa_v2.py`.

Serve para três coisas: validar o backend de ponta a ponta sem hardware, ser a especificação que o firmware C++ copia (`firmware.py` + `docs/contratos/maquina_de_estados_totem.md`) e ser o plano B do estande.

**Todo número que sai daqui é simulado.** Decisões em `docs/decisoes/ADR-020_totem_virtual.md`.

## Rodar

Sempre da **raiz do repositório**, com as dependências do `requirements.txt` da raiz instaladas (não há dependência nova).

```
python -m totem_virtual painel --bolso      # página em http://127.0.0.1:8765, backend em memória
python -m totem_virtual roteiro --bolso     # teste de aceitação, backend em memória
python -m pytest totem_virtual/testes -q    # testes (cerca de 2 min; o roteiro roda em tempo real)
```

`--bolso` usa o FastAPI de `backend/` com o `supabase_falso.py`, dentro do mesmo processo: não precisa de Supabase, `.env` nem chave. É o que roda antes de cada merge.

Contra o backend local de verdade:

1. Peça ao Daniel, por canal privado, a saída de `python provisionar.py placa-v2 --carregadores <v1>,<v2>,<v3>,<v4> --nome "Totem virtual"` e as tags de teste.
2. Copie `totem_virtual/exemplo.env` para `totem_virtual/.env` e preencha.
3. Suba o backend (`uvicorn main:app`, de dentro de `backend/`).
4. `python -m totem_virtual painel` ou `python -m totem_virtual roteiro`.

## A página

Só responde em `127.0.0.1`, exige um token sorteado a cada execução e nunca recebe a chave da placa. Nela dá para: aproximar tag, apertar o botão de cada vaga, plugar e desplugar celular (capacidade e % inicial), mudar a luz do painel e a carga da bateria, derrubar o Wi-Fi e reiniciar a placa.

Com `--bolso` e com o backend de hoje, tag numa vaga livre responde "sem recarga preparada": o fluxo tag-primeiro depende do Totem v2.1 no servidor. Para ver vaga carregando hoje, prepare a recarga no app e depois encoste a tag (é o que o roteiro faz no cenário `app_duas_vagas`).

## O roteiro

| Resultado | Significa |
|---|---|
| PASSOU | o backend respondeu o que o contrato manda |
| FALHOU | respondeu outra coisa; o comando sai com código 1 |
| AGUARDANDO BACKEND | o backend ainda responde sem o Totem v2.1 (RFID sem `acao`). Não é falha |
| PULADO | falta uma tag ou conta no `.env` |

Cenários: conexão, timeout de 15 s, solar na telemetria, duas vagas pelo app, Wi-Fi caiu, reboot, início pela tag, vaga ocupada, duas vagas pela tag, mesma tag em outra vaga, desplugado, encerrar pela tag, saldo insuficiente, tag alheia, vaga sem celular, celular cheio, bateria solar baixa.

Contra o backend real o roteiro leva alguns minutos (o timeout de 15 s é de verdade, e os cenários de desplugado/cheio esperam o backend por até `ROTEIRO_ESPERA_S`). Ele precisa começar com as quatro vagas livres.

## Arquivos

| Arquivo | Papel |
|---|---|
| `firmware.py` | a lógica: máquina de estados, relés, telemetria, falhas. **É o que o `.ino` copia** |
| `bancada.py` | o hardware de mentira e a HAL que o firmware enxerga |
| `fisica.py` | celular (curva do contrato), INA219, painel, bateria |
| `rede.py` | enlace com o backend em volta da `PlacaV2` |
| `lcd.py` | tela 20x4 sem acento |
| `totem.py` | junta tudo e roda o laço numa thread |
| `painel.py`, `painel.html` | a página local |
| `roteiro.py` | o teste de aceitação |
| `backend_de_bolso.py` | backend de verdade em memória, com um totem semeado |
| `testes/servidor_v21.py` | servidor v2.1 **de referência, só para teste** (leitura do contrato, não é o backend) |

## Limites conhecidos

- O modelo solar é simplificado; os limiares de tensão precisam ser calibrados na bancada real.
- O backend grava as leituras deste totem como `origem = 'medido'`. Até o pedido em `docs/decisoes/pedidos/2026-10-06_totem_virtual_backend.md` ser atendido, não use esse banco para número rotulado como medido.
- No `--bolso` o laço de 10 s do simulador do backend não roda: esperas de cartão não expiram sozinhas.
