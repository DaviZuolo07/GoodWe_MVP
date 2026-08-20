import { memo } from 'react'
import ArteCarregador from './ArteCarregador.jsx'
import ArteVeiculo from './ArteVeiculo.jsx'

const STATUS = {
  disponivel: { label: 'Disponível', cor: 'text-live', dot: 'bg-live', borda: 'hover:border-live/50' },
  em_uso: { label: 'Em uso', cor: 'text-flux', dot: 'bg-flux', borda: 'hover:border-flux/50' },
  fila: { label: 'Fila', cor: 'text-queue', dot: 'bg-queue', borda: 'hover:border-queue/50' },
  offline: { label: 'Offline', cor: 'text-dim', dot: 'bg-off', borda: 'hover:border-line' },
}

/** 72 -> "1h 12m" | 58 -> "58 min" */
function tempo(min) {
  if (min == null) return '—'
  if (min < 60) return `${min} min`
  return `${Math.floor(min / 60)}h ${String(min % 60).padStart(2, '0')}m`
}

function ChargerCard({ charger, sessao, onSelecionar, selecionado = false }) {
  const st = STATUS[charger.status] || STATUS.offline
  const emUso = charger.status === 'em_uso'
  const bateria = Math.round(sessao?.percentual_bateria_atual || 0)
  const temperatura = Number(charger.temperatura_c)
  const quente = Number.isFinite(temperatura) && temperatura > 35

  return (
    <button
      type="button"
      onClick={() => onSelecionar(charger)}
      aria-pressed={selecionado}
      className={`sweep group relative w-full overflow-hidden rounded-panel border bg-panel p-5 text-left
        transition duration-200 ease-out will-change-transform
        hover:-translate-y-1 hover:bg-raise/50 hover:shadow-lift active:scale-[0.995]
        ${selecionado ? 'border-flux/70 shadow-flux' : `border-line ${st.borda}`}`}
    >
      {selecionado && <span className="bus" aria-hidden="true" />}

      <div className="relative flex items-start justify-between gap-3">
        <span className="num rounded-chip bg-raise px-2.5 py-1 text-sm font-semibold text-ink">
          {charger.numero}
        </span>

        <span className={`flex items-center gap-2 text-xs font-medium ${st.cor}`}>
          <span
            className={`h-2 w-2 rounded-full ${st.dot} ${emUso ? 'dot-live' : ''}`}
            style={emUso ? { color: 'var(--color-flux)' } : undefined}
          />
          {st.label}
        </span>
      </div>

      {/* Retrato: o carro quando há recarga, o equipamento quando está livre */}
      <div className="relative flex h-36 items-center justify-center py-2">
        {emUso && sessao ? (
          <ArteVeiculo modelo={sessao.veiculos?.modelo} className="h-28" />
        ) : (
          <ArteCarregador status={charger.status} modelo={charger.modelo} className="h-32" />
        )}

        {quente && (
          <span className="num absolute right-0 top-0 rounded-chip border border-queue/30 bg-queue/10 px-2 py-0.5 text-[11px] text-queue">
            {temperatura.toFixed(0)}°C
          </span>
        )}
      </div>

      {sessao ? (
        <div className="relative">
          <p className="truncate font-medium text-ink">{sessao.veiculos?.modelo || 'Veículo'}</p>
          <p className="num mb-3 text-xs text-dim">{sessao.veiculos?.placa || '—'}</p>

          <div className="mb-3 flex items-center gap-3">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-raise">
              <div
                className="flux-bar h-full rounded-full transition-[width] duration-700 ease-out"
                style={{ width: `${bateria}%` }}
              />
            </div>
            <span className="num text-sm font-semibold text-ink">{bateria}%</span>
          </div>

          <dl className="grid grid-cols-3 gap-2 border-t border-hair pt-3">
            <div>
              <dt className="eyebrow text-[10px]">Potência</dt>
              <dd className="num text-sm text-ink">{sessao.potencia_atual_kw} kW</dd>
            </div>
            <div>
              <dt className="eyebrow text-[10px]">Energia</dt>
              <dd className="num text-sm text-ink">
                {Number(sessao.energia_entregue_kwh || 0).toFixed(2)} kWh
              </dd>
            </div>
            <div>
              <dt className="eyebrow text-[10px]">Restante</dt>
              <dd className="num text-sm text-ink">{tempo(sessao.tempo_estimado_min)}</dd>
            </div>
          </dl>
        </div>
      ) : (
        <div className="relative">
          <p className="num text-lg font-semibold text-ink">
            {charger.tipo} {charger.potencia_maxima_kw} kW
          </p>
          <p className="mb-3 text-xs text-mute">{charger.conector}</p>

          <div className="flex items-center justify-between border-t border-hair pt-3">
            <span className="num text-xs text-dim">
              R$ {Number(charger.tarifa_kwh).toFixed(2)} / kWh
            </span>
            <span
              className={`flex items-center gap-1.5 text-xs font-medium transition-colors ${
                charger.status === 'disponivel' ? 'text-flux group-hover:text-flare' : 'text-dim'
              }`}
            >
              {charger.status === 'disponivel' ? 'Selecionar' : 'Aguardando liberação'}
              {charger.status === 'disponivel' && (
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-1"
                  aria-hidden="true"
                >
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              )}
            </span>
          </div>
        </div>
      )}
    </button>
  )
}

export default memo(ChargerCard)
