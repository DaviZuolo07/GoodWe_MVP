import { useMemo, useRef, useState } from 'react'
import { horaCurta, num, potencia } from '../lib/formato.js'

/**
 * A série de UMA recarga (db/23, leituras_sessao), em dois gráficos com o
 * MESMO eixo de tempo - nunca dois eixos y no mesmo desenho:
 *   1. potência que a vaga entregou (área) e o que o water-filling liberou
 *      (linha tracejada). No totem, com a divisão por tempo, a área vira um
 *      "pente": o relé abre e fecha em rodízio;
 *   2. % da bateria (linha).
 * Passar o mouse mostra o instante nos dois. Nada é calculado aqui além da
 * escala do desenho: os números vêm prontos do backend.
 */

const W = 1000
const H = 170
const L = 58
const R = 12
const T = 12
const B = 22

function escala(pontos, campo, minimoTopo) {
  const max = Math.max(minimoTopo, ...pontos.map((p) => Number(p[campo]) || 0))
  return max * 1.1
}

function Painel({ pontos, x, valores, topo, rotuloY, formatar, cor, tracejada, foco, setFoco, area, legenda }) {
  const alturaUtil = H - T - B
  const y = (v) => T + alturaUtil - (Math.max(0, v) / topo) * alturaUtil
  const caminho = (campo) => pontos
    .map((p, i) => (p[campo] == null ? null : `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(Number(p[campo])).toFixed(1)}`))
    .filter(Boolean).join(' ')
  const linha = caminho(valores)
  const marcas = [0, topo / 2, topo]
  const refSvg = useRef(null)

  function mover(e) {
    const r = refSvg.current?.getBoundingClientRect()
    if (!r || pontos.length < 2) return
    const px = ((e.clientX - r.left) / r.width) * W
    const passo = (W - L - R) / (pontos.length - 1)
    setFoco(Math.max(0, Math.min(pontos.length - 1, Math.round((px - L) / passo))))
  }

  return (
    <figure className="m-0">
      <figcaption className="mb-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-mute">
        <span className="font-medium text-ink">{rotuloY}</span>
        {legenda}
      </figcaption>
      <svg ref={refSvg} viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full touch-none" role="img"
           aria-label={rotuloY} onPointerMove={mover} onPointerLeave={() => setFoco(null)}>
        {marcas.map((m) => (
          <g key={m}>
            <line x1={L} x2={W - R} y1={y(m)} y2={y(m)} className="stroke-hair" strokeWidth="1" />
            <text x={L - 8} y={y(m) + 4} textAnchor="end" className="fill-dim num" fontSize="12">{formatar(m)}</text>
          </g>
        ))}
        {area && linha && (
          <path d={`${linha} L${x(pontos.length - 1).toFixed(1)},${y(0)} L${x(0).toFixed(1)},${y(0)} Z`}
                className={cor} fill="currentColor" opacity="0.18" />
        )}
        {linha && <path d={linha} className={cor} stroke="currentColor" strokeWidth="2" fill="none"
                        strokeLinejoin="round" />}
        {tracejada && caminho(tracejada) && (
          <path d={caminho(tracejada)} className="text-mute" stroke="currentColor" strokeWidth="2" fill="none"
                strokeDasharray="6 5" />
        )}
        {foco != null && pontos[foco] && (
          <>
            <line x1={x(foco)} x2={x(foco)} y1={T} y2={H - B} className="stroke-mute" strokeWidth="1" />
            {pontos[foco][valores] != null && (
              <circle cx={x(foco)} cy={y(Number(pontos[foco][valores]))} r="5" className={`${cor} stroke-panel`}
                      fill="currentColor" strokeWidth="2" />
            )}
          </>
        )}
      </svg>
    </figure>
  )
}

function GraficoSessao({ serie }) {
  const [foco, setFoco] = useState(null)
  const pontos = useMemo(() => serie?.pontos || [], [serie])

  if (pontos.length < 2) {
    return (
      <p className="rounded-panel border border-dashed border-line px-5 py-10 text-center text-sm text-dim">
        Aguardando as primeiras leituras desta recarga. Se ela já acabou e nada aparece, o db/23 ainda não
        foi aplicado no banco.
      </p>
    )
  }

  const x = (i) => L + (i / (pontos.length - 1)) * (W - L - R)
  const topoKw = escala(pontos, 'potencia_kw', Math.max(...pontos.map((p) => Number(p.alocado_kw) || 0), 0.001))
  const p = foco != null ? pontos[foco] : pontos[pontos.length - 1]
  const comLiberado = pontos.some((q) => q.alocado_kw != null)

  return (
    <div className="space-y-3">
      <Painel pontos={pontos} x={x} valores="potencia_kw" tracejada={comLiberado ? 'alocado_kw' : null}
              topo={topoKw} rotuloY="Potência" formatar={(v) => potencia(v, 1)} cor="text-live" area
              foco={foco} setFoco={setFoco}
              legenda={<>
                <span className="inline-flex items-center gap-1.5"><i className="inline-block h-2 w-3 rounded-sm bg-live" aria-hidden />entregue</span>
                {comLiberado && <span className="inline-flex items-center gap-1.5"><i className="inline-block w-4 border-t-2 border-dashed border-mute" aria-hidden />liberado pelo water-filling</span>}
              </>} />
      <Painel pontos={pontos} x={x} valores="percentual" topo={110} rotuloY="Bateria"
              formatar={(v) => `${num(Math.min(v, 100), 0)}%`} cor="text-flux" foco={foco} setFoco={setFoco} />
      <div className="flex flex-wrap items-baseline justify-between gap-2 rounded-chip border border-hair bg-raise/40 px-3 py-2 text-xs">
        <span className="num text-mute">{foco != null ? horaCurta(p.t) : 'agora'}</span>
        <span className="num text-ink">{potencia(p.potencia_kw)} · {p.percentual != null ? `${num(p.percentual, 1)}%` : '—'}
          {p.alocado_kw != null && <span className="text-mute"> · liberado {potencia(p.alocado_kw)}</span>}
          {p.tempo_restante_min != null && <span className="text-mute"> · fim em {p.tempo_restante_min} min</span>}
        </span>
      </div>
      <div className="flex justify-between text-[0.6875rem] text-dim num">
        <span>{horaCurta(pontos[0].t)}</span><span>{pontos.length} pontos</span><span>{horaCurta(pontos[pontos.length - 1].t)}</span>
      </div>
    </div>
  )
}

export default GraficoSessao
