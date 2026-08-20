import { useEffect, useRef, useState } from 'react'
import { API_URL } from '../config.js'

/**
 * Assistente ChargeOps.
 *
 * Hoje fala com POST /chatbot, que responde por regras usando os dados reais
 * do Supabase. Quando o Ollama + RAG entrarem, só o backend muda — este
 * componente continua igual, porque o contrato é o mesmo:
 *   envia { message, usuario_id, charger_id } -> recebe { reply, timestamp }
 *
 * O histórico vem de `chat_mensagens`, que o backend já grava nos dois lados
 * da conversa. Por isso a conversa sobrevive a um F5.
 */

const SUGESTOES = [
  'Quais carregadores estão disponíveis?',
  'Quanto tempo falta para minha recarga?',
  'Qual a potência da minha recarga?',
  'Qual o custo estimado até agora?',
]

function Balao({ de, texto, hora }) {
  const meu = de === 'usuario'

  return (
    <div className={`flex ${meu ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`rise max-w-[85%] rounded-panel px-4 py-2.5 text-sm leading-relaxed ${
          meu
            ? 'bg-flux text-white'
            : 'border border-hair bg-raise/70 text-ink'
        }`}
      >
        <p className="whitespace-pre-wrap">{texto}</p>
        {hora && (
          <p className={`num mt-1.5 text-[0.625rem] ${meu ? 'text-white/70' : 'text-dim'}`}>
            {hora}
          </p>
        )}
      </div>
    </div>
  )
}

function horaDe(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
}

function ChatPanel({ sessao, chargerId, aberto, onFechar }) {
  const usuarioId = sessao?.usuario?.id
  const primeiroNome = (sessao?.usuario?.nome || '').split(' ')[0]

  const [mensagens, setMensagens] = useState([])
  const [texto, setTexto] = useState('')
  const [pensando, setPensando] = useState(false)
  const [erro, setErro] = useState('')

  const fimRef = useRef(null)
  const inputRef = useRef(null)

  // Chat operacional, não assistente de conversa longa: cada abertura começa
  // do zero. O backend continua gravando em `chat_mensagens` para auditoria,
  // mas a interface não traz o histórico de volta.
  useEffect(() => {
    if (aberto) {
      inputRef.current?.focus()
      return
    }
    setMensagens([])
    setTexto('')
    setErro('')
    setPensando(false)
  }, [aberto])

  // Rolagem para a última mensagem
  useEffect(() => {
    fimRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [mensagens, pensando])

  // Esc fecha
  useEffect(() => {
    if (!aberto) return
    const onKey = (e) => e.key === 'Escape' && onFechar()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [aberto, onFechar])

  async function enviar(mensagem) {
    const conteudo = (mensagem ?? texto).trim()
    if (!conteudo || pensando) return

    setErro('')
    setTexto('')
    setPensando(true)

    const agora = new Date().toISOString()
    setMensagens((m) => [
      ...m,
      { id: `local-${agora}`, de: 'usuario', texto: conteudo, hora: horaDe(agora) },
    ])

    try {
      const res = await fetch(`${API_URL}/chatbot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: conteudo,
          usuario_id: usuarioId,
          charger_id: chargerId || null,
        }),
      })
      const data = await res.json()

      if (!res.ok) {
        setErro(data.detail || 'O assistente não respondeu. Tente de novo.')
        return
      }

      setMensagens((m) => [
        ...m,
        {
          id: `bot-${data.timestamp || Date.now()}`,
          de: 'bot',
          texto: data.reply,
          hora: horaDe(data.timestamp || new Date().toISOString()),
        },
      ])
    } catch {
      setErro('Sem conexão com o servidor. O backend está rodando?')
    } finally {
      setPensando(false)
    }
  }

  if (!aberto) return null

  return (
    <>
      {/* Fundo clicável só abaixo de xl, onde o painel cobre a tela */}
      <div
        className="fixed inset-0 z-40 bg-black/50 xl:hidden"
        onClick={onFechar}
        aria-hidden="true"
      />

      <aside
        className="slide-in fixed right-0 top-0 z-50 flex h-screen w-full max-w-[400px] flex-col
                   border-l border-line bg-panel shadow-lift"
        role="complementary"
        aria-label="Assistente ChargeOps"
      >
        {/* Cabeçalho */}
        <header className="flex items-center gap-3 border-b border-hair px-5 py-4">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-chip bg-flux/12 text-flux ring-1 ring-flux/25">
            <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M13 2.5 4.8 13.8H11l-1 7.7 8.2-11.3H12l1-7.7Z" />
            </svg>
          </span>

          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="truncate font-medium text-ink">ChargeOps AI</p>
              <span className="rounded-md border border-flux/30 bg-flux/10 px-1.5 py-0.5 font-mono text-[0.5625rem] tracking-wider text-flux">
                BETA
              </span>
            </div>
            <p className="truncate text-xs text-dim">Seu assistente de recarga</p>
          </div>

          <button
            type="button"
            onClick={onFechar}
            aria-label="Fechar assistente"
            className="rounded-md p-1.5 text-dim transition-colors duration-200 hover:bg-raise hover:text-ink"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </header>

        {/* Conversa */}
        <div className="scroll-slim flex-1 space-y-3 overflow-y-auto px-5 py-5">
          {mensagens.length === 0 && (
            <Balao
              de="bot"
              texto={`Olá${primeiroNome ? `, ${primeiroNome}` : ''}. Posso consultar status dos carregadores, tempo restante, potência e custo da sua recarga.`}
            />
          )}

          {mensagens.map((m) => (
            <Balao key={m.id} de={m.de} texto={m.texto} hora={m.hora} />
          ))}

          {pensando && (
            <div className="flex justify-start">
              <div className="flex items-center gap-1.5 rounded-panel border border-hair bg-raise/70 px-4 py-3">
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="h-1.5 w-1.5 rounded-full bg-dim"
                    style={{ animation: `gw-ping 1.2s ease-in-out ${i * 0.15}s infinite` }}
                  />
                ))}
              </div>
            </div>
          )}

          <div ref={fimRef} />
        </div>

        {/* Sugestões — só enquanto a conversa está vazia */}
        {mensagens.length === 0 && (
          <div className="flex flex-wrap gap-2 px-5 pb-3">
            {SUGESTOES.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => enviar(s)}
                className="rounded-chip border border-line bg-raise/40 px-3 py-2 text-left text-xs text-mute
                           transition-colors duration-200 hover:border-flux/40 hover:bg-flux/10 hover:text-ink"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {erro && (
          <p className="mx-5 mb-2 rounded-chip border border-flux/30 bg-flux/10 px-3 py-2 text-xs text-flux">
            {erro}
          </p>
        )}

        {/* Envio */}
        <div className="border-t border-hair p-4">
          <div className="flex items-end gap-2">
            <input
              ref={inputRef}
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), enviar())}
              placeholder="Pergunte sobre sua recarga"
              className="flex-1 rounded-chip border border-line bg-raise/50 px-4 py-2.5 text-sm text-ink
                         placeholder-dim transition-colors duration-200 focus:border-flux/50 focus:outline-none"
            />
            <button
              type="button"
              onClick={() => enviar()}
              disabled={!texto.trim() || pensando}
              aria-label="Enviar mensagem"
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-chip bg-flux text-white
                         transition-all duration-200 hover:bg-flare disabled:cursor-not-allowed disabled:opacity-40"
            >
              <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 12l16-8-6 8 6 8-16-8Z" />
              </svg>
            </button>
          </div>
          <p className="mt-2.5 text-center text-[0.6875rem] text-dim">
            A IA pode errar. Confira informações importantes.
          </p>
        </div>
      </aside>
    </>
  )
}

/** Botão flutuante que abre o assistente. */
export function BotaoChat({ onClick, escondido }) {
  if (escondido) return null

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Abrir assistente ChargeOps"
      className="group fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full
                 bg-flux text-white shadow-flux transition-all duration-200
                 hover:scale-105 hover:bg-flare active:scale-95"
    >
      <span className="absolute inset-0 rounded-full bg-flux opacity-40 transition-transform duration-500 group-hover:scale-125 group-hover:opacity-0" />
      <svg viewBox="0 0 24 24" className="relative h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <path d="M13 2.5 4.8 13.8H11l-1 7.7 8.2-11.3H12l1-7.7Z" />
      </svg>
    </button>
  )
}

export default ChatPanel
