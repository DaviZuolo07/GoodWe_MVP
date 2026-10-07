import { useEffect, useRef, useState } from 'react'
import { post } from '../lib/api.js'
import { num, potencia } from '../lib/formato.js'

/**
 * "E se N carros ligarem juntos?" — POST /gestor/simular-demanda.
 *
 * O backend roda o MESMO distribuir() da operação real e não grava nada.
 * Esta tela só escolhe o cenário e desenha a resposta: quantos entram, com
 * quantos kW cada um, quantos esperam e o pico evitado. A única "conta" aqui
 * é a escala das barras do desenho.
 *
 * Recalcula quando o controle para de mexer (220 ms), e descarta respostas
 * que chegam fora de ordem — arrastar o slider rápido não pode deixar na
 * tela o resultado de um cenário antigo.
 */

const POTENCIAS = [
  { kw: 3.7, rotulo: '3,7 kW', dica: 'tomada monofásica' },
  { kw: 7.4, rotulo: '7,4 kW', dica: 'wallbox residencial' },
  { kw: 11, rotulo: '11 kW', dica: 'wallbox trifásico' },
]

function BarraComparacao({ rotulo, valor, escala, tipo }) {
  const largura = escala > 0 ? Math.min(100, (Number(valor) / escala) * 100) : 0
  return (
    <div className="grid grid-cols-[var(--rot)_1fr_var(--val)] items-center gap-3">
      <span className="text-xs text-mute">{rotulo}</span>
      <div className="h-5 overflow-hidden rounded-[5px] bg-raise">
        {tipo === 'hipotetico' ? (
          <div className="h-full rounded-[5px] border border-dashed border-mute/70 transition-[width] duration-500"
               style={{
                 width: `${largura}%`,
                 backgroundImage: 'repeating-linear-gradient(45deg, color-mix(in oklab, var(--color-mute) 45%, transparent) 0 1.5px, transparent 1.5px 6px)',
               }} />
        ) : (
          <div className="h-full rounded-[5px] bg-flux transition-[width] duration-500" style={{ width: `${largura}%` }} />
        )}
      </div>
      <span className="num text-right text-sm text-ink">{potencia(valor)}</span>
    </div>
  )
}

