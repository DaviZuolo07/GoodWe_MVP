function ConfirmarStopModal({ onCancelar, onConfirmar, carregando }) {
  return (
    <div className="fixed inset-0 bg-void/80 flex items-center justify-center z-50 p-4">
      <div className="bg-panel border border-line rounded-2xl w-full max-w-sm p-6 text-center">
        <p className="text-ink font-medium mb-2">Encerrar recarga?</p>
        <p className="text-sm text-mute mb-6">
          Tem certeza que deseja encerrar o carregamento sem completar a recarga?
        </p>
        <div className="flex gap-3">
          <button
            onClick={onCancelar}
            className="flex-1 bg-raise hover:bg-raise rounded-lg py-2 font-medium transition"
          >
            Cancelar
          </button>
          <button
            onClick={onConfirmar}
            disabled={carregando}
            className="flex-1 bg-flux hover:bg-flare disabled:opacity-50 rounded-lg py-2 font-medium transition"
          >
            {carregando ? 'Encerrando...' : 'Sim, encerrar'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ConfirmarStopModal
