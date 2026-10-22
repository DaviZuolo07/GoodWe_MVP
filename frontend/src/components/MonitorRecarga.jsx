import { useEffect, useMemo, useRef, useState } from 'react'
import { supabase, canal as novoCanal } from '../supabaseClient.js'
import { get, post } from '../lib/api.js'
import { brl, duracao, energia, horaCurta, num, potencia } from '../lib/formato.js'

/**
 * Monitor da recarga ao vivo - o MESMO para o eletroposto simulado e para o
 * totem do Next.
 *
 *   - a linha da sessão (%, energia, custo, potência liberada, previsão)
 *     chega por Realtime, sem polling;
 *   - a série do gráfico vem de GET /recargas/{id}/serie (db/23), gravada
 *     pelo backend a cada atualização da recarga, a cada 5 s;
 *   - no totem, se o app estiver aberto no PRÓPRIO celular que carrega
 *     (Chrome do Android expõe a bateria), o % real vai para o backend e
 *     corrige o modelo de carga - e o app mostra "lido do seu celular".
 *
 * Dois gráficos com o mesmo eixo de tempo (potência e bateria), nunca dois
 * eixos y no mesmo desenho. Nenhum número é calculado aqui além da escala.
 */

const ORIGEM = {
  simulado: 'Simulado pelo modelo de carga (sem sensor de corrente)',
  medido: 'Medido pelo sensor do ponto',
  estimado: 'Estimado',
}

function Numero({ rotulo, valor, destaque, sub }) {
  return (
    <div className="rounded-chip border border-hair bg-raise/40 px-3 py-2.5">
      <p className="text-[0.625rem] uppercase tracking-wider text-dim">{rotulo}</p>
      <p className={`num mt-1 text-[0.9375rem] font-semibold ${destaque || 'text-ink'}`}>{valor}</p>
      {sub && <p className="num text-[0.625rem] text-dim">{sub}</p>}
    </div>
  )
}

