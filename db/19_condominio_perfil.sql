-- ============================================================================
-- 19_condominio_perfil.sql  -  marca o condomínio do Totem como "bancada"
-- ============================================================================
-- Contexto: no cadastro, o ponto do Totem (estande do Next) só carrega celular
-- e não tem bloco/apto. Até agora o frontend adivinhava isso pelo NOME do
-- condomínio. Esta coluna torna a marcação explícita e reaproveita o mesmo
-- vocabulário que os carregadores já usam (perfil 'bancada').
--
-- Seguro de rodar mais de uma vez (idempotente) e compatível com o que já
-- existe: a coluna nasce com 'residencial', então nenhum condomínio muda de
-- comportamento sem ser marcado de propósito.
--
-- O backend (/condominios) passa a devolver `perfil`; se esta migration ainda
-- não tiver sido aplicada, ele cai no formato antigo sozinho (não quebra).
-- ============================================================================

alter table public.condominios
    add column if not exists perfil text not null default 'residencial';

alter table public.condominios drop constraint if exists condominios_perfil_check;
alter table public.condominios add constraint condominios_perfil_check
    check (perfil in ('residencial', 'bancada'));

-- O estande do Totem (criado por backend/preparar_totem.py) é de bancada.
-- Marca pelo id fixo e, por garantia, por qualquer condomínio cujo nome o
-- identifique como estande/totem.
update public.condominios
   set perfil = 'bancada'
 where id = 'e57a4de0-0000-4000-8000-000000000000'
    or nome ilike '%totem%'
    or nome ilike '%estande%';
