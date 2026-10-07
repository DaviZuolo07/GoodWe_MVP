import { memo } from 'react'
import { potencia } from '../lib/formato.js'

/* ===========================================================================
   FluxoEnergia — o diagrama unifilar vivo do condomínio
   ---------------------------------------------------------------------------
   Rede -> quadro (com o limite de potência) -> barramento -> um ramal por
   ponto de recarga. Uma regra só: MOVIMENTO = ENERGIA PASSANDO. Ramal de
   ponto que não está carregando fica parado; quanto mais potência no quadro,
   mais rápido a corrente corre no tronco.

   Não calcula nada de cobrança. Usa os mesmos números que os indicadores já
   mostram (potência das sessões em andamento e limite do condomínio).
   =========================================================================== */

const COR_STATUS = {
  disponivel: 'var(--color-live)',
  em_uso: 'var(--color-flux)',
  manutencao: 'var(--color-queue)',
  offline: 'var(--color-off)',
}

/** Duração de um ciclo do tracejado: 0% de carga = lento, 100% = rápido. */
function ritmo(fracao) {
  const f = Math.min(1, Math.max(0, fracao))
  return `${(2.6 - 1.9 * f).toFixed(2)}s`
}

function Diagrama({ largura, altura, chargers, sessoesPorPonto, fracao, emUsoKw, selecionadoId }) {
  const compacto = largura < 500
  const yTronco = compacto ? 40 : 46
  const xRede = compacto ? 20 : 30
  const xQuadro = compacto ? 86 : 150
  const raio = compacto ? 20 : 26
  const xInicio = xQuadro + raio + (compacto ? 26 : 60)
  const xFim = largura - (compacto ? 18 : 30)
  const yPonto = altura - (compacto ? 26 : 30)

  const n = chargers.length
  const passo = n > 1 ? (xFim - xInicio) / (n - 1) : 0
  const pontos = chargers.map((c, i) => ({
    c,
    x: n > 1 ? xInicio + passo * i : (xInicio + xFim) / 2,
    sessao: sessoesPorPonto.get(c.id),
  }))
  const ativos = pontos.filter((p) => p.sessao)
  const ultimoAtivoX = ativos.length ? Math.max(...ativos.map((p) => p.x)) : null

  const circ = 2 * Math.PI * raio
  const corArco = fracao >= 0.95 ? 'var(--color-flux)' : fracao >= 0.7 ? 'var(--color-queue)' : 'var(--color-live)'
  const fluindo = emUsoKw > 0

  return (
    <svg viewBox={`0 0 ${largura} ${altura}`} className="block h-auto w-full" role="img"
         aria-label={`Diagrama do condomínio: ${ativos.length} de ${n} pontos carregando`}
         style={{ '--fluxo-dur': ritmo(fracao) }}>
      {/* Tronco: rede -> quadro -> barramento */}
      <path className="fio" d={`M${xRede + 9} ${yTronco}H${xQuadro - raio}`} />
      <path className="fio" d={`M${xQuadro + raio} ${yTronco}H${xFim}`} />
      {fluindo && (
        <>
          <path className="corrente" d={`M${xRede + 9} ${yTronco}H${xQuadro - raio}`} />
          <path className="corrente" d={`M${xQuadro + raio} ${yTronco}H${ultimoAtivoX}`} />
        </>
      )}

      {/* Rede: o poste, como símbolo */}
      <g stroke="var(--color-mute)" strokeWidth="1.5" strokeLinecap="round" fill="none">
        <path d={`M${xRede} ${yTronco - 15}V${yTronco + 15}M${xRede - 8} ${yTronco - 9}H${xRede + 8}M${xRede - 5} ${yTronco - 2}H${xRede + 5}`} />
      </g>

      {/* Quadro: medidor em anel, quanto do limite está em uso */}
      {fluindo && <circle className="halo" cx={xQuadro} cy={yTronco} r={raio + 5} fill="var(--color-flux)" />}
      <circle cx={xQuadro} cy={yTronco} r={raio} fill="var(--color-panel)" stroke="var(--color-line)" strokeWidth="1.5" />
      <circle className="arco" cx={xQuadro} cy={yTronco} r={raio - 5} fill="none" stroke={corArco} strokeWidth="3.5"
              strokeLinecap="round" strokeDasharray={circ * ((raio - 5) / raio)}
              strokeDashoffset={circ * ((raio - 5) / raio) * (1 - Math.max(0.015, Math.min(1, fracao)))}
              transform={`rotate(-90 ${xQuadro} ${yTronco})`} />
      <text x={xQuadro} y={yTronco + 4} textAnchor="middle" fontSize={compacto ? 10 : 12} fontWeight="600"
            fill="var(--color-ink)" fontFamily="var(--font-mono)">
        {Math.round(fracao * 100)}%
      </text>

      {/* Ramais: um por ponto */}
      {pontos.map(({ c, x, sessao }) => {
        const cor = COR_STATUS[c.status] || COR_STATUS.offline
        const sel = selecionadoId === c.id
        return (
          <g key={c.id}>
            <path className="fio" d={`M${x} ${yTronco}V${yPonto - 9}`} />
            {sessao && <path className="corrente" d={`M${x} ${yTronco}V${yPonto - 9}`} />}
            <circle cx={x} cy={yTronco} r="2.5" fill={sessao ? 'var(--color-flux)' : 'var(--color-line)'} />
            {sessao && <rect className="halo" x={x - 13} y={yPonto - 13} width="26" height="26" rx="8" fill="var(--color-flux)" />}
            <rect x={x - 9} y={yPonto - 9} width="18" height="18" rx="5.5"
                  fill="var(--color-panel)" stroke={sel ? 'var(--color-ink)' : cor} strokeWidth={sel ? 2 : 1.5} />
            <circle cx={x} cy={yPonto} r="3" fill={cor} />
            <text x={x} y={yPonto + 22} textAnchor="middle" fontSize={compacto ? 9 : 10} fill="var(--color-dim)"
                  fontFamily="var(--font-mono)">{c.numero}</text>
          </g>
        )
      })}
    </svg>
  )
}

