import { useLayoutEffect, useState } from 'react'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import { aplicarTema, lerTema } from './lib/tema.js'

function App() {
  // Guarda o usuário logado. Enquanto for null, mostra a tela de Login.
  // Depois do login/cadastro, guardamos {usuario, veiculo} aqui.
  const [sessao, setSessao] = useState(null)

  // useLayoutEffect e não useEffect: o tema precisa estar no <html> antes da
  // primeira pintura, senão quem usa o claro vê um flash preto ao abrir.
  useLayoutEffect(() => {
    aplicarTema(lerTema())
  }, [])

  return (
    <ErrorBoundary>
      {sessao ? (
        <Dashboard sessao={sessao} onLogout={() => setSessao(null)} />
      ) : (
        <Login onLoginSuccess={(dados) => setSessao(dados)} />
      )}
    </ErrorBoundary>
  )
}

export default App
