/* ===========================================================================
   Sidebar — navegação principal
   ---------------------------------------------------------------------------
   Como plugar uma página nova (Histórico, Notificações, Configurações):
     1. troque `page: null` pelo id da página aqui embaixo (ex: 'historico')
     2. renderize a página no Dashboard.jsx: {pagina === 'historico' && <...>}
   Nada mais. Item com `page: null` já aparece desabilitado e marcado
   como "em breve" — é a fila de trabalho visível no próprio código.
   =========================================================================== */

export const NAV_GROUPS = [
  {
    titulo: 'Operação',
    itens: [
      { label: 'Dashboard', page: 'inicio', icon: 'dashboard' },
      { label: 'Assistente IA', page: null, acao: 'chat', icon: 'chat' },
      { label: 'Meus Veículos', page: 'veiculos', icon: 'car' },
      { label: 'Histórico de Recargas', page: 'historico', icon: 'history' },
    ],
  },
  {
    titulo: 'Conta',
    itens: [
      { label: 'Carteira', page: 'carteira', icon: 'wallet' },
      { label: 'Notificações', page: 'notificacoes', icon: 'bell' },
      { label: 'Configurações', page: 'configuracoes', icon: 'settings' },
      { label: 'Suporte', page: 'suporte', icon: 'help' },
    ],
  },
]

/* --------------------------------------------------------------------------
   Ícones (SVG inline — sem dependência nova no projeto)
   -------------------------------------------------------------------------- */

const PATHS = {
  dashboard: (
    <>
      <rect x="3" y="3" width="7.5" height="8.5" rx="1.5" />
      <rect x="13.5" y="3" width="7.5" height="5" rx="1.5" />
      <rect x="13.5" y="10.5" width="7.5" height="10.5" rx="1.5" />
      <rect x="3" y="14" width="7.5" height="7" rx="1.5" />
    </>
  ),
  car: (
    <>
      <path d="M5 11.5 6.4 7.2A2 2 0 0 1 8.3 5.8h7.4a2 2 0 0 1 1.9 1.4l1.4 4.3" />
      <rect x="3" y="11.5" width="18" height="6" rx="2" />
      <path d="M7 15h1.5M15.5 15H17" />
      <path d="M6.5 17.5V19M17.5 17.5V19" />
    </>
  ),
  history: (
    <>
      <path d="M3.2 12a8.8 8.8 0 1 0 2.9-6.5" />
      <path d="M3 4.5V9h4.5" />
      <path d="M12 7.8V12l2.8 1.8" />
    </>
  ),
  wallet: (
    <>
      <rect x="3" y="6" width="18" height="13" rx="2.5" />
      <path d="M3 10.2h18" />
      <circle cx="17" cy="14.8" r="1.1" />
    </>
  ),
  bell: (
    <>
      <path d="M18 9a6 6 0 1 0-12 0c0 6-2.2 7.5-2.2 7.5h16.4S18 15 18 9" />
      <path d="M13.8 20a2.2 2.2 0 0 1-3.6 0" />
    </>
  ),
  settings: (
    <>
      <path d="M4 7h4.5M13 7h7M4 12h9M17.5 12H20M4 17h2.5M11 17h9" />
      <circle cx="10.5" cy="7" r="2" />
      <circle cx="15" cy="12" r="2" />
      <circle cx="8.5" cy="17" r="2" />
    </>
  ),
  help: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.6 9.4a2.5 2.5 0 1 1 3.3 2.4c-.6.2-.9.7-.9 1.3v.4" />
      <path d="M12 16.6h.01" />
    </>
  ),
  power: (
    <>
      <path d="M12 4v7.5" />
      <path d="M7.6 7.2a7 7 0 1 0 8.8 0" />
    </>
  ),
  bolt: <path d="M13 2.5 4.8 13.8H11l-1 7.7 8.2-11.3H12l1-7.7Z" />,
  chat: (
    <>
      <path d="M20.5 12.2c0 4-3.8 7.2-8.5 7.2a9.9 9.9 0 0 1-2.6-.34L4.5 20.5l1.3-3.6A6.9 6.9 0 0 1 3.5 12.2C3.5 8.2 7.3 5 12 5s8.5 3.2 8.5 7.2Z" />
      <path d="M9.2 12h.01M12 12h.01M14.8 12h.01" />
    </>
  ),
}

function Ico({ name, className = 'h-[18px] w-[18px]' }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  )
}

/* --------------------------------------------------------------------------
   Item de navegação
   -------------------------------------------------------------------------- */

function NavItem({ item, ativo, onNavigate, onAcao, badge = 0 }) {
  const clicavel = item.page !== null || Boolean(item.acao)

  function acionar() {
    if (item.acao) return onAcao?.(item.acao)
    if (item.page) return onNavigate(item.page)
  }

  return (
    <button
      type="button"
      disabled={!clicavel}
      onClick={acionar}
      aria-current={ativo ? 'page' : undefined}
      className={`group relative flex w-full items-center gap-3 rounded-chip px-3.5 py-2.5 text-left text-[0.9375rem] transition-all duration-200 ${
        ativo
          ? 'bg-raise text-ink'
          : clicavel
            ? 'text-mute hover:bg-raise/60 hover:text-ink'
            : 'cursor-default text-dim/70'
      }`}
    >
      {ativo && <span className="bus" />}

      <Ico
        name={item.icon}
        className={`h-[18px] w-[18px] shrink-0 transition-colors duration-200 ${
          ativo ? 'text-flux' : clicavel ? 'text-dim group-hover:text-mute' : 'text-dim/60'
        }`}
      />

      <span className="truncate">{item.label}</span>

      {!clicavel && (
        <span className="ml-auto rounded-md border border-hair px-1.5 py-0.5 font-mono text-[0.5625rem] tracking-wider text-dim/80">
          EM BREVE
        </span>
      )}

      {badge > 0 && (
        <span className="num ml-auto rounded-md bg-flux px-1.5 py-0.5 text-[0.625rem] font-semibold text-white">
          {badge > 9 ? '9+' : badge}
        </span>
      )}

      {item.acao === 'chat' && (
        <span className="ml-auto rounded-md border border-flux/30 bg-flux/10 px-1.5 py-0.5 font-mono text-[0.5625rem] tracking-wider text-flux">
          BETA
        </span>
      )}
    </button>
  )
}

