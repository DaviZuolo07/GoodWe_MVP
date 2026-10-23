import { useCallback, useEffect, useState } from 'react'
import { del, get, patch, post } from '../lib/api.js'
import { brl, energia, num, potencia } from '../lib/formato.js'
import GraficoDemanda from '../components/GraficoDemanda.jsx'
import SimuladorDemanda from '../components/SimuladorDemanda.jsx'

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

/** `null` do backend (migration não rodou, divisão sem base) vira travessão, nunca zero. */
function contagem(v) {
  return v == null ? '—' : num(v, 0)
}

function Indicador({ rotulo, valor, nota, cor, destaque }) {
  return (
    <div className={`px-5 py-4 ${destaque ? 'bg-[color-mix(in_oklab,var(--color-live)_8%,var(--color-panel))]' : 'bg-panel'}`}>
      <p className="text-xs text-mute">{rotulo}</p>
      <p className={`num mt-1.5 text-2xl font-semibold leading-none 2xl:text-[1.75rem] ${cor || 'text-ink'}`}>{valor}</p>
      {nota && <p className={`mt-2 text-xs leading-snug ${cor || 'text-dim'}`}>{nota}</p>}
    </div>
  )
}

/* --------------------------------------------------------------------------
   Gestão de demanda: os quatro números do mês e o gráfico do dia.
   Todos os valores vêm prontos de `dados.demanda` e `por_hora`.
   -------------------------------------------------------------------------- */
function SecaoDemanda({ demanda, porHora, condominio, onAbrirSimulador }) {
  const m = demanda.mes
  const d = demanda.hoje
  const evitou = Number(m.pico_evitado_kw) > 0

  return (
    <section className="mb-5 overflow-hidden rounded-panel border border-line bg-panel shadow-lift">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pb-4 pt-5">
        <div className="max-w-[62ch]">
          <h3 className="text-lg font-semibold tracking-tight text-ink">Gestão de demanda</h3>
          <p className="mt-1 text-sm leading-relaxed text-mute">
            O quadro elétrico da garagem aguenta {potencia(demanda.limite_kw)}. Quando os carros pedem mais do que
            isso, o sistema divide a potência entre eles em vez de deixar o disjuntor desarmar.
          </p>
        </div>
        <span className="rounded-chip border border-line bg-raise/60 px-3 py-1.5 text-xs text-mute">Neste mês</span>
      </div>

      {/* gap-px sobre fundo hair: divisórias de 1px sem brigar com o grid responsivo */}
      <div className="grid grid-cols-2 gap-px border-y border-hair bg-hair lg:grid-cols-4">
        <Indicador rotulo="Limite do quadro" valor={potencia(demanda.limite_kw)}
                   nota={`${potencia(demanda.limite_ponta_kw)} no horário de ponta`} />
        <Indicador rotulo="Pico sem gestão" valor={potencia(m.pico_sem_gestao_kw)}
                   nota={m.estouraria_limite ? 'Teria passado do limite' : 'Dentro do limite'}
                   cor={m.estouraria_limite ? 'text-queue' : undefined} />
        <Indicador rotulo="Pico com gestão" valor={potencia(m.pico_com_gestao_kw)}
                   nota="O que o prédio puxou de fato" />
        <Indicador rotulo="Pico evitado" valor={potencia(m.pico_evitado_kw)}
                   nota={evitou ? 'Potência segurada para o disjuntor não desarmar' : 'Nenhuma limitação foi necessária'}
                   cor={evitou ? 'text-live' : undefined} destaque={evitou} />
      </div>

      <div className="flex flex-wrap gap-x-6 gap-y-1.5 border-b border-hair bg-raise/30 px-5 py-2.5 text-xs text-mute">
        <span>Horas com limitação no mês: <span className="num text-ink">{contagem(m.horas_com_limitacao)}</span></span>
        <span>Recargas que esperaram por limite: <span className="num text-ink">{contagem(m.recusas_por_limite)}</span></span>
        <span>
          Hoje: pico <span className="num text-ink">{potencia(d.pico_com_gestao_kw)}</span>
          {Number(d.pico_evitado_kw) > 0 && <>, evitou <span className="num text-live">{potencia(d.pico_evitado_kw)}</span></>}
        </span>
      </div>

      <div className="px-5 pb-5 pt-4">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h4 className="font-medium text-ink">Potência por hora, hoje</h4>
          <p className="text-xs text-dim">A área tracejada acima da barra é o que a gestão segurou.</p>
        </div>
        <GraficoDemanda
          porHora={porHora}
          limiteKw={demanda.limite_kw}
          limitePontaKw={demanda.limite_ponta_kw}
          pontaInicio={condominio.ponta_inicio}
          pontaFim={condominio.ponta_fim}
          onAbrirSimulador={onAbrirSimulador}
        />
      </div>
    </section>
  )
}

