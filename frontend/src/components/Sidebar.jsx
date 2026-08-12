function Sidebar({ sessao, paginaAtiva, onNavigate, onLogout }) {
  const { usuario, veiculo } = sessao

  const navItems = [
    { label: 'Dashboard', page: 'inicio' },
    { label: 'Meus Veículos', page: 'veiculos' },
    { label: 'Carteira', page: 'carteira' },
    { label: 'Histórico de Recargas', page: null },
    { label: 'Notificações', page: null },
    { label: 'Configurações', page: null },
    { label: 'Suporte', page: null },
  ]

  return (
    <aside className="w-64 bg-neutral-950 border-r border-neutral-800 flex flex-col h-screen sticky top-0">
      <div className="p-6">
        <h1 className="text-xl font-bold text-red-500">GOODWE</h1>
        <p className="text-xs text-neutral-500">ChargeOps AI Assistant</p>
      </div>

      <nav className="flex-1 px-3 space-y-1">
        {navItems.map((item) => {
          const ativo = item.page === paginaAtiva
          const clicavel = item.page !== null
          return (
            <button
              key={item.label}
              disabled={!clicavel}
              onClick={() => clicavel && onNavigate(item.page)}
              className={`w-full text-left px-3 py-2 rounded-lg text-sm transition ${
                ativo
                  ? 'bg-red-500/10 text-red-400 border border-red-500/30'
                  : clicavel
                  ? 'text-neutral-400 hover:bg-neutral-900 hover:text-white'
                  : 'text-neutral-700 cursor-default'
              }`}
            >
              {item.label}
            </button>
          )
        })}
      </nav>

      <div className="p-4 border-t border-neutral-800">
        <div className="bg-neutral-900 rounded-xl p-4 mb-3">
          <p className="font-medium text-white">{usuario.nome}</p>
          <p className="text-xs text-neutral-500 mb-2 capitalize">{usuario.tipo_usuario || 'morador'}</p>

          <div className="text-xs text-neutral-400 space-y-1">
            {usuario.bloco_apto && <p>Bloco/Apto: {usuario.bloco_apto}</p>}
            {veiculo && <p>Veículo: {veiculo.modelo}</p>}
            {typeof usuario.saldo === 'number' && (
              <p className="text-green-400 font-medium pt-1">Saldo: R$ {usuario.saldo.toFixed(2)}</p>
            )}
          </div>
        </div>

        <button
          onClick={onLogout}
          className="w-full text-sm text-neutral-500 hover:text-red-400 transition"
        >
          Sair
        </button>
      </div>
    </aside>
  )
}

export default Sidebar
