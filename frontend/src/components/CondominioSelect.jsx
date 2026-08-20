import { useEffect, useMemo, useRef, useState } from 'react'
import { API_URL } from '../config.js'

/**
 * Seletor de condomínio.
 *
 * Usado em dois lugares com aparências diferentes:
 *   - `variante="campo"`  -> no cadastro, como campo de formulário
 *   - `variante="titulo"` -> no topo do Dashboard, como troca de local
 *
 * A busca existe porque uma rede real tem dezenas de condomínios: rolar uma
 * lista inteira não escala, digitar três letras sim.
 */

export function useCondominios() {
  const [condominios, setCondominios] = useState([])
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState('')

  useEffect(() => {
    let cancelado = false

    async function carregar() {
      try {
        const res = await fetch(`${API_URL}/condominios`)
        const data = await res.json()
        if (cancelado) return
        setCondominios(Array.isArray(data) ? data : [])
      } catch {
        if (!cancelado) setErro('Não foi possível carregar os condomínios.')
      } finally {
        if (!cancelado) setCarregando(false)
      }
    }

    carregar()
    return () => {
      cancelado = true
    }
  }, [])

  return { condominios, carregando, erro }
}

function normalizar(texto) {
  return (texto || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
}

function CondominioSelect({
  condominios,
  valorId,
  onSelecionar,
  variante = 'campo',
  carregando = false,
}) {
  const [aberto, setAberto] = useState(false)
  const [busca, setBusca] = useState('')
  const caixaRef = useRef(null)

  const selecionado = condominios.find((c) => c.id === valorId) || null

  const filtrados = useMemo(() => {
    const q = normalizar(busca)
    if (!q) return condominios
    return condominios.filter(
      (c) => normalizar(c.nome).includes(q) || normalizar(c.endereco).includes(q),
    )
  }, [condominios, busca])

  // Fecha ao clicar fora
  useEffect(() => {
    if (!aberto) return
    function onClique(e) {
      if (!caixaRef.current?.contains(e.target)) setAberto(false)
    }
    function onEsc(e) {
      if (e.key === 'Escape') setAberto(false)
    }
    document.addEventListener('mousedown', onClique)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onClique)
      document.removeEventListener('keydown', onEsc)
    }
  }, [aberto])

  function escolher(c) {
    onSelecionar(c)
    setAberto(false)
    setBusca('')
  }

  const ehTitulo = variante === 'titulo'

  return (
    <div ref={caixaRef} className="relative">
      <button
        type="button"
        onClick={() => setAberto((v) => !v)}
        aria-expanded={aberto}
        aria-haspopup="listbox"
        className={
          ehTitulo
            ? 'group flex max-w-full items-center gap-2 rounded-chip px-2 py-1 -mx-2 transition-colors duration-200 hover:bg-raise/60'
            : 'flex w-full items-center justify-between gap-3 rounded-chip border border-line bg-raise/50 px-4 py-2.5 text-left text-sm transition-colors duration-200 hover:border-flux/40 focus:border-flux/50 focus:outline-none'
        }
      >
        {ehTitulo ? (
          <h1 className="truncate text-xl font-semibold tracking-tight text-ink lg:text-2xl">
            {selecionado?.nome || (carregando ? 'Carregando...' : 'Selecionar local')}
          </h1>
        ) : (
          <span className={selecionado ? 'truncate text-ink' : 'text-dim'}>
            {selecionado?.nome || (carregando ? 'Carregando condomínios...' : 'Escolha seu condomínio')}
          </span>
        )}

        <svg
          viewBox="0 0 24 24"
          className={`h-4 w-4 shrink-0 transition-transform duration-200 ${
            ehTitulo ? 'text-dim group-hover:text-mute' : 'text-dim'
          } ${aberto ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {aberto && (
        <div className="slide-in absolute left-0 z-50 mt-2 w-[min(380px,90vw)] overflow-hidden rounded-panel border border-line bg-panel shadow-lift">
          <div className="border-b border-hair p-3">
            <input
              autoFocus
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              placeholder="Buscar por nome ou endereço"
              className="w-full rounded-chip border border-line bg-raise/50 px-3.5 py-2 text-sm text-ink
                         placeholder-dim transition-colors duration-200 focus:border-flux/50 focus:outline-none"
            />
          </div>

          <ul className="scroll-slim max-h-72 overflow-y-auto py-1" role="listbox">
            {filtrados.length === 0 && (
              <li className="px-4 py-6 text-center text-sm text-dim">
                Nenhum condomínio encontrado.
              </li>
            )}

            {filtrados.map((c) => {
              const ativo = c.id === valorId
              return (
                <li key={c.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={ativo}
                    onClick={() => escolher(c)}
                    className={`flex w-full items-start gap-3 px-4 py-3 text-left transition-colors duration-150 ${
                      ativo ? 'bg-flux/10' : 'hover:bg-raise/60'
                    }`}
                  >
                    <span
                      className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                        ativo ? 'bg-flux' : 'bg-off'
                      }`}
                    />
                    <span className="min-w-0">
                      <span className={`block truncate text-sm ${ativo ? 'text-ink' : 'text-mute'}`}>
                        {c.nome}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-dim">{c.endereco}</span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}

export default CondominioSelect