function SimuladorDemanda({ limiteKw }) {
  const [carros, setCarros] = useState(6)
  const [potenciaCarro, setPotenciaCarro] = useState(7.4)
  const [emPonta, setEmPonta] = useState(false)
  const [resultado, setResultado] = useState(null)
  const [calculando, setCalculando] = useState(false)
  const [erro, setErro] = useState('')
  const pedido = useRef(0)

  useEffect(() => {
    const meu = ++pedido.current
    const t = setTimeout(async () => {
      setCalculando(true)
      setErro('')
      try {
        const r = await post('/gestor/simular-demanda', {
          carros, potencia_carro_kw: potenciaCarro, em_ponta: emPonta,
        })
        if (meu === pedido.current) setResultado(r)
      } catch (e) {
        if (meu === pedido.current) setErro(e.message)
      } finally {
        if (meu === pedido.current) setCalculando(false)
      }
    }, 220)
    return () => clearTimeout(t)
  }, [carros, potenciaCarro, emPonta])

  const r = resultado
  const escala = r ? Math.max(Number(r.pico_sem_gestao_kw) || 0, Number(r.limite_kw) || 0) * 1.05 : 1
  const posLimite = r && escala > 0 ? Math.min(100, (Number(r.limite_kw) / escala) * 100) : 0

  return (
    <section id="simulador" className="mb-5 scroll-mt-28 overflow-hidden rounded-panel border border-line bg-panel">
      <div className="px-5 pb-4 pt-5">
        <h3 className="text-lg font-semibold tracking-tight text-ink">Simulador: e se vários carros ligarem juntos?</h3>
        <p className="mt-1 max-w-[64ch] text-sm leading-relaxed text-mute">
          Roda o mesmo algoritmo que divide a potência na operação real, com o limite deste condomínio
          {limiteKw ? <> (<span className="num">{potencia(limiteKw)}</span>)</> : null}. Nada é gravado.
        </p>
      </div>

      <div className="grid gap-0 border-t border-hair lg:grid-cols-[minmax(0,20rem)_1fr]">
        {/* Controles */}
        <div className="space-y-5 border-b border-hair px-5 py-5 lg:border-b-0 lg:border-r">
          <div>
            <div className="mb-2 flex items-baseline justify-between">
              <label htmlFor="sim-carros" className="text-sm text-mute">Carros carregando ao mesmo tempo</label>
              <span className="num text-2xl font-semibold text-ink">{carros}</span>
            </div>
            <input id="sim-carros" type="range" min="1" max="30" step="1" value={carros}
                   onChange={(e) => setCarros(Number(e.target.value))}
                   className="w-full accent-[var(--color-flux)]" />
            <div className="num mt-1 flex justify-between text-[0.6875rem] text-dim">
              <span>1</span><span>30</span>
            </div>
          </div>

          <fieldset>
            <legend className="mb-2 text-sm text-mute">Potência de cada carregador</legend>
            <div className="grid grid-cols-3 gap-1.5">
              {POTENCIAS.map((p) => (
                <button key={p.kw} type="button" onClick={() => setPotenciaCarro(p.kw)}
                        aria-pressed={potenciaCarro === p.kw} title={p.dica}
                        className={`num rounded-chip py-2 text-sm transition ${
                          potenciaCarro === p.kw ? 'bg-flux text-white' : 'bg-raise text-mute hover:bg-line hover:text-ink'}`}>
                  {p.rotulo}
                </button>
              ))}
            </div>
          </fieldset>

          <label className="flex cursor-pointer items-center justify-between gap-3 rounded-chip border border-line px-3 py-2.5">
            <span>
              <span className="block text-sm text-ink">Horário de ponta</span>
              <span className="block text-xs text-dim">O limite cai para a fração da ponta</span>
            </span>
            <span className="relative inline-flex">
              <input type="checkbox" checked={emPonta} onChange={(e) => setEmPonta(e.target.checked)}
                     className="peer sr-only" />
              <span className="h-6 w-11 rounded-full bg-raise ring-1 ring-line transition peer-checked:bg-queue
                               peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2
                               peer-focus-visible:outline-[var(--color-flux)]" />
              <span className="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-ink shadow transition peer-checked:translate-x-5" />
            </span>
          </label>
        </div>

        {/* Resultado */}
        <div className={`px-5 py-5 transition-opacity duration-200 ${calculando && r ? 'opacity-60' : ''}`} aria-live="polite">
          {erro && (
            <p className="mb-4 rounded-chip border border-flux/40 bg-flux/10 px-3 py-2 text-sm text-flux">{erro}</p>
          )}

          {!r ? (
            <div className="space-y-3">
              <div className="skeleton h-6 w-3/4 rounded-md" />
              <div className="skeleton h-5 w-full rounded-md" />
              <div className="skeleton h-5 w-full rounded-md" />
              <div className="skeleton h-16 w-full rounded-md" />
            </div>
          ) : (
            <>
              {/* A frase que resume o cenário */}
              <p className="text-base leading-relaxed text-ink">
                <span className="num">{r.carros}</span> {r.carros === 1 ? 'carro pedindo' : 'carros pedindo'}{' '}
                <span className="num">{potencia(r.potencia_carro_kw)}</span> somam{' '}
                <span className={`num font-semibold ${r.estouraria_limite ? 'text-queue' : ''}`}>
                  {potencia(r.pico_sem_gestao_kw)}
                </span>
                {r.estouraria_limite
                  ? <>, acima do limite de <span className="num">{potencia(r.limite_kw)}</span>.</>
                  : <>, dentro do limite de <span className="num">{potencia(r.limite_kw)}</span>.</>}
              </p>
              <p className="mt-1 text-sm leading-relaxed text-mute">
                {!r.estouraria_limite ? (
                  'Todos carregam na potência cheia. A gestão não precisa intervir.'
                ) : r.na_fila === 0 ? (
                  <>
                    Todos carregam, cada um com <span className="num text-ink">{potencia(r.kw_por_carro)}</span>{' '}
                    ({num((r.fracao_da_potencia_nominal || 0) * 100, 0)}% do nominal). O disjuntor não desarma.
                  </>
                ) : (
                  <>
                    <span className="num text-ink">{r.admitidos}</span> carregam com{' '}
                    <span className="num text-ink">{potencia(r.kw_por_carro)}</span> cada, e{' '}
                    <span className="num text-queue">{r.na_fila}</span> esperam na fila: abaixo de{' '}
                    <span className="num">{potencia(r.minimo_por_carro_kw)}</span> por carro a recarga não
                    avança de forma útil.
                  </>
                )}
              </p>

              {/* Sem × com gestão na mesma escala */}
              <div className="relative mt-5 space-y-2 [--rot:4.75rem] [--val:3.75rem] sm:[--rot:6.5rem] sm:[--val:4.5rem]">
                <BarraComparacao rotulo="Sem gestão" valor={r.pico_sem_gestao_kw} escala={escala}
                                 tipo="hipotetico" />
                <BarraComparacao rotulo="Com gestão" valor={r.pico_com_gestao_kw} escala={escala} tipo="real" />
                {/* Linha do limite atravessando as duas barras */}
                <div className="pointer-events-none absolute inset-y-[-6px] left-[calc(var(--rot)+0.75rem)] right-[calc(var(--val)+0.75rem)]">
                  <div className="absolute inset-y-0 w-0.5 bg-ink transition-[left] duration-500"
                       style={{ left: `${posLimite}%` }}>
                    <span className="num absolute -top-4 left-1/2 -translate-x-1/2 whitespace-nowrap text-[0.625rem] text-ink">
                      limite
                    </span>
                  </div>
                </div>
              </div>

              {/* Um bloco por carro: altura = fração da potência nominal que ele recebe */}
              <div className="mt-6">
                <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-mute">
                  <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-flux" /> carregando</span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm border border-dashed border-queue" /> na fila
                  </span>
                  <span className="text-dim">altura = parte da potência nominal que cada carro recebe</span>
                </div>
                <div className="flex h-16 items-end gap-1" role="img"
                     aria-label={`${r.admitidos} carros carregando, ${r.na_fila} na fila`}>
                  {Array.from({ length: r.carros }).map((_, i) => {
                    const admitido = i < r.admitidos
                    return (
                      <div key={i} className="relative h-full min-w-0 flex-1 max-w-8">
                        {admitido ? (
                          <>
                            <div className="absolute inset-0 rounded-[3px] bg-raise" />
                            <div className="absolute inset-x-0 bottom-0 rounded-[3px] bg-flux transition-[height] duration-500"
                                 style={{ height: `${Math.max(4, (r.fracao_da_potencia_nominal || 0) * 100)}%` }} />
                          </>
                        ) : (
                          <div className="absolute inset-x-0 bottom-0 h-1/3 rounded-[3px] border border-dashed border-queue/70" />
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>

              <dl className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-chip border border-hair bg-hair sm:grid-cols-4">
                {[
                  ['Carregando', num(r.admitidos, 0)],
                  ['Na fila', num(r.na_fila, 0), r.na_fila > 0 ? 'text-queue' : undefined],
                  ['Por carro', potencia(r.kw_por_carro)],
                  ['Pico evitado', potencia(r.excesso_evitado_kw), r.excesso_evitado_kw > 0 ? 'text-live' : undefined],
                ].map(([rotulo, valor, cor]) => (
                  <div key={rotulo} className="bg-panel px-3 py-2.5">
                    <dt className="text-[0.6875rem] text-dim">{rotulo}</dt>
                    <dd className={`num mt-0.5 text-base font-semibold ${cor || 'text-ink'}`}>{valor}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
        </div>
      </div>
    </section>
  )
}

export default SimuladorDemanda
