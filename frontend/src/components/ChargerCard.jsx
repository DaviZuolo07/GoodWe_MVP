const STATUS_CONFIG = {
  disponivel: { label: 'Disponível', dot: 'bg-green-500', text: 'text-green-500' },
  em_uso: { label: 'Em uso', dot: 'bg-red-500', text: 'text-red-500' },
  fila: { label: 'Fila', dot: 'bg-amber-500', text: 'text-amber-500' },
  offline: { label: 'Offline', dot: 'bg-neutral-600', text: 'text-neutral-500' },
}

function ChargerCard({ charger, sessao, onSelecionar }) {
  const status = STATUS_CONFIG[charger.status] || STATUS_CONFIG.offline

  return (
    <button
      onClick={() => onSelecionar(charger)}
      className="text-left bg-neutral-900 border border-neutral-800 hover:border-red-500/50 rounded-xl p-4 transition"
    >
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-white bg-neutral-800 px-2 py-0.5 rounded">
          {charger.numero}
        </span>
        <span className={`flex items-center gap-1.5 text-xs font-medium ${status.text}`}>
          <span className={`w-2 h-2 rounded-full ${status.dot}`} />
          {status.label}
        </span>
      </div>

      {sessao ? (
        <div>
          <p className="font-medium text-white">{sessao.veiculos?.modelo || 'Veículo'}</p>
          <p className="text-xs text-neutral-500 mb-3">{sessao.veiculos?.placa}</p>

          <div className="w-full bg-neutral-800 rounded-full h-1.5 mb-3">
            <div
              className="bg-red-500 h-1.5 rounded-full transition-all"
              style={{ width: `${sessao.percentual_bateria_atual || 0}%` }}
            />
          </div>

          <div className="grid grid-cols-3 gap-2 text-xs text-neutral-400">
            <div>
              <p className="text-neutral-600">Potência</p>
              <p className="text-white">{sessao.potencia_atual_kw} kW</p>
            </div>
            <div>
              <p className="text-neutral-600">Energia</p>
              <p className="text-white">{sessao.energia_entregue_kwh?.toFixed(2)} kWh</p>
            </div>
            <div>
              <p className="text-neutral-600">Tempo</p>
              <p className="text-white">{sessao.tempo_estimado_min}m</p>
            </div>
          </div>
        </div>
      ) : (
        <div>
          <p className="text-sm text-white">{charger.tipo} {charger.potencia_maxima_kw}kW</p>
          <p className="text-xs text-neutral-500">{charger.conector}</p>
        </div>
      )}
    </button>
  )
}

export default ChargerCard
