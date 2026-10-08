import { useCallback, useEffect, useState } from 'react'
import { get, post } from '../lib/api.js'
import { brl } from '../lib/formato.js'

/**
 * Carro esquecido na vaga (taxa de ociosidade, db/21).
 *
 * Quando a recarga num ponto simulado termina sozinha, a energia já foi
 * cobrada, mas o ponto continua ocupado até o morador avisar que tirou o
 * carro. Depois da tolerância corre uma taxa por minuto, com teto. Quem
 * calcula é o backend; aqui só mostramos e oferecemos o botão.
 *
 * Consulta a cada 15 s: o valor muda de minuto em minuto, e o aviso precisa
 * aparecer em qualquer página do app, não só no painel de carregadores.
 */

const INTERVALO_MS = 15000

function hora(iso) {
  return iso ? new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : ''
}

function AvisoVagaOcupada({ onLiberada }) {
  const [vaga, setVaga] = useState(null)
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState('')

  const consultar = useCallback(async () => {
    try {
      setVaga((await get('/recargas/vaga-ocupada')).vaga)
    } catch {
      // Sem a migration 21 ou sem rede: o aviso simplesmente não aparece.
    }
  }, [])

  useEffect(() => {
    consultar()
    const id = setInterval(consultar, INTERVALO_MS)
    return () => clearInterval(id)
  }, [consultar])

  if (!vaga) return null

  async function liberar() {
    setEnviando(true)
    setErro('')
    try {
      await post(`/recargas/${vaga.sessao_id}/liberar-vaga`)
      setVaga(null)
      onLiberada?.()
    } catch (e) {
      setErro(e.message)
    } finally {
      setEnviando(false)
    }
  }

  const correndo = vaga.valor > 0
  const noTeto = vaga.valor >= vaga.teto
  return (
    <div role="status"
         className={`mb-5 flex flex-wrap items-center justify-between gap-3 rounded-panel border px-4 py-3 text-sm
                     ${correndo ? 'border-flux/50 bg-flux/10' : 'border-queue/40 bg-queue/10'}`}>
      <div className="min-w-0">
        <p className={`font-medium ${correndo ? 'text-flux' : 'text-queue'}`}>
          {correndo
            ? `Taxa de ociosidade: ${brl(vaga.valor)}${noTeto ? ' (teto atingido)' : ''}`
            : `Carga completa no ponto ${vaga.carregador}. Retire o carro.`}
        </p>
        <p className="mt-0.5 text-mute">
          {correndo
            ? `Seu carro está no ponto ${vaga.carregador} há ${Math.round(vaga.minutos_parado)} min. `
            : `Sem custo até ${hora(vaga.cobra_a_partir_de)}. `}
          Depois da tolerância de {vaga.tolerancia_min} min: {brl(vaga.taxa_por_min)}/min, no máximo {brl(vaga.teto)}.
        </p>
        {erro && <p className="mt-1 text-flux">{erro}</p>}
      </div>
      <button type="button" onClick={liberar} disabled={enviando}
              className="shrink-0 rounded-chip bg-flux px-4 py-2 font-medium text-white transition-colors
                         hover:bg-flare disabled:opacity-60">
        {enviando ? 'Liberando…' : 'Já retirei o carro'}
      </button>
    </div>
  )
}

export default AvisoVagaOcupada
