/**
 * Ponto único de configuração do frontend.
 *
 * Sem VITE_API_URL no .env, a URL da API é deduzida do endereço que abriu a
 * página: quem acessa http://192.168.0.10:5173 pelo celular fala com
 * http://192.168.0.10:8000. Antes, `localhost:8000` fixo quebrava no celular
 * (para o celular, localhost é o próprio celular).
 */

export const API_URL =
  import.meta.env.VITE_API_URL ||
  `${window.location.protocol}//${window.location.hostname}:8000`

/** Usado só quando ainda não sabemos o local do usuário (primeiro acesso). */
export const CONDOMINIO_PADRAO = '11111111-1111-1111-1111-111111111111'
