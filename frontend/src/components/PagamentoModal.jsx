import { useEffect, useState } from 'react'
import { API_URL } from '../config.js'

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

  // A prévia vem do backend, não de uma conta paralela aqui.
  // O cálculo real considera curva de carga (a bateria desacelera depois dos
  // 80%), derating térmico do carregador e perdas de conversão — replicar
  // isso no frontend garantiria divergência entre o que se mostra e o que se
  // cobra. Uma conta, um dono.
  const [estimativa, setEstimativa] = useState(null)
  const [calculando, setCalculando] = useState(false)

  useEffect(() => {
    if (etapa !== ETAPAS.CONFIRMAR || !veiculo) return

    let cancelado = false
    setCalculando(true)

    async function calcular() {
      try {
        const res = await fetch(`${API_URL}/charge/preview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            charger_id: charger.id,
            veiculo_id: veiculo.id,
            percentual_bateria_atual: Number(percentual),
          }),
        })
        const data = await res.json()
        if (!cancelado && res.ok) setEstimativa(data)
      } catch {
        if (!cancelado) setErro('Não foi possível calcular a prévia.')
      } finally {
        if (!cancelado) setCalculando(false)
      }
    }

    calcular()
    return () => {
      cancelado = true
    }
  }, [etapa, veiculo, charger.id, percentual])

  const energiaNecessaria = estimativa?.energia_necessaria_kwh ?? 0
  const tempoEstimadoMin = estimativa?.tempo_estimado_min ?? 0
  const custoEstimado = estimativa?.custo_estimado ?? 0
  const temperatura = estimativa?.temperatura_c
  const comDerating = estimativa?.fator_termico != null && estimativa.fator_termico < 1

  const saldoInsuficiente = estimativa != null && usuario.saldo < custoEstimado

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
      <div className="fixed inset-0 bg-void/80 flex items-center justify-center z-50 p-4">
        <div className="bg-panel border border-line rounded-2xl w-full max-w-sm p-6 text-center">
          <p className="text-ink mb-4">Você ainda não tem nenhum veículo cadastrado.</p>
          <button onClick={onClose} className="bg-raise hover:bg-raise rounded-lg py-2 px-4">
            Fechar
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 bg-void/80 flex items-center justify-center z-50 p-4">
      <div className="bg-panel border border-line rounded-2xl w-full max-w-sm p-6">
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-ink">Carregador {charger.numero}</h3>
          <button onClick={onClose} className="text-dim hover:text-ink">✕</button>
        </div>

        {erro && (
          <div className="bg-flux/10 border border-flux/40 text-flux text-sm rounded-lg px-3 py-2 mb-4">
            {erro}
          </div>
        )}

        {veiculos.length > 1 && etapa !== ETAPAS.CONFIRMAR && (
          <div className="mb-4">
            <label className="text-sm text-mute mb-1 block">Qual veículo?</label>
            <select
              className="w-full bg-raise border border-line rounded-lg px-3 py-2 text-ink"
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
            <div className="w-16 h-16 mx-auto mb-4 rounded-full border-2 border-flux flex items-center justify-center text-2xl">
              📶
            </div>
            <p className="text-ink mb-1">Aproxime seu cartão RFID</p>
            <p className="text-xs text-dim mb-6">Simulação — clique para aproximar</p>
            <button
              onClick={() => setEtapa(ETAPAS.BATERIA)}
              className="w-full bg-flux hover:bg-flare rounded-lg py-2 font-medium transition"
            >
              Aproximar cartão
            </button>
          </div>
        )}

        {etapa === ETAPAS.BATERIA && (
          <div>
            <p className="text-sm text-mute mb-2">Qual a % de bateria atual do veículo?</p>
            <input
              type="number"
              min="0"
              max="100"
              value={percentual}
              onChange={(e) => setPercentual(e.target.value)}
              className="w-full bg-raise border border-line rounded-lg px-4 py-2 text-ink mb-4"
            />
            <button
              onClick={() => setEtapa(ETAPAS.CONFIRMAR)}
              className="w-full bg-flux hover:bg-flare rounded-lg py-2 font-medium transition"
            >
              Continuar
            </button>
          </div>
        )}

        {etapa === ETAPAS.CONFIRMAR && (
          <div>
            <div className="bg-raise/50 rounded-lg p-4 mb-4 space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-dim">Veículo</span>
                <span className="text-ink">{veiculo.modelo}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-dim">Energia necessária</span>
                <span className="text-ink">{energiaNecessaria.toFixed(2)} kWh</span>
              </div>
              <div className="flex justify-between">
                <span className="text-dim">Tempo estimado</span>
                <span className="text-ink">
                  {tempoEstimadoMin < 60
                    ? `${tempoEstimadoMin} min`
                    : `${Math.floor(tempoEstimadoMin / 60)}h ${String(tempoEstimadoMin % 60).padStart(2, '0')}m`}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-dim">Custo estimado</span>
                <span className="text-ink">R$ {custoEstimado.toFixed(2)}</span>
              </div>
              <hr className="border-line" />
              <div className="flex justify-between">
                <span className="text-dim">Seu saldo</span>
                <span className={saldoInsuficiente ? 'text-flux' : 'text-live'}>
                  R$ {usuario.saldo.toFixed(2)}
                </span>
              </div>
            </div>

            {comDerating && (
              <p className="mb-3 rounded-lg border border-queue/30 bg-queue/10 px-3 py-2 text-xs text-queue">
                Carregador a {Number(temperatura).toFixed(0)}°C — a potência foi reduzida para
                proteger o equipamento, então o tempo estimado subiu.
              </p>
            )}

            {calculando && !estimativa ? (
              <p className="py-2 text-center text-sm text-dim">Calculando...</p>
            ) : saldoInsuficiente ? (
              <div>
                <p className="text-xs text-flux mb-3">Saldo insuficiente para essa recarga.</p>
                <button
                  onClick={onIrParaCarteira}
                  className="w-full bg-raise hover:bg-line rounded-lg py-2 font-medium transition"
                >
                  Ir para Carteira
                </button>
              </div>
            ) : (
              <button
                onClick={confirmarRecarga}
                disabled={carregando || !estimativa}
                className="w-full bg-flux hover:bg-flare disabled:opacity-50 rounded-lg py-2 font-medium transition"
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
