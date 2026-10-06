# ADR-017 — Escala de bancada 1:1000 (W medido → kW de produto)

- **Status:** ACEITO em 06/10/2026 (decisão vigente do contrato v1); detalhes de implementação abaixo, P1 a confirmar pelo Daniel
- **Chat:** D1 — Totem v2.1 no servidor
- **Entrega:** `db/17_totem_escala_fontes.sql` (seções 1 e 2), `fisica.py`, `dispositivos.py`, `hardware_api.py`, `testes/test_totem_v21.py`

---

## 0. Estado verificado

| # | Item | Verificado em | Consequência |
|---|------|---------------|--------------|
| 1 | `potencia_w / 1000` direto | `hardware_api._processar_leitura` | Celular de 7,5 W vira 0,0075 kW: abaixo do mínimo de 1,4 kW do `demanda.py`, cobrança em centavos |
| 2 | Handshake devolve `sessao_ativa.energia_wh` | `_resumo_sessao` | É com este número que o totem retoma o contador depois de um reboot (ADR-020 D6) |
| 3 | Detecção de celular cheio: 0,5 W e 0,2 Wh | `_processar_leitura` | Limiar físico do sensor, não de produto |
| 4 | Placa v1 do Gus | `dispositivos` + carregador 0,025 kW + celular 0,015 kWh | Cadastrada em unidades de bancada |

## D1. Onde mora o fator

`dispositivos.fator_escala numeric not null default 1000`, com check `0 < fator ≤ 100000`.
Placa que **já existe** quando o 17 roda fica com **1**; placa criada depois nasce com 1000.

**Rejeitado:** 1000 para todas. A placa do Gus e os veículos dela foram cadastrados em unidades de bancada (0,025 kW, 0,015 kWh); escalar a medição sem recadastrar o resto faria o celular chegar a 100% na primeira leitura e a reserva estourar.
**Rejeitado:** fator por carregador. A escala é da bancada inteira (mesmo sensor, mesma placa); por porta só abriria espaço para duas portas da mesma placa discordarem.

## D2. Conversão SÓ na entrada da telemetria

- Na entrada (`/v2/telemetria`, `/telemetria` v1): `kW = W × fator / 1000`, `kWh = Wh × fator / 1000`. Daí em diante (sessão, alocador, cobrança, curva, recibo) tudo é kW/kWh de produto.
- `leituras_hardware` guarda **o bruto e o escalado** (`potencia_w`, `energia_wh` + `fator_escala`, `potencia_escalada_kw`, `energia_escalada_kwh`). A RPC lê o fator da linha do dispositivo, não do chamador.
- **Tudo que volta para a placa volta no bruto:** `energia_wh` (handshake e telemetria), `potencia_media_w`, `alocado_kw`. Se o handshake devolvesse 12 000 Wh para um contador de 12 Wh, a próxima leitura seria cobrada mil vezes.
- **Detecção física fica no bruto:** 0,5 W e 0,2 Wh comparam o que o INA219 mediu.

**Rejeitado:** converter também capacidade e potência do veículo "na hora" (`capacidade × fator`). Espalharia a conversão por física, estimativa, prévia e chatbot. Em vez disso:

## D3. Cadastro em unidades de produto

As vagas do totem e os celulares do estande são cadastrados **como o ponto e o carro que representam**:

| Objeto | Bancada | Cadastro |
|---|---|---|
| Vaga do totem | ~7,5 W | `perfil='bancada'`, `potencia_maxima_kw = 7.5`, `tarifa_kwh = 1.15` |
| Celular | 12–15 Wh, 7,5 W | `tipo='celular'`, `capacidade_bateria_kwh = 15`, `potencia_carro_kw = 7.5` |

`perfil='bancada'` continua aceitando só celular e sem mínimo de 1,4 kW (o relé não modula).

## D4. Origem do dado (regra 5)

`dispositivos.virtual boolean default false`. Placa virtual grava leituras, fontes e geração com `origem = 'simulado'`; placa física, `'medido'`. Resolve o P4 do ADR-020.

## D5. Selo na tela

O valor escalado é o que o app mostra; o selo "maquete 1:1000 — medido na bancada" é do frontend. O morador já lê `leituras_hardware` da própria sessão (política do 11), com bruto e escalado lado a lado.

## Riscos

- **Trocar o fator com sessão ativa** quebra a conta daquela sessão (energia antiga em uma escala, nova em outra). Regra: só trocar com as portas livres.
- **Provisionar o totem antes do 17** faria ele nascer com fator 1. Ordem: 17 → `placa-v2`.

## Pontos para o Daniel

| # | Ponto | Padrão adotado |
|---|---|---|
| P1 | Placas existentes ficam com fator 1 | Sim |
