/**
 * Único ponto de configuração do painel: o endereço da API ADMINISTRATIVA.
 * Sem VITE_ADMIN_API_URL, usa o host que abriu a página, na porta 8001.
 */
// OAuth Client ID (Google Cloud -> APIs e serviços -> Credenciais), do tipo
// "Aplicativo da Web", com a origem do painel autorizada. Vazio = sem o
// botão "Entrar com Google" (operadores não entram).
export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''

export const API_URL =
  import.meta.env.VITE_ADMIN_API_URL ||
  `${window.location.protocol}//${window.location.hostname}:8001`
