/**
 * Único ponto de configuração do painel: o endereço da API ADMINISTRATIVA.
 * Sem VITE_ADMIN_API_URL, usa o host que abriu a página, na porta 8001.
 */
export const API_URL =
  import.meta.env.VITE_ADMIN_API_URL ||
  `${window.location.protocol}//${window.location.hostname}:8001`
