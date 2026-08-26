import { useCallback, useEffect, useRef, useState } from 'react'
import { API_URL } from '../config.js'
import { supabase } from '../supabaseClient.js'

/**
 * Modal de início de recarga.
 *
 * A ORDEM DAS ETAPAS MUDOU
 * ------------------------
 * Antes: cartão (simulado, um clique) -> bateria -> confirmar -> inicia.
 * O cartão era decoração; quem iniciava a recarga era o botão.
 *
 * Agora: bateria e alvo -> confirmar -> ESPERA o cartão físico -> inicia.
 * Quem decide é a aproximação do cartão no ESP32. O botão só prepara.
 *
 * COMO A TELA DESCOBRE O QUE ACONTECEU
 * ------------------------------------
 * O cartão é lido pelo ESP32, que fala com o backend. O navegador não está
 * nessa conversa - se a autorização falhar por saldo, o erro acontece num
 * canal onde o morador não está ouvindo.
 *
 * Por isso a tela não espera resposta de requisição nenhuma: ela se inscreve
 * no Realtime da LINHA da sessão. Sucesso, recusa por saldo e expiração
 * chegam todos como UPDATE naquela linha. O banco é o canal de retorno.
 */

const ETAPAS = {
  BATERIA: 'bateria',
  CONFIRMAR: 'confirmar',
  AGUARDANDO: 'aguardando',
  RECUSADO: 'recusado',
}

