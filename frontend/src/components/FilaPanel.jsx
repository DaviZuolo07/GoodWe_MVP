import { useCallback, useEffect, useId, useState } from 'react'
import { supabase } from '../supabaseClient.js'
import { API_URL } from '../config.js'

/**
 * Fila de espera de um carregador ocupado.
 *
 * Mostra o que dá para saber de verdade: quem está carregando, em quantos
 * por cento está, e quanto falta pela estimativa do backend (que já considera
 * curva de carga e temperatura).
 *
 * O que NÃO fazemos: prever o tempo das posições 2 em diante. Isso dependeria
 * do carro da pessoa e do quanto de bateria ela precisa - dados que só
 * existem quando ela pluga. Inventar um número ali seria mentir com precisão.
 */

function minutos(min) {
  if (min == null) return '—'
  if (min < 60) return `${min} min`
  return `${Math.floor(min / 60)}h ${String(min % 60).padStart(2, '0')}m`
}

function FilaPanel({ charger, sessaoAtiva, usuarioId }) {
  // Este painel aparece duas vezes na árvore: na coluna lateral (xl) e no
  // fluxo (abaixo de xl). O CSS esconde uma, mas o React monta as duas — e o
  // supabase-js lança exceção se dois canais assinarem o mesmo tópico. Por
  // isso o tópico carrega um id único por instância.
  const instancia = useId().replace(/:/g, '')
  const [fila, setFila] = useState([])
  const [carregando, setCarregando] = useState(true)
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState('')

  const carregarFila = useCallback(async () => {
    const { data } = await supabase
      .from('fila')
      .select('*, usuarios(nome)')
      .eq('carregador_id', charger.id)
      .order('posicao')

    setFila(data || [])
    setCarregando(false)
  }, [charger.id])

  useEffect(() => {
    carregarFila()

    const canal = supabase
      .channel(`fila-${charger.id}-${instancia}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'fila' }, carregarFila)
      .subscribe()

    return () => {
      supabase.removeChannel(canal)
    }
  }, [carregarFila, charger.id, instancia])

  const minhaPosicao = fila.find((f) => f.usuario_id === usuarioId)?.posicao || null

  async function acao(caminho) {
    setErro('')
    setEnviando(true)
    try {
      const res = await fetch(`${API_URL}/fila/${caminho}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ charger_id: charger.id, usuario_id: usuarioId }),
      })
      const data = await res.json()
      if (!res.ok) {
        setErro(data.detail || 'Não foi possível atualizar a fila.')
        return
      }
      carregarFila()
    } catch {
      setErro('Não foi possível conectar ao servidor.')
    } finally {
      setEnviando(false)
    }
  }

  const soc = Math.round(sessaoAtiva?.percentual_bateria_atual || 0)

  return (
    <div className="space-y-5">
      {/* Quem está usando agora */}
      {sessaoAtiva ? (
        <div className="rounded-panel border border-line bg-raise/40 p-4">
          <p className="eyebrow mb-3">Em recarga agora</p>

          <p className="truncate font-medium text-ink">
            {sessaoAtiva.veiculos?.modelo || 'Veículo'}
          </p>
          <p className="num mb-3 text-xs text-dim">{sessaoAtiva.veiculos?.placa || '—'}</p>

          <div className="mb-3 flex items-center gap-3">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-panel">
              <div
                className="flux-bar h-full rounded-full transition-[width] duration-700 ease-out"
                style={{ width: `${soc}%` }}
              />
            </div>
            <span className="num text-sm font-semibold text-ink">{soc}%</span>
          </div>

          <div className="flex items-baseline justify-between border-t border-hair pt-3">
            <span className="text-xs text-dim">Libera em aproximadamente</span>
            <span className="num text-sm font-semibold text-ink">
              {minutos(sessaoAtiva.tempo_estimado_min)}
            </span>
          </div>
        </div>
      ) : (
        <div className="rounded-panel border border-dashed border-line px-4 py-6 text-center">
          <p className="text-sm text-mute">Ninguém carregando neste ponto agora.</p>
        </div>
      )}

      {/* A fila */}
      <div>
        <div className="mb-3 flex items-baseline justify-between">
          <p className="eyebrow">Fila de espera</p>
          <span className="num text-xs text-dim">
            {fila.length} {fila.length === 1 ? 'pessoa' : 'pessoas'}
          </span>
        </div>

        {carregando ? (
          <div className="skeleton h-16 rounded-panel" />
        ) : fila.length === 0 ? (
          <p className="rounded-panel border border-dashed border-line px-4 py-5 text-center text-sm text-dim">
            Fila vazia. Você seria o primeiro.
          </p>
        ) : (
          <ol className="space-y-2">
            {fila.map((f) => {
              const meu = f.usuario_id === usuarioId
              return (
                <li
                  key={f.id}
                  className={`flex items-center gap-3 rounded-chip border px-3.5 py-2.5 ${
                    meu ? 'border-flux/40 bg-flux/10' : 'border-hair bg-raise/30'
                  }`}
                >
                  <span
                    className={`num flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-xs font-semibold ${
                      meu ? 'bg-flux text-white' : 'bg-panel text-mute'
                    }`}
                  >
                    {f.posicao}
                  </span>
                  <span className={`truncate text-sm ${meu ? 'text-ink' : 'text-mute'}`}>
                    {meu ? 'Você' : f.usuarios?.nome || 'Morador'}
                  </span>
                </li>
              )
            })}
          </ol>
        )}
      </div>

      {erro && (
        <p className="rounded-chip border border-flux/30 bg-flux/10 px-3 py-2 text-xs text-flux">
          {erro}
        </p>
      )}

      {/* Ação */}
      {minhaPosicao ? (
        <div className="space-y-3">
          <div className="rounded-chip border border-live/25 bg-live/10 px-4 py-3">
            <p className="text-sm text-ink">
              Você é o <span className="num font-semibold">{minhaPosicao}º</span> da fila.
            </p>
            <p className="mt-1 text-xs leading-relaxed text-dim">
              {minhaPosicao === 1
                ? 'Assim que este carregador liberar, você recebe uma notificação.'
                : 'O tempo das posições seguintes depende de quanto cada carro precisa carregar.'}
            </p>
          </div>

          <button
            type="button"
            onClick={() => acao('sair')}
            disabled={enviando}
            className="w-full rounded-chip border border-line bg-panel px-5 py-2.5 text-sm text-mute
                       transition-colors duration-200 hover:border-flux/40 hover:bg-flux/10 hover:text-flux
                       disabled:opacity-40"
          >
            {enviando ? 'Saindo...' : 'Sair da fila'}
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => acao('entrar')}
          disabled={enviando}
          className="w-full rounded-chip bg-flux px-5 py-3 text-sm font-medium text-white
                     transition-all duration-200 hover:bg-flare hover:shadow-flux
                     active:scale-[0.99] disabled:opacity-40"
        >
          {enviando ? 'Entrando...' : 'Entrar na fila de espera'}
        </button>
      )}
    </div>
  )
}

export default FilaPanel
