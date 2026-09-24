import { useEffect, useMemo, useRef, useState } from 'react'
import { supabase, canal as novoCanal } from '../supabaseClient.js'
import { get } from '../lib/api.js'
import { brl, duracao, energia, horaCurta, num, potencia } from '../lib/formato.js'

/**
 * Monitor da recarga ao vivo.
 *
 * É a resposta à pergunta "vocês sabem lidar com os dados da energia?".
 * Tudo aqui vem de medição, não de enfeite:
 *   - a linha da sessão (SoC, energia, custo, potência alocada) chega por
 *     Realtime, sem polling;
 *   - a série de potência vem de `leituras_hardware`, que é o que o sensor do
 *     ESP32 mandou a cada 2 s. O gráfico é desenhado em SVG puro, sem
 *     biblioteca nova.
 *
 * Ponto simulado não tem sensor: aí o gráfico some e ficam os números da
 * sessão, que o simulador calcula pelo mesmo modelo físico.
 */

function Numero({ rotulo, valor, destaque }) {
  return (
    <div className="rounded-chip border border-hair bg-raise/40 px-3 py-2.5">
      <p className="text-[0.625rem] uppercase tracking-wider text-dim">{rotulo}</p>
      <p className={`num mt-1 text-[0.9375rem] font-semibold ${destaque || 'text-ink'}`}>{valor}</p>
    </div>
  )
}

function GraficoPotencia({ leituras }) {
  const pontos = useMemo(() => {
    const vals = leituras.map((l) => Number(l.potencia_w) || 0)
    if (vals.length < 2) return null
    const max = Math.max(...vals, 1)
    const passo = 100 / (vals.length - 1)
    const caminho = vals.map((v, i) => `${i === 0 ? 'M' : 'L'} ${(i * passo).toFixed(2)} ${(100 - (v / max) * 92).toFixed(2)}`).join(' ')
    return { caminho, max, area: `${caminho} L 100 100 L 0 100 Z` }
  }, [leituras])

  if (!pontos) {
    return (
      <p className="rounded-chip border border-dashed border-line px-3 py-6 text-center text-xs text-dim">
        Aguardando as primeiras leituras do medidor...
      </p>
    )
  }

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <p className="eyebrow">Potência medida</p>
        <p className="num text-[0.625rem] text-dim">pico {num(pontos.max, 1)} W</p>
      </div>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-24 w-full">
        <path d={pontos.area} fill="var(--color-flux)" opacity="0.12" />
        <path d={pontos.caminho} fill="none" stroke="var(--color-flux)" strokeWidth="1.4"
              vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      </svg>
      <div className="flex justify-between text-[0.625rem] text-dim">
        <span>{horaCurta(leituras[0]?.criado_em)}</span>
        <span>{horaCurta(leituras[leituras.length - 1]?.criado_em)}</span>
      </div>
    </div>
  )
}

function MonitorRecarga({ sessaoId, sessaoInicial, temSensor, onEncerrada, compacto = false }) {
  const [s, setS] = useState(sessaoInicial || null)
  const [leituras, setLeituras] = useState([])

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

  // Série do medidor: carga inicial + cada leitura nova por Realtime.
  useEffect(() => {
    if (!sessaoId || !temSensor) return
    let vivo = true

    get(`/recargas/${sessaoId}/leituras`)
      .then((dados) => { if (vivo) setLeituras((dados || []).slice().reverse().slice(-60)) })
      .catch(() => {})

    const canal = novoCanal(`leituras-${sessaoId}`)
      .on('postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'leituras_hardware', filter: `sessao_id=eq.${sessaoId}` },
        (evento) => setLeituras((atual) => [...atual, evento.new].slice(-60)))
      .subscribe()

    return () => { vivo = false; supabase.removeChannel(canal) }
  }, [sessaoId, temSensor])

  if (!s) return null

  const soc = Number(s.percentual_bateria_atual || 0)
  const alvo = Number(s.alvo_percentual || 100)
  const ultima = leituras[leituras.length - 1]
  // Mesma conta do backend: energia fora da ponta pela tarifa base, energia
  // na ponta pela tarifa vezes o multiplicador. O valor oficial continua
  // sendo o `custo_final` que o backend grava ao encerrar.
  const energiaTotal = Number(s.energia_entregue_kwh || 0)
  const energiaPonta = Math.min(energiaTotal, Number(s.energia_ponta_kwh || 0))
  const tarifa = Number(s.tarifa_kwh || 0)
  const custo = (energiaTotal - energiaPonta) * tarifa +
    energiaPonta * tarifa * Number(s.multiplicador_ponta || 1)
  const reservado = Number(s.valor_pre_autorizado || 0)

  return (
    <div className="space-y-4">
      <div>
        <div className="mb-1.5 flex items-baseline justify-between">
          <p className="eyebrow">Carga</p>
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
        <Numero rotulo="Potência" valor={potencia(s.potencia_atual_kw)} destaque="text-flux" />
        <Numero rotulo="Energia" valor={energia(s.energia_entregue_kwh)} />
        <Numero rotulo="Restante" valor={duracao(s.tempo_estimado_min)} />
        <Numero rotulo="Consumido" valor={brl(Math.min(custo, reservado || custo))} />
      </div>

      {ultima && (
        <div className="grid grid-cols-3 gap-2 text-center">
          {[['Tensão', `${num(ultima.tensao_v, 2)} V`],
            ['Corrente', `${num(ultima.corrente_a, 3)} A`],
            ['Temp.', `${num(ultima.temperatura_c, 1)} °C`]].map(([r, v]) => (
            <div key={r}>
              <p className="text-[0.625rem] uppercase tracking-wider text-dim">{r}</p>
              <p className="num text-sm text-mute">{v}</p>
            </div>
          ))}
        </div>
      )}

      {temSensor && <GraficoPotencia leituras={leituras} />}

      {reservado > 0 && (
        <p className="rounded-chip border border-hair bg-raise/40 px-3 py-2 text-xs leading-relaxed text-dim">
          {brl(reservado)} estão reservados no seu saldo. No fim, cobramos só o consumo medido e
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
