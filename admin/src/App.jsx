import { useCallback, useEffect, useLayoutEffect, useState } from 'react'
import Entrar from './pages/Entrar.jsx'
import PainelPage from './pages/PainelPage.jsx'
import SegurancaPage from './pages/SegurancaPage.jsx'
import VisaoGeralPage from './pages/VisaoGeralPage.jsx'
import { definirAoExpirar, definirToken } from './lib/api.js'
import { aplicarTema, lerTema } from './lib/tema.js'

const ABAS = [
  { id: 'geral', rotulo: 'Visão geral', soGlobal: true },
  { id: 'painel', rotulo: 'Operação' },
  { id: 'seguranca', rotulo: 'Acesso e segurança' },
]

function App() {
  const [sessao, setSessao] = useState(null)   // { gestor, expiraEm, mfa }
  const [aviso, setAviso] = useState('')
  const [aba, setAba] = useState('painel')
  const [restante, setRestante] = useState(null)

  useLayoutEffect(() => { aplicarTema(lerTema()) }, [])

  const entrar = useCallback((dados) => {
    definirToken(dados.token)
    setAviso('')
    // Sem segundo fator: começa por cadastrá-lo. Admin da plataforma abre na Visão geral.
    setAba(!dados.mfa ? 'seguranca' : dados.global ? 'geral' : 'painel')
    setSessao({ gestor: dados.gestor, expiraEm: dados.expira_em, mfa: Boolean(dados.mfa),
                global: Boolean(dados.global) })
  }, [])

  const sair = useCallback((motivo = '') => {
    definirToken(null)
    setAviso(motivo)
    setSessao(null)
  }, [])

  useEffect(() => {
    definirAoExpirar(() => sair('Sua sessão expirou. Entre novamente.'))
    return () => definirAoExpirar(null)
  }, [sair])

  // Sessão curta de propósito, com o tempo que falta sempre visível.
  const expiraEm = sessao?.expiraEm
  useEffect(() => {
    if (!expiraEm) return
    const tique = () => {
      const s = Math.round(expiraEm - Date.now() / 1000)
      if (s <= 0) sair('Sua sessão expirou. Entre novamente.')
      else setRestante(s)
    }
    tique()
    const id = setInterval(tique, 1000)
    return () => clearInterval(id)
  }, [expiraEm, sair])

  if (!sessao) return <Entrar onEntrar={entrar} aviso={aviso} />

  const min = Math.floor((restante ?? 0) / 60)
  const seg = String((restante ?? 0) % 60).padStart(2, '0')

  return (
    <div className="ambient min-h-screen bg-void font-display text-ink">
      <header className="topbar sticky top-0 z-30 border-b border-line bg-void/70 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1360px] flex-wrap items-center justify-between gap-x-6 gap-y-3 px-4 py-3 lg:px-9">
          <div className="flex items-baseline gap-3">
            <p className="marca text-xl font-bold leading-none tracking-[0.08em] text-flux">GOODWE</p>
            <p className="text-sm text-mute">Painel do gestor</p>
          </div>

          <nav className="order-3 flex w-full gap-1 overflow-x-auto sm:order-none sm:w-auto" aria-label="Seções do painel">
            {ABAS.filter((a) => !a.soGlobal || sessao.global).map((a) => (
              <button key={a.id} type="button" onClick={() => setAba(a.id)}
                      aria-current={aba === a.id ? 'page' : undefined}
                      className={`relative shrink-0 rounded-chip px-3.5 py-2 text-sm transition-colors ${
                        aba === a.id ? 'nav-ativo text-ink' : 'text-mute hover:bg-raise/60 hover:text-ink'}`}>
                {a.rotulo}
                {a.id === 'seguranca' && !sessao.mfa && (
                  <span className="ml-2 inline-block h-2 w-2 rounded-full bg-queue align-middle" aria-label="pendente" />
                )}
              </button>
            ))}
          </nav>

          <div className="flex items-center gap-4 text-sm">
            <span className="hidden text-mute md:inline">{sessao.gestor.nome}</span>
            <span className={`num text-xs ${restante !== null && restante < 120 ? 'text-queue' : 'text-dim'}`}
                  title="A sessão do painel é curta de propósito">
              sessão {min}:{seg}
            </span>
            <button type="button" onClick={() => sair()}
                    className="rounded-chip border border-line px-3 py-1.5 text-mute transition-colors hover:border-flux/50 hover:text-flux">
              Sair
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1360px] px-4 py-7 lg:px-9 lg:py-9">
        {aba === 'geral' && sessao.global && <VisaoGeralPage />}
        {aba === 'painel' && <PainelPage />}
        {aba === 'seguranca' && (
          <SegurancaPage
            mfa={sessao.mfa}
            onMfaAtivado={(dados) => {
              definirToken(dados.token)
              setSessao((s) => ({ ...s, mfa: true, expiraEm: dados.expira_em }))
            }}
          />
        )}
      </main>
    </div>
  )
}

export default App
