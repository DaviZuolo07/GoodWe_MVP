import { useEffect, useState } from 'react'
import { supabase } from '../supabaseClient.js'

/**
 * Histórico de recargas — só as sessões do usuário logado.
 *
 * Leitura direta do Supabase, no mesmo padrão do Dashboard. Não passa pelo
 * backend porque não há ação nenhuma aqui: é consulta pura.
 *
 * Sessões com status 'carregando' ficam de fora — essas aparecem ao vivo no
 * Dashboard. Aqui é o que já terminou.
 */

const STATUS = {
  finalizada: { label: 'Concluída', cor: 'text-live', borda: 'border-live/25', fundo: 'bg-live/10' },
  cancelada: { label: 'Cancelada', cor: 'text-dim', borda: 'border-line', fundo: 'bg-raise' },
}

function duracao(inicio, fim) {
  if (!inicio || !fim) return '—'
  const min = Math.max(0, Math.round((new Date(fim) - new Date(inicio)) / 60000))
  if (min < 60) return `${min} min`
  return `${Math.floor(min / 60)}h ${String(min % 60).padStart(2, '0')}m`
}

function dataHora(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function Resumo({ sessoes }) {
  const energia = sessoes.reduce((s, r) => s + Number(r.energia_entregue_kwh || 0), 0)
  const gasto = sessoes.reduce((s, r) => s + Number(r.custo_final ?? r.custo_estimado ?? 0), 0)

  const cards = [
    { label: 'Recargas realizadas', valor: String(sessoes.length) },
    { label: 'Energia total', valor: `${energia.toFixed(1)} kWh` },
    { label: 'Total gasto', valor: `R$ ${gasto.toFixed(2)}` },
  ]

  return (
    <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
      {cards.map((c) => (
        <div key={c.label} className="rounded-panel border border-line bg-panel p-5">
          <p className="eyebrow mb-2">{c.label}</p>
          <p className="num text-2xl font-semibold text-ink 2xl:text-3xl">{c.valor}</p>
        </div>
      ))}
    </div>
  )
}

function LinhaSessao({ s }) {
  const st = STATUS[s.status] || STATUS.cancelada
  const custo = Number(s.custo_final ?? s.custo_estimado ?? 0)
  const inicial = s.percentual_bateria_inicial
  const final = s.percentual_bateria_atual

  return (
    <div className="sweep group relative overflow-hidden border-b border-hair px-5 py-4 transition-colors duration-200 last:border-0 hover:bg-raise/40">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="num rounded-md bg-raise px-2 py-0.5 text-xs font-semibold text-ink">
              {s.carregadores?.numero || '—'}
            </span>
            <p className="truncate font-medium text-ink">{s.veiculos?.modelo || 'Veículo'}</p>
            <span className={`rounded-md border px-2 py-0.5 text-[0.6875rem] ${st.borda} ${st.fundo} ${st.cor}`}>
              {st.label}
            </span>
          </div>
          <p className="num mt-1.5 text-xs text-dim">{dataHora(s.iniciado_em)}</p>
        </div>

        <p className="num shrink-0 text-lg font-semibold text-ink">R$ {custo.toFixed(2)}</p>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <dt className="eyebrow text-[10px]">Energia</dt>
          <dd className="num mt-0.5 text-sm text-ink">
            {Number(s.energia_entregue_kwh || 0).toFixed(2)} kWh
          </dd>
        </div>
        <div>
          <dt className="eyebrow text-[10px]">Duração</dt>
          <dd className="num mt-0.5 text-sm text-ink">{duracao(s.iniciado_em, s.finalizado_em)}</dd>
        </div>
        <div>
          <dt className="eyebrow text-[10px]">Bateria</dt>
          <dd className="num mt-0.5 text-sm text-ink">
            {inicial != null && final != null
              ? `${Math.round(inicial)}% → ${Math.round(final)}%`
              : '—'}
          </dd>
        </div>
        <div>
          <dt className="eyebrow text-[10px]">Origem</dt>
          <dd className="mt-0.5 text-sm capitalize text-mute">{s.origem || '—'}</dd>
        </div>
      </dl>
    </div>
  )
}

function HistoricoPage({ sessao }) {
  const usuarioId = sessao.usuario.id

  const [sessoes, setSessoes] = useState([])
  const [carregando, setCarregando] = useState(true)

  useEffect(() => {
    let cancelado = false

    async function carregar() {
      const { data } = await supabase
        .from('sessoes_recarga')
        .select('*, carregadores(numero, modelo), veiculos(modelo, placa)')
        .eq('usuario_id', usuarioId)
        .in('status', ['finalizada', 'cancelada'])
        .order('iniciado_em', { ascending: false })
        .limit(100)

      if (cancelado) return
      setSessoes(data || [])
      setCarregando(false)
    }

    carregar()
    return () => {
      cancelado = true
    }
  }, [usuarioId])

  return (
    <div>
      <div className="mb-8">
        <h2 className="text-xl font-semibold tracking-tight text-ink lg:text-[1.375rem]">
          Histórico de Recargas
        </h2>
        <p className="mt-1 text-sm text-dim">Todas as suas recargas concluídas neste condomínio.</p>
      </div>

      {carregando ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="skeleton h-28 rounded-panel" />
          ))}
        </div>
      ) : sessoes.length === 0 ? (
        <div className="rounded-panel border border-dashed border-line bg-panel/40 px-6 py-16 text-center">
          <p className="font-medium text-ink">Nenhuma recarga concluída ainda</p>
          <p className="mx-auto mt-1.5 max-w-[40ch] text-sm leading-relaxed text-dim">
            Assim que você finalizar uma recarga no Dashboard, ela aparece aqui com energia,
            duração e custo.
          </p>
        </div>
      ) : (
        <>
          <Resumo sessoes={sessoes} />
          <div className="overflow-hidden rounded-panel border border-line bg-panel">
            {sessoes.map((s) => (
              <LinhaSessao key={s.id} s={s} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export default HistoricoPage
