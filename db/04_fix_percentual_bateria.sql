-- =============================================================
-- GoodWe ChargeOps AI Assistant - Correção: percentual_bateria
-- =============================================================
-- Problema: a coluna veiculos.percentual_bateria tinha um valor padrão
-- (50) forçado pelo banco. Mesmo removendo do backend, o Postgres
-- aplicava 50 sozinho em todo cadastro novo - um dado inventado sendo
-- gravado como se fosse real.
--
-- Correção: a % de bateria só é conhecida de verdade quando o usuário
-- informa na hora do pagamento (RFID) para iniciar uma recarga. Até lá,
-- o campo deve ficar vazio (NULL) - "não sabemos ainda", em vez de um
-- número forjado.
-- =============================================================

alter table veiculos
    alter column percentual_bateria drop not null;

alter table veiculos
    alter column percentual_bateria drop default;

-- Corrige os cadastros que já foram feitos com o valor forjado 50
-- (só reverte para NULL quem nunca teve uma sessão de recarga real -
-- ou seja, o 50 ali era mesmo inventado, não um dado de uma recarga)
update veiculos
set percentual_bateria = null
where percentual_bateria = 50
  and id not in (
      select veiculo_id from sessoes_recarga where veiculo_id is not null
  );
