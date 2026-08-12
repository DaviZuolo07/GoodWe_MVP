function ConfirmarStopModal({ onCancelar, onConfirmar, carregando }) {
  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-neutral-900 border border-neutral-800 rounded-2xl w-full max-w-sm p-6 text-center">
        <p className="text-white font-medium mb-2">Encerrar recarga?</p>
        <p className="text-sm text-neutral-400 mb-6">
          Tem certeza que deseja encerrar o carregamento sem completar a recarga?
        </p>
        <div className="flex gap-3">
          <button
            onClick={onCancelar}
            className="flex-1 bg-neutral-800 hover:bg-neutral-700 rounded-lg py-2 font-medium transition"
          >
            Cancelar
          </button>
          <button
            onClick={onConfirmar}
            disabled={carregando}
            className="flex-1 bg-red-500 hover:bg-red-600 disabled:opacity-50 rounded-lg py-2 font-medium transition"
          >
            {carregando ? 'Encerrando...' : 'Sim, encerrar'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ConfirmarStopModal
