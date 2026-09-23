import { useCallback, useEffect, useState } from 'react'
import { get, patch } from '../lib/api.js'
import { brl, energia, num, potencia } from '../lib/formato.js'

/**
 * Painel do gestor (síndico) - a tela que faltava para a gestão de demanda
 * deixar de ser uma coluna no banco e virar produto.
 *
 * Responde, com dado medido:
 *   - quanto da potência do prédio a garagem está usando AGORA e quanto sobra
 *   - se o alocador está segurando alguém para não estourar o quadro
 *   - a curva de carga do dia (onde estão os picos e o horário de ponta)
 *   - faturamento, estornos e recargas recusadas por saldo
 *   - consumo por morador no mês, para rateio
 * E deixa mudar o limite e a janela de ponta sem tocar no banco.
 */

function Cartao({ rotulo, valor, sub, cor }) {
  return (
    <div className="rounded-panel border border-line bg-panel p-5">
      <p className="text-sm text-mute">{rotulo}</p>
      <p className={`num mt-2 text-2xl font-semibold ${cor || 'text-ink'}`}>{valor}</p>
      {sub && <p className="mt-1 text-xs text-dim">{sub}</p>}
    </div>
  )
}

function CurvaDeCarga({ horas, pontaInicio, pontaFim }) {
  const max = Math.max(...horas.map((h) => h.energia_kwh), 0.0001)
  const ini = Number(String(pontaInicio).slice(0, 2))
  const fim = Number(String(pontaFim).slice(0, 2))

  return (
    <div className="rounded-panel border border-line bg-panel p-5">
      <div className="mb-4 flex items-baseline justify-between">
        <h3 className="font-medium text-ink">Curva de carga de hoje</h3>
        <span className="flex items-center gap-1.5 text-xs text-dim">
          <span className="h-2 w-2 rounded-sm bg-queue" /> horário de ponta
        </span>
      </div>
      <div className="flex h-36 items-end gap-[2px]">
        {horas.map((h) => {
          const ehPonta = h.hora >= ini && h.hora < fim
          const altura = Math.max(2, (h.energia_kwh / max) * 100)
          return (
            <div key={h.hora} className="group relative flex-1" title={`${h.hora}h — ${energia(h.energia_kwh)}`}>
              <div className={`w-full rounded-t-sm transition-all duration-500 ${ehPonta ? 'bg-queue' : 'bg-flux'}`}
                   style={{ height: `${altura}%`, opacity: h.energia_kwh > 0 ? 1 : 0.25 }} />
            </div>
          )
        })}
      </div>
      <div className="mt-2 flex justify-between text-[0.625rem] text-dim">
        {[0, 6, 12, 18, 23].map((h) => <span key={h}>{h}h</span>)}
      </div>
    </div>
  )
}

