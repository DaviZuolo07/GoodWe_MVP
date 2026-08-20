import { Component } from 'react'

/**
 * Rede de segurança.
 *
 * Sem isso, uma exceção em qualquer componente desmonta a árvore inteira e o
 * usuário vê uma tela preta sem explicação — que foi exatamente o que
 * aconteceu com o painel de fila. Com o boundary, a falha fica contida: o
 * resto da aplicação continua de pé e o erro aparece escrito na tela em vez
 * de só no console.
 *
 * Em produção você não mostraria a mensagem técnica. Aqui mostramos de
 * propósito: é um MVP em desenvolvimento e ver o erro acelera o conserto.
 */
class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { erro: null }
  }

  static getDerivedStateFromError(erro) {
    return { erro }
  }

  componentDidCatch(erro, info) {
    console.error('[ErrorBoundary]', erro, info?.componentStack)
  }

  render() {
    if (!this.state.erro) return this.props.children

    return (
      <div className="flex min-h-screen items-center justify-center bg-void p-6 font-display text-ink">
        <div className="w-full max-w-md rounded-panel border border-line bg-panel p-6">
          <span className="flex h-10 w-10 items-center justify-center rounded-chip bg-flux/12 text-flux ring-1 ring-flux/25">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 8v5M12 17h.01" />
              <circle cx="12" cy="12" r="9" />
            </svg>
          </span>

          <h1 className="mt-4 text-lg font-semibold">Algo quebrou nesta tela</h1>
          <p className="mt-1.5 text-sm leading-relaxed text-dim">
            O restante do sistema continua funcionando. Recarregue a página para voltar.
          </p>

          <pre className="scroll-slim mt-4 max-h-40 overflow-auto rounded-chip border border-hair bg-raise/50 p-3 font-mono text-[0.6875rem] leading-relaxed text-mute">
            {String(this.state.erro?.message || this.state.erro)}
          </pre>

          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-4 w-full rounded-chip bg-flux px-5 py-2.5 text-sm font-medium text-white transition-all duration-200 hover:bg-flare hover:shadow-flux"
          >
            Recarregar
          </button>
        </div>
      </div>
    )
  }
}

export default ErrorBoundary
