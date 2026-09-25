import { useState } from 'react'
import CondominioSelect, { useCondominios } from '../components/CondominioSelect.jsx'
import { CONDOMINIO_PADRAO } from '../config.js'
import { post } from '../lib/api.js'

/** Presets do cadastro: carro elétrico ou o celular da bancada do ESP32. */
const PRESETS = {
  carro: { capacidade: 40, potencia: 7.4, rotulo: 'Carro elétrico', exemplo: 'BYD Dolphin Mini' },
  celular: { capacidade: 0.015, potencia: 0.018, rotulo: 'Celular (bancada ESP32)', exemplo: 'Celular de bancada' },
}

function Login({ onLoginSuccess, aviso }) {
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
  const [veiculoTipo, setVeiculoTipo] = useState('carro')

  async function handleLogin(e) {
    e.preventDefault()
    setErro('')
    setCarregando(true)
    try {
      onLoginSuccess(await post('/login', { nome: loginNome, senha: loginSenha }))
    } catch (e) {
      setErro(e.message)
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
      onLoginSuccess(await post('/cadastro', {
        nome,
        senha,
        condominio_id: condominioId || CONDOMINIO_PADRAO,
        tipo_usuario: tipoUsuario,
        bloco_apto: blocoApto,
        veiculo_modelo: veiculoModelo,
        veiculo_placa: veiculoPlaca || null,
        veiculo_tipo: veiculoTipo,
        capacidade_bateria_kwh: Number(capacidadeBateria),
        potencia_carro_kw: Number(potenciaCarro),
      }))
    } catch (e) {
      setErro(e.message)
    } finally {
      setCarregando(false)
    }
  }

  const inputClass =
    'w-full bg-raise/70 border border-line rounded-lg px-4 py-2.5 text-ink placeholder-dim transition-colors focus:outline-none focus:border-flux'
  const labelClass = 'text-sm text-mute mb-1 block'

  return (
    <div className="carbono grid min-h-screen bg-void font-display text-ink lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
      {/* Painel de marca — só visual, não participa do formulário */}
      <aside className="chevrons relative hidden overflow-hidden border-r border-line lg:flex lg:flex-col lg:justify-between lg:p-12"
             aria-hidden="true">
        {/* Véu escuro da esquerda para a direita: o texto fica sobre o carbono
            liso e os chevrons aparecem só na metade que aponta para o formulário */}
        <div className="pointer-events-none absolute inset-0 bg-linear-to-r from-void via-void/90 via-45% to-transparent" />
        <div className="relative">
          <p className="text-[2.25rem] marca font-bold leading-none tracking-[0.08em] text-flux">GOODWE</p>
          <p className="mt-3 text-sm tracking-wide text-mute">ChargeOps AI Assistant</p>
        </div>
        <div className="relative max-w-sm">
          <p className="text-3xl font-semibold leading-tight tracking-tight text-ink">
            Recarga de veículos elétricos no condomínio, sem desarmar o quadro.
          </p>
          <p className="mt-4 text-sm leading-relaxed text-mute">
            Gestão de demanda em tempo real, cobrança pelo kWh medido e um assistente que explica cada recarga.
          </p>
        </div>
        <p className="eyebrow relative">Smart Energy Innovator</p>
      </aside>

      <div className="flex items-center justify-center p-4 sm:p-8">
      <div className="w-full max-w-md rounded-2xl border border-line bg-panel/80 p-8 shadow-lift backdrop-blur-xl">
        <p className="mb-6 text-[1.5rem] marca font-bold leading-none tracking-[0.08em] text-flux lg:hidden">GOODWE</p>
        <h1 className="text-2xl font-bold text-flux mb-1">GoodWe ChargeOps AI</h1>
        <p className="text-mute mb-6">
          {modo === 'login' ? 'Entrar na sua conta' : 'Criar seu cadastro'}
        </p>

        {aviso && !erro && (
          <div className="mb-4 rounded-lg border border-queue/40 bg-queue/10 px-4 py-2 text-sm text-queue">
            {aviso}
          </div>
        )}

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
                autoComplete="username"
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
                placeholder="Sua senha"
                autoComplete="current-password"
                required
              />
            </div>
            <button
              type="submit"
              disabled={carregando}
              className="brilho-flux w-full bg-flux hover:bg-flare disabled:opacity-50 rounded-lg py-2.5 font-medium text-white transition"
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
              <input className={inputClass} value={nome} onChange={(e) => setNome(e.target.value)} autoComplete="username" maxLength={60} required />
            </div>
            <div>
              <label className={labelClass}>Senha</label>
              <input
                className={inputClass}
                type="password"
                value={senha}
                onChange={(e) => setSenha(e.target.value)}
                placeholder="Mínimo 8 caracteres"
                autoComplete="new-password"
                minLength={8}
                required
              />
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
            <p className="text-sm text-mute">O que você vai carregar</p>

            <div className="flex gap-2">
              {Object.entries(PRESETS).map(([chave, preset]) => (
                <button key={chave} type="button"
                        onClick={() => {
                          setVeiculoTipo(chave)
                          setCapacidadeBateria(preset.capacidade)
                          setPotenciaCarro(preset.potencia)
                          if (!veiculoModelo) setVeiculoModelo(preset.exemplo)
                        }}
                        className={`flex-1 rounded-lg py-2 text-sm transition ${
                          veiculoTipo === chave ? 'bg-flux text-white' : 'bg-raise text-mute hover:bg-line'}`}>
                  {preset.rotulo}
                </button>
              ))}
            </div>

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
                <input className={inputClass} type="number" step="0.001" value={capacidadeBateria} onChange={(e) => setCapacidadeBateria(e.target.value)} />
              </div>
              <div>
                <label className={labelClass}>Potência aceita (kW)</label>
                <input className={inputClass} type="number" step="0.001" value={potenciaCarro} onChange={(e) => setPotenciaCarro(e.target.value)} />
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
    </div>
  )
}

export default Login
