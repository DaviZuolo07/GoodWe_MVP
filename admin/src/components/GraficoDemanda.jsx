import { useId, useState } from 'react'
import { potencia } from '../lib/formato.js'

/**
 * "Sem gestão × com gestão", hora a hora, no dia de hoje.
 *
 * Duas séries por hora, sobrepostas na mesma coluna:
 *   - demanda_kw  o que o prédio TERIA puxado se ninguém fosse limitado
 *                 (hipotético: contorno tracejado com hachura, tom fraco)
 *   - pico_kw     o que o prédio puxou DE FATO (real: barra sólida)
 * e uma linha horizontal no limite do quadro.
 *
 * O backend garante demanda_kw >= pico_kw. A área hachurada que sobra acima
 * da barra sólida É a gestão de demanda: potência que foi segurada para o
 * disjuntor não desarmar. Nada é calculado aqui além da escala do desenho.
 */

const L = 64   // margem esquerda (rótulos do eixo)
const R = 12
const T = 18
const B = 28
const W = 1000
const H = 340

/** Passo "redondo" (1, 2, 2,5 ou 5 × 10^n) para a grade do eixo — só desenho. */
function passoRedondo(bruto) {
  if (!(bruto > 0)) return 1
  const ordem = 10 ** Math.floor(Math.log10(bruto))
  const f = bruto / ordem
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * ordem
}

function horaDe(valor) {
  const n = Number(String(valor || '').slice(0, 2))
  return Number.isFinite(n) ? n : null
}

