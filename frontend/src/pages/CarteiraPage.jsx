import { useCallback, useEffect, useState } from 'react'
import { supabase } from '../supabaseClient.js'
import { post } from '../lib/api.js'
import { brl, dataHora } from '../lib/formato.js'

/**
 * Carteira - e, principalmente, o EXTRATO.
 *
 * Toda movimentação vira linha em `movimentacoes_carteira`: crédito, reserva
 * (pré-autorização ao aproximar o cartão) e estorno da diferença no fim.
 * Mostrar as três é o que torna a cobrança explicável - era o ponto que a
 * banca apontou como pouco claro.
 */

const ROTULOS = {
  credito: { texto: 'Crédito adicionado', cor: 'text-live', sinal: '+' },
  pre_autorizacao: { texto: 'Reservado para a recarga', cor: 'text-flux', sinal: '−' },
  estorno: { texto: 'Estorno da diferença', cor: 'text-live', sinal: '+' },
  ajuste: { texto: 'Ajuste', cor: 'text-mute', sinal: '' },
}

function CarteiraPage({ sessao, onSaldoAtualizado }) {
  const [valor, setValor] = useState(50)
  const [carregando, setCarregando] = useState(false)
  const [erro, setErro] = useState('')
  const [extrato, setExtrato] = useState([])

  const carregarExtrato = useCallback(async () => {
    const { data } = await supabase
      .from('movimentacoes_carteira')
      .select('*')
      .order('criado_em', { ascending: false })
      .limit(40)
    setExtrato(data || [])
  }, [])

  useEffect(() => {
    carregarExtrato()
    // Realtime: a reserva e o estorno acontecem no backend, disparados pelo
    // cartão e pelo fim da recarga - não por um clique nesta tela.
    const canal = supabase
      .channel('extrato-carteira')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'movimentacoes_carteira' },
        carregarExtrato)
      .subscribe()
    return () => supabase.removeChannel(canal)
  }, [carregarExtrato])

  async function creditar(e) {
    e.preventDefault()
    setErro(''); setCarregando(true)
    try {
      const d = await post('/me/carteira/creditar', { valor: Number(valor) })
      onSaldoAtualizado(d.saldo_atual)
      carregarExtrato()
    } catch (e2) {
      setErro(e2.message)
    } finally {
      setCarregando(false)
    }
  }

  return (
    <div>
      <div className="mb-8">
        <h2 className="text-xl font-semibold tracking-tight text-ink lg:text-[1.375rem]">Carteira</h2>
        <p className="mt-1 text-sm text-dim">Seu saldo, o que foi reservado e o que voltou.</p>
      </div>

      <div className="mb-5 grid gap-5 lg:grid-cols-[1fr_1.2fr]">
        <div className="rounded-panel border border-line bg-panel p-6">
          <p className="text-sm text-dim">Saldo disponível</p>
          <p className="num mb-5 mt-1 text-3xl font-semibold text-live">{brl(sessao.usuario.saldo)}</p>

          {erro && (
            <div className="mb-3 rounded-chip border border-flux/40 bg-flux/10 px-3 py-2 text-sm text-flux">{erro}</div>
          )}

          <form onSubmit={creditar} className="flex gap-3">
            <input type="number" min="1" max="500" step="any" value={valor}
                   onChange={(e) => setValor(e.target.value)}
                   className="w-32 rounded-chip border border-line bg-raise px-4 py-2 text-ink" />
            <button type="submit" disabled={carregando}
                    className="flex-1 rounded-chip bg-flux px-5 py-2 font-medium text-white transition
                               hover:bg-flare disabled:opacity-40">
              {carregando ? 'Processando...' : 'Adicionar saldo'}
            </button>
          </form>
          <p className="mt-2 text-xs text-dim">Crédito simulado — não há cobrança real por trás.</p>
        </div>

        <div className="rounded-panel border border-line bg-panel p-6">
          <h3 className="font-medium text-ink">Como a cobrança funciona</h3>
          <ol className="mt-3 space-y-2.5 text-sm leading-relaxed text-mute">
            <li><span className="text-ink">1. Reserva.</span> Ao aproximar o cartão, o valor estimado da recarga
              fica reservado no seu saldo. Sem saldo, a recarga não começa.</li>
            <li><span className="text-ink">2. Medição.</span> Cada kWh é contado pela tarifa do horário em que foi
              entregue — na ponta custa mais.</li>
            <li><span className="text-ink">3. Teto.</span> Se o consumo alcançar o valor reservado, a recarga para
              sozinha. Você nunca paga mais do que autorizou.</li>
            <li><span className="text-ink">4. Estorno.</span> No fim, cobramos só o consumo real e a diferença
              volta na hora para a carteira.</li>
          </ol>
        </div>
      </div>

      <h3 className="mb-3 text-lg font-semibold text-ink">Extrato</h3>
      <div className="overflow-hidden rounded-panel border border-line bg-panel">
        {extrato.length === 0 && <p className="p-5 text-sm text-dim">Nenhuma movimentação ainda.</p>}
        <div className="divide-y divide-hair">
          {extrato.map((m) => {
            const r = ROTULOS[m.tipo] || ROTULOS.ajuste
            return (
              <div key={m.id} className="flex items-center justify-between gap-4 px-5 py-3.5">
                <div className="min-w-0">
                  <p className="text-sm text-ink">{r.texto}</p>
                  <p className="truncate text-xs text-dim">{m.descricao} · {dataHora(m.criado_em)}</p>
                </div>
                <div className="text-right">
                  <p className={`num text-sm font-medium ${r.cor}`}>{r.sinal} {brl(m.valor)}</p>
                  <p className="num text-[0.625rem] text-dim">saldo {brl(m.saldo_apos)}</p>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default CarteiraPage