/* --------------------------------------------------------------------------
   Navegação compacta — abaixo de lg, onde a sidebar não cabe
   -------------------------------------------------------------------------- */

export function NavCompacta({ paginaAtiva, onNavigate }) {
  const itens = NAV_GROUPS.flatMap((g) => g.itens).filter((i) => i.page !== null)

  return (
    <nav className="scroll-slim flex gap-2 overflow-x-auto lg:hidden" aria-label="Navegação">
      {itens.map((item) => {
        const ativo = item.page === paginaAtiva
        return (
          <button
            key={item.label}
            type="button"
            onClick={() => onNavigate(item.page)}
            className={`flex shrink-0 items-center gap-2 rounded-chip border px-3 py-2 text-sm transition-colors duration-200 ${
              ativo
                ? 'border-flux/40 bg-flux/10 text-ink'
                : 'border-line bg-panel text-mute hover:text-ink'
            }`}
          >
            <Ico name={item.icon} className={`h-4 w-4 ${ativo ? 'text-flux' : 'text-dim'}`} />
            {item.label}
          </button>
        )
      })}
    </nav>
  )
}

/* --------------------------------------------------------------------------
   Sidebar
   -------------------------------------------------------------------------- */

function Sidebar({ sessao, paginaAtiva, onNavigate, onLogout, onAbrirChat, naoLidas = 0 }) {
  const { usuario, veiculo } = sessao

  const iniciais = (usuario.nome || '?')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0])
    .join('')
    .toUpperCase()

  return (
    <aside className="sticky top-0 hidden h-screen w-[276px] shrink-0 flex-col border-r border-line bg-panel/60 lg:flex 2xl:w-[300px]">
      {/* Marca */}
      <div className="flex items-center gap-3 px-6 pb-7 pt-7">
        <span className="flex h-9 w-9 items-center justify-center rounded-chip bg-flux/12 text-flux ring-1 ring-flux/25">
          <Ico name="bolt" className="h-[18px] w-[18px]" />
        </span>
        <div className="min-w-0">
          <p className="text-[1.0625rem] font-bold leading-none tracking-[0.14em] text-flux">
            GOODWE
          </p>
          <p className="mt-1.5 truncate text-[0.6875rem] tracking-wide text-dim">
            ChargeOps AI Assistant
          </p>
        </div>
      </div>

      {/* Navegação */}
      <nav className="scroll-slim flex-1 overflow-y-auto px-3.5 pb-4" aria-label="Navegação principal">
        {NAV_GROUPS.map((grupo, i) => (
          <div key={grupo.titulo} className={i > 0 ? 'mt-7' : ''}>
            <p className="eyebrow px-3.5 pb-2.5">{grupo.titulo}</p>
            <div className="space-y-1">
              {grupo.itens.map((item) => (
                <NavItem
                  key={item.label}
                  item={item}
                  ativo={item.page !== null && item.page === paginaAtiva}
                  onNavigate={onNavigate}
                  onAcao={(acao) => acao === 'chat' && onAbrirChat?.()}
                  badge={item.page === 'notificacoes' ? naoLidas : 0}
                />
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* Identidade do usuário */}
      <div className="border-t border-line p-3.5">
        <div className="rounded-panel border border-hair bg-raise/50 p-4">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-chip bg-flux/12 font-mono text-sm font-semibold text-flux ring-1 ring-flux/25">
              {iniciais}
            </span>
            <div className="min-w-0">
              <p className="truncate font-medium leading-tight text-ink">{usuario.nome}</p>
              <p className="mt-0.5 truncate text-xs capitalize text-dim">
                {usuario.tipo_usuario || usuario.papel || 'morador'}
              </p>
            </div>
          </div>

          <div className="mt-4 space-y-2.5 border-t border-hair pt-4 text-sm">
            {usuario.bloco_apto && (
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-xs text-dim">Bloco / Apto</span>
                <span className="truncate text-mute">{usuario.bloco_apto}</span>
              </div>
            )}
            {veiculo && (
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-xs text-dim">Veículo</span>
                <span className="truncate text-mute">{veiculo.modelo}</span>
              </div>
            )}
            {typeof usuario.saldo === 'number' && (
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-xs text-dim">Saldo</span>
                <span className="num text-[0.9375rem] font-semibold text-live">
                  R$ {usuario.saldo.toFixed(2)}
                </span>
              </div>
            )}
          </div>
        </div>

        <button
          type="button"
          onClick={onLogout}
          className="group mt-2.5 flex w-full items-center justify-center gap-2 rounded-chip px-3 py-2.5 text-sm text-dim transition-colors duration-200 hover:bg-flux/10 hover:text-flux"
        >
          <Ico name="power" className="h-4 w-4" />
          Sair
        </button>

        <p className="eyebrow mt-3 text-center text-[0.5625rem] text-dim/60">
          GoodWe · Smart Energy Innovator
        </p>
      </div>
    </aside>
  )
}

export default Sidebar
