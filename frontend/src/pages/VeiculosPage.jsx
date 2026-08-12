import { useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL

function VeiculosPage({ sessao, veiculos, onVeiculoAdicionado }) {
  const [mostrarForm, setMostrarForm] = useState(false)
  const [modelo, setModelo] = useState('')
  const [placa, setPlaca] = useState('')
  const [capacidade, setCapacidade] = useState(40)
  const [potencia, setPotencia] = useState(7.4)
  const [erro, setErro] = useState('')
  const [carregando, setCarregando] = useState(false)

  async function handleAdicionar(e) {
    e.preventDefault()
    setErro('')
    setCarregando(true)
    try {
      const res = await fetch(`${API_URL}/veiculos`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          usuario_id: sessao.usuario.id,
          modelo,
          placa,
          capacidade_bateria_kwh: Number(capacidade),
          potencia_carro_kw: Number(potencia),
        }),
      })
      const data = await res.json()
      if (!res.ok) {
        setErro(data.detail || 'Não foi possível adicionar o veículo.')
        return
      }
      onVeiculoAdicionado()
      setModelo('')
      setPlaca('')
      setCapacidade(40)
      setPotencia(7.4)
      setMostrarForm(false)
    } catch {
      setErro('Não foi possível conectar ao servidor.')
    } finally {
      setCarregando(false)
    }
  }

  const inputClass =
    'w-full bg-neutral-900 border border-neutral-700 rounded-lg px-4 py-2 text-white placeholder-neutral-500 focus:outline-none focus:border-red-500'
  const labelClass = 'text-sm text-neutral-400 mb-1 block'

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold">Meus Veículos</h2>
        <button
          onClick={() => setMostrarForm((v) => !v)}
          className="bg-red-500 hover:bg-red-600 px-4 py-2 rounded-lg text-sm font-medium transition"
        >
          {mostrarForm ? 'Cancelar' : '+ Adicionar veículo'}
        </button>
      </div>

      {mostrarForm && (
        <form onSubmit={handleAdicionar} className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 mb-6 space-y-3">
          {erro && (
            <div className="bg-red-500/10 border border-red-500/40 text-red-400 text-sm rounded-lg px-3 py-2">
              {erro}
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelClass}>Modelo</label>
              <input className={inputClass} value={modelo} onChange={(e) => setModelo(e.target.value)} required />
            </div>
            <div>
              <label className={labelClass}>Placa</label>
              <input className={inputClass} value={placa} onChange={(e) => setPlaca(e.target.value)} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelClass}>Capacidade da bateria (kWh)</label>
              <input className={inputClass} type="number" value={capacidade} onChange={(e) => setCapacidade(e.target.value)} />
            </div>
            <div>
              <label className={labelClass}>Potência do carro (kW)</label>
              <input className={inputClass} type="number" step="0.1" value={potencia} onChange={(e) => setPotencia(e.target.value)} />
            </div>
          </div>
          <button
            type="submit"
            disabled={carregando}
            className="bg-red-500 hover:bg-red-600 disabled:opacity-50 px-4 py-2 rounded-lg text-sm font-medium transition"
          >
            {carregando ? 'Salvando...' : 'Salvar veículo'}
          </button>
        </form>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {veiculos.map((v) => (
          <div key={v.id} className="bg-neutral-900 border border-neutral-800 rounded-xl p-4">
            <p className="font-medium text-white">{v.modelo}</p>
            <p className="text-xs text-neutral-500 mb-3">{v.placa || 'Sem placa cadastrada'}</p>
            <div className="grid grid-cols-2 gap-2 text-xs text-neutral-400">
              <div>
                <p className="text-neutral-600">Bateria</p>
                <p className="text-white">{v.capacidade_bateria_kwh} kWh</p>
              </div>
              <div>
                <p className="text-neutral-600">Potência</p>
                <p className="text-white">{v.potencia_carro_kw} kW</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default VeiculosPage
