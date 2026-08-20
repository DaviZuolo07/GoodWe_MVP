import { memo, useState } from 'react'
import { fotoCarregador } from '../lib/midia.js'

/**
 * Retrato do carregador.
 *
 * A foto fica sobre uma "plataforma" de luz: um halo radial na cor do status
 * mais um brilho neutro. Isso resolve dois problemas de uma vez — dá o clima
 * de vitrine de produto e disfarça a diferença entre um recorte transparente
 * e uma foto com fundo claro.
 *
 * Se a foto não carregar, cai no wallbox vetorial. O produto nunca fica com
 * um card furado.
 */

const COR_STATUS = {
  disponivel: 'var(--color-live)',
  em_uso: 'var(--color-flux)',
  fila: 'var(--color-queue)',
  offline: 'var(--color-off)',
}

function WallboxVetorial({ cor, ativo }) {
  return (
    <svg viewBox="0 0 120 150" className="h-full w-auto" role="img" aria-label="Carregador">
      <ellipse cx="60" cy="70" rx="50" ry="56" fill={cor} opacity="0.10" />
      <path d="M60 116 C60 132 84 128 92 138 C98 145 88 149 80 145" fill="none" stroke="#0f1218" strokeWidth="7" strokeLinecap="round" />
      <path d="M60 116 C60 132 84 128 92 138 C98 145 88 149 80 145" fill="none" stroke="#20252f" strokeWidth="3" strokeLinecap="round" />
      <rect x="27" y="8" width="66" height="110" rx="16" fill="#171b24" stroke="#39404f" strokeWidth="1" />
      <rect x="42" y="20" width="36" height="4" rx="2" fill={cor} opacity={ativo ? 1 : 0.9}>
        {ativo && <animate attributeName="opacity" values="1;0.25;1" dur="2.4s" repeatCount="indefinite" />}
      </rect>
      <circle cx="60" cy="76" r="19" fill="#0a0c11" stroke="#3a4150" strokeWidth="1.5" />
      <circle cx="60" cy="76" r="14.5" fill="#12151d" />
      <circle cx="53.5" cy="69" r="3.4" fill="#454d5e" />
      <circle cx="66.5" cy="69" r="3.4" fill="#454d5e" />
      <circle cx="49.5" cy="78.5" r="2.2" fill="#3a4150" />
      <circle cx="56" cy="83" r="2.2" fill="#3a4150" />
      <circle cx="64" cy="83" r="2.2" fill="#3a4150" />
      <circle cx="70.5" cy="78.5" r="2.2" fill="#3a4150" />
    </svg>
  )
}

function ArteCarregador({ status = 'disponivel', modelo, className = 'h-32' }) {
  const [falhou, setFalhou] = useState(false)
  const cor = COR_STATUS[status] || COR_STATUS.offline
  const ativo = status === 'em_uso'
  const src = fotoCarregador(modelo)

  return (
    <div className={`${className} relative flex w-full items-center justify-center`}>
      {/* plataforma de luz */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 rounded-panel opacity-80 transition-opacity duration-300 group-hover:opacity-100"
        style={{
          background: `radial-gradient(58% 62% at 50% 42%, ${cor}22, transparent 72%),
                       radial-gradient(38% 40% at 50% 30%, rgba(255,255,255,0.10), transparent 70%)`,
        }}
      />

      {/* sombra de apoio — elipse difusa, não uma barra */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute bottom-2 left-1/2 h-3 w-28 -translate-x-1/2 -translate-y-0 rounded-[100%] blur-[10px] transition-all duration-300 group-hover:w-32"
        style={{ background: cor, opacity: 0.16 }}
      />

      {falhou || !src ? (
        <WallboxVetorial cor={cor} ativo={ativo} />
      ) : (
        <img
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => setFalhou(true)}
          className="relative h-full w-auto object-contain drop-shadow-[0_10px_24px_rgba(0,0,0,0.55)]
                     transition-transform duration-300 ease-out group-hover:-translate-y-1 group-hover:scale-[1.04]"
        />
      )}
    </div>
  )
}

export default memo(ArteCarregador)
