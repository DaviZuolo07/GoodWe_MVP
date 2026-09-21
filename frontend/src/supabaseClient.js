import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
// Chave PÚBLICA (publishable ou anon). Ela vai embutida no JavaScript e
// qualquer um pode ler. Não abre nada sozinha: com o RLS do 11_seguranca.sql,
// sem token de morador ela só enxerga o catálogo de condomínios.
const supabaseKey = import.meta.env.VITE_SUPABASE_KEY

/*
 * Quem diz ao banco "sou o morador X" é o token emitido pelo NOSSO backend
 * no /login, assinado com a chave privada que só o backend tem. O Supabase
 * confere a assinatura e aplica o RLS em nome desse morador.
 *
 * O token fica numa variável deste módulo, não no localStorage. Recarregar a
 * página pede login de novo; em troca, um script injetado na página não
 * encontra o token guardado no disco do navegador.
 */
let tokenAtual = null

export const supabase = createClient(supabaseUrl, supabaseKey, {
  // Chamado a cada requisição REST e a cada heartbeat do Realtime.
  // Sem token, o supabase-js usa a chave pública no lugar (visitante).
  accessToken: async () => tokenAtual,
})

export function definirToken(token) {
  tokenAtual = token
  // Sem argumento: o Realtime relê o token pelo callback acima. Importante
  // quando alguém sai e outra pessoa entra no mesmo navegador.
  supabase.realtime.setAuth()
}

// O Bloco 2 usa isto para mandar o token também nas chamadas ao backend.
export function obterToken() {
  return tokenAtual
}

export function encerrarSessaoSupabase() {
  supabase.removeAllChannels()
  tokenAtual = null
  supabase.realtime.setAuth()
}
