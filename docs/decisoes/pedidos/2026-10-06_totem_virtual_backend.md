# Pedido ao backend — Totem virtual (chat V1, ADR-020)

- **De:** Davi · **Para:** Daniel · **Data:** 06/10/2026
- **Bloqueia o gate de 11/10?** Só o item 1 (é o próprio D1). Os demais têm padrão provisório no totem.

Nenhum destes itens foi alterado por mim em `backend/` ou `db/`.

## 1. Fluxo tag-primeiro (já é o D1)

Hoje `POST /hardware/v2/rfid` numa vaga livre responde `sem_recarga_preparada`, sem `acao` e sem `tela`. O totem trata essa resposta e o roteiro marca os cenários como **aguardando backend**. O roteiro passa a cobrar o v2.1 no momento em que a resposta do RFID trouxer a chave `acao`.

O que o roteiro vai conferir (para você rodar contra o seu branch):

| Cenário | Espera do backend |
|---|---|
| Tag A na vaga 1 livre | `autorizado: true`, `motivo: iniciada`, `acao: ligar` |
| Tag B na vaga 1 ocupada | `autorizado: false`, `motivo: vaga_ocupada`, `acao: nenhuma` |
| Tag A na vaga 3, já carregando na 1 | `motivo: ja_carregando_em_outra_vaga` |
| Tag A na vaga 1 dela | `motivo: encerrada`, `acao: desligar` |
| Tag sem saldo | `motivo: saldo_insuficiente`, sem ligar |
| Tag não cadastrada | `cartao_nao_cadastrado` (aceito também `cartao_de_outro_condominio` / `cartao_de_outro_usuario`) |
| Celular desplugado | a vaga volta a `livre` e o relé recebe `desligar` (comando ou `deve_liberar: false`) |
| Vaga sem celular | idem |
| Celular cheio | `estado` vira `completa_tolerancia`/`completa_taxa`, ou a vaga é liberada |

## 2. Prazo de detecção (P6)

Em quanto tempo o backend libera a vaga quando a corrente é zero (desplugado / sem celular) ou de manutenção (cheio)? Hoje são 30 s **e** exige mais de 0,2 Wh entregues, o que nunca acontece na vaga sem celular. O roteiro espera até 90 s (`ROTEIRO_ESPERA_S`). Se o prazo no estande for outro, me diga o número.

## 3. Origem das leituras do totem virtual (P4) — regra 5

`registrar_lote_telemetria` grava `origem = 'medido'`. Para o totem virtual isso é falso: são números simulados. Sugestão (aditiva): uma marca no dispositivo (`dispositivos.virtual boolean default false`, ligada pelo `provisionar.py placa-v2 --virtual`) que faz o lote gravar `origem = 'simulado'`. O totem já se apresenta no handshake com `firmware: "totem-virtual-0.1"` e `mac: "VIRTUAL"`.

Enquanto isso não entra: **não usar o banco do totem virtual para nenhum número do pitch rotulado como medido.**

## 4. `fontes` na telemetria (P3 e P5)

O totem já manda, a cada amostra:

```json
"fontes": [
  { "fonte": "painel",  "t_ms": 12000, "potencia_w": 7.41, "tensao_v": 5.88, "corrente_a": 1.2602 },
  { "fonte": "bateria", "t_ms": 12000, "potencia_w": 0.0,  "tensao_v": 3.91, "corrente_a": 0.0 }
]
```

- **Sinal (P3):** `potencia_w` e `corrente_a` são o que a fonte **fornece**, sempre ≥ 0. Bateria sendo carregada pelo painel aparece como 0 W, e a tensão sobe. Se você preferir corrente com sinal (negativa = carregando), é só avisar: é uma constante no totem. Só não deixe um `ge=0` recusar o lote inteiro.
- **Confirmação (P5):** hoje o campo é ignorado em silêncio e a resposta não diz nada. Peço um campo opcional na resposta, por exemplo `"fontes_gravadas": 2`. O roteiro marca o cenário solar como "aguardando backend" até ver `fontes_gravadas` (ou `fontes`) na resposta.
- **Lote só com `fontes`:** o contrato permite `leituras` vazia, mas hoje `min_length=1` recusa. O totem sempre manda as leituras das vagas junto, então não depende disso.

## 5. Provisionamento do totem virtual

Preciso, por canal privado, do resultado de:

```
python provisionar.py placa-v2 --carregadores <vaga1>,<vaga2>,<vaga3>,<vaga4> --nome "Totem virtual"
```

(`DEVICE_ID` e `DEVICE_KEY_HEX`, que vão para `totem_virtual/.env`), e de quatro tags para o roteiro: duas de moradores com saldo (`TAG_A`, `TAG_B`), uma de morador sem saldo (`TAG_SEM_SALDO`) e, se quiser, uma de outro condomínio (`TAG_DESCONHECIDA`; sem ela uso um UID que não existe).

## 6. Travas locais do relé (P1 e P2) — só confirmar

- Relé fechado + `deve_liberar: false` na telemetria → o totem abre.
- 120 s sem conseguir falar com o servidor → o totem abre todos os relés.

Se alguma dessas brigar com a taxa de ocupação ou com o `aguardando_energia`, me avise.
