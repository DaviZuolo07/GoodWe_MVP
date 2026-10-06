# Contrato Totem v2.1 — o que o servidor responde (implementado no D1)

Base: protocolo v2 (ADR-015), sem alteração de assinatura, numeração ou lote.
Decisões: ADR-017 (escala) e ADR-018 (tag primeiro, fila de energia, fontes).
Toda mudança é **aditiva**: nenhum campo antigo some.

## 1. Unidades

- A placa manda e recebe **W, Wh, V, A brutos**. O backend multiplica por `fator_escala` (1000 na maquete) só na entrada.
- Voltam no bruto: `energia_wh` (handshake e telemetria), `potencia_media_w`, `alocado_kw`.
- O handshake informa `fator_escala`, `porta_solar` e `max_fontes_lote` (20).

## 2. `POST /hardware/v2/rfid` `{porta, uid}`

```json
{ "porta": 1, "autorizado": true, "motivo": "iniciada", "acao": "ligar",
  "tela": ["Vaga 1 liberada", "Boa recarga, Ana!"],
  "mensagem": "Recarga iniciada na vaga 1. ...", "sessao_id": "uuid", "fila_posicao": null,
  "saldo_atual": 31.25, "valor_reservado": 18.75, "percentual_inicial": 20.0, "percentual_origem": "estimado" }
```

`tela`: até 4 linhas, até 20 caracteres, ASCII sem acento — o totem mostra exatamente isso.

| Situação | autorizado | motivo | acao |
|---|---|---|---|
| Tag pessoal, vaga livre, cabe no limite | true | `iniciada` | `ligar` |
| Idem, sem orçamento de energia (ou fila na frente) | true | `aguardando_energia` (+ `fila_posicao`) | `nenhuma` |
| A tag que iniciou, na vaga dela (carregando ou esperando) | true | `encerrada` | `desligar` |
| Outra tag em vaga ocupada | false | `vaga_ocupada` (+ evento) | `nenhuma` |
| Recarga preparada no app + tag certa | true | `confirmada_app` (ou `aguardando_energia`) | `ligar` (ou `nenhuma`) |
| Já tem sessão viva em outra vaga | false | `ja_carregando_em_outra_vaga` | `nenhuma` |
| Saldo menor que a reserva | false | `saldo_insuficiente` | `nenhuma` |
| Tag desconhecida | false | `cartao_nao_cadastrado` (+ `uid`) | `nenhuma` |
| Tag pessoal de outro morador numa recarga do app | false | `cartao_de_outro_usuario` | `nenhuma` |
| Tag de outro condomínio | false | `cartao_de_outro_condominio` | `nenhuma` |
| Morador sem veículo compatível | false | `sem_veiculo` | `nenhuma` |
| UID que não normaliza | false | `uid_invalido` | `nenhuma` |
| Cartão compartilhado em vaga livre (legado) | false | `sem_recarga_preparada` | `nenhuma` |
| Taxa de ocupação pendente | — | `taxa_pendente` | **D2** |

Porta que a placa não tem: `422 porta_inexistente`.

## 3. `POST /hardware/v2/telemetria`

Corpo: `{t_envio_ms, leituras: [0..30], fontes: [0..20]}` — pelo menos um item no total.

```json
"fontes": [{ "fonte": "painel", "t_ms": 12000, "potencia_w": 7.41, "tensao_v": 5.88, "corrente_a": 1.26 },
           { "fonte": "bateria", "t_ms": 12000, "potencia_w": 0.0, "tensao_v": 3.91, "corrente_a": 0.0 }]
```

Resposta: `{ok, gravadas, fontes_gravadas, portas: [...]}`. Por porta, além do que já havia:

| Campo | Valores |
|---|---|
| `estado` | `livre` · `aguardando_energia` · `carregando` · `pausada` (D2 acrescenta `completa_tolerancia`, `completa_taxa`) |
| `deve_liberar` | `false` em livre, aguardando_energia e pausada (trava de sessão abre o relé) |
| `fonte` | só na porta solar: `solar` · `rede` |
| `percentual_origem` | `informado` · `estimado` |

## 4. `/v2/comandos`

Vocabulário inalterado: `liberar` ≡ `ligar`, `bloquear` ≡ `desligar`. Novos usos: `liberar` quando sai da fila de energia ou retoma a vaga solar; `bloquear` quando a vaga solar pausa.

## 5. Erros

Inalterados (ADR-015). Lote vazio, fonte fora de `painel|bateria`, mais de 30 leituras ou 20 fontes → `422` (o lote inteiro é recusado e o seq não é gasto). `replay` e `assinatura_invalida` passam a gerar evento de segurança.

## 6. Provisionar o Totem Central (Daniel, depois do 17)

```
python provisionar.py placa-v2 --carregadores <v1>,<v2>,<v3>,<v4> --nome "Totem Central" --perfil bancada
```
```sql
update carregadores set potencia_maxima_kw = 7.5, tarifa_kwh = 1.15 where id in ('<v1>','<v2>','<v3>','<v4>');
update dispositivos set porta_solar = 4 where id = '<totem>';
update dispositivos set virtual = true where id = '<totem virtual>';   -- só o gêmeo digital
```
Celulares do estande: `tipo = 'celular'`, `capacidade_bateria_kwh = 15`, `potencia_carro_kw = 7.5`.
