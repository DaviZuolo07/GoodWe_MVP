import { useCallback, useEffect, useState } from 'react'
import { get, post } from '../lib/api.js'
import { dataHora } from '../lib/formato.js'

/**
 * Operadores - só para o admin da plataforma. Quem entra com o Google no
 * painel vira um PEDIDO para um condomínio; nada é liberado até alguém aqui
 * aprovar. Aprovado, o operador vê só aquele condomínio e precisa do app
 * autenticador antes de qualquer dado. Revogar corta o acesso na hora.
 */

const COR = { pendente: 'text-queue', aprovado: 'text-live', recusado: 'text-dim', revogado: 'text-flux' }

function OperadoresPage() {
  const [lista, setLista] = useState(null)
  const [erro, setErro] = useState('')
  const [ocupado, setOcupado] = useState(null)

  const carregar = useCallback(async () => {
    try { setLista(await get('/admin/operadores')); setErro('') } catch (e) { setErro(e.message) }
  }, [])

  useEffect(() => {
    carregar()
    const t = setInterval(carregar, 10000)
    return () => clearInterval(t)
  }, [carregar])

  async function decidir(p, acao) {
    if (acao === 'revogar' && !window.confirm(`Tirar o acesso de ${p.email} agora?`)) return
    setOcupado(p.id)
    try { await post(`/admin/operadores/${p.id}/${acao}`); carregar() }
    catch (e) { setErro(e.message) } finally { setOcupado(null) }
  }

  const pendentes = (lista || []).filter((p) => p.status === 'pendente').length
  return (
    <div>
      <h2 className="text-2xl font-semibold tracking-tight text-ink">Operadores dos condomínios</h2>
      <p className="mt-1 max-w-3xl text-sm text-mute">
        O operador pede acesso entrando com a conta Google em "Entrar com Google" e escolhendo o condomínio. A conta só
        nasce quando você aprova aqui - presa àquele condomínio, sem senha, e com o app autenticador obrigatório.
        {pendentes > 0 && <span className="ml-1 text-queue">{pendentes} aguardando.</span>}
      </p>
      {erro && <p className="mt-4 rounded-chip border border-flux/40 bg-flux/10 px-4 py-3 text-sm text-flux">{erro}</p>}
      {!lista && !erro && <div className="skeleton mt-5 h-40 rounded-panel" />}
      {lista && !lista.length && (
        <p className="mt-5 rounded-panel border border-line bg-panel px-5 py-8 text-center text-sm text-mute">Nenhum pedido ainda.</p>
      )}
      {lista && lista.length > 0 && (
        <div className="mt-5 overflow-x-auto rounded-panel border border-line bg-panel">
          <table className="w-full min-w-[680px] text-left text-sm">
            <thead><tr className="border-b border-hair text-xs text-dim">
              {['Pedido em', 'Conta Google', 'Condomínio', 'Situação', ''].map((c) => <th key={c} className="px-4 py-3 font-normal">{c}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-hair">
              {lista.map((p) => (
                <tr key={p.id}>
                  <td className="num px-4 py-2.5 text-mute">{dataHora(p.criado_em)}</td>
                  <td className="px-4 py-2.5"><span className="text-ink">{p.nome_google || '—'}</span>
                    <span className="block text-xs text-dim">{p.email}</span></td>
                  <td className="px-4 py-2.5">{p.local || '—'}</td>
                  <td className={`px-4 py-2.5 text-xs font-medium ${COR[p.status] || 'text-mute'}`}>{p.status}
                    {p.decidido_em && <span className="block font-normal text-dim">{dataHora(p.decidido_em)}</span>}</td>
                  <td className="px-4 py-2.5 text-right">
                    {p.status === 'pendente' && (
                      <span className="inline-flex gap-2">
                        <button type="button" disabled={ocupado === p.id} onClick={() => decidir(p, 'aprovar')}
                                className="rounded-chip bg-flux px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">Aprovar</button>
                        <button type="button" disabled={ocupado === p.id} onClick={() => decidir(p, 'recusar')}
                                className="rounded-chip border border-line px-3 py-1.5 text-sm text-mute hover:text-ink">Recusar</button>
                      </span>
                    )}
                    {p.status === 'aprovado' && (
                      <button type="button" disabled={ocupado === p.id} onClick={() => decidir(p, 'revogar')}
                              className="rounded-chip border border-flux/50 px-3 py-1.5 text-sm text-flux">Revogar</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default OperadoresPage
