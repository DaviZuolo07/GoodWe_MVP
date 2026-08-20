import { memo, useEffect, useState } from 'react'
import { CARRO_PADRAO, porteVeiculo } from '../lib/midia.js'

/**
 * Retrato do veículo.
 *
 * Uma imagem cinza única para todos: o card precisa comunicar "tem carro
 * plugado aqui", não identificar o modelo - isso já está escrito logo abaixo.
 * Sem imagem no /public, cai na silhueta vetorial.
 */

function Silhueta({ porte }) {
  const suv = porte === 'suv'

  const carroceria = suv
    ? 'M14 62 L22 40 C24 34 29 31 36 31 L88 31 C95 31 101 34 105 40 L118 58 L142 63 C148 64 150 68 150 73 L150 82 C150 85 148 87 145 87 L10 87 C7 87 5 85 5 82 L5 73 C5 67 8 63 14 62 Z'
    : 'M14 66 L24 46 C27 40 32 37 39 37 L86 37 C93 37 99 40 103 45 L117 62 L141 67 C147 68 150 71 150 76 L150 84 C150 87 148 89 145 89 L10 89 C7 89 5 87 5 84 L5 76 C5 70 8 67 14 66 Z'

  const vidros = suv
    ? 'M32 38 L84 38 C89 38 93 40 96 44 L104 56 L30 56 Z'
    : 'M36 43 L83 43 C87 43 91 45 94 48 L102 59 L33 59 Z'

  const eixoY = suv ? 87 : 89

  return (
    <svg viewBox="0 0 155 105" className="h-full w-auto" role="img" aria-hidden="true">
      <ellipse cx="77" cy={eixoY + 10} rx="66" ry="6" fill="var(--color-flux)" opacity="0.12" />
      <path d={carroceria} fill="#1b202b" stroke="#39404f" strokeWidth="1.2" strokeLinejoin="round" />
      <path d={vidros} fill="#0c0f15" stroke="#39404f" strokeWidth="1" strokeLinejoin="round" />
      <path d={`M60 ${suv ? 31 : 37} L60 ${suv ? 56 : 59}`} stroke="#39404f" strokeWidth="1" />
      <circle cx="38" cy={eixoY} r={suv ? 13 : 12} fill="#0a0c11" stroke="#3f4757" strokeWidth="2" />
      <circle cx="38" cy={eixoY} r={suv ? 5 : 4.5} fill="#2a3140" />
      <circle cx="116" cy={eixoY} r={suv ? 13 : 12} fill="#0a0c11" stroke="#3f4757" strokeWidth="2" />
      <circle cx="116" cy={eixoY} r={suv ? 5 : 4.5} fill="#2a3140" />
      <rect x="146" y={suv ? 68 : 72} width="5" height="4" rx="2" fill="var(--color-flux)" opacity="0.85" />
      <rect x="5" y={suv ? 68 : 72} width="5" height="4" rx="2" fill="#e8edf5" opacity="0.5" />
    </svg>
  )
}

function ArteVeiculo({ modelo, className = 'h-24' }) {
  const src = CARRO_PADRAO
  const [falhou, setFalhou] = useState(false)

  // Modelo novo = nova tentativa de carregar a imagem.
  useEffect(() => setFalhou(false), [modelo])

  return (
    <div className={`${className} relative flex w-full items-center justify-center`}>
      <span
        aria-hidden="true"
        className="pointer-events-none absolute bottom-0 left-1/2 h-2 w-32 -translate-x-1/2 rounded-full bg-flux/25 blur-[6px]"
      />

      {falhou || !src ? (
        <Silhueta porte={porteVeiculo(modelo)} />
      ) : (
        <img
          src={src}
          alt={modelo || 'Veículo'}
          loading="lazy"
          decoding="async"
          onError={() => setFalhou(true)}
          className="relative h-full w-auto object-contain drop-shadow-[0_10px_20px_rgba(0,0,0,0.5)]
                     transition-transform duration-300 ease-out group-hover:scale-[1.05]"
        />
      )}
    </div>
  )
}

export default memo(ArteVeiculo)
