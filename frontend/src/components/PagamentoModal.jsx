import { useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL

const ETAPAS = {
  RFID: 'rfid',
  BATERIA: 'bateria',
  CONFIRMAR: 'confirmar',
}

function PagamentoModal({ charger, sessao, veiculos, onClose, onSucesso, onIrParaCarteira }) {
  const { usuario } = sessao

  const [veiculoId, setVeiculoId] = useState(veiculos[0]?.id || '')
  const [etapa, setEtapa] = useState(ETAPAS.RFID)
  const [percentual, setPercentual] = useState(20)
  const [erro, setErro] = useState('')
  const [carregando, setCarregando] = useState(false)

  const veiculo = veiculos.find((v) => v.id === veiculoId) || veiculos[0]

  const potenciaEfetiva = veiculo ? Math.min(charger.potencia_maxima_kw, veiculo.potencia_carro_kw) : 0
  const energiaNecessaria = veiculo ? veiculo.capacidade_bateria_kwh * (1 - percentual / 100) : 0
  const tempoEstimadoMin = potenciaEfetiva > 0 ? Math.round((energiaNecessaria / potenciaEfetiva) * 60) : 0
  const custoEstimado = Math.round(energiaNecessaria * charger.tarifa_kwh * 100) / 100

  const saldoInsuficiente = usuario.saldo < custoEstimado

  async function confirmarRecarga() {
    setErro('')
    setCarregando(true)
    try {
      const res = await fetch(`${API_URL}/charge/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          charger_id: charger.id,
          usuario_id: usuario.id,
          veiculo_id: veiculoId,
          percentual_bateria_atual: Number(percentual),
        }),
      })
      const data = await res.json()

      if (!res.ok) {
        // Cobre os dois casos de concorrência: carregador ocupado ou o
        // próprio veículo já carregando em outro lugar.
        setErro(data.detail || 'Não foi possível iniciar a recarga.')
        return
      }

      onSucesso(data.saldo_atual)
    } catch {
      setErro('Não foi possível conectar ao servidor.')
    } finally {
      setCarregando(false)
    }
  }

  if (!veiculo) {
    return (
      <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
        <div className="bg-neutral-900 border border-neutral-800 rounded-2xl w-full max-w-sm p-6 text-center">
          <p className="text-white mb-4">Você ainda não tem nenhum veículo cadastrado.</p>
          <button onClick={onClose} className="bg-neutral-800 hover:bg-neutral-700 rounded-lg py-2 px-4">
            Fechar
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-neutral-900 border border-neutral-800 rounded-2xl w-full max-w-sm p-6">
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-white">Carregador {charger.numero}</h3>
          <button onClick={onClose} className="text-neutral-500 hover:text-white">✕</button>
        </div>

        {erro && (
          <div className="bg-red-500/10 border border-red-500/40 text-red-400 text-sm rounded-lg px-3 py-2 mb-4">
            {erro}
          </div>
        )}

        {veiculos.length > 1 && etapa !== ETAPAS.CONFIRMAR && (
          <div className="mb-4">
            <label className="text-sm text-neutral-400 mb-1 block">Qual veículo?</label>
            <select
              className="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-white"
              value={veiculoId}
              onChange={(e) => setVeiculoId(e.target.value)}
            >
              {veiculos.map((v) => (
                <option key={v.id} value={v.id}>{v.modelo} {v.placa ? `- ${v.placa}` : ''}</option>
              ))}
            </select>
          </div>
        )}

        {etapa === ETAPAS.RFID && (
          <div className="text-center py-6">
            <div className="w-16 h-16 mx-auto mb-4 rounded-full border-2 border-red-500 flex items-center justify-center text-2xl">
              📶
            </div>
            <p className="text-white mb-1">Aproxime seu cartão RFID</p>
            <p className="text-xs text-neutral-500 mb-6">Simulação — clique para aproximar</p>
            <button
              onClick={() => setEtapa(ETAPAS.BATERIA)}
              className="w-full bg-red-500 hover:bg-red-600 rounded-lg py-2 font-medium transition"
            >
              Aproximar cartão
            </button>
          </div>
        )}

        {etapa === ETAPAS.BATERIA && (
          <div>
            <p className="text-sm text-neutral-400 mb-2">Qual a % de bateria atual do veículo?</p>
            <input
              type="number"
              min="0"
              max="100"
              value={percentual}
              onChange={(e) => setPercentual(e.target.value)}
              className="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-4 py-2 text-white mb-4"
            />
            <button
              onClick={() => setEtapa(ETAPAS.CONFIRMAR)}
              className="w-full bg-red-500 hover:bg-red-600 rounded-lg py-2 font-medium transition"
            >
              Continuar
            </button>
          </div>
        )}

        {etapa === ETAPAS.CONFIRMAR && (
          <div>
            <div className="bg-neutral-800/50 rounded-lg p-4 mb-4 space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-neutral-500">Veículo</span>
                <span className="text-white">{veiculo.modelo}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-500">Energia necessária</span>
                <span className="text-white">{energiaNecessaria.toFixed(2)} kWh</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-500">Tempo estimado</span>
                <span className="text-white">{tempoEstimadoMin} min</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-500">Custo estimado</span>
                <span className="text-white">R$ {custoEstimado.toFixed(2)}</span>
              </div>
              <hr className="border-neutral-700" />
              <div className="flex justify-between">
                <span className="text-neutral-500">Seu saldo</span>
                <span className={saldoInsuficiente ? 'text-red-400' : 'text-green-400'}>
                  R$ {usuario.saldo.toFixed(2)}
                </span>
              </div>
            </div>

            {saldoInsuficiente ? (
              <div>
                <p className="text-xs text-red-400 mb-3">Saldo insuficiente para essa recarga.</p>
                <button
                  onClick={onIrParaCarteira}
                  className="w-full bg-neutral-700 hover:bg-neutral-600 rounded-lg py-2 font-medium transition"
                >
                  Ir para Carteira
                </button>
              </div>
            ) : (
              <button
                onClick={confirmarRecarga}
                disabled={carregando}
                className="w-full bg-red-500 hover:bg-red-600 disabled:opacity-50 rounded-lg py-2 font-medium transition"
              >
                {carregando ? 'Iniciando...' : 'Confirmar pagamento e iniciar'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default PagamentoModal