function GraficoDemanda({ porHora, limiteKw, limitePontaKw, pontaInicio, pontaFim, onAbrirSimulador }) {
  const idHachura = `hachura-${useId().replace(/:/g, '')}`
  const [foco, setFoco] = useState(null)

  const horas = porHora || []
  const maxSerie = Math.max(0, ...horas.map((h) => Number(h.demanda_kw) || 0), ...horas.map((h) => Number(h.pico_kw) || 0))
  const bruto = Math.max(Number(limiteKw) || 0, maxSerie) * 1.08
  const passoY = passoRedondo(bruto / 4)
  const topo = Math.max(passoY, Math.ceil(bruto / passoY) * passoY)
  const vazio = maxSerie === 0

  const larguraUtil = W - L - R
  const alturaUtil = H - T - B
  const passo = larguraUtil / 24
  const larguraBarra = Math.max(4, passo * 0.62)
  const y = (kw) => T + alturaUtil - (Math.max(0, kw) / topo) * alturaUtil
  const x = (hora) => L + hora * passo + (passo - larguraBarra) / 2

  const ini = horaDe(pontaInicio)
  const fim = horaDe(pontaFim)
  const temPonta = ini != null && fim != null && fim > ini

  const marcas = Array.from({ length: Math.round(topo / passoY) + 1 }, (_, i) => i * passoY)

  const h = foco != null ? horas.find((p) => p.hora === foco) : null

  return (
    <div>
      {/* Legenda */}
      <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-mute">
        <span className="flex items-center gap-2">
          <svg width="14" height="12" aria-hidden="true">
            <defs>
              <pattern id={`${idHachura}-l`} width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <line x1="0" y1="0" x2="0" y2="4" style={{ stroke: 'var(--color-mute)' }} strokeWidth="1.4" />
              </pattern>
            </defs>
            <rect x="0.5" y="0.5" width="13" height="11" rx="2" fill={`url(#${idHachura}-l)`}
                  style={{ stroke: 'var(--color-mute)' }} strokeDasharray="2 2" />
          </svg>
          sem gestão (hipotético)
        </span>
        <span className="flex items-center gap-2">
          <span className="h-3 w-3.5 rounded-[2px] bg-flux" /> com gestão (real)
        </span>
        <span className="flex items-center gap-2">
          <span className="h-0 w-4 border-t-2 border-ink" /> limite do quadro
        </span>
        {temPonta && (
          <span className="flex items-center gap-2">
            <span className="h-3 w-3.5 rounded-[2px] bg-queue/20" /> janela de ponta (dias úteis)
          </span>
        )}
      </div>

      {/* Abaixo de ~640px o gráfico rola na horizontal em vez de encolher até ficar ilegível */}
      <div className="scroll-slim -mx-1 overflow-x-auto px-1">
      <div className="relative min-w-[640px]">
        <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img"
             aria-label={`Potência por hora hoje. Limite do quadro ${potencia(limiteKw)}.`}
             onMouseLeave={() => setFoco(null)}>
          <defs>
            <pattern id={idHachura} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="6" style={{ stroke: 'var(--color-mute)' }} strokeWidth="1.6" strokeOpacity="0.55" />
            </pattern>
          </defs>

          {/* Janela de ponta */}
          {temPonta && (
            <rect x={L + ini * passo} y={T} width={(fim - ini) * passo} height={alturaUtil}
                  style={{ fill: 'var(--color-queue)' }} fillOpacity="0.08" />
          )}

          {/* Grade horizontal + rótulos */}
          {marcas.map((v, i) => (
            <g key={i}>
              <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} style={{ stroke: 'var(--color-hair)' }} strokeWidth="1" />
              <text x={L - 8} y={y(v) + 3.5} textAnchor="end" fontSize="12"
                    style={{ fill: 'var(--color-dim)', fontFamily: 'var(--font-mono)' }}>
                {v === 0 ? '0' : potencia(v, 1)}
              </text>
            </g>
          ))}

          {/* Barras */}
          {horas.map((p) => {
            const sem = Number(p.demanda_kw) || 0
            const com = Number(p.pico_kw) || 0
            const ativo = foco === p.hora
            return (
              <g key={p.hora}>
                {ativo && (
                  <rect x={L + p.hora * passo} y={T} width={passo} height={alturaUtil}
                        style={{ fill: 'var(--color-ink)' }} fillOpacity="0.05" />
                )}
                {/* Só o trecho que a gestão segurou: de pico_kw até demanda_kw */}
                {sem > com && (
                  <rect x={x(p.hora)} y={y(sem)} width={larguraBarra} height={Math.max(0, y(com) - y(sem))} rx="2"
                        fill={`url(#${idHachura})`} style={{ stroke: 'var(--color-mute)' }}
                        strokeOpacity="0.7" strokeDasharray="3 2.5" strokeWidth="1" />
                )}
                {com > 0 && (
                  <rect x={x(p.hora)} y={y(com)} width={larguraBarra} height={Math.max(0, y(0) - y(com))} rx="2"
                        style={{ fill: 'var(--color-flux)' }} />
                )}
                {/* Alvo de hover do tamanho da coluna inteira */}
                <rect x={L + p.hora * passo} y={T} width={passo} height={alturaUtil} fill="transparent"
                      onMouseEnter={() => setFoco(p.hora)} onFocus={() => setFoco(p.hora)}
                      tabIndex={vazio ? -1 : 0}
                      aria-label={`${p.hora}h: com gestão ${potencia(com)}, sem gestão ${potencia(sem)}`} />
              </g>
            )
          })}

          {/* Limite do quadro */}
          {Number(limiteKw) > 0 && (
            <g>
              <line x1={L} x2={W - R} y1={y(limiteKw)} y2={y(limiteKw)}
                    style={{ stroke: 'var(--color-ink)' }} strokeWidth="1.6" />
              <text x={W - R} y={y(limiteKw) - 6} textAnchor="end" fontSize="13" fontWeight="600"
                    paintOrder="stroke" strokeWidth="4" strokeLinejoin="round"
                    style={{ fill: 'var(--color-ink)', stroke: 'var(--color-panel)', fontFamily: 'var(--font-display)' }}>
                limite {potencia(limiteKw)}
              </text>
            </g>
          )}

          {/* Limite reduzido dentro da janela de ponta */}
          {temPonta && Number(limitePontaKw) > 0 && Number(limitePontaKw) < Number(limiteKw) && (
            <g>
              <line x1={L + ini * passo} x2={L + fim * passo} y1={y(limitePontaKw)} y2={y(limitePontaKw)}
                    style={{ stroke: 'var(--color-queue)' }} strokeWidth="1.6" strokeDasharray="5 3" />
              <text x={L + ini * passo + 4} y={y(limitePontaKw) - 6} fontSize="12" fontWeight="600"
                    paintOrder="stroke" strokeWidth="4" strokeLinejoin="round"
                    style={{ fill: 'var(--color-queue)', stroke: 'var(--color-panel)', fontFamily: 'var(--font-display)' }}>
                na ponta {potencia(limitePontaKw)}
              </text>
            </g>
          )}

          {/* Eixo das horas */}
          {[0, 3, 6, 9, 12, 15, 18, 21, 23].map((hr) => (
            <text key={hr} x={L + hr * passo + passo / 2} y={H - 8} textAnchor="middle" fontSize="12"
                  style={{ fill: foco === hr ? 'var(--color-ink)' : 'var(--color-dim)', fontFamily: 'var(--font-mono)' }}>
              {hr}h
            </text>
          ))}
        </svg>

        {/* Leitura da hora em foco */}
        {h && !vazio && (
          <div className="pointer-events-none absolute right-2 top-2 rounded-chip border border-line bg-panel/95 px-3 py-2
                          text-xs shadow-lift backdrop-blur">
            <p className="num mb-1 font-semibold text-ink">{String(h.hora).padStart(2, '0')}h</p>
            <p className="flex justify-between gap-4 text-mute">
              sem gestão <span className="num text-ink">{potencia(h.demanda_kw)}</span>
            </p>
            <p className="flex justify-between gap-4 text-mute">
              com gestão <span className="num text-flux">{potencia(h.pico_kw)}</span>
            </p>
          </div>
        )}

        {vazio && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="max-w-sm rounded-panel border border-line bg-panel/95 px-5 py-4 text-center shadow-lift">
              <p className="text-sm font-medium text-ink">Nenhuma recarga hoje ainda</p>
              <p className="mt-1 text-xs leading-relaxed text-mute">
                As barras aparecem conforme os carros carregam.
                {onAbrirSimulador && ' Para ver o alocador trabalhando com vários carros, use o simulador.'}
              </p>
              {onAbrirSimulador && (
                <button type="button" onClick={onAbrirSimulador}
                        className="mt-3 rounded-chip border border-flux/40 px-3 py-1.5 text-xs font-medium text-flux
                                   transition hover:bg-flux/10">
                  Abrir simulador
                </button>
              )}
            </div>
          </div>
        )}
      </div>
      </div>
    </div>
  )
}

export default GraficoDemanda
