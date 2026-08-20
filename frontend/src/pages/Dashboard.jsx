import { useEffect, useState, useCallback } from 'react'
import { supabase } from '../supabaseClient.js'
import { API_URL, CONDOMINIO_PADRAO } from '../config.js'
import Sidebar, { NavCompacta } from '../components/Sidebar.jsx'
import TopStats from '../components/TopStats.jsx'
import ChargerCard from '../components/ChargerCard.jsx'
import PagamentoModal from '../components/PagamentoModal.jsx'
import ConfirmarStopModal from '../components/ConfirmarStopModal.jsx'
import ChatPanel, { BotaoChat } from '../components/ChatPanel.jsx'
import CondominioSelect, { useCondominios } from '../components/CondominioSelect.jsx'
import FilaPanel from '../components/FilaPanel.jsx'
import VeiculosPage from './VeiculosPage.jsx'
import CarteiraPage from './CarteiraPage.jsx'
import HistoricoPage from './HistoricoPage.jsx'
import NotificacoesPage from './NotificacoesPage.jsx'
import ConfiguracoesPage from './ConfiguracoesPage.jsx'
import SuportePage from './SuportePage.jsx'

const STATUS = {
  disponivel: { label: 'Disponível', cor: 'text-live', ponto: 'bg-live', borda: 'border-live/30', fundo: 'bg-live/10' },
  em_uso: { label: 'Em uso', cor: 'text-flux', ponto: 'bg-flux', borda: 'border-flux/30', fundo: 'bg-flux/10' },
  fila: { label: 'Fila', cor: 'text-queue', ponto: 'bg-queue', borda: 'border-queue/30', fundo: 'bg-queue/10' },
  offline: { label: 'Offline', cor: 'text-dim', ponto: 'bg-off', borda: 'border-line', fundo: 'bg-raise' },
}

/* --------------------------------------------------------------------------
   Relógio — estado próprio pra não re-renderizar o dashboard inteiro a cada
   segundo (o grid de carregadores não precisa saber que horas são).
   -------------------------------------------------------------------------- */
