import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { GOOGLE_CLIENT_ID } from '../config.js'

/**
 * Entrada do painel do gestor. Dois caminhos, o mesmo segundo fator:
 *   - nome e senha (admin da plataforma, criado pelo provisionar.py);
 *   - "Entrar com Google" (operador de condomínio, aprovado pelo admin).
 * Em qualquer um, o código de 6 dígitos do app autenticador é obrigatório;
 * quem ainda não tem o app cadastrado entra numa tela que SÓ cadastra.
 * Senha e credencial do Google ficam só na memória desta tela.
 */

let scriptGoogle = null
function carregarGoogle() {
  if (!scriptGoogle) {
    scriptGoogle = new Promise((ok, falha) => {
      const s = document.createElement('script')
      s.src = 'https://accounts.google.com/gsi/client'
      s.async = true
      s.onload = () => ok(window.google)
      s.onerror = () => { scriptGoogle = null; falha(new Error('Não consegui carregar o Google.')) }
      document.head.appendChild(s)
    })
  }
  return scriptGoogle
}

function Entrar({ onEntrar, aviso }) {
  const [nome, setNome] = useState('')
  const [senha, setSenha] = useState('')
  const [codigo, setCodigo] = useState('')
  const [passo, setPasso] = useState('senha')   // 'senha' | 'codigo' | 'condominio' | 'pendente'
  const [via, setVia] = useState('senha')       // 'senha' | 'google'
  const [credencial, setCredencial] = useState('')
  const [condominios, setCondominios] = useState([])
  const [condominio, setCondominio] = useState('')
  const [email, setEmail] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState('')
  const campoCodigo = useRef(null)
  const botaoGoogle = useRef(null)

  function tratar(r) {
    if (r?.mfa_necessario) {
      setPasso('codigo')
      setTimeout(() => campoCodigo.current?.focus(), 0)
    } else if (r?.precisa_condominio) {
      setCondominios(r.condominios || []); setEmail(r.email || ''); setPasso('condominio')
    } else if (r?.pedido === 'pendente') {
      setEmail(r.email || ''); setPasso('pendente'); setCredencial('')
    } else if (r?.success) {
      setSenha(''); setCodigo(''); setCredencial('')
      onEntrar(r)
    }
  }

  async function google(cred, extra = {}) {
    setErro(''); setEnviando(true)
    try {
      tratar(await api('/admin/google', { method: 'POST', anonimo: true, body: { credencial: cred, ...extra } }))
    } catch (e) {
      setErro(e.message)
      if (extra.codigo) setCodigo('')
    } finally {
      setEnviando(false)
    }
  }

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || passo !== 'senha') return
    let vivo = true
    carregarGoogle().then((g) => {
      if (!vivo || !botaoGoogle.current) return
      g.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (r) => { setVia('google'); setCredencial(r.credential); google(r.credential) },
      })
      g.accounts.id.renderButton(botaoGoogle.current, { theme: 'outline', size: 'large', width: 320, text: 'signin_with' })
    }).catch((e) => setErro(e.message))
    return () => { vivo = false }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [passo])

  async function enviar(e) {
    e.preventDefault()
    if (via === 'google') {
      if (passo === 'condominio') return google(credencial, { condominio_id: condominio })
      return google(credencial, { codigo })
    }
    setErro(''); setEnviando(true)
    try {
      tratar(await api('/admin/login', {
        method: 'POST', anonimo: true,
        body: { nome, senha, ...(passo === 'codigo' ? { codigo } : {}) },
      }))
    } catch (e2) {
      setErro(e2.message)
      if (passo === 'codigo') setCodigo('')
    } finally {
      setEnviando(false)
    }
  }

  function voltar() {
    setPasso('senha'); setVia('senha'); setSenha(''); setCodigo(''); setCredencial(''); setErro('')
  }

  const campo = 'w-full rounded-lg border border-line bg-raise/70 px-4 py-2.5 text-ink placeholder-dim transition-colors focus:border-flux focus:outline-none'
  const TITULO = { senha: 'Entrar no painel', codigo: 'Confirme com o autenticador',
                   condominio: 'De qual condomínio você é?', pendente: 'Pedido enviado' }

  return (
    <div className="carbono flex min-h-screen items-center justify-center bg-void p-4 font-display text-ink">
      <div className="w-full max-w-sm">
        <p className="marca text-center text-2xl font-bold leading-none tracking-[0.08em] text-flux">GOODWE</p>
        <p className="mb-6 mt-2 text-center text-sm text-mute">Painel do gestor</p>

        <form onSubmit={enviar} className="rounded-2xl border border-line bg-panel/80 p-6 shadow-lift backdrop-blur-xl sm:p-7">
          <h1 className="text-lg font-semibold text-ink">{TITULO[passo]}</h1>
          <p className="mb-5 mt-1 text-sm text-mute">
            {passo === 'senha' && 'Acesso restrito a quem administra o condomínio.'}
            {passo === 'codigo' && 'Digite o código de 6 dígitos que o app autenticador mostra agora.'}
            {passo === 'condominio' && `Conta ${email}. O acesso só é liberado depois que o administrador aprovar.`}
            {passo === 'pendente' && `Seu pedido (${email}) está com o administrador da plataforma. Volte a entrar com o Google depois da aprovação.`}
          </p>

          {aviso && !erro && (
            <p className="mb-4 rounded-lg border border-queue/40 bg-queue/10 px-4 py-2 text-sm text-queue">{aviso}</p>
          )}
          {erro && (
            <p role="alert" className="mb-4 rounded-lg border border-flux/40 bg-flux/10 px-4 py-2 text-sm text-flux">{erro}</p>
          )}

          {passo === 'senha' && (
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
          )}
          {passo === 'codigo' && (
            <label className="block">
              <span className="mb-1 block text-sm text-mute">Código</span>
              <input ref={campoCodigo} className={`${campo} num text-center text-2xl tracking-[0.4em]`}
                     value={codigo} onChange={(e) => setCodigo(e.target.value.replace(/\D/g, '').slice(0, 6))}
                     inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" placeholder="000000" required />
            </label>
          )}
          {passo === 'condominio' && (
            <select className={campo} value={condominio} onChange={(e) => setCondominio(e.target.value)} required>
              <option value="">Escolha o condomínio</option>
              {condominios.map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}
            </select>
          )}

          {passo !== 'pendente' && (
            <button type="submit" disabled={enviando || (passo === 'codigo' && codigo.length !== 6) || (passo === 'condominio' && !condominio)}
                    className="brilho-flux mt-5 w-full rounded-lg bg-flux py-2.5 font-medium text-white transition hover:bg-flare disabled:opacity-50">
              {enviando ? 'Conferindo...' : passo === 'senha' ? 'Continuar' : passo === 'condominio' ? 'Pedir acesso' : 'Entrar'}
            </button>
          )}
          {passo !== 'senha' && (
            <button type="button" onClick={voltar} className="mt-3 w-full text-sm text-mute hover:text-ink">Voltar</button>
          )}
          {passo === 'senha' && GOOGLE_CLIENT_ID && (
            <div className="mt-5 border-t border-hair pt-5">
              <p className="mb-3 text-center text-xs text-dim">Operador de condomínio</p>
              <div ref={botaoGoogle} className="flex justify-center" />
            </div>
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
