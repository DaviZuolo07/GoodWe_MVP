import { useState } from 'react'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'

function App() {
  // Guarda o usuário logado. Enquanto for null, mostra a tela de Login.
  // Depois do login/cadastro, guardamos {usuario, veiculo} aqui.
  const [sessao, setSessao] = useState(null)

  if (!sessao) {
    return <Login onLoginSuccess={(dados) => setSessao(dados)} />
  }

  return <Dashboard sessao={sessao} onLogout={() => setSessao(null)} />
}

export default App
