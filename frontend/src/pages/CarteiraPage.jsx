import { useEffect, useState } from 'react'
import { supabase } from '../supabaseClient.js'

const API_URL = import.meta.env.VITE_API_URL

function CarteiraPage({ sessao, onSaldoAtualizado }) {
  const [valor, setValor] = useState(50)
  const [carregando, setCarregando] = useState(false)
  const [erro, setErro] = useState('')
  const [historico, setHistorico] = useState([])

  useEffect(() => {
    async function carregarHistorico() {
      const { data } = await supabase
        .from('pagamentos')
        .select('*, sessoes_recarga(iniciado_em, carregadores(numero))')
        .order('criado_em', { ascending: false })
        .limit(20)
      setHistorico(data || [])
    }
    carregarHistorico()
  }, [])

  async function handleRecarregar(e) {
    e.preventDefault()
    setErro('')
    setCarregando(true)
    try {
      const res = await fetch(`${API_URL}/usuarios/${sessao.usuario.id}/recarregar-saldo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ valor: Number(valor) }),
      })
      const data = await res.json()
      if (!res.ok) {
        setErro(data.detail || 'Não foi possível recarregar o saldo.')
        return
      }
      onSaldoAtualizado(data.saldo_atual)
    } catch {
      setErro('Não foi possível conectar ao servidor.')
    } finally {
      setCarregando(false)
    }
  }

  return (
    <div>
      <h2 className="text-xl font-bold mb-6">Carteira</h2>

      <div className="bg-panel border border-line rounded-xl p-6 mb-6">
        <p className="text-sm text-dim mb-1">Saldo atual</p>
        <p className="text-3xl font-bold text-live mb-4">R$ {sessao.usuario.saldo.toFixed(2)}</p>

        {erro && (
          <div className="bg-flux/10 border border-flux/40 text-flux text-sm rounded-lg px-3 py-2 mb-3">
            {erro}
          </div>
        )}

        <form onSubmit={handleRecarregar} className="flex gap-3">
          <input
            type="number"
            min="1"
            step="any"
            value={valor}
            onChange={(e) => setValor(e.target.value)}
            className="bg-raise border border-line rounded-lg px-4 py-2 text-ink w-40"
          />
          <button
            type="submit"
            disabled={carregando}
            className="bg-flux hover:bg-flare disabled:opacity-50 px-5 py-2 rounded-lg font-medium transition"
          >
            {carregando ? 'Processando...' : 'Adicionar saldo'}
          </button>
        </form>
        <p className="text-xs text-dim mt-2">
          Simulação de recarga de saldo — não é uma cobrança real.
        </p>
      </div>

      <h3 className="text-lg font-semibold mb-3">Histórico de pagamentos</h3>
      <div className="bg-panel border border-line rounded-xl divide-y divide-hair">
        {historico.length === 0 && (
          <p className="p-4 text-sm text-dim">Nenhum pagamento ainda.</p>
        )}
        {historico.map((p) => (
          <div key={p.id} className="p-4 flex justify-between items-center text-sm">
            <div>
              <p className="text-ink">
                Carregador {p.sessoes_recarga?.carregadores?.numero || '—'}
              </p>
              <p className="text-xs text-dim">
                {p.criado_em ? new Date(p.criado_em).toLocaleString('pt-BR') : ''}
              </p>
            </div>
            <span className="text-flux font-medium">R$ {Number(p.valor).toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default CarteiraPage