function FluxoEnergia({ chargers, sessions, condominio, selecionadoId }) {
  const limite = Number(condominio?.limite_potencia_kw) || 0
  const emUsoKw = sessions.reduce((soma, s) => soma + Number(s.potencia_atual_kw || 0), 0)
  const fracao = limite > 0 ? emUsoKw / limite : 0
  const sessoesPorPonto = new Map(sessions.map((s) => [s.carregador_id, s]))
  const carregando = chargers.filter((c) => sessoesPorPonto.has(c.id)).length

  const frase = carregando === 0
    ? 'Nenhum ponto carregando agora.'
    : `${carregando} ${carregando === 1 ? 'ponto carregando' : 'pontos carregando'}, ${potencia(emUsoKw, 1)} passando pelo quadro.`

  const props = { chargers, sessoesPorPonto, fracao, emUsoKw, selecionadoId }

  return (
    <section className="mb-4 overflow-hidden rounded-panel border border-line bg-panel" aria-label="Fluxo de energia do condomínio">
      <div className="flex flex-col gap-1 px-5 pt-4 sm:flex-row sm:items-baseline sm:justify-between">
        <h2 className="text-sm font-medium text-ink">Energia no condomínio, agora</h2>
        <p className="text-xs text-mute">
          {frase}{' '}
          {limite > 0 && <span className="text-dim">Limite do quadro: <span className="num">{potencia(limite, 0)}</span>.</span>}
        </p>
      </div>
      <div className="px-2 pb-1 pt-1 sm:hidden">
        <Diagrama largura={360} altura={116} {...props} />
      </div>
      <div className="hidden px-3 pb-1 sm:block">
        <Diagrama largura={920} altura={124} {...props} />
      </div>
    </section>
  )
}

export default memo(FluxoEnergia)