/** Percentual pronto do backend; `null` (sem base para dividir) vira travessão. */
function pct(v) {
  return v == null ? '—' : `${num(v, 1)}%`
}

/* --------------------------------------------------------------------------
   Valor: o que o sistema entrega para cada lado, com números de `dados.valor`.
   Nenhuma conta aqui — receita, custo, margem e percentuais vêm prontos.
   As tarifas da distribuidora são PREMISSAS do síndico, e a tela diz isso.
   -------------------------------------------------------------------------- */
function SecaoValor({ valor, mes, demanda, onAjustarPremissas }) {
  const margemPct = valor.margem_percentual
  const barraMargem = margemPct == null ? null : Math.max(0, Math.min(100, Number(margemPct)))
  const premissas = valor.premissas || {}
  const economiaBateria = Number(valor.economia_potencial_armazenamento_mes) || 0

  const publicos = [
    {
      quem: 'Morador',
      oque: 'Paga pelo kWh medido, com recibo linha a linha. O que reservou e não usou volta para a carteira.',
      numero: brl(mes.estornado),
      legenda: 'devolvido aos moradores no mês',
    },
    {
      quem: 'Síndico',
      oque: 'A garagem cabe no quadro elétrico que já existe, e a recarga paga a própria energia.',
      numero: brl(valor.margem_mes),
      legenda: margemPct == null ? 'margem estimada no mês' : `margem estimada no mês (${pct(margemPct)})`,
      cor: Number(valor.margem_mes) < 0 ? 'text-flux' : 'text-live',
    },
    {
      quem: 'GoodWe',
      oque: 'A energia comprada cara na ponta poderia vir de uma bateria carregada fora dela.',
      numero: brl(economiaBateria),
      legenda: 'economia potencial por mês com armazenamento',
      cor: economiaBateria > 0 ? 'text-ink' : undefined,
    },
  ]

  return (
    <section className="mb-5 overflow-hidden rounded-panel border border-line bg-panel">
      <div className="px-5 pb-4 pt-5">
        <h3 className="text-lg font-semibold tracking-tight text-ink">O que a recarga gera</h3>
        <p className="mt-1 max-w-[62ch] text-sm leading-relaxed text-mute">
          Quanto os moradores pagaram, quanto essa energia custou ao condomínio e o que sobra, neste mês.
        </p>
      </div>

      {/* Receita = custo + margem, numa barra só */}
      <div className="border-t border-hair px-5 py-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-sm text-mute">
            Receita das recargas <span className="num ml-1 text-lg font-semibold text-ink">{brl(valor.receita_mes)}</span>
          </p>
          <p className="num text-xs text-dim">{energia(valor.energia_mes_kwh)} faturados</p>
        </div>

        {barraMargem != null ? (
          <div className="mt-3 flex h-3 overflow-hidden rounded-full bg-raise" role="img"
               aria-label={`Custo da energia ${brl(valor.custo_energia_mes)}, margem ${brl(valor.margem_mes)}`}>
            <div className="h-full bg-off" style={{ width: `${100 - barraMargem}%` }} />
            <div className="h-full bg-live" style={{ width: `${barraMargem}%` }} />
          </div>
        ) : (
          <div className="mt-3 h-3 rounded-full bg-raise" />
        )}

        <div className="mt-2.5 flex flex-wrap gap-x-6 gap-y-1 text-xs">
          <span className="flex items-center gap-2 text-mute">
            <span className="h-2 w-2 rounded-full bg-off" />
            Custo da energia <span className="num text-ink">{brl(valor.custo_energia_mes)}</span>
          </span>
          <span className="flex items-center gap-2 text-mute">
            <span className="h-2 w-2 rounded-full bg-live" />
            Margem <span className="num text-ink">{brl(valor.margem_mes)}</span>
          </span>
          <span className="flex items-center gap-2 text-mute">
            <span className="h-2 w-2 rounded-full bg-queue" />
            Na ponta <span className="num text-ink">{energia(valor.energia_ponta_mes_kwh)}</span>
            <span className="text-dim">({pct(valor.participacao_ponta_percentual)} da energia)</span>
          </span>
        </div>
      </div>

      {/* Para quem é o valor */}
      <ul className="divide-y divide-hair border-t border-hair">
        {publicos.map((p) => (
          <li key={p.quem} className="grid gap-x-6 gap-y-1 px-5 py-3.5 sm:grid-cols-[7rem_1fr_auto] sm:items-center">
            <p className="text-sm font-semibold text-ink">{p.quem}</p>
            <p className="text-sm leading-relaxed text-mute">{p.oque}</p>
            <div className="sm:text-right">
              <p className={`num text-lg font-semibold ${p.cor || 'text-ink'}`}>{p.numero}</p>
              <p className="text-[0.6875rem] text-dim">{p.legenda}</p>
            </div>
          </li>
        ))}
      </ul>

      {Number(demanda?.mes?.pico_evitado_kw) > 0 && (
        <p className="border-t border-hair px-5 py-3 text-sm text-mute">
          Sem a gestão de demanda, o pico do mês teria sido de{' '}
          <span className="num text-ink">{potencia(demanda.mes.pico_sem_gestao_kw)}</span>, acima do quadro de{' '}
          <span className="num text-ink">{potencia(demanda.limite_kw)}</span>: seria preciso ampliar a entrada de
          energia do prédio para atender os mesmos carros.
        </p>
      )}

      {/* Premissas — sempre visíveis, junto dos números que dependem delas */}
      <div className="flex flex-wrap items-start justify-between gap-3 border-t border-dashed border-line bg-raise/30 px-5 py-3">
        <p className="max-w-[70ch] text-xs leading-relaxed text-dim">
          Custo da energia calculado com <span className="num text-mute">{brl(premissas.custo_energia_kwh)}/kWh</span> fora
          da ponta e <span className="num text-mute">{brl(premissas.custo_energia_ponta_kwh)}/kWh</span> na ponta.{' '}
          {premissas.observacao}
        </p>
        {onAjustarPremissas && (
          <button type="button" onClick={onAjustarPremissas}
                  className="shrink-0 text-xs font-medium text-mute underline decoration-line underline-offset-4
                             transition-colors hover:text-flux hover:decoration-flux">
            Ajustar premissas
          </button>
        )}
      </div>
    </section>
  )
}

