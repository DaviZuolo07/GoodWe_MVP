import { useCallback, useEffect, useLayoutEffect, useState } from 'react'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { aplicarTema, lerTema } from './lib/tema.js'
import { definirAoExpirar } from './lib/api.js'
import { definirToken, encerrarSessaoSupabase } from './supabaseClient.js'

function App() {
  // Enquanto for null, mostra o Login. O token NÃO entra aqui: ele mora só no
  // supabaseClient.js, em memória (recarregar a página pede login de novo, e
  // em troca nenhum script acha o token guardado no disco do navegador).
  const [sessao, setSessao] = useState(null)
  const [avisoSaida, setAvisoSaida] = useState('')

  useLayoutEffect(() => {
    aplicarTema(lerTema())
  }, [])

  const entrar = useCallback((dados) => {
    // O token precisa estar instalado ANTES do Dashboard montar: é na montagem
    // que ele consulta o banco e abre o canal de tempo real.
    definirToken(dados.token)
    setAvisoSaida('')
    setSessao({
      usuario: dados.usuario,
      veiculo: dados.veiculo,
      veiculos: dados.veiculos || [],
      expiraEm: dados.expira_em,
    })
  }, [])

  const sair = useCallback((motivo = '') => {
    encerrarSessaoSupabase()
    setAvisoSaida(motivo)
    setSessao(null)
  }, [])

  // Qualquer 401 do backend (token vencido, conta removida) volta ao login
  // com explicação, em vez de deixar a tela vazia parecendo erro de dados.
  useEffect(() => {
    definirAoExpirar(() => sair('Sua sessão expirou. Entre novamente.'))
    return () => definirAoExpirar(null)
  }, [sair])

  const expiraEm = sessao?.expiraEm
  useEffect(() => {
    if (!expiraEm) return
    const restante = expiraEm * 1000 - Date.now()
    if (restante <= 0) {
      sair('Sua sessão expirou. Entre novamente.')
      return
    }
    const id = setTimeout(() => sair('Sua sessão expirou. Entre novamente.'), restante)
    return () => clearTimeout(id)
  }, [expiraEm, sair])

  return (
    <ErrorBoundary>
      {sessao ? (
        <Dashboard sessao={sessao} onLogout={() => sair()} />
      ) : (
        <Login onLoginSuccess={entrar} aviso={avisoSaida} />
      )}
    </ErrorBoundary>
  )
}

export default App