function GestorPage() {
  const [dados, setDados] = useState(null)
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)
  const [form, setForm] = useState(null)

  const carregar = useCallback(async () => {
    try {
      const d = await get('/gestor/painel')
      setDados(d)
      setForm((atual) => atual || {
        limite_potencia_kw: d.condominio.limite_potencia_kw,
        ponta_inicio: String(d.condominio.ponta_inicio).slice(0, 5),
        ponta_fim: String(d.condominio.ponta_fim).slice(0, 5),
        ponta_fator_limite: d.condominio.ponta_fator_limite,
        ponta_multiplicador_tarifa: d.condominio.ponta_multiplicador_tarifa,
      })
    } catch (e) {
      setErro(e.message)
    }
  }, [])

  useEffect(() => {
    carregar()
    const id = setInterval(carregar, 10000)     // mesmo ritmo do alocador
    return () => clearInterval(id)
  }, [carregar])

  async function salvar(e) {
    e.preventDefault()
    setSalvando(true); setErro('')
    try {
      await patch('/gestor/condominio', {
        limite_potencia_kw: Number(form.limite_potencia_kw),
        ponta_inicio: form.ponta_inicio,
        ponta_fim: form.ponta_fim,
        ponta_fator_limite: Number(form.ponta_fator_limite),
        ponta_multiplicador_tarifa: Number(form.ponta_multiplicador_tarifa),
      })
      await carregar()
    } catch (e2) {
      setErro(e2.message)
    } finally {
      setSalvando(false)
    }
  }

  if (erro && !dados) {
    return <p className="rounded-panel border border-flux/30 bg-flux/10 p-4 text-sm text-flux">{erro}</p>
  }
  if (!dados) return <div className="skeleton h-64 rounded-panel" />

  const { agora, condominio, carregadores, hoje, mes, por_hora, por_morador } = dados
  const uso = agora.limite_kw > 0 ? Math.min(1, agora.alocado_kw / agora.limite_kw) : 0
  const campo = 'w-full rounded-chip border border-line bg-raise/50 px-3 py-2 text-sm text-ink'

  return (
    <div>
      <div className="mb-8 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-ink lg:text-[1.375rem]">Gestão do condomínio</h2>
          <p className="mt-1 text-sm text-dim">{condominio.nome} · atualiza a cada 10 segundos</p>
        </div>
        {agora.em_ponta && (
          <span className="rounded-chip border border-queue/30 bg-queue/10 px-3 py-1.5 text-xs font-medium text-queue">
            Horário de ponta ativo
          </span>
        )}
      </div>

      {/* Demanda agora */}
      <div className="mb-5 rounded-panel border border-line bg-panel p-5">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="font-medium text-ink">Potência em uso agora</h3>
          <p className="num text-sm text-mute">
            {potencia(agora.alocado_kw)} de {potencia(agora.limite_kw)} liberados
            {agora.em_ponta && ` (limite cheio: ${potencia(agora.limite_nominal_kw)})`}
          </p>
        </div>
        <div className="h-2.5 overflow-hidden rounded-full bg-raise">
          <div className={`h-full rounded-full transition-[width] duration-700 ${uso > 0.85 ? 'bg-queue' : 'bg-flux'}`}
               style={{ width: `${uso * 100}%` }} />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Cartao rotulo="Folga" valor={potencia(agora.folga_kw)} />
          <Cartao rotulo="Demanda pedida" valor={potencia(agora.demanda_kw)}
                  sub={agora.limitando ? 'O alocador está limitando recargas' : 'Todos recebem o que pedem'}
                  cor={agora.limitando ? 'text-queue' : undefined} />
          <Cartao rotulo="Recargas ativas" valor={num(agora.sessoes?.length || 0, 0)} />
          <Cartao rotulo="Tarifa de ponta"
                  valor={`${num(condominio.ponta_multiplicador_tarifa, 2)}x`}
                  sub={`${String(condominio.ponta_inicio).slice(0, 5)}–${String(condominio.ponta_fim).slice(0, 5)}, dias úteis`} />
        </div>
      </div>

      {/* Resultado */}
      <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Cartao rotulo="Energia hoje" valor={energia(hoje.energia_kwh)}
                sub={`${energia(hoje.energia_ponta_kwh)} na ponta`} />
        <Cartao rotulo="Faturamento hoje" valor={brl(hoje.faturamento)}
                sub={`${hoje.recargas} recarga(s) · ${brl(hoje.estornado)} estornados`} cor="text-live" />
        <Cartao rotulo="Faturamento no mês" valor={brl(mes.faturamento)}
                sub={`${mes.recargas} recargas · ${energia(mes.energia_kwh)}`} />
        <Cartao rotulo="Recusadas por saldo" valor={num(mes.recusas_saldo, 0)}
                sub="No mês — indica quem precisa de aviso de saldo"
                cor={mes.recusas_saldo > 0 ? 'text-queue' : undefined} />
      </div>

      <div className="mb-5">
        <CurvaDeCarga horas={por_hora} pontaInicio={condominio.ponta_inicio} pontaFim={condominio.ponta_fim} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Pontos */}
        <div className="overflow-hidden rounded-panel border border-line bg-panel">
          <h3 className="border-b border-hair px-5 py-4 font-medium text-ink">Pontos de recarga</h3>
          <div className="divide-y divide-hair">
            {carregadores.map((c) => (
              <div key={c.id} className="flex items-center justify-between gap-3 px-5 py-3">
                <div className="min-w-0">
                  <p className="num text-sm text-ink">
                    Ponto {c.numero}
                    {c.origem === 'hardware' && (
                      <span className="ml-2 rounded-md border border-flux/30 bg-flux/10 px-1.5 py-0.5 text-[0.5625rem] text-flux">
                        ESP32
                      </span>
                    )}
                  </p>
                  <p className="text-xs capitalize text-dim">
                    {c.status.replace('_', ' ')} · até {potencia(c.potencia_maxima_kw)} · {brl(c.tarifa_kwh)}/kWh
                  </p>
                </div>
                <div className="text-right">
                  <p className="num text-sm text-ink">{potencia(c.potencia_atual_kw || 0)}</p>
                  {c.potencia_alocada_kw != null && (
                    <p className="num text-[0.625rem] text-dim">alocado {potencia(c.potencia_alocada_kw)}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Consumo por morador */}
        <div className="overflow-hidden rounded-panel border border-line bg-panel">
          <h3 className="border-b border-hair px-5 py-4 font-medium text-ink">Consumo por morador (mês)</h3>
          {por_morador.length === 0 ? (
            <p className="px-5 py-6 text-sm text-dim">Nenhuma recarga concluída neste mês.</p>
          ) : (
            <div className="divide-y divide-hair">
              {por_morador.map((m) => (
                <div key={m.nome} className="flex items-center justify-between gap-3 px-5 py-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-ink">{m.nome}</p>
                    <p className="text-xs text-dim">{m.bloco_apto || '—'} · {m.recargas} recarga(s)</p>
                  </div>
                  <div className="text-right">
                    <p className="num text-sm text-ink">{brl(m.valor)}</p>
                    <p className="num text-[0.625rem] text-dim">{energia(m.energia_kwh)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Configuração */}
      <form onSubmit={salvar} className="mt-5 rounded-panel border border-line bg-panel p-5">
        <h3 className="font-medium text-ink">Parâmetros de demanda</h3>
        <p className="mt-1 text-sm leading-relaxed text-dim">
          Mudanças valem no ciclo seguinte do alocador, sem reiniciar nada. O limite é a potência que a garagem
          pode puxar; na ponta ele cai para a fração escolhida.
        </p>
        {erro && <p className="mt-3 rounded-chip border border-flux/30 bg-flux/10 px-3 py-2 text-xs text-flux">{erro}</p>}

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {[
            ['Limite (kW)', 'limite_potencia_kw', 'number', '1'],
            ['Ponta começa', 'ponta_inicio', 'time', undefined],
            ['Ponta termina', 'ponta_fim', 'time', undefined],
            ['Fração na ponta', 'ponta_fator_limite', 'number', '0.05'],
            ['Multiplicador da tarifa', 'ponta_multiplicador_tarifa', 'number', '0.1'],
          ].map(([rotulo, chave, tipo, passo]) => (
            <label key={chave} className="block">
              <span className="mb-1 block text-xs text-dim">{rotulo}</span>
              <input className={campo} type={tipo} step={passo} value={form[chave]}
                     onChange={(e) => setForm({ ...form, [chave]: e.target.value })} />
            </label>
          ))}
        </div>

        <button type="submit" disabled={salvando}
                className="mt-4 rounded-chip bg-flux px-5 py-2.5 text-sm font-medium text-white transition
                           hover:bg-flare disabled:opacity-40">
          {salvando ? 'Salvando...' : 'Salvar parâmetros'}
        </button>
      </form>
    </div>
  )
}

export default GestorPage