function Mini({ titulo, pontos, campo, tracejado, cor, topo, formatar, foco, setFoco }) {
  const ref = useRef(null)
  const caminho = (c) => pontos.map((p, i) => (p[c] == null ? null
    : `${i === 0 ? 'M' : 'L'} ${(i / (pontos.length - 1) * 100).toFixed(2)} ${(100 - Math.max(0, p[c]) / topo * 92).toFixed(2)}`))
    .filter(Boolean).join(' ')
  const linha = caminho(campo)
  const p = pontos[foco ?? pontos.length - 1]

  function mover(e) {
    const r = ref.current?.getBoundingClientRect()
    if (r) setFoco(Math.max(0, Math.min(pontos.length - 1, Math.round((e.clientX - r.left) / r.width * (pontos.length - 1)))))
  }

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <p className="eyebrow">{titulo}</p>
        <p className="num text-[0.6875rem] text-mute">{p?.[campo] != null ? formatar(p[campo]) : '—'}
          {foco != null && <span className="text-dim"> · {horaCurta(p.t)}</span>}</p>
      </div>
      <svg ref={ref} viewBox="0 0 100 100" preserveAspectRatio="none" className="h-20 w-full touch-none"
           role="img" aria-label={titulo} onPointerMove={mover} onPointerLeave={() => setFoco(null)}>
        {linha && <path d={`${linha} L 100 100 L 0 100 Z`} fill={cor} opacity="0.12" />}
        {linha && <path d={linha} fill="none" stroke={cor} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />}
        {tracejado && caminho(tracejado) && (
          <path d={caminho(tracejado)} fill="none" stroke="var(--color-mute)" strokeWidth="1.5" strokeDasharray="4 4"
                vectorEffect="non-scaling-stroke" />
        )}
        {foco != null && (
          <line x1={foco / (pontos.length - 1) * 100} x2={foco / (pontos.length - 1) * 100} y1="0" y2="100"
                stroke="var(--color-mute)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        )}
      </svg>
    </div>
  )
}

function Graficos({ serie }) {
  const [foco, setFoco] = useState(null)
  const pontos = useMemo(() => serie?.pontos || [], [serie])
  if (pontos.length < 2) {
    return (
      <p className="rounded-chip border border-dashed border-line px-3 py-6 text-center text-xs text-dim">
        Aguardando as primeiras leituras desta recarga...
      </p>
    )
  }
  const topoKw = Math.max(0.0001, ...pontos.map((p) => Math.max(p.potencia_kw || 0, p.alocado_kw || 0))) * 1.1
  const comLiberado = pontos.some((p) => p.alocado_kw != null)
  return (
    <div className="space-y-3">
      <Mini titulo="Potência" pontos={pontos} campo="potencia_kw" tracejado={comLiberado ? 'alocado_kw' : null}
            cor="var(--color-flux)" topo={topoKw} formatar={(v) => potencia(v)} foco={foco} setFoco={setFoco} />
      <Mini titulo="Bateria" pontos={pontos} campo="percentual" cor="var(--color-live)" topo={100}
            formatar={(v) => `${num(v, 1)}%`} foco={foco} setFoco={setFoco} />
      <div className="flex flex-wrap justify-between gap-2 text-[0.625rem] text-dim">
        <span>{horaCurta(pontos[0].t)}</span>
        {comLiberado && <span><i className="mr-1 inline-block w-3 border-t border-dashed border-mute align-middle" aria-hidden />liberado pela gestão de demanda</span>}
        <span>{horaCurta(pontos[pontos.length - 1].t)}</span>
      </div>
      {serie.origem && <p className="text-[0.625rem] text-dim">{ORIGEM[serie.origem] || serie.origem}</p>}
    </div>
  )
}

/** Battery Status API: só o Chrome/Edge do Android tem. Manda o % enquanto o celular está carregando. */
function useBateriaDoCelular(sessaoId, ativa) {
  useEffect(() => {
    if (!sessaoId || !ativa || typeof navigator === 'undefined' || !navigator.getBattery) return
    let vivo = true
    let bateria = null
    async function enviar() {
      try {
        bateria = bateria || await navigator.getBattery()
        // Só conta se ESTE aparelho está carregando: é a prova de que está na vaga.
        if (vivo && bateria.charging) await post(`/recargas/${sessaoId}/bateria`, { percentual: Math.round(bateria.level * 100) })
      } catch { /* sem a API ou recusado: segue o modelo */ }
    }
    enviar()
    const t = setInterval(enviar, 30000)
    return () => { vivo = false; clearInterval(t) }
  }, [sessaoId, ativa])
}

function MonitorRecarga({ sessaoId, sessaoInicial, onEncerrada, compacto = false }) {
  const [s, setS] = useState(sessaoInicial || null)
  const [serie, setSerie] = useState(null)

  // O callback do pai costuma ser uma arrow function nova a cada render. Se
  // entrasse nas dependências do efeito, o canal seria recriado a cada
  // render do pai. Guardado num ref, o efeito depende só da sessão.
  const onEncerradaRef = useRef(onEncerrada)
  useEffect(() => { onEncerradaRef.current = onEncerrada }, [onEncerrada])

  // A linha da sessão: uma leitura e depois só Realtime.
  useEffect(() => {
    if (!sessaoId) return
    let vivo = true

    async function carregar() {
      const { data } = await supabase.from('sessoes_recarga').select('*').eq('id', sessaoId).single()
      if (vivo && data) setS(data)
    }
    carregar()

    const canal = novoCanal(`monitor-${sessaoId}`)
      .on('postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'sessoes_recarga', filter: `id=eq.${sessaoId}` },
        (evento) => {
          setS(evento.new)
          if (evento.new.status !== 'carregando') onEncerradaRef.current?.(evento.new)
        })
      .subscribe()

    return () => { vivo = false; supabase.removeChannel(canal) }
  }, [sessaoId])

  // A série do gráfico, a cada 5 s enquanto a recarga anda (simulada ou totem).
  const carregando = s?.status === 'carregando'
  useEffect(() => {
    if (!sessaoId) return
    let vivo = true
    const buscar = () => get(`/recargas/${sessaoId}/serie`).then((d) => { if (vivo) setSerie(d) }).catch(() => {})
    buscar()
    if (!carregando) return () => { vivo = false }
    const t = setInterval(buscar, 5000)
    return () => { vivo = false; clearInterval(t) }
  }, [sessaoId, carregando])

  useBateriaDoCelular(sessaoId, carregando && s?.origem === 'hardware')

  if (!s) return null

  const soc = Number(s.percentual_bateria_atual || 0)
  const alvo = Number(s.alvo_percentual || 100)
  // Mesma conta do backend: energia fora da ponta pela tarifa base, energia
  // na ponta pela tarifa vezes o multiplicador. O valor oficial continua
  // sendo o `custo_final` que o backend grava ao encerrar.
  const energiaTotal = Number(s.energia_entregue_kwh || 0)
  const energiaPonta = Math.min(energiaTotal, Number(s.energia_ponta_kwh || 0))
  const tarifa = Number(s.tarifa_kwh || 0)
  const custo = (energiaTotal - energiaPonta) * tarifa +
    energiaPonta * tarifa * Number(s.multiplicador_ponta || 1)
  const reservado = Number(s.valor_pre_autorizado || 0)
  // Hora prevista: instante do último ponto da série + a previsão daquele ponto.
  const ultimo = serie?.pontos?.[serie.pontos.length - 1]
  const fim = carregando && ultimo?.tempo_restante_min != null
    ? new Date(new Date(ultimo.t).getTime() + ultimo.tempo_restante_min * 60000).toISOString() : null

  return (
    <div className="space-y-4">
      <div>
        <div className="mb-1.5 flex items-baseline justify-between">
          <p className="eyebrow">Carga{s.percentual_origem === 'celular' && <span className="ml-2 normal-case tracking-normal text-live">lido do seu celular</span>}</p>
          <p className="num text-sm text-mute">alvo {num(alvo, 0)}%</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-raise">
            <div className="flux-bar h-full rounded-full transition-[width] duration-700 ease-out"
                 style={{ width: `${Math.min(100, soc)}%` }} />
            <span className="absolute top-0 h-full w-px bg-ink/40" style={{ left: `${alvo}%` }} />
          </div>
          <span className="num text-lg font-semibold text-ink">{num(soc, 1)}%</span>
        </div>
      </div>

      <div className={`grid gap-2 ${compacto ? 'grid-cols-2' : 'grid-cols-2 sm:grid-cols-4'}`}>
        <Numero rotulo="Potência" valor={potencia(s.potencia_atual_kw)} destaque="text-flux"
                sub={s.potencia_media_kw ? `média ${potencia(s.potencia_media_kw)}` : null} />
        <Numero rotulo="Energia" valor={energia(s.energia_entregue_kwh)} />
        <Numero rotulo="Termina em" valor={duracao(s.tempo_estimado_min)} sub={fim ? `por volta das ${horaCurta(fim)}` : null} />
        <Numero rotulo="Consumido" valor={brl(Math.min(custo, reservado || custo))} />
      </div>

      <Graficos serie={serie} />

      {reservado > 0 && (
        <p className="rounded-chip border border-hair bg-raise/40 px-3 py-2 text-xs leading-relaxed text-dim">
          {brl(reservado)} estão reservados no seu saldo. No fim, cobramos só o consumo e
          devolvemos a diferença.
        </p>
      )}

      {s.potencia_alocada_kw != null && Number(s.potencia_alocada_kw) > 0 && (
        <p className="text-xs text-dim">
          Potência liberada pela gestão de demanda do condomínio: {potencia(s.potencia_alocada_kw)}.
        </p>
      )}
    </div>
  )
}

export default MonitorRecarga
