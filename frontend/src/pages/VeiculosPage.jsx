import { useState } from 'react'
import { post } from '../lib/api.js'
import { energia, potencia } from '../lib/formato.js'

/** Presets: o celular da bancada do ESP32 tem ~15 Wh e puxa ~18 W. */
const PRESETS = {
  carro: { capacidade: 40, potencia: 7.4, rotulo: 'Carro elétrico' },
  celular: { capacidade: 0.015, potencia: 0.018, rotulo: 'Celular (bancada ESP32)' },
}

function VeiculosPage({ veiculos, onVeiculoAdicionado }) {
  const [mostrarForm, setMostrarForm] = useState(false)
  const [tipo, setTipo] = useState('carro')
  const [modelo, setModelo] = useState('')
  const [placa, setPlaca] = useState('')
  const [capacidade, setCapacidade] = useState(40)
  const [potenciaKw, setPotenciaKw] = useState(7.4)
  const [erro, setErro] = useState('')
  const [carregando, setCarregando] = useState(false)

  async function handleAdicionar(e) {
    e.preventDefault()
    setErro('')
    setCarregando(true)
    try {
      await post('/me/veiculos', {
        modelo,
        placa: placa || null,
        tipo,
        capacidade_bateria_kwh: Number(capacidade),
        potencia_carro_kw: Number(potenciaKw),
      })
      onVeiculoAdicionado()
      setModelo(''); setPlaca(''); setMostrarForm(false)
    } catch (e) {
      setErro(e.message)
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
          <div>
            <label className={labelClass}>Tipo</label>
            <div className="flex gap-2">
              {Object.entries(PRESETS).map(([chave, preset]) => (
                <button key={chave} type="button"
                        onClick={() => {
                          setTipo(chave)
                          setCapacidade(preset.capacidade)
                          setPotenciaKw(preset.potencia)
                        }}
                        className={`flex-1 rounded-chip py-2 text-sm transition ${
                          tipo === chave ? 'bg-flux text-white' : 'bg-raise text-mute hover:bg-line'}`}>
                  {preset.rotulo}
                </button>
              ))}
            </div>
            <p className="mt-1.5 text-xs text-dim">
              O ponto do ESP32 é uma bancada USB: só aceita dispositivos do tipo celular.
            </p>
          </div>

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
              <input className={inputClass} type="number" step="0.001" value={capacidade} onChange={(e) => setCapacidade(e.target.value)} />
            </div>
            <div>
              <label className={labelClass}>Potência aceita (kW)</label>
              <input className={inputClass} type="number" step="0.001" value={potenciaKw} onChange={(e) => setPotenciaKw(e.target.value)} />
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
            <div className="mb-3 flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate font-medium text-ink">{v.modelo}</p>
                <p className="text-xs text-dim">{v.placa || (v.tipo === 'celular' ? 'Dispositivo de bancada' : 'Sem placa')}</p>
              </div>
              {v.tipo === 'celular' && (
                <span className="rounded-md border border-flux/30 bg-flux/10 px-1.5 py-0.5 text-[0.5625rem] text-flux">
                  ESP32
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs text-mute">
              <div>
                <p className="text-dim">Bateria</p>
                <p className="num text-ink">{energia(v.capacidade_bateria_kwh, 3)}</p>
              </div>
              <div>
                <p className="text-dim">Potência</p>
                <p className="num text-ink">{potencia(v.potencia_carro_kw)}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default VeiculosPage
