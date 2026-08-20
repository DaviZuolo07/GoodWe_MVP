/**
 * Ponto único de configuração do frontend.
 *
 * CONDOMINIO_ID está aqui — e só aqui — de propósito. Quando entrar o
 * seletor de local (2+ condomínios no banco), o que muda é este arquivo
 * virar um estado/contexto; nenhum componente precisa saber o UUID de cor.
 *
 * Quem precisar do local ativo importa daqui, nunca escreve o UUID inline.
 */

export const API_URL = import.meta.env.VITE_API_URL

/**
 * Local usado só quando não sabemos qual é o do usuário (primeiro acesso,
 * cadastro sem escolha). O local real vem de `usuario.condominio_id` e pode
 * ser trocado no topo do Dashboard.
 */
export const CONDOMINIO_PADRAO = '11111111-1111-1111-1111-111111111111'

/** Alias legado — ainda importado por arquivos antigos. */
export const CONDOMINIO_ID = CONDOMINIO_PADRAO
