# Pedido ao totem — Backend D1 entregue (ADR-017/018)

- **De:** Daniel · **Para:** Davi · **Data:** 06/10/2026
- **Bloqueia o gate de 11/10?** Item 1 sim (o pytest do `totem_virtual` fica vermelho até ele entrar).

Respostas ao ADR-020 seção 9 e ao pedido de 06/10: ADR-018 seção 9.

## 1. Três testes do totem afirmam o backend de antes do v2.1

Com o D1, o `--bolso` responde v2.1. Resultado do roteiro contra o backend D1 (em memória):

- **14 PASSOU:** conexao, timeout_escolha, solar_na_telemetria, app_duas_vagas, wifi_caiu, reboot, inicia_pela_tag, vaga_ocupada, duas_vagas_pela_tag, mesma_tag_outra_vaga, encerra_pela_tag, saldo_insuficiente, tag_alheia, bateria_solar_baixa
- **3 FALHOU, todos D2** (fim de sessão pelo INA219): desplugado, vaga_sem_celular, celular_cheio

Testes a atualizar na tua pasta:
- `test_roteiro.py::test_roteiro_no_backend_de_hoje_nada_falha` — exige AGUARDANDO no tag-primeiro.
- `test_maquina_de_estados.py::test_tag_e_botao_mandam_porta_e_uid_e_a_tela_volta_sozinha` — exige `sem_recarga_preparada` na vaga livre (agora é `iniciada`).
- `test_maquina_de_estados.py::test_duas_vagas_carregam_juntas_pelo_fluxo_do_app` — exige resposta sem `acao` (agora vem `confirmada_app`/`ligar`).

Sugestão: os três cenários de D2 como "aguardando D2" até o próximo chat meu.

## 2. `fonte: "rede"` na porta solar

Com o Modbus 10024 ligado e a bateria abaixo do 10030, a resposta da porta solar traz `fonte: "rede"`. Se a bancada tiver caminho de rede para a vaga 4, o totem comuta (abre uma fonte antes de fechar a outra). Se não tiver, tratar como pausa (abrir o relé) e me avisar, que eu removo a opção.

## 3. Sinal da bateria em `fontes`

Hoje ≥ 0 está ok. Quando existir caminho de rede na vaga 4: bateria **carregando = potência negativa**. O backend já aceita.

## 4. Nenhum campo removido

Todas as respostas antigas continuam. Campos novos: ver `docs/contratos/totem_v2_1.md`.
