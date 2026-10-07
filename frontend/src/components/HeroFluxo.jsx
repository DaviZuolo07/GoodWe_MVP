/* ===========================================================================
   HeroFluxo — a ilustração da tela de entrada
   ---------------------------------------------------------------------------
   O argumento do produto num desenho só: sol e rede entram no quadro, o quadro
   reparte a potência entre os carros SEM passar do limite. Puramente
   decorativa (aria-hidden): não mostra dado real, por isso não tem número.
   =========================================================================== */

const VAGAS = [
  { x: 372, nivel: 0.82, ativo: true },
  { x: 432, nivel: 0.46, ativo: true },
  { x: 492, nivel: 0, ativo: false },
  { x: 552, nivel: 0.64, ativo: true },
]

function HeroFluxo({ className = '' }) {
  return (
    <svg viewBox="14 34 566 240" className={className} aria-hidden="true" style={{ '--fluxo-dur': '1.3s' }}>
      {/* Sol */}
      <g className="entra" style={{ '--i': 1 }}>
        <circle cx="70" cy="74" r="15" fill="none" stroke="var(--color-queue)" strokeWidth="1.5" />
        <g stroke="var(--color-queue)" strokeWidth="1.5" strokeLinecap="round">
          {[0, 45, 90, 135, 180, 225, 270, 315].map((a) => (
            <path key={a} d="M70 50V44" transform={`rotate(${a} 70 74)`} />
          ))}
        </g>
        {/* Painel */}
        <path d="M44 122 96 122 106 150 34 150Z" fill="none" stroke="var(--color-mute)" strokeWidth="1.5" strokeLinejoin="round" />
        <path d="M70 122V150M40 136H100" stroke="var(--color-mute)" strokeWidth="1" />
      </g>

      {/* Rede */}
      <g className="entra" style={{ '--i': 2 }} stroke="var(--color-mute)" strokeWidth="1.5" strokeLinecap="round" fill="none">
        <path d="M70 196V256M52 208H88M57 220H83" />
      </g>

      {/* Condutores de entrada */}
      <g className="entra" style={{ '--i': 3 }}>
        <path className="fio" d="M106 138H170Q190 138 190 158V160" />
        <path className="fio" d="M88 214H170Q190 214 190 194V192" />
        <path className="corrente corrente-sol" d="M106 138H170Q190 138 190 158V160" />
        <path className="corrente" d="M88 214H170Q190 214 190 194V192" />
        <path className="fio" d="M190 176H222" />
        <path className="corrente" d="M190 176H222" />
      </g>

      {/* Quadro com o limite */}
      <g className="entra" style={{ '--i': 4 }}>
        <circle className="halo" cx="262" cy="176" r="50" fill="var(--color-flux)" />
        <circle cx="262" cy="176" r="40" fill="var(--color-panel)" stroke="var(--color-line)" strokeWidth="1.5" />
        <circle cx="262" cy="176" r="31" fill="none" stroke="var(--color-hair)" strokeWidth="5" />
        <circle cx="262" cy="176" r="31" fill="none" stroke="var(--color-flux)" strokeWidth="5" strokeLinecap="round"
                strokeDasharray="195" strokeDashoffset="52" transform="rotate(-90 262 176)" />
        <path d="M266 160 254 179H262L259 193 271 174H263Z" fill="var(--color-ink)" />
      </g>

      {/* Barramento e vagas */}
      <g className="entra" style={{ '--i': 5 }}>
        <path className="fio" d="M302 176H552" />
        <path className="corrente" d="M302 176H552" />
        {VAGAS.map((v, i) => (
          <g key={v.x}>
            <path className="fio" d={`M${v.x} 176V208`} />
            {v.ativo && <path className="corrente" d={`M${v.x} 176V208`} />}
            <circle cx={v.x} cy="176" r="3" fill={v.ativo ? 'var(--color-flux)' : 'var(--color-line)'} />
            {/* a bateria de cada carro */}
            <rect x={v.x - 16} y="210" width="32" height="52" rx="7" fill="var(--color-panel)"
                  stroke={v.ativo ? 'var(--color-flux)' : 'var(--color-line)'} strokeWidth="1.5" />
            <rect x={v.x - 5} y="205" width="10" height="5" rx="2" fill={v.ativo ? 'var(--color-flux)' : 'var(--color-line)'} />
            {v.ativo && (
              <rect className="pulsa" x={v.x - 11} y={257 - 42 * v.nivel} width="22" height={42 * v.nivel} rx="3.5"
                    fill="var(--color-flux)" style={{ animationDelay: `${i * 0.4}s` }} />
            )}
          </g>
        ))}
      </g>
    </svg>
  )
}

export default HeroFluxo