function CurvaDeCarga({ horas, pontaInicio, pontaFim }) {
  const max = Math.max(...horas.map((h) => h.energia_kwh), 0.0001)
  const ini = Number(String(pontaInicio).slice(0, 2))
  const fim = Number(String(pontaFim).slice(0, 2))

  return (
    <div className="rounded-panel border border-line bg-panel p-5">
      <div className="mb-4 flex items-baseline justify-between">
        <h3 className="font-medium text-ink">Energia entregue por hora, hoje</h3>
        <span className="flex items-center gap-1.5 text-xs text-dim">
          <span className="h-2 w-2 rounded-sm bg-queue" /> horário de ponta
        </span>
      </div>
      <div className="flex h-36 items-end gap-[2px]">
        {horas.map((h) => {
          const ehPonta = h.hora >= ini && h.hora < fim
          const altura = Math.max(2, (h.energia_kwh / max) * 100)
          return (
            <div key={h.hora} className="group relative flex h-full flex-1 items-end" title={`${h.hora}h — ${energia(h.energia_kwh)}`}>
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
  const [premissasOriginais, setPremissasOriginais] = useState(null)
  const [cartoes, setCartoes] = useState([])
  const [novoUid, setNovoUid] = useState('')

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
        // Premissas de custo: se o condomínio ainda não tem valor gravado, o
        // campo mostra a premissa que o backend usou no cálculo.
        custo_energia_kwh: d.condominio.custo_energia_kwh ?? d.valor?.premissas?.custo_energia_kwh ?? '',
        custo_energia_ponta_kwh: d.condominio.custo_energia_ponta_kwh ?? d.valor?.premissas?.custo_energia_ponta_kwh ?? '',
      })
      setPremissasOriginais((atual) => atual || {
        custo_energia_kwh: String(d.condominio.custo_energia_kwh ?? d.valor?.premissas?.custo_energia_kwh ?? ''),
        custo_energia_ponta_kwh: String(d.condominio.custo_energia_ponta_kwh ?? d.valor?.premissas?.custo_energia_ponta_kwh ?? ''),
      })
    } catch (e) {
      setErro(e.message)
    }
  }, [])

  const carregarCartoes = useCallback(async () => {
    try { setCartoes(await get('/gestor/cartoes')) } catch { /* seção vazia */ }
  }, [])

  useEffect(() => {
    carregar()
    carregarCartoes()
    const id = setInterval(carregar, 10000)     // mesmo ritmo do alocador
    return () => clearInterval(id)
  }, [carregar, carregarCartoes])

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
        // Só vão no corpo se o síndico mexeu: num banco sem essas colunas,
        // salvar o limite continua funcionando como antes.
        ...['custo_energia_kwh', 'custo_energia_ponta_kwh'].reduce((extra, k) => (
          String(form[k]) !== '' && String(form[k]) !== premissasOriginais?.[k]
            ? { ...extra, [k]: Number(form[k]) } : extra
        ), {}),
      })
      setPremissasOriginais({
        custo_energia_kwh: String(form.custo_energia_kwh),
        custo_energia_ponta_kwh: String(form.custo_energia_ponta_kwh),
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

  const { agora, condominio, carregadores, hoje, mes, por_hora, por_morador, demanda, valor } = dados
  const abrirParametros = () =>
    document.getElementById('parametros')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  const abrirSimulador = () =>
    document.getElementById('simulador')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
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

      {demanda && (
        <SecaoDemanda demanda={demanda} porHora={por_hora} condominio={condominio}
                      onAbrirSimulador={abrirSimulador} />
      )}

      {demanda && <SimuladorDemanda limiteKw={demanda.limite_kw} />}

      {valor && (
        <SecaoValor valor={valor} mes={mes} demanda={demanda} onAjustarPremissas={abrirParametros} />
      )}

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

      {/* Cartões compartilhados */}
      <div className="mt-5 rounded-panel border border-line bg-panel p-5">
        <h3 className="font-medium text-ink">Cartões do condomínio</h3>
        <p className="mt-1 text-sm leading-relaxed text-dim">
          Um cartão compartilhado prova PRESENÇA no ponto, não identidade: ele libera a recarga que
          estiver preparada ali, e a cobrança sai de quem a preparou no aplicativo. É assim que um
          único cartão físico atende todos os moradores. Quem quiser trava por pessoa cadastra um
          cartão pessoal em Configurações — esse passa a valer só para ele.
        </p>

        <div className="mt-4 flex flex-wrap gap-2">
          <input className="w-44 rounded-chip border border-line bg-raise/50 px-3 py-2 text-sm text-ink"
                 placeholder="UID (ex.: A1B2C3D4)" value={novoUid}
                 onChange={(e) => setNovoUid(e.target.value)} />
          <button
            disabled={!novoUid.trim()}
            onClick={async () => {
              setErro('')
              try {
                await post('/gestor/cartoes', { uid: novoUid.trim() })
                setNovoUid('')
                await carregarCartoes()
              } catch (e) { setErro(e.message) }
            }}
            className="rounded-chip bg-flux px-4 py-2 text-sm font-medium text-white transition
                       hover:bg-flare disabled:opacity-40">
            Cadastrar cartão
          </button>
        </div>

        {cartoes.length > 0 ? (
          <ul className="mt-4 space-y-2">
            {cartoes.map((c) => (
              <li key={c.uid}
                  className="flex items-center justify-between gap-3 rounded-chip border border-hair
                             bg-raise/40 px-4 py-2.5">
                <div className="min-w-0">
                  <p className="num truncate text-sm text-ink">{c.uid}</p>
                  <p className="truncate text-xs text-dim">
                    {c.apelido || 'Cartão do condomínio'}
                    {c.ultimo_uso ? ` · último uso ${new Date(c.ultimo_uso).toLocaleString('pt-BR')}` : ''}
                  </p>
                </div>
                <button
                  onClick={async () => {
                    try { await del(`/gestor/cartoes/${c.uid}`); await carregarCartoes() }
                    catch (e) { setErro(e.message) }
                  }}
                  className="shrink-0 text-xs text-dim transition-colors hover:text-flux">
                  remover
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-4 rounded-chip border border-dashed border-line px-4 py-3 text-xs text-dim">
            Nenhum cartão compartilhado. Sem ele, cada morador precisa cadastrar o próprio cartão.
          </p>
        )}
      </div>

      {/* Configuração */}
      <form id="parametros" onSubmit={salvar} className="mt-5 scroll-mt-28 rounded-panel border border-line bg-panel p-5">
        <h3 className="font-medium text-ink">Parâmetros de demanda</h3>
        <p className="mt-1 text-sm leading-relaxed text-dim">
          Mudanças valem no ciclo seguinte do alocador, sem reiniciar nada. O limite é a potência que a garagem
          pode puxar; na ponta ele cai para a fração escolhida. Os custos da energia são as premissas usadas no
          bloco de valor: coloque o que a distribuidora cobra do condomínio.
        </p>
        {erro && <p className="mt-3 rounded-chip border border-flux/30 bg-flux/10 px-3 py-2 text-xs text-flux">{erro}</p>}

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-7">
          {[
            ['Limite (kW)', 'limite_potencia_kw', 'number', '1'],
            ['Ponta começa', 'ponta_inicio', 'time', undefined],
            ['Ponta termina', 'ponta_fim', 'time', undefined],
            ['Fração na ponta', 'ponta_fator_limite', 'number', '0.05'],
            ['Multiplicador da tarifa', 'ponta_multiplicador_tarifa', 'number', '0.1'],
            ['Custo da energia (R$/kWh)', 'custo_energia_kwh', 'number', '0.01'],
            ['Custo na ponta (R$/kWh)', 'custo_energia_ponta_kwh', 'number', '0.01'],
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
