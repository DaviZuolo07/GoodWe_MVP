# Totem virtual

Gêmeo digital do ESP32 "Totem Central": 4 vagas com relé e INA219, leitor RFID, 4 botões, LCD 16x2 e a vaga 4 solar (bateria 18650 **ou** rede, por um relé reversor; um 5º INA219 mede a bateria com sinal). Fala o protocolo v2 com o backend, assinando com a `PlacaV2` de `backend/testes/placa_v2.py`.

Serve para três coisas: validar o backend de ponta a ponta sem hardware, ser a especificação que o firmware C++ copia (`firmware.py` + `docs/contratos/maquina_de_estados_totem.md` → `firmware/totem_central/`) e ser o plano B do estande.

**Todo número que sai daqui é simulado.** Decisões em `docs/decisoes/ADR-020_totem_virtual.md`, `ADR-021_recusa_de_autenticacao.md` e `ADR-022_totem_fisico.md`.

## Rodar

Sempre da **raiz do repositório**, com as dependências do `requirements.txt` da raiz instaladas (não há dependência nova).

```
python -m totem_virtual painel --bolso      # página em http://127.0.0.1:8765, backend em memória
python -m totem_virtual roteiro --bolso     # teste de aceitação, backend em memória
python -m pytest totem_virtual/testes -q    # testes (cerca de 4 min; o roteiro roda em tempo real)
```

`--bolso` usa o FastAPI de `backend/` com o `supabase_falso.py`, dentro do mesmo processo: não precisa de Supabase, `.env` nem chave. É o que roda antes de cada merge.

Contra o backend local de verdade:

1. Dentro de `backend/`: `python preparar_totem.py` (cria vagas, placa, moradores de teste e grava `totem_virtual/.env`).
2. Confira se o relógio do Windows está sincronizado (ver "Recusado" abaixo).
3. Suba o backend (`uvicorn main:app`, de dentro de `backend/`).
4. `python -m totem_virtual painel` ou `python -m totem_virtual roteiro`.

## Recusado pelo servidor (401)

Três 401 seguidos do mesmo tipo e o totem **para de insistir**: imprime um diagnóstico no terminal (e na página), mostra o motivo no LCD e tenta de novo uma vez por minuto (ADR-021).

| LCD | Causa | O que fazer |
|---|---|---|
| `Chave invalida` | a chave do `.env` não bate com a `DEVICE_MASTER_KEY` do backend, ou o `DEVICE_ID` não existe no banco dele | `python preparar_totem.py` de novo, dentro de `backend/` |
| `Relogio servidor` | recusou mesmo logo depois de acertar a hora: o relógio do PC do backend está fora do relógio do Supabase (o `/hora` devolve o relógio do PC) | Configurações → Hora e idioma → **Sincronizar agora** (ou `w32tm /resync` como administrador) e reiniciar o backend |

Recusa no meio de uma recarga conta como servidor ausente: depois de 120 s a trava offline abre os relés.

## A página

Só responde em `127.0.0.1`, exige um token sorteado a cada execução e nunca recebe a chave da placa. Nela dá para: aproximar tag, apertar o botão de cada vaga, plugar e desplugar celular (capacidade e % inicial), mudar a luz do painel e a carga da bateria, derrubar o Wi-Fi e reiniciar a placa.

## O roteiro

| Resultado | Significa |
|---|---|
| PASSOU | o backend respondeu o que o contrato manda |
| FALHOU | respondeu outra coisa; o comando sai com código 1 |
| AGUARDANDO BACKEND | o backend ainda responde sem o Totem v2.1 (RFID sem `acao`). Não é falha |
| PULADO | falta uma tag ou conta no `.env` |

Cenários: conexão, timeout de 15 s, solar na telemetria, duas vagas pelo app, Wi-Fi caiu, reboot, início pela tag, vaga ocupada, duas vagas pela tag, mesma tag em outra vaga, desplugado, encerrar pela tag, saldo insuficiente, tag alheia, vaga sem celular, celular cheio, bateria solar baixa.

`conexao` distingue "o backend não respondeu" de "respondeu e recusou a autenticação". `desplugado`, `vaga_sem_celular` e `celular_cheio` falham até o fim de sessão pela medição (chat D2 do backend) entrar.

Contra o backend real o roteiro leva alguns minutos (o timeout de 15 s é de verdade, e os cenários de desplugado/cheio esperam o backend por até `ROTEIRO_ESPERA_S`). Ele precisa começar com as quatro vagas livres.

## Arquivos

| Arquivo | Papel |
|---|---|
| `firmware.py` | a lógica: máquina de estados, relés, telemetria, falhas. **É o que `firmware/totem_central/` traduz** |
| `bancada.py` | o hardware de mentira e a HAL que o firmware enxerga |
| `fisica.py` | celular (curva do contrato), INA219, painel de 1 W, bateria 18650 |
| `rede.py` | enlace com o backend em volta da `PlacaV2` |
| `lcd.py` | tela 16x2 sem acento, re-quebra e paginação |
| `totem.py` | junta tudo e roda o laço numa thread |
| `painel.py`, `painel.html` | a página local |
| `roteiro.py` | o teste de aceitação |
| `backend_de_bolso.py` | backend de verdade em memória, com um totem semeado |
| `testes/servidor_v21.py` | servidor v2.1 **de referência, só para teste** (leitura do contrato, não é o backend) |

## Limites conhecidos

- O modelo solar é simplificado; os limiares de tensão precisam ser calibrados na bancada real.
- No `--bolso` o laço de 10 s do simulador do backend não roda sozinho: esperas de cartão não expiram e a fila de energia só anda no fim de uma recarga (o teste chama `simulador.ciclo()`).
- O totem virtual e o ESP32 usam a **mesma placa** criada pelo `preparar_totem.py`: rode um de cada vez.