function Relogio() {
  const [agora, setAgora] = useState(() => new Date())

  useEffect(() => {
    const id = setInterval(() => setAgora(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="text-right leading-tight">
      <p className="num text-lg font-semibold text-ink">
        {agora.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
      </p>
      <p className="num text-[0.6875rem] text-dim">
        {agora.toLocaleDateString('pt-BR')}
      </p>
    </div>
  )
}

function StatusRealtime({ estado }) {
  const conectado = estado === 'SUBSCRIBED'
  return (
    <div
      className={`flex items-center gap-2 rounded-chip border px-3 py-1.5 transition-colors duration-300 ${
        conectado ? 'border-live/25 bg-live/8' : 'border-line bg-panel'
      }`}
      title={conectado ? 'Recebendo atualizações do banco em tempo real' : 'Reconectando ao canal de tempo real'}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${conectado ? 'bg-live text-live dot-live' : 'bg-queue'}`}
      />
      <span className="eyebrow text-[0.625rem] text-mute">
        {conectado ? 'Tempo real' : 'Conectando'}
      </span>
    </div>
  )
}

function Chip({ status }) {
  const s = STATUS[status] || STATUS.offline
  return (
    <span className={`inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs font-medium ${s.borda} ${s.fundo} ${s.cor}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.ponto}`} />
      {s.label}
    </span>
  )
}

function Spec({ label, valor, destaque }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2.5">
      <span className="text-sm text-dim">{label}</span>
      <span className={`num text-sm ${destaque || 'text-ink'}`}>{valor}</span>
    </div>
  )
}

/* --------------------------------------------------------------------------
   Painel de detalhe do carregador.
   Mesmas condições e mesmos handlers da versão anterior — só a moldura mudou.
   -------------------------------------------------------------------------- */
function PainelCarregador({ charger, sessaoAtiva, ehMinhaSessao, onFechar, onIniciar, onEncerrar }) {
  const temperatura = Number(charger.temperatura_c)
  const temTemperatura = Number.isFinite(temperatura)
  const derating = temTemperatura && temperatura > 35

  return (
    <div className="rise overflow-hidden rounded-panel border border-line bg-panel shadow-lift">
      <div className="flex items-start justify-between gap-4 border-b border-hair px-5 py-4">
        <div>
          <p className="eyebrow">Carregador</p>
          <p className="num mt-1 text-2xl font-semibold text-ink">{charger.numero}</p>
        </div>
        <div className="flex items-center gap-2">
          <Chip status={charger.status} />
          <button
            type="button"
            onClick={onFechar}
            aria-label="Fechar detalhe"
            className="rounded-md p-1.5 text-dim transition-colors duration-200 hover:bg-raise hover:text-ink"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
      </div>

      <div className="divide-y divide-hair px-5">
        <Spec label="Modelo" valor={charger.modelo || '—'} />
        <Spec label="Tipo" valor={charger.tipo} />
        <Spec label="Potência máxima" valor={`${charger.potencia_maxima_kw} kW`} />
        <Spec label="Conector" valor={charger.conector} />
        {charger.tensao_v != null && <Spec label="Tensão" valor={`${charger.tensao_v} V`} />}
        {charger.corrente_maxima_a != null && <Spec label="Corrente máxima" valor={`${charger.corrente_maxima_a} A`} />}
        <Spec label="Tarifa" valor={`R$ ${Number(charger.tarifa_kwh).toFixed(2)} / kWh`} />
        {temTemperatura && (
          <Spec
            label="Temperatura"
            valor={`${temperatura.toFixed(1)} °C`}
            destaque={derating ? 'text-queue' : 'text-ink'}
          />
        )}
      </div>

      {derating && (
        <p className="mx-5 mb-4 mt-3 rounded-chip border border-queue/25 bg-queue/8 px-3 py-2.5 text-xs leading-relaxed text-queue">
          Acima de 35 °C o carregador reduz a potência entregue. O tempo estimado já
          considera essa perda.
        </p>
      )}

      {/* Sessão em andamento neste carregador */}
      {sessaoAtiva && (
        <div className="mx-5 mb-4 rounded-panel border border-hair bg-raise/40 p-4">
          <div className="flex items-baseline justify-between gap-3">
            <p className="truncate font-medium text-ink">{sessaoAtiva.veiculos?.modelo || 'Veículo'}</p>
            <p className="num text-sm text-mute">{sessaoAtiva.veiculos?.placa}</p>
          </div>

          <div className="mt-3 flex items-center gap-3">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-raise">
              <div
                className="flux-bar h-full rounded-full transition-[width] duration-700 ease-out"
                style={{ width: `${sessaoAtiva.percentual_bateria_atual || 0}%` }}
              />
            </div>
            <span className="num text-sm font-semibold text-ink">
              {Math.round(sessaoAtiva.percentual_bateria_atual || 0)}%
            </span>
          </div>

          <div className="mt-4 grid grid-cols-3 gap-3">
            {[
              ['Potência', `${sessaoAtiva.potencia_atual_kw} kW`],
              ['Energia', `${Number(sessaoAtiva.energia_entregue_kwh || 0).toFixed(2)} kWh`],
              ['Restante', `${sessaoAtiva.tempo_estimado_min} min`],
            ].map(([label, valor]) => (
              <div key={label}>
                <p className="text-[0.6875rem] text-dim">{label}</p>
                <p className="num mt-0.5 text-sm text-ink">{valor}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="px-5 pb-5">
        {charger.status === 'disponivel' && (
          <button
            type="button"
            onClick={onIniciar}
            className="w-full rounded-chip bg-flux px-5 py-3 font-medium text-white transition-all duration-200 hover:bg-flare hover:shadow-flux active:scale-[0.99]"
          >
            Iniciar recarga
          </button>
        )}

        {charger.status === 'em_uso' && ehMinhaSessao && (
          <button
            type="button"
            onClick={onEncerrar}
            className="w-full rounded-chip border border-line bg-raise px-5 py-3 font-medium text-mute transition-all duration-200 hover:border-flux/40 hover:bg-flux/10 hover:text-flux"
          >
            Encerrar recarga
          </button>
        )}

        {charger.status === 'em_uso' && !ehMinhaSessao && (
          <p className="rounded-chip border border-hair bg-raise/40 px-4 py-3 text-center text-sm text-dim">
            Em uso por outro veículo
          </p>
        )}

        {charger.status === 'fila' && (
          <p className="rounded-chip border border-queue/25 bg-queue/8 px-4 py-3 text-center text-sm text-queue">
            Aguardando liberação
          </p>
        )}
      </div>
    </div>
  )
}

function EsqueletoCard() {
  return (
    <div className="rounded-panel border border-hair bg-panel p-5">
      <div className="flex items-center justify-between">
        <div className="skeleton h-6 w-10 rounded-md" />
        <div className="skeleton h-4 w-20 rounded-md" />
      </div>
      <div className="skeleton mt-6 h-5 w-2/3 rounded-md" />
      <div className="skeleton mt-2.5 h-4 w-1/3 rounded-md" />
      <div className="skeleton mt-6 h-1.5 w-full rounded-full" />
    </div>
  )
}

/* ========================================================================== */

function Dashboard({ sessao: sessaoInicial, onLogout }) {
  const [sessao, setSessao] = useState(sessaoInicial)
  const [pagina, setPagina] = useState('inicio')

  const [condominio, setCondominio] = useState(null)
  const [chargers, setChargers] = useState([])
  const [sessions, setSessions] = useState([])
  const [sessoesHoje, setSessoesHoje] = useState([])
  const [veiculos, setVeiculos] = useState([])
  const [filaCount, setFilaCount] = useState(0)
  const [carregando, setCarregando] = useState(true)
  const [selectedCharger, setSelectedCharger] = useState(null)
  const [modalPagamentoAberto, setModalPagamentoAberto] = useState(false)
  const [modalStopAberto, setModalStopAberto] = useState(false)
  const [encerrando, setEncerrando] = useState(false)
  const [realtime, setRealtime] = useState('CONNECTING')
  const [chatAberto, setChatAberto] = useState(false)
  const [naoLidas, setNaoLidas] = useState(0)

  // Local ativo: começa no condomínio do usuário e pode ser trocado no topo.
  // Trocar aqui recarrega carregadores, sessões e fila daquele local.
  const [condominioId, setCondominioId] = useState(
    sessaoInicial.usuario?.condominio_id || CONDOMINIO_PADRAO,
  )
  const { condominios, carregando: carregandoCondominios } = useCondominios()

  const carregarDados = useCallback(async () => {
    // Duas etapas de propósito.
    //
    // Sessões e fila não têm coluna de condomínio: elas apontam para um
    // carregador, e é o carregador que pertence a um local. Buscar tudo de
    // uma vez trazia a recarga de todos os condomínios para dentro do que
    // deveria ser a visão de um só — por isso primeiro descobrimos quais
    // carregadores são deste local, e só então filtramos por eles.
    const [condRes, chargersRes, veiculosRes, naoLidasRes] = await Promise.all([
      supabase.from('condominios').select('*').eq('id', condominioId).single(),
      supabase.from('carregadores').select('*').eq('condominio_id', condominioId).order('numero'),
      supabase.from('veiculos').select('*').eq('usuario_id', sessao.usuario.id),
      supabase
        .from('notificacoes')
        .select('*', { count: 'exact', head: true })
        .eq('usuario_id', sessao.usuario.id)
        .eq('lida', false),
    ])

    const chargersDoLocal = chargersRes.data || []
    const idsDoLocal = chargersDoLocal.map((c) => c.id)

    let sessoesDoLocal = []
    let filaDoLocal = []
    let sessoesHojeDoLocal = []

    // Meia-noite de hoje, no fuso do navegador.
    const inicioDoDia = new Date()
    inicioDoDia.setHours(0, 0, 0, 0)

    if (idsDoLocal.length > 0) {
      const [sessionsRes, filaRes, hojeRes] = await Promise.all([
        supabase
          .from('sessoes_recarga')
          .select('*, veiculos(modelo, placa)')
          .eq('status', 'carregando')
          .in('carregador_id', idsDoLocal),
        supabase.from('fila').select('id').in('carregador_id', idsDoLocal),
        // Tudo que rodou hoje neste local, encerrado ou não. Sem isso, a
        // energia do dia zerava toda vez que uma recarga terminava — como se
        // o que já foi entregue deixasse de existir.
        supabase
          .from('sessoes_recarga')
          .select('energia_entregue_kwh, iniciado_em, carregador_id')
          .in('carregador_id', idsDoLocal)
          .gte('iniciado_em', inicioDoDia.toISOString()),
      ])

      sessoesDoLocal = sessionsRes.data || []
      filaDoLocal = filaRes.data || []
      sessoesHojeDoLocal = hojeRes.data || []
    }

    if (condRes.data) setCondominio(condRes.data)
    setChargers(chargersDoLocal)
    setSessions(sessoesDoLocal)
    setSessoesHoje(sessoesHojeDoLocal)
    if (veiculosRes.data) setVeiculos(veiculosRes.data)
    setFilaCount(filaDoLocal.length)
    setNaoLidas(naoLidasRes.count || 0)
    setCarregando(false)
  }, [sessao.usuario.id, condominioId])

  useEffect(() => {
    carregarDados()

    const canal = supabase
      .channel('dashboard-realtime')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'carregadores' }, carregarDados)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'sessoes_recarga' }, carregarDados)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'notificacoes' }, carregarDados)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'fila' }, carregarDados)
      .subscribe((status) => setRealtime(status))

    return () => {
      supabase.removeChannel(canal)
    }
  }, [carregarDados])

  function sessaoDoCarregador(chargerId) {
    return sessions.find((s) => s.carregador_id === chargerId) || null
  }

  async function handleEncerrarRecarga(sessaoId) {
    setEncerrando(true)
    try {
      await fetch(`${API_URL}/charge/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessao_id: sessaoId }),
      })
      setModalStopAberto(false)
      setSelectedCharger(null)
    } finally {
      setEncerrando(false)
    }
  }

  // O carregador selecionado precisa refletir o estado mais recente do banco
  // (status muda sozinho pelo realtime) — por isso reconciliamos com a lista.
  const chargerSelecionado = selectedCharger
    ? chargers.find((c) => c.id === selectedCharger.id) || selectedCharger
    : null

  const sessaoSelecionada = chargerSelecionado ? sessaoDoCarregador(chargerSelecionado.id) : null
  const ehMinhaSessao = sessaoSelecionada && sessaoSelecionada.usuario_id === sessao.usuario.id

  const painel = chargerSelecionado ? (
    <PainelCarregador
      charger={chargerSelecionado}
      sessaoAtiva={sessaoSelecionada}
      ehMinhaSessao={ehMinhaSessao}
      onFechar={() => setSelectedCharger(null)}
      onIniciar={() => setModalPagamentoAberto(true)}
      onEncerrar={() => setModalStopAberto(true)}
    />
  ) : null

  // Sem carregador selecionado não existe coluna lateral: o grid ocupa a tela
  // inteira e ganha uma coluna a mais.
  const mostrarPainelLateral = pagina === 'inicio' && Boolean(chargerSelecionado)

  const gridCarregadores = chargerSelecionado
    ? 'grid grid-cols-1 gap-5 sm:grid-cols-2 2xl:grid-cols-3'
    : 'grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4'

  return (
    <div className="ambient flex min-h-screen bg-void font-display text-ink">
      <Sidebar
        sessao={sessao}
        paginaAtiva={pagina}
        onNavigate={setPagina}
        onLogout={onLogout}
        onAbrirChat={() => setChatAberto(true)}
        naoLidas={naoLidas}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* ---------------- Barra superior ---------------- */}
        <header className="sticky top-0 z-30 border-b border-line bg-void/85 backdrop-blur-xl">
          <div className="flex items-center justify-between gap-6 px-5 py-4 lg:px-9">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                {condominios.length > 0 ? (
                  <CondominioSelect
                    variante="titulo"
                    condominios={condominios}
                    valorId={condominioId}
                    carregando={carregandoCondominios}
                    onSelecionar={(c) => {
                      if (c.id === condominioId) return
                      // Limpa a visão do local anterior: sem isso, os cards do
                      // condomínio antigo ficam na tela até a nova consulta
                      // voltar, e por um instante o número mostrado é mentira.
                      setSelectedCharger(null)
                      setChargers([])
                      setSessions([])
                      setSessoesHoje([])
                      setFilaCount(0)
                      setCondominio(null)
                      setCarregando(true)
                      setCondominioId(c.id)
                    }}
                  />
                ) : condominio ? (
                  <h1 className="truncate text-xl font-semibold tracking-tight text-ink lg:text-2xl">
                    {condominio.nome}
                  </h1>
                ) : (
                  <div className="skeleton h-7 w-56 rounded-md" />
                )}

                {condominioId !== sessao.usuario?.condominio_id && (
                  <span className="rounded-md border border-queue/30 bg-queue/10 px-1.5 py-0.5 font-mono text-[0.5625rem] tracking-wider text-queue">
                    VISITANTE
                  </span>
                )}
              </div>
              <p className="mt-1 truncate text-sm text-dim">{condominio?.endereco}</p>
            </div>

            <div className="flex shrink-0 items-center gap-4">
              <div className="hidden sm:block">
                <StatusRealtime estado={realtime} />
              </div>
              <div className="hidden h-9 w-px bg-line sm:block" />
              <Relogio />
            </div>
          </div>

          {/* Navegação compacta abaixo de lg, onde a sidebar não aparece */}
          <div className="px-5 pb-3 lg:hidden">
            <NavCompacta paginaAtiva={pagina} onNavigate={setPagina} />
          </div>
        </header>

        {/* ---------------- Conteúdo + coluna de detalhe ---------------- */}
        <div className="flex min-w-0 flex-1">
          <main className="min-w-0 flex-1 px-5 py-7 lg:px-9 lg:py-9">
            <div className="mx-auto w-full max-w-[1360px]">
              {pagina === 'veiculos' && (
                <VeiculosPage sessao={sessao} veiculos={veiculos} onVeiculoAdicionado={carregarDados} />
              )}

              {pagina === 'carteira' && (
                <CarteiraPage
                  sessao={sessao}
                  onSaldoAtualizado={(novoSaldo) =>
                    setSessao((s) => ({ ...s, usuario: { ...s.usuario, saldo: novoSaldo } }))
                  }
                />
              )}

              {pagina === 'historico' && <HistoricoPage sessao={sessao} />}

              {pagina === 'notificacoes' && <NotificacoesPage sessao={sessao} />}

              {pagina === 'configuracoes' && (
                <ConfiguracoesPage
                  sessao={sessao}
                  condominio={condominio}
                  onUsuarioAtualizado={(campos) =>
                    setSessao((s) => ({ ...s, usuario: { ...s.usuario, ...campos } }))
                  }
                />
              )}

              {pagina === 'suporte' && <SuportePage onAbrirChat={() => setChatAberto(true)} />}

              {pagina === 'inicio' && (
                <>
                  <TopStats
                    chargers={chargers}
                    sessoesHoje={sessoesHoje}
                    sessions={sessions}
                    condominio={condominio}
                    filaCount={filaCount}
                  />

                  <div className="mb-5 mt-10 flex flex-wrap items-end justify-between gap-3">
                    <div>
                      <h2 className="text-xl font-semibold tracking-tight text-ink lg:text-[1.375rem]">
                        Carregadores
                      </h2>
                      <p className="mt-1 text-sm text-dim">
                        Selecione um carregador disponível para iniciar sua recarga.
                      </p>
                    </div>

                    <div className="flex items-center gap-4">
                      {['disponivel', 'em_uso', 'fila'].map((s) => (
                        <span key={s} className="flex items-center gap-2 text-xs text-mute">
                          <span className={`h-1.5 w-1.5 rounded-full ${STATUS[s].ponto}`} />
                          {STATUS[s].label}
                        </span>
                      ))}
                    </div>
                  </div>

                  {carregando ? (
                    <div className={gridCarregadores}>
                      {Array.from({ length: 6 }).map((_, i) => (
                        <EsqueletoCard key={i} />
                      ))}
                    </div>
                  ) : chargers.length === 0 ? (
                    <div className="rounded-panel border border-dashed border-line bg-panel/40 px-6 py-14 text-center">
                      <p className="font-medium text-ink">Nenhum carregador neste local</p>
                      <p className="mt-1.5 text-sm text-dim">
                        Cadastre um carregador no banco para que ele apareça aqui.
                      </p>
                    </div>
                  ) : (
                    <div className={gridCarregadores}>
                      {chargers.map((charger) => (
                        <ChargerCard
                          key={charger.id}
                          charger={charger}
                          sessao={sessaoDoCarregador(charger.id)}
                          selecionado={chargerSelecionado?.id === charger.id}
                          onSelecionar={setSelectedCharger}
                        />
                      ))}
                    </div>
                  )}

                  {/* Abaixo de xl não existe coluna lateral: o painel entra no fluxo */}
                  {chargerSelecionado && (
                    <div className="mt-6 xl:hidden">
                      {painel}
                      {chargerSelecionado.status === 'fila' && (
                        <div className="mt-6">
                          <FilaPanel
                            charger={chargerSelecionado}
                            sessaoAtiva={sessaoSelecionada}
                            usuarioId={sessao.usuario.id}
                          />
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </main>

          {mostrarPainelLateral && (
            <aside className="slide-in hidden w-[368px] shrink-0 border-l border-line bg-panel/30 xl:block 2xl:w-[400px]">
              <div className="scroll-slim sticky top-[89px] max-h-[calc(100vh-89px)] overflow-y-auto px-5 py-7">
                <p className="eyebrow mb-3">Detalhe</p>
                {painel}

                {chargerSelecionado?.status === 'fila' && (
                  <div className="mt-6 border-t border-hair pt-6">
                    <FilaPanel
                      charger={chargerSelecionado}
                      sessaoAtiva={sessaoSelecionada}
                      usuarioId={sessao.usuario.id}
                    />
                  </div>
                )}

                {/* ChatPanel entra aqui embaixo, na mesma coluna. */}
              </div>
            </aside>
          )}
        </div>
      </div>

      {/* ---------------- Assistente ---------------- */}
      <BotaoChat onClick={() => setChatAberto(true)} escondido={chatAberto} />
      <ChatPanel
        sessao={sessao}
        chargerId={chargerSelecionado?.id}
        aberto={chatAberto}
        onFechar={() => setChatAberto(false)}
      />

      {/* ---------------- Modais (lógica intocada) ---------------- */}
      {modalPagamentoAberto && chargerSelecionado && (
        <PagamentoModal
          charger={chargerSelecionado}
          sessao={sessao}
          veiculos={veiculos}
          onClose={() => setModalPagamentoAberto(false)}
          onSucesso={(novoSaldo) => {
            setSessao((s) => ({ ...s, usuario: { ...s.usuario, saldo: novoSaldo } }))
            setModalPagamentoAberto(false)
            setSelectedCharger(null)
          }}
          onIrParaCarteira={() => {
            setModalPagamentoAberto(false)
            setPagina('carteira')
          }}
        />
      )}

      {modalStopAberto && sessaoSelecionada && (
        <ConfirmarStopModal
          carregando={encerrando}
          onCancelar={() => setModalStopAberto(false)}
          onConfirmar={() => handleEncerrarRecarga(sessaoSelecionada.id)}
        />
      )}
    </div>
  )
}

export default Dashboard
