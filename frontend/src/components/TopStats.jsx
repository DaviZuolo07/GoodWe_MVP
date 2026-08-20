import { memo } from 'react'

/* Ícones locais em SVG — nenhuma dependência nova, ~200 bytes cada. */
const ICONES = {
  energia: (
    <>
      <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z" />
    </>
  ),
  plug: (
    <>
      <path d="M9 3v6M15 3v6" />
      <path d="M6 9h12v3a6 6 0 0 1-12 0V9z" />
      <path d="M12 18v3" />
    </>
  ),
  fila: (
    <>
      <circle cx="9" cy="8" r="3" />
      <path d="M3 20a6 6 0 0 1 12 0" />
      <path d="M16 5.5a3 3 0 0 1 0 5" />
      <path d="M18 20a6 6 0 0 0-2-4.5" />
    </>
  ),
  folha: (
    <>
      <path d="M20 4c0 9-5.5 15-14 15" />
      <path d="M20 4C9 4 4 9 4 15a5 5 0 0 0 5 5" />
    </>
  ),
}

function Icone({ nome, className }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {ICONES[nome]}
    </svg>
  )
}

function TopStats({ chargers, sessions, condominio, filaCount, sessoesHoje }) {
  // ---- cálculo inalterado ----
  const limiteEnergia = condominio?.limite_energia_kw ?? 80

  const potenciaEmUso = sessions.reduce((soma, s) => soma + (s.potencia_atual_kw || 0), 0)
  const energiaDisponivel = Math.max(0, limiteEnergia - potenciaEmUso)

  const emUsoCount = chargers.filter((c) => c.status === 'em_uso').length
  const totalCarregadores = chargers.length

  // Energia do dia inclui o que já terminou, não só o que está carregando
  // agora. Quando `sessoesHoje` não é passado, cai no comportamento antigo.
  const hoje = new Date().toDateString()
  const doDia =
    sessoesHoje ??
    sessions.filter((s) => s.iniciado_em && new Date(s.iniciado_em).toDateString() === hoje)

  const energiaHoje = doDia.reduce((soma, s) => soma + Number(s.energia_entregue_kwh || 0), 0)

  // Tarifa média real deste local, em vez de um 2,10 fixo que só valia para
  // o primeiro condomínio.
  const tarifas = chargers.map((c) => Number(c.tarifa_kwh)).filter((n) => Number.isFinite(n))
  const tarifaMedia = tarifas.length ? tarifas.reduce((a, b) => a + b, 0) / tarifas.length : 2.1
  const custoHoje = energiaHoje * tarifaMedia
  // ---- fim do cálculo inalterado ----

  const ocupacao = totalCarregadores > 0 ? emUsoCount / totalCarregadores : 0

  const cards = [
    {
      icone: 'energia',
      cor: 'text-flux',
      fundo: 'bg-flux/10',
      label: 'Energia disponível',
      value: `${energiaDisponivel.toFixed(1)} kW`,
      sub: `de ${limiteEnergia} kW de limite`,
      barra: limiteEnergia > 0 ? energiaDisponivel / limiteEnergia : 0,
      barraCor: 'bg-flux',
    },
    {
      icone: 'plug',
      cor: 'text-live',
      fundo: 'bg-live/10',
      label: 'Carregadores em uso',
      value: `${emUsoCount} / ${totalCarregadores}`,
      sub: totalCarregadores > 0 ? `${Math.round(ocupacao * 100)}% ocupados` : 'Nenhum cadastrado',
      barra: ocupacao,
      barraCor: 'bg-live',
    },
    {
      icone: 'fila',
      cor: 'text-queue',
      fundo: 'bg-queue/10',
      label: 'Veículos na fila',
      value: `${filaCount}`,
      sub: filaCount > 0 ? 'Aguardando carregador' : 'Nenhuma fila agora',
    },
    {
      icone: 'folha',
      cor: 'text-live',
      fundo: 'bg-live/10',
      label: 'Energia entregue hoje',
      value: `${energiaHoje.toFixed(1)} kWh`,
      sub: `Custo gerado: R$ ${custoHoje.toFixed(2)}`,
    },
  ]

  return (
    <div className="mb-10 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => (
        <div
          key={card.label}
          className="group rounded-panel border border-line bg-panel p-5 transition duration-200
                     hover:-translate-y-0.5 hover:border-line hover:bg-raise/50 hover:shadow-lift"
        >
          <div className="mb-4 flex items-center gap-3">
            <span
              className={`flex h-9 w-9 items-center justify-center rounded-chip ${card.fundo} ${card.cor}`}
            >
              <Icone nome={card.icone} className="h-[18px] w-[18px]" />
            </span>
            <p className="text-sm text-mute">{card.label}</p>
          </div>

          <p className="num text-3xl font-semibold leading-none text-ink 2xl:text-4xl">
            {card.value}
          </p>

          {card.barra != null && (
            <div className="mt-3 h-1 overflow-hidden rounded-full bg-raise">
              <div
                className={`h-full rounded-full ${card.barraCor} transition-[width] duration-700 ease-out`}
                style={{ width: `${Math.min(100, Math.max(0, card.barra * 100))}%` }}
              />
            </div>
          )}

          <p className="mt-3 text-xs text-dim">{card.sub}</p>
        </div>
      ))}
    </div>
  )
}

export default memo(TopStats)
