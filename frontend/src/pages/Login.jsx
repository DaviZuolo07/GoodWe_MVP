import { useState } from 'react'
import CondominioSelect, { useCondominios } from '../components/CondominioSelect.jsx'
import { API_URL, CONDOMINIO_PADRAO } from '../config.js'

function Login({ onLoginSuccess }) {
  const { condominios, carregando: carregandoCondominios } = useCondominios()
  const [modo, setModo] = useState('login') // 'login' | 'cadastro'
  const [carregando, setCarregando] = useState(false)
  const [erro, setErro] = useState('')

  // Campos do login
  const [loginNome, setLoginNome] = useState('')
  const [loginSenha, setLoginSenha] = useState('')

  // Campos do cadastro
  const [nome, setNome] = useState('')
  const [senha, setSenha] = useState('')
  const [tipoUsuario, setTipoUsuario] = useState('morador')
  const [condominioId, setCondominioId] = useState(null)
  const [blocoApto, setBlocoApto] = useState('')
  const [veiculoModelo, setVeiculoModelo] = useState('')
  const [veiculoPlaca, setVeiculoPlaca] = useState('')
  const [capacidadeBateria, setCapacidadeBateria] = useState(40)
  const [potenciaCarro, setPotenciaCarro] = useState(7.4)

  async function handleLogin(e) {
    e.preventDefault()
    setErro('')
    setCarregando(true)
    try {
      const res = await fetch(`${API_URL}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome: loginNome, senha: loginSenha }),
      })
      const data = await res.json()

      if (!res.ok) {
        setErro(data.detail || 'Não foi possível entrar. Tente novamente.')
        return
      }

      onLoginSuccess(data)
    } catch {
      setErro('Não foi possível conectar ao servidor. O backend está rodando?')
    } finally {
      setCarregando(false)
    }
  }

  async function handleCadastro(e) {
    e.preventDefault()
    setErro('')

    if (!condominioId) {
      setErro('Escolha o condomínio onde você mora ou vai carregar.')
      return
    }

    setCarregando(true)
    try {
      const res = await fetch(`${API_URL}/cadastro`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          nome,
          condominio_id: condominioId || CONDOMINIO_PADRAO,
          tipo_usuario: tipoUsuario,
          bloco_apto: blocoApto,
          veiculo_modelo: veiculoModelo,
          veiculo_placa: veiculoPlaca,
          capacidade_bateria_kwh: Number(capacidadeBateria),
          potencia_carro_kw: Number(potenciaCarro),
        }),
      })
      const data = await res.json()

      if (!res.ok) {
        // 409 = nome duplicado (mensagem do backend já explica isso)
        setErro(data.detail || 'Não foi possível cadastrar. Tente novamente.')
        return
      }

      onLoginSuccess(data)
    } catch {
      setErro('Não foi possível conectar ao servidor. O backend está rodando?')
    } finally {
      setCarregando(false)
    }
  }

  const inputClass =
    'w-full bg-panel border border-line rounded-lg px-4 py-2 text-ink placeholder-dim focus:outline-none focus:border-flux'
  const labelClass = 'text-sm text-mute mb-1 block'

  return (
    <div className="min-h-screen bg-void text-ink flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-panel/60 border border-line rounded-2xl p-8">
        <h1 className="text-2xl font-bold text-flux mb-1">GoodWe ChargeOps AI</h1>
        <p className="text-mute mb-6">
          {modo === 'login' ? 'Entrar na sua conta' : 'Criar seu cadastro'}
        </p>

        {erro && (
          <div className="bg-flux/10 border border-flux/40 text-flux text-sm rounded-lg px-4 py-2 mb-4">
            {erro}
          </div>
        )}

        {modo === 'login' ? (
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className={labelClass}>Nome de usuário</label>
              <input
                className={inputClass}
                value={loginNome}
                onChange={(e) => setLoginNome(e.target.value)}
                placeholder="Como você se cadastrou"
                required
              />
            </div>
            <div>
              <label className={labelClass}>Senha</label>
              <input
                className={inputClass}
                type="password"
                value={loginSenha}
                onChange={(e) => setLoginSenha(e.target.value)}
                placeholder="Qualquer senha (MVP)"
              />
            </div>
            <button
              type="submit"
              disabled={carregando}
              className="w-full bg-flux hover:bg-flare disabled:opacity-50 rounded-lg py-2 font-medium transition"
            >
              {carregando ? 'Entrando...' : 'Entrar'}
            </button>
            <button
              type="button"
              className="w-full text-sm text-mute hover:text-ink pt-2"
              onClick={() => { setErro(''); setModo('cadastro') }}
            >
              Sou novo aqui — Cadastrar-se
            </button>
          </form>
        ) : (
          <form onSubmit={handleCadastro} className="space-y-3">
            <div>
              <label className={labelClass}>Nome</label>
              <input className={inputClass} value={nome} onChange={(e) => setNome(e.target.value)} required />
            </div>
            <div>
              <label className={labelClass}>Senha</label>
              <input className={inputClass} type="password" value={senha} onChange={(e) => setSenha(e.target.value)} placeholder="Qualquer senha (MVP)" />
            </div>

            <div>
              <label className={labelClass}>Condomínio</label>
              <CondominioSelect
                condominios={condominios}
                valorId={condominioId}
                onSelecionar={(c) => setCondominioId(c.id)}
                carregando={carregandoCondominios}
              />
              <p className="mt-1.5 text-xs text-dim">
                Não achou o seu? Busque pelo endereço. Atendemos {condominios.length || '...'} locais.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelClass}>Tipo</label>
                <select className={inputClass} value={tipoUsuario} onChange={(e) => setTipoUsuario(e.target.value)}>
                  <option value="morador">Morador</option>
                  <option value="visitante">Visitante</option>
                </select>
              </div>
              <div>
                <label className={labelClass}>Bloco / Apto</label>
                <input className={inputClass} value={blocoApto} onChange={(e) => setBlocoApto(e.target.value)} placeholder="Bloco A - 101" />
              </div>
            </div>

            <hr className="border-line my-2" />
            <p className="text-sm text-mute">Dados do veículo</p>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelClass}>Modelo</label>
                <input className={inputClass} value={veiculoModelo} onChange={(e) => setVeiculoModelo(e.target.value)} placeholder="BYD Dolphin Mini" required />
              </div>
              <div>
                <label className={labelClass}>Placa</label>
                <input className={inputClass} value={veiculoPlaca} onChange={(e) => setVeiculoPlaca(e.target.value)} placeholder="ABC1D23" />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelClass}>Capacidade da bateria (kWh)</label>
                <input className={inputClass} type="number" value={capacidadeBateria} onChange={(e) => setCapacidadeBateria(e.target.value)} />
              </div>
              <div>
                <label className={labelClass}>Potência do carro (kW)</label>
                <input className={inputClass} type="number" step="0.1" value={potenciaCarro} onChange={(e) => setPotenciaCarro(e.target.value)} />
              </div>
            </div>
            <p className="text-xs text-dim">
              A % de bateria atual será perguntada na hora de iniciar a recarga, não agora.
            </p>

            <button
              type="submit"
              disabled={carregando}
              className="w-full bg-flux hover:bg-flare disabled:opacity-50 rounded-lg py-2 font-medium transition mt-2"
            >
              {carregando ? 'Cadastrando...' : 'Cadastrar-se e entrar'}
            </button>
            <button
              type="button"
              className="w-full text-sm text-mute hover:text-ink pt-2"
              onClick={() => { setErro(''); setModo('login') }}
            >
              Já tenho cadastro
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

export default Login
