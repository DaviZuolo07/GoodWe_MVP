function Dashboard({ sessao, onLogout }) {
  return (
    <div className="min-h-screen bg-neutral-950 text-white p-8">
      <h1 className="text-3xl font-bold text-red-500 mb-2">Dashboard (placeholder)</h1>
      <p className="text-neutral-400 mb-6">
        Logado como: {sessao.usuario.nome} — vamos construir o layout de verdade nos próximos passos.
      </p>
      <button
        className="bg-neutral-800 hover:bg-neutral-700 px-4 py-2 rounded-lg"
        onClick={onLogout}
      >
        Voltar pro login
      </button>
    </div>
  )
}

export default Dashboard
