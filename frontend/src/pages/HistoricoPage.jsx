import { useEffect, useState } from 'react'
import { supabase } from '../supabaseClient.js'
import { brl, energia as fmtEnergia } from '../lib/formato.js'
import ReciboModal from '../components/ReciboModal.jsx'

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
  recusada: { label: 'Recusada por saldo', cor: 'text-flux', borda: 'border-flux/25', fundo: 'bg-flux/10' },
}

/** Por que a recarga terminou - gravado pelo backend em `encerrado_por`. */
const MOTIVOS = {
  usuario: 'encerrada por você',
  alvo_atingido: 'alvo de carga atingido',
  bateria_cheia: 'bateria cheia',
  dispositivo_carregado: 'o dispositivo parou de puxar energia',
  limite_pre_autorizado: 'valor reservado atingido',
  dispositivo_offline: 'o ponto perdeu conexão',
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
  const total = sessoes.reduce((s, r) => s + Number(r.energia_entregue_kwh || 0), 0)
  const gasto = sessoes.reduce((s, r) => s + Number(r.custo_final ?? 0), 0)
  const estornado = sessoes.reduce((s, r) => s + Number(r.valor_estornado ?? 0), 0)

  const cards = [
    { label: 'Recargas realizadas', valor: String(sessoes.length) },
    { label: 'Energia total', valor: fmtEnergia(total) },
    { label: 'Total pago', valor: brl(gasto), sub: estornado > 0 ? `${brl(estornado)} estornados` : null },
  ]

  return (
    <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
      {cards.map((c) => (
        <div key={c.label} className="rounded-panel border border-line bg-panel p-5">
          <p className="eyebrow mb-2">{c.label}</p>
          <p className="num text-2xl font-semibold text-ink 2xl:text-3xl">{c.valor}</p>
          {c.sub && <p className="mt-1 text-xs text-dim">{c.sub}</p>}
        </div>
      ))}
    </div>
  )
}

function LinhaSessao({ s, onAbrir }) {
  const st = STATUS[s.status] || STATUS.cancelada
  const custo = Number(s.custo_final ?? s.custo_estimado ?? 0)
  const estorno = Number(s.valor_estornado ?? 0)
  const inicial = s.percentual_bateria_inicial
  const final = s.percentual_bateria_atual

  return (
    <button
      type="button"
      onClick={() => onAbrir(s.id)}
      aria-label={`Ver recibo da recarga no ponto ${s.carregadores?.numero || ''}`}
      className="sweep group relative block w-full overflow-hidden border-b border-hair px-5 py-4 text-left
                 transition-colors duration-200 last:border-0 hover:bg-raise/40 focus-visible:bg-raise/40"
    >
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

        <div className="shrink-0 text-right">
          <p className="num text-lg font-semibold text-ink">{brl(custo)}</p>
          {estorno > 0 && (
            <p className="num text-[0.6875rem] text-live">{brl(estorno)} estornados</p>
          )}
          {s.encerrado_por && MOTIVOS[s.encerrado_por] && (
            <p className="text-[0.6875rem] text-dim">{MOTIVOS[s.encerrado_por]}</p>
          )}
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <dt className="eyebrow text-[10px]">Energia</dt>
          <dd className="num mt-0.5 text-sm text-ink">{fmtEnergia(s.energia_entregue_kwh)}</dd>
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

      <p className="mt-3 flex items-center gap-1.5 text-xs font-medium text-mute transition-colors group-hover:text-flux">
        <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3z" /><path d="M9 8h6M9 12h6" />
        </svg>
        Ver recibo
      </p>
    </button>
  )
}

function HistoricoPage({ sessao }) {
  const usuarioId = sessao.usuario.id

  const [sessoes, setSessoes] = useState([])
  const [carregando, setCarregando] = useState(true)
  const [reciboId, setReciboId] = useState(null)

  useEffect(() => {
    let cancelado = false

    async function carregar() {
      const { data } = await supabase
        .from('sessoes_recarga')
        .select('*, carregadores(numero, modelo), veiculos(modelo, placa)')
        .eq('usuario_id', usuarioId)
        .in('status', ['finalizada', 'cancelada', 'recusada'])
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
        <p className="mt-1 text-sm text-dim">
          Suas recargas, com energia medida, custo real e o que foi estornado. Toque numa recarga para ver o recibo.
        </p>
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
              <LinhaSessao key={s.id} s={s} onAbrir={setReciboId} />
            ))}
          </div>
        </>
      )}

      {reciboId && <ReciboModal sessaoId={reciboId} onFechar={() => setReciboId(null)} />}
    </div>
  )
}

export default HistoricoPage
