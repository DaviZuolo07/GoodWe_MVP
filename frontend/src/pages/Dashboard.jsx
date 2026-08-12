import { useEffect, useState, useCallback } from 'react'
import { supabase } from '../supabaseClient.js'
import Sidebar from '../components/Sidebar.jsx'
import TopStats from '../components/TopStats.jsx'
import ChargerCard from '../components/ChargerCard.jsx'
import PagamentoModal from '../components/PagamentoModal.jsx'
import ConfirmarStopModal from '../components/ConfirmarStopModal.jsx'
import VeiculosPage from './VeiculosPage.jsx'
import CarteiraPage from './CarteiraPage.jsx'

const API_URL = import.meta.env.VITE_API_URL
const CONDOMINIO_ID = '11111111-1111-1111-1111-111111111111'

function Dashboard({ sessao: sessaoInicial, onLogout }) {
  const [sessao, setSessao] = useState(sessaoInicial)
  const [pagina, setPagina] = useState('inicio')

  const [condominio, setCondominio] = useState(null)
  const [chargers, setChargers] = useState([])
  const [sessions, setSessions] = useState([])
  const [veiculos, setVeiculos] = useState([])
  const [filaCount, setFilaCount] = useState(0)
  const [carregando, setCarregando] = useState(true)
  const [selectedCharger, setSelectedCharger] = useState(null)
  const [modalPagamentoAberto, setModalPagamentoAberto] = useState(false)
  const [modalStopAberto, setModalStopAberto] = useState(false)
  const [encerrando, setEncerrando] = useState(false)

  const carregarDados = useCallback(async () => {
    const [condRes, chargersRes, sessionsRes, filaRes, veiculosRes] = await Promise.all([
      supabase.from('condominios').select('*').eq('id', CONDOMINIO_ID).single(),
      supabase.from('carregadores').select('*').eq('condominio_id', CONDOMINIO_ID).order('numero'),
      supabase.from('sessoes_recarga').select('*, veiculos(modelo, placa)').eq('status', 'carregando'),
      supabase.from('fila').select('*', { count: 'exact', head: true }),
      supabase.from('veiculos').select('*').eq('usuario_id', sessao.usuario.id),
    ])

    if (condRes.data) setCondominio(condRes.data)
    if (chargersRes.data) setChargers(chargersRes.data)
    if (sessionsRes.data) setSessions(sessionsRes.data)
    if (veiculosRes.data) setVeiculos(veiculosRes.data)
    setFilaCount(filaRes.count || 0)
    setCarregando(false)
  }, [sessao.usuario.id])

  useEffect(() => {
    carregarDados()

    const canal = supabase
      .channel('dashboard-realtime')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'carregadores' }, carregarDados)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'sessoes_recarga' }, carregarDados)
      .subscribe()

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

  const sessaoSelecionada = selectedCharger ? sessaoDoCarregador(selectedCharger.id) : null
  const ehMinhaSessao = sessaoSelecionada && sessaoSelecionada.usuario_id === sessao.usuario.id

  return (
    <div className="min-h-screen bg-neutral-950 text-white flex">
      <Sidebar sessao={sessao} paginaAtiva={pagina} onNavigate={setPagina} onLogout={onLogout} />

      <main className="flex-1 p-6">
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

        {pagina === 'inicio' && (
          <>
            <div className="mb-6">
              <h2 className="text-xl font-bold">{condominio?.nome || 'Carregando...'}</h2>
              <p className="text-sm text-neutral-500">{condominio?.endereco}</p>
            </div>

            <TopStats chargers={chargers} sessions={sessions} condominio={condominio} filaCount={filaCount} />

            <h3 className="text-lg font-semibold mb-3">Carregadores</h3>

            {carregando ? (
              <p className="text-neutral-500">Carregando dados...</p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {chargers.map((charger) => (
                  <ChargerCard
                    key={charger.id}
                    charger={charger}
                    sessao={sessaoDoCarregador(charger.id)}
                    onSelecionar={setSelectedCharger}
                  />
                ))}
              </div>
            )}

            {selectedCharger && (
              <div className="mt-6 bg-neutral-900 border border-neutral-800 rounded-xl p-4 flex items-center justify-between">
                <div>
                  <p className="text-white font-medium">Carregador {selectedCharger.numero}</p>
                  <p className="text-sm text-neutral-500">
                    {selectedCharger.tipo} {selectedCharger.potencia_maxima_kw}kW • {selectedCharger.conector}
                  </p>
                </div>

                {selectedCharger.status === 'disponivel' && (
                  <button
                    onClick={() => setModalPagamentoAberto(true)}
                    className="bg-red-500 hover:bg-red-600 px-5 py-2 rounded-lg font-medium transition"
                  >
                    Iniciar recarga
                  </button>
                )}

                {selectedCharger.status === 'em_uso' && ehMinhaSessao && (
                  <button
                    onClick={() => setModalStopAberto(true)}
                    className="bg-neutral-800 hover:bg-red-500/20 hover:text-red-400 px-5 py-2 rounded-lg font-medium transition"
                  >
                    Encerrar recarga
                  </button>
                )}

                {selectedCharger.status === 'em_uso' && !ehMinhaSessao && (
                  <span className="text-sm text-neutral-500">Em uso por outro veículo</span>
                )}

                {selectedCharger.status === 'fila' && (
                  <span className="text-sm text-neutral-500">Aguardando liberação</span>
                )}
              </div>
            )}

            {modalPagamentoAberto && selectedCharger && (
              <PagamentoModal
                charger={selectedCharger}
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
          </>
        )}
      </main>
    </div>
  )
}

export default Dashboard
