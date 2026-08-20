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
    'w-full bg-panel border border-line rounded-lg px-4 py-2 text-ink placeholder-dim focus:outline-none focus:border-flux'
  const labelClass = 'text-sm text-mute mb-1 block'

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold">Meus Veículos</h2>
        <button
          onClick={() => setMostrarForm((v) => !v)}
          className="bg-flux hover:bg-flare px-4 py-2 rounded-lg text-sm font-medium transition"
        >
          {mostrarForm ? 'Cancelar' : '+ Adicionar veículo'}
        </button>
      </div>

      {mostrarForm && (
        <form onSubmit={handleAdicionar} className="bg-panel border border-line rounded-xl p-4 mb-6 space-y-3">
          {erro && (
            <div className="bg-flux/10 border border-flux/40 text-flux text-sm rounded-lg px-3 py-2">
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
            className="bg-flux hover:bg-flare disabled:opacity-50 px-4 py-2 rounded-lg text-sm font-medium transition"
          >
            {carregando ? 'Salvando...' : 'Salvar veículo'}
          </button>
        </form>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {veiculos.map((v) => (
          <div key={v.id} className="bg-panel border border-line rounded-xl p-4">
            <p className="font-medium text-ink">{v.modelo}</p>
            <p className="text-xs text-dim mb-3">{v.placa || 'Sem placa cadastrada'}</p>
            <div className="grid grid-cols-2 gap-2 text-xs text-mute">
              <div>
                <p className="text-dim">Bateria</p>
                <p className="text-ink">{v.capacidade_bateria_kwh} kWh</p>
              </div>
              <div>
                <p className="text-dim">Potência</p>
                <p className="text-ink">{v.potencia_carro_kw} kW</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default VeiculosPage