function PagamentoModal({ charger, sessao, veiculos, onClose, onSucesso, onIrParaCarteira }) {
  const { usuario } = sessao

  const [veiculoId, setVeiculoId] = useState(veiculos[0]?.id || '')
  const [etapa, setEtapa] = useState(ETAPAS.BATERIA)
  const [percentual, setPercentual] = useState(20)
  const [alvo, setAlvo] = useState(100)
  const [erro, setErro] = useState('')
  const [carregando, setCarregando] = useState(false)

  const [sessaoPreparada, setSessaoPreparada] = useState(null)
  const [segundos, setSegundos] = useState(0)
  const [motivoRecusa, setMotivoRecusa] = useState('')

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

  // ---------------------------------------------------------------------
  // Etapa 1 — preparar: cria a sessão parada esperando o cartão
  // ---------------------------------------------------------------------
  async function prepararRecarga() {
    setErro('')
    setCarregando(true)
    try {
      const res = await fetch(`${API_URL}/charge/preparar-rfid`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          charger_id: charger.id,
          usuario_id: usuario.id,
          veiculo_id: veiculoId,
          percentual_bateria_atual: Number(percentual),
          alvo_percentual: Number(alvo),
        }),
      })
      const data = await res.json()

      if (!res.ok) {
        // Cobre saldo insuficiente (402), ponto offline (503), carregador já
        // aguardando outro morador (409) e concorrência de veículo.
        setErro(data.detail || 'Não foi possível preparar a recarga.')
        return
      }

      setSessaoPreparada(data.sessao)
      setSegundos(data.segundos_para_aproximar || 120)
      setEtapa(ETAPAS.AGUARDANDO)
    } catch {
      setErro('Não foi possível conectar ao servidor.')
    } finally {
      setCarregando(false)
    }
  }

  // ---------------------------------------------------------------------
  // Etapa 2 — escutar a linha da sessão até ela mudar de estado
  // ---------------------------------------------------------------------
  useEffect(() => {
    if (etapa !== ETAPAS.AGUARDANDO || !sessaoPreparada?.id) return

    const canal = supabase
      .channel(`espera-cartao-${sessaoPreparada.id}`)
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'sessoes_recarga',
          filter: `id=eq.${sessaoPreparada.id}`,
        },
        (evento) => {
          const nova = evento.new
          if (nova.status === 'carregando') {
            // O ESP32 leu o cartão e o backend autorizou. O saldo já foi
            // debitado lá; aqui só refletimos na tela.
            onSucesso(Number((usuario.saldo - (nova.custo_estimado || 0)).toFixed(2)))
          } else if (nova.status === 'recusada') {
            setMotivoRecusa(nova.motivo_recusa || 'Saldo insuficiente para esta recarga.')
            setEtapa(ETAPAS.RECUSADO)
          } else if (nova.status === 'cancelada') {
            setMotivoRecusa(
              nova.motivo_recusa === 'tempo_esgotado'
                ? 'O tempo para aproximar o cartão se esgotou.'
                : 'A recarga foi cancelada.',
            )
            setEtapa(ETAPAS.RECUSADO)
          }
        },
      )
      .subscribe()

    return () => {
      supabase.removeChannel(canal)
    }
  }, [etapa, sessaoPreparada, usuario.saldo, onSucesso])

  // Contagem regressiva. É só informativa — quem cancela de verdade é o
  // backend, no laço que roda a cada 10s. Duas fontes de verdade para o mesmo
  // prazo dariam divergência; aqui o relógio é enfeite honesto.
  useEffect(() => {
    if (etapa !== ETAPAS.AGUARDANDO) return
    const t = setInterval(() => setSegundos((s) => Math.max(0, s - 1)), 1000)
    return () => clearInterval(t)
  }, [etapa])

  const cancelarEspera = useCallback(async () => {
    if (!sessaoPreparada?.id) return
    try {
      await fetch(`${API_URL}/charge/cancelar-rfid`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessao_id: sessaoPreparada.id, usuario_id: usuario.id }),
      })
    } catch {
      /* fechar mesmo assim: o prazo expira sozinho no backend */
    }
    onClose()
  }, [sessaoPreparada, usuario.id, onClose])

  // Fechar no X durante a espera precisa cancelar, senão o ponto fica preso
  // até o prazo vencer.
  const fechar = etapa === ETAPAS.AGUARDANDO ? cancelarEspera : onClose

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
          <button onClick={fechar} className="text-dim hover:text-ink">✕</button>
        </div>

        {erro && (
          <div className="bg-flux/10 border border-flux/40 text-flux text-sm rounded-lg px-3 py-2 mb-4">
            {erro}
          </div>
        )}

        {veiculos.length > 1 && etapa === ETAPAS.BATERIA && (
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

        {etapa === ETAPAS.BATERIA && (
          <div>
            <p className="text-sm text-mute mb-2">Qual a % de bateria atual do veículo?</p>
            <input
              type="number"
              min="0"
              max="99"
              value={percentual}
              onChange={(e) => setPercentual(e.target.value)}
              className="w-full bg-raise border border-line rounded-lg px-4 py-2 text-ink mb-4"
            />

            <p className="text-sm text-mute mb-2">Carregar até quanto?</p>
            <div className="mb-2 flex gap-2">
              {[80, 90, 100].map((v) => (
                <button
                  key={v}
                  onClick={() => setAlvo(v)}
                  className={`flex-1 rounded-lg py-2 text-sm transition ${
                    Number(alvo) === v
                      ? 'bg-flux text-white'
                      : 'bg-raise text-mute hover:bg-line'
                  }`}
                >
                  {v}%
                </button>
              ))}
            </div>
            <p className="mb-4 text-xs text-dim">
              Parar em 80% carrega bem mais rápido: acima disso a bateria aceita
              cada vez menos potência.
            </p>

            <button
              onClick={() => {
                if (Number(alvo) <= Number(percentual)) {
                  setErro('O alvo precisa ser maior que a bateria atual.')
                  return
                }
                setErro('')
                setEtapa(ETAPAS.CONFIRMAR)
              }}
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
                <span className="text-dim">Carregar</span>
                <span className="text-ink">{percentual}% → {alvo}%</span>
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
                onClick={prepararRecarga}
                disabled={carregando || !estimativa}
                className="w-full bg-flux hover:bg-flare disabled:opacity-50 rounded-lg py-2 font-medium transition"
              >
                {carregando ? 'Preparando...' : 'Confirmar e aproximar cartão'}
              </button>
            )}
          </div>
        )}

        {etapa === ETAPAS.AGUARDANDO && (
          <div className="py-4 text-center">
            <div className="relative mx-auto mb-5 flex h-20 w-20 items-center justify-center">
              <span
                className="absolute inset-0 rounded-full border-2 border-flux/40"
                style={{ animation: 'gw-ping 1.6s ease-out infinite' }}
              />
              <span className="flex h-16 w-16 items-center justify-center rounded-full border-2 border-flux text-flux">
                <svg viewBox="0 0 24 24" className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                  <rect x="3" y="6" width="18" height="12" rx="2" />
                  <path d="M14 10.5a3 3 0 0 1 0 3M16.5 8.5a6 6 0 0 1 0 7" />
                </svg>
              </span>
            </div>

            <p className="mb-1 font-medium text-ink">Aproxime seu cartão do leitor</p>
            <p className="mb-5 text-xs text-dim">
              A recarga só começa depois da leitura no carregador {charger.numero}.
            </p>

            <div className="mb-5 rounded-lg bg-raise/50 px-4 py-3 text-sm">
              <div className="flex justify-between">
                <span className="text-dim">Será debitado</span>
                <span className="text-ink">R$ {custoEstimado.toFixed(2)}</span>
              </div>
              <div className="mt-1 flex justify-between">
                <span className="text-dim">Tempo para aproximar</span>
                <span className={segundos <= 20 ? 'text-flux' : 'text-mute'}>
                  {Math.floor(segundos / 60)}:{String(segundos % 60).padStart(2, '0')}
                </span>
              </div>
            </div>

            <button
              onClick={cancelarEspera}
              className="w-full rounded-lg bg-raise py-2 font-medium text-mute transition hover:bg-line hover:text-ink"
            >
              Cancelar
            </button>
          </div>
        )}

        {etapa === ETAPAS.RECUSADO && (
          <div className="py-4 text-center">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full border-2 border-flux text-flux">
              <svg viewBox="0 0 24 24" className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <path d="M12 8v5M12 16.5v.01" />
                <circle cx="12" cy="12" r="9" />
              </svg>
            </div>

            <p className="mb-1 font-medium text-ink">Recarga não autorizada</p>
            <p className="mb-5 text-sm text-dim">{motivoRecusa}</p>

            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="flex-1 rounded-lg bg-raise py-2 font-medium text-mute transition hover:bg-line hover:text-ink"
              >
                Fechar
              </button>
              <button
                onClick={onIrParaCarteira}
                className="flex-1 rounded-lg bg-flux py-2 font-medium text-white transition hover:bg-flare"
              >
                Adicionar saldo
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default PagamentoModal
