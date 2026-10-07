import { useCallback, useEffect, useState } from 'react'
import QRCode from 'qrcode'
import { get, post } from '../lib/api.js'

const ACOES = {
  login: { rotulo: 'Entrada no painel', cor: 'text-live' },
  login_recusado: { rotulo: 'Entrada recusada', cor: 'text-flux' },
  alteracao: { rotulo: 'Alteração', cor: 'text-ink' },
  mfa_iniciado: { rotulo: 'Cadastro do segundo fator iniciado', cor: 'text-queue' },
  mfa_ativado: { rotulo: 'Segundo fator ativado', cor: 'text-live' },
}

function quando(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'medium' })
}

function CadastroMfa({ onAtivado }) {
  const [dados, setDados] = useState(null)       // { segredo, uri }
  const [qr, setQr] = useState('')
  const [codigo, setCodigo] = useState('')
  const [erro, setErro] = useState('')
  const [enviando, setEnviando] = useState(false)

  async function iniciar() {
    setErro(''); setEnviando(true)
    try {
      const d = await post('/admin/mfa/iniciar')
      setDados(d)
      // O QR é desenhado aqui no navegador: o segredo não passa por nenhum
      // serviço de terceiros.
      setQr(await QRCode.toDataURL(d.uri, { margin: 1, width: 220 }))
    } catch (e) { setErro(e.message) } finally { setEnviando(false) }
  }

  async function confirmar(e) {
    e.preventDefault()
    setErro(''); setEnviando(true)
    try {
      onAtivado(await post('/admin/mfa/confirmar', { codigo }))
    } catch (e2) { setErro(e2.message); setCodigo('') } finally { setEnviando(false) }
  }

  return (
    <section className="rounded-panel border border-queue/40 bg-queue/5 p-5 sm:p-6">
      <h2 className="text-lg font-semibold text-ink">Ative o segundo fator</h2>
      <p className="mt-1 max-w-2xl text-sm leading-relaxed text-mute">
        Hoje esta conta entra só com a senha. Com o segundo fator, entrar passa a exigir também um código que
        muda a cada 30 segundos no seu celular — quem descobrir a senha não entra sem ele.
      </p>
      {erro && <p role="alert" className="mt-4 rounded-lg border border-flux/40 bg-flux/10 px-4 py-2 text-sm text-flux">{erro}</p>}

      {!dados ? (
        <button type="button" onClick={iniciar} disabled={enviando}
                className="brilho-flux mt-5 rounded-lg bg-flux px-5 py-2.5 font-medium text-white transition hover:bg-flare disabled:opacity-50">
          {enviando ? 'Gerando...' : 'Cadastrar app autenticador'}
        </button>
      ) : (
        <div className="mt-5 grid gap-6 md:grid-cols-[auto_1fr]">
          {qr && <img src={qr} alt="QR code para o app autenticador" width="220" height="220" className="rounded-lg bg-white p-2" />}
          <form onSubmit={confirmar} className="max-w-md">
            <ol className="list-decimal space-y-2 pl-5 text-sm leading-relaxed text-mute">
              <li>Abra o Google Authenticator, Microsoft Authenticator, Authy ou 1Password.</li>
              <li>Adicione uma conta lendo o QR code — ou digite a chave abaixo.</li>
              <li>Digite aqui o código de 6 dígitos que o app mostrar.</li>
            </ol>
            <p className="num mt-4 select-all break-all rounded-lg border border-line bg-raise/60 px-3 py-2 text-sm text-ink">{dados.segredo}</p>
            <p className="mt-1.5 text-xs text-dim">Esta chave aparece só agora. Não envie por mensagem.</p>
            <div className="mt-4 flex gap-3">
              <input className="num w-40 rounded-lg border border-line bg-raise/70 px-4 py-2.5 text-center text-lg tracking-[0.3em] text-ink focus:border-flux focus:outline-none"
                     value={codigo} onChange={(e) => setCodigo(e.target.value.replace(/\D/g, '').slice(0, 6))}
                     inputMode="numeric" autoComplete="one-time-code" placeholder="000000" aria-label="Código de 6 dígitos" required />
              <button type="submit" disabled={enviando || codigo.length !== 6}
                      className="rounded-lg bg-flux px-5 py-2.5 font-medium text-white transition hover:bg-flare disabled:opacity-50">
                {enviando ? 'Conferindo...' : 'Ativar'}
              </button>
            </div>
          </form>
        </div>
      )}
    </section>
  )
}

function SegurancaPage({ mfa, onMfaAtivado }) {
  const [eventos, setEventos] = useState(null)
  const [erro, setErro] = useState('')

  const carregar = useCallback(async () => {
    try { setEventos((await get('/admin/auditoria?limite=80')).eventos) }
    catch (e) { setErro(e.message) }
  }, [])

  useEffect(() => { carregar() }, [carregar, mfa])

  return (
    <div className="space-y-8">
      {mfa ? (
        <section className="rounded-panel border border-line bg-panel p-5 sm:p-6">
          <h2 className="text-lg font-semibold text-ink">Segundo fator ativo</h2>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-mute">
            Esta conta só entra com senha e código do app autenticador. Para trocar de celular, peça a quem
            administra o servidor — a troca não é feita por esta tela, para que uma sessão aberta não consiga
            substituir o seu segundo fator.
          </p>
        </section>
      ) : (
        <CadastroMfa onAtivado={onMfaAtivado} />
      )}

      <section>
        <div className="mb-3 flex items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-ink">Registro de acesso</h2>
            <p className="mt-1 text-sm text-mute">Entradas, recusas e alterações feitas no painel deste condomínio.</p>
          </div>
          <button type="button" onClick={carregar} className="rounded-chip border border-line px-3 py-1.5 text-sm text-mute hover:text-ink">
            Atualizar
          </button>
        </div>
        {erro && <p className="rounded-panel border border-flux/30 bg-flux/10 p-4 text-sm text-flux">{erro}</p>}
        {!eventos && !erro && <div className="skeleton h-40 rounded-panel" />}
        {eventos && eventos.length === 0 && (
          <p className="rounded-panel border border-dashed border-line px-5 py-10 text-center text-sm text-dim">
            Nada registrado ainda. Se você acabou de entrar e esta lista segue vazia, a tabela de auditoria
            (db/18) ainda não foi criada no banco.
          </p>
        )}
        {eventos && eventos.length > 0 && (
          <div className="overflow-x-auto rounded-panel border border-line bg-panel">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs text-dim">
                  <th className="px-4 py-3 font-medium">Quando</th>
                  <th className="px-4 py-3 font-medium">O quê</th>
                  <th className="px-4 py-3 font-medium">Detalhe</th>
                  <th className="px-4 py-3 font-medium">De onde</th>
                </tr>
              </thead>
              <tbody>
                {eventos.map((ev, i) => {
                  const a = ACOES[ev.acao] || { rotulo: ev.acao, cor: 'text-mute' }
                  return (
                    <tr key={`${ev.criado_em}-${i}`} className="border-b border-hair last:border-0">
                      <td className="num whitespace-nowrap px-4 py-2.5 text-mute">{quando(ev.criado_em)}</td>
                      <td className={`px-4 py-2.5 ${a.cor}`}>{a.rotulo}</td>
                      <td className="num px-4 py-2.5 text-xs text-mute">{ev.detalhe || '—'}</td>
                      <td className="num px-4 py-2.5 text-xs text-dim">{ev.ip || '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

export default SegurancaPage
