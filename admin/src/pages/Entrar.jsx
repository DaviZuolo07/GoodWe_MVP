import { useRef, useState } from 'react'
import { api } from '../lib/api.js'

/**
 * Entrada do painel do gestor. Dois passos na mesma tela:
 *   1. nome e senha;
 *   2. código de 6 dígitos do app autenticador (quando a conta tem).
 * A senha fica só na memória desta tela entre um passo e outro e é apagada
 * assim que o login termina ou a pessoa volta.
 */
function Entrar({ onEntrar, aviso }) {
  const [nome, setNome] = useState('')
  const [senha, setSenha] = useState('')
  const [codigo, setCodigo] = useState('')
  const [passo, setPasso] = useState('senha')   // 'senha' | 'codigo'
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState('')
  const campoCodigo = useRef(null)

  async function enviar(e) {
    e.preventDefault()
    setErro(''); setEnviando(true)
    try {
      const r = await api('/admin/login', {
        method: 'POST', anonimo: true,
        body: { nome, senha, ...(passo === 'codigo' ? { codigo } : {}) },
      })
      if (r?.mfa_necessario) {
        setPasso('codigo')
        setTimeout(() => campoCodigo.current?.focus(), 0)
        return
      }
      setSenha(''); setCodigo('')
      onEntrar(r)
    } catch (e2) {
      setErro(e2.message)
      if (passo === 'codigo') setCodigo('')
    } finally {
      setEnviando(false)
    }
  }

  function voltar() {
    setPasso('senha'); setSenha(''); setCodigo(''); setErro('')
  }

  const campo = 'w-full rounded-lg border border-line bg-raise/70 px-4 py-2.5 text-ink placeholder-dim transition-colors focus:border-flux focus:outline-none'

  return (
    <div className="carbono flex min-h-screen items-center justify-center bg-void p-4 font-display text-ink">
      <div className="w-full max-w-sm">
        <p className="marca text-center text-2xl font-bold leading-none tracking-[0.08em] text-flux">GOODWE</p>
        <p className="mb-6 mt-2 text-center text-sm text-mute">Painel do gestor</p>

        <form onSubmit={enviar} className="rounded-2xl border border-line bg-panel/80 p-6 shadow-lift backdrop-blur-xl sm:p-7">
          <h1 className="text-lg font-semibold text-ink">
            {passo === 'senha' ? 'Entrar no painel' : 'Confirme com o autenticador'}
          </h1>
          <p className="mb-5 mt-1 text-sm text-mute">
            {passo === 'senha'
              ? 'Acesso restrito a quem administra o condomínio.'
              : 'Digite o código de 6 dígitos que o app autenticador mostra agora.'}
          </p>

          {aviso && !erro && (
            <p className="mb-4 rounded-lg border border-queue/40 bg-queue/10 px-4 py-2 text-sm text-queue">{aviso}</p>
          )}
          {erro && (
            <p role="alert" className="mb-4 rounded-lg border border-flux/40 bg-flux/10 px-4 py-2 text-sm text-flux">{erro}</p>
          )}

          {passo === 'senha' ? (
            <div className="space-y-4">
              <label className="block">
                <span className="mb-1 block text-sm text-mute">Nome de usuário</span>
                <input className={campo} value={nome} onChange={(e) => setNome(e.target.value)}
                       autoComplete="username" maxLength={60} required autoFocus />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm text-mute">Senha</span>
                <input className={campo} type="password" value={senha} onChange={(e) => setSenha(e.target.value)}
                       autoComplete="current-password" maxLength={128} required />
              </label>
            </div>
          ) : (
            <label className="block">
              <span className="mb-1 block text-sm text-mute">Código</span>
              <input ref={campoCodigo} className={`${campo} num text-center text-2xl tracking-[0.4em]`}
                     value={codigo} onChange={(e) => setCodigo(e.target.value.replace(/\D/g, '').slice(0, 6))}
                     inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" placeholder="000000" required />
            </label>
          )}

          <button type="submit" disabled={enviando || (passo === 'codigo' && codigo.length !== 6)}
                  className="brilho-flux mt-5 w-full rounded-lg bg-flux py-2.5 font-medium text-white transition hover:bg-flare disabled:opacity-50">
            {enviando ? 'Conferindo...' : passo === 'senha' ? 'Continuar' : 'Entrar'}
          </button>
          {passo === 'codigo' && (
            <button type="button" onClick={voltar} className="mt-3 w-full text-sm text-mute hover:text-ink">
              Voltar
            </button>
          )}
        </form>

        <p className="mt-5 text-center text-xs leading-relaxed text-dim">
          Toda entrada e toda alteração feita aqui ficam registradas.
        </p>
      </div>
    </div>
  )
}

export default Entrar
