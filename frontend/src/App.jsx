import { useCallback, useEffect, useLayoutEffect, useState } from 'react'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { aplicarTema, lerTema } from './lib/tema.js'
import { definirToken, encerrarSessaoSupabase } from './supabaseClient.js'

function App() {
  // Enquanto for null, mostra a tela de Login. Depois: {usuario, veiculo, expiraEm}.
  // O token NÃO entra aqui: ele mora só no supabaseClient.js.
  const [sessao, setSessao] = useState(null)

  // useLayoutEffect e não useEffect: o tema precisa estar no <html> antes da
  // primeira pintura, senão quem usa o claro vê um flash preto ao abrir.
  useLayoutEffect(() => {
    aplicarTema(lerTema())
  }, [])

  const entrar = useCallback((dados) => {
    // O token precisa estar instalado ANTES do Dashboard montar: é na montagem
    // que ele faz as primeiras consultas e abre o canal Realtime.
    definirToken(dados.token)
    setSessao({ usuario: dados.usuario, veiculo: dados.veiculo, expiraEm: dados.expira_em })
  }, [])

  const sair = useCallback(() => {
    encerrarSessaoSupabase()
    setSessao(null)
  }, [])

  // Token vencido faz o banco devolver tudo vazio, e a tela pareceria
  // "sem dados". Melhor voltar ao login no instante em que ele expira.
  const expiraEm = sessao?.expiraEm
  useEffect(() => {
    if (!expiraEm) return
    const restante = expiraEm * 1000 - Date.now()
    if (restante <= 0) {
      sair()
      return
    }
    const id = setTimeout(sair, restante)
    return () => clearTimeout(id)
  }, [expiraEm, sair])

  return (
    <ErrorBoundary>
      {sessao ? (
        <Dashboard sessao={sessao} onLogout={sair} />
      ) : (
        <Login onLoginSuccess={entrar} />
      )}
    </ErrorBoundary>
  )
}

export default App
