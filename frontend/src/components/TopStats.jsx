function TopStats({ chargers, sessions, condominio, filaCount }) {
  const limiteEnergia = condominio?.limite_energia_kw ?? 80

  const potenciaEmUso = sessions.reduce((soma, s) => soma + (s.potencia_atual_kw || 0), 0)
  const energiaDisponivel = Math.max(0, limiteEnergia - potenciaEmUso)

  const emUsoCount = chargers.filter((c) => c.status === 'em_uso').length
  const totalCarregadores = chargers.length

  const hoje = new Date().toDateString()
  const sessoesHoje = sessions.filter((s) => s.iniciado_em && new Date(s.iniciado_em).toDateString() === hoje)
  const energiaHoje = sessoesHoje.reduce((soma, s) => soma + (s.energia_entregue_kwh || 0), 0)
  const custoHoje = sessoesHoje.reduce((soma, s) => soma + (s.energia_entregue_kwh || 0) * 2.1, 0)

  const cards = [
    {
      label: 'Energia disponível',
      value: `${energiaDisponivel.toFixed(1)} kW`,
      sub: `de ${limiteEnergia} kW limite`,
    },
    {
      label: 'Carregadores em uso',
      value: `${emUsoCount} / ${totalCarregadores}`,
      sub: totalCarregadores > 0 ? `${Math.round((emUsoCount / totalCarregadores) * 100)}% ocupados` : '—',
    },
    {
      label: 'Veículos na fila',
      value: `${filaCount}`,
      sub: filaCount > 0 ? 'Aguardando carregador' : 'Nenhuma fila agora',
    },
    {
      label: 'Energia entregue hoje',
      value: `${energiaHoje.toFixed(1)} kWh`,
      sub: `Custo gerado: R$ ${custoHoje.toFixed(2)}`,
    },
  ]

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {cards.map((card) => (
        <div key={card.label} className="bg-neutral-900 border border-neutral-800 rounded-xl p-4">
          <p className="text-xs text-neutral-500 mb-1">{card.label}</p>
          <p className="text-2xl font-semibold text-white">{card.value}</p>
          <p className="text-xs text-neutral-500 mt-1">{card.sub}</p>
        </div>
      ))}
    </div>
  )
}

export default TopStats
