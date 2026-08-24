import { useCallback, useEffect, useRef, useState } from 'react'
import { API_URL } from '../config.js'

/**
 * Assistente ChargeOps.
 *
 * Contrato com o backend (POST /chatbot):
 *   envia  { message, usuario_id, charger_id, condominio_id }
 *   recebe { reply, timestamp, ... }
 *
 * `condominio_id` é novo e é o ponto central deste componente: o assistente
 * responde sobre UM local por vez, e quem escolhe o local é o usuário, no
 * seletor do cabeçalho. Vale dizer que esse campo é um PEDIDO, não uma
 * permissão — o backend valida contra os favoritos antes de aceitar. Se
 * alguém adulterar o valor no DevTools, a resposta volta sobre o condomínio
 * de moradia.
 *
 * O seletor mostra só os FAVORITOS, porque uma rede real tem dezenas de
 * locais e o usuário carrega em dois ou três. A lista completa fica atrás de
 * um "ver todos", para adicionar.
 *
 * Chat operacional, não conversa longa: o histórico zera a cada abertura E a
 * cada troca de local — misturar respostas de dois condomínios na mesma
 * thread é o tipo de coisa que confunde quem assiste.
 */

const SUGESTOES = [
  'Quais carregadores estão disponíveis?',
  'Qual o preço por kWh aqui?',
  'Quanto tempo falta para minha recarga?',
  'Tem gente na fila?',
]

function Balao({ de, texto, hora }) {
  const meu = de === 'usuario'

  return (
    <div className={`flex ${meu ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`rise max-w-[85%] rounded-panel px-4 py-2.5 text-sm leading-relaxed ${
          meu ? 'bg-flux text-white' : 'border border-hair bg-raise/70 text-ink'
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

function Estrela({ cheia }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-3.5 w-3.5"
      fill={cheia ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9Z" />
    </svg>
  )
}

/**
 * Seletor de local do chat.
 *
 * Diferente do CondominioSelect do Dashboard de propósito: aquele lista todos
 * os locais da rede e serve para navegar; este lista favoritos e serve para
 * dizer "estou aqui agora". Comportamentos distintos, componentes distintos —
 * unificar os dois criaria um componente com dois modos e nenhuma clareza.
 */
function SeletorLocal({ locais, ativoId, onEscolher, onFavoritar, onDesfavoritar, ocupado }) {
  const [aberto, setAberto] = useState(false)
  const [verTodos, setVerTodos] = useState(false)
  const caixaRef = useRef(null)

  const favoritos = locais?.favoritos || []
  const todos = locais?.todos || []
  const padraoId = locais?.padrao_id
  const idsFavoritos = new Set(favoritos.map((c) => c.id))

  // Rede de segurança: se por algum motivo não houver favoritos, mostra a
  // lista inteira em vez de um seletor vazio.
  const listaBase = favoritos.length > 0 ? favoritos : todos
  const lista = verTodos ? todos : listaBase
  const ativo = todos.find((c) => c.id === ativoId) || listaBase[0] || null

  useEffect(() => {
    if (!aberto) return
    function onClique(e) {
      if (!caixaRef.current?.contains(e.target)) setAberto(false)
    }
    document.addEventListener('mousedown', onClique)
    return () => document.removeEventListener('mousedown', onClique)
  }, [aberto])

  useEffect(() => {
    if (!aberto) setVerTodos(false)
  }, [aberto])

  return (
    <div ref={caixaRef} className="relative">
      <button
        type="button"
        onClick={() => setAberto((v) => !v)}
        aria-expanded={aberto}
        aria-haspopup="listbox"
        className="flex w-full items-center gap-2 rounded-chip border border-line bg-raise/40 px-3 py-2
                   text-left transition-colors duration-200 hover:border-flux/40 hover:bg-raise/70"
      >
        <svg
          viewBox="0 0 24 24"
          className="h-3.5 w-3.5 shrink-0 text-flux"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M12 21s7-6.3 7-11a7 7 0 1 0-14 0c0 4.7 7 11 7 11Z" />
          <circle cx="12" cy="10" r="2.5" />
        </svg>

        <span className="min-w-0 flex-1">
          <span className="block text-[0.625rem] uppercase tracking-wider text-dim">
            Respondendo sobre
          </span>
          <span className="block truncate text-xs font-medium text-ink">
            {ativo?.nome || 'Selecionar local'}
          </span>
        </span>

        <svg
          viewBox="0 0 24 24"
          className={`h-3.5 w-3.5 shrink-0 text-dim transition-transform duration-200 ${
            aberto ? 'rotate-180' : ''
          }`}
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
        <div
          className="slide-in absolute left-0 right-0 z-50 mt-2 overflow-hidden rounded-panel
                     border border-line bg-panel shadow-lift"
        >
          <ul className="scroll-slim max-h-64 overflow-y-auto py-1" role="listbox">
            {lista.length === 0 && (
              <li className="px-4 py-6 text-center text-xs text-dim">
                Nenhum local disponível.
              </li>
            )}

            {lista.map((c) => {
              const selecionado = c.id === ativoId
              const favorito = idsFavoritos.has(c.id)
              const ehMoradia = c.id === padraoId

              return (
                <li key={c.id} className="flex items-stretch">
                  <button
                    type="button"
                    role="option"
                    aria-selected={selecionado}
                    onClick={() => {
                      onEscolher(c)
                      setAberto(false)
                    }}
                    className={`flex min-w-0 flex-1 items-start gap-2.5 px-3 py-2.5 text-left
                                transition-colors duration-150 ${
                                  selecionado ? 'bg-flux/10' : 'hover:bg-raise/60'
                                }`}
                  >
                    <span
                      className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                        selecionado ? 'bg-flux' : 'bg-off'
                      }`}
                    />
                    <span className="min-w-0">
                      <span
                        className={`block truncate text-xs ${
                          selecionado ? 'text-ink' : 'text-mute'
                        }`}
                      >
                        {c.nome}
                        {ehMoradia && (
                          <span className="ml-1.5 text-[0.5625rem] uppercase tracking-wider text-dim">
                            seu condomínio
                          </span>
                        )}
                      </span>
                      <span className="mt-0.5 block truncate text-[0.6875rem] text-dim">
                        {c.endereco}
                      </span>
                    </span>
                  </button>

                  {/* Moradia é favorito implícito: sem estrela, não dá para remover */}
                  {!ehMoradia && (
                    <button
                      type="button"
                      disabled={ocupado}
                      onClick={() => (favorito ? onDesfavoritar(c.id) : onFavoritar(c.id))}
                      aria-label={favorito ? `Remover ${c.nome} dos favoritos` : `Favoritar ${c.nome}`}
                      title={favorito ? 'Remover dos favoritos' : 'Adicionar aos favoritos'}
                      className={`px-3 transition-colors duration-200 disabled:opacity-40 ${
                        favorito ? 'text-flux hover:text-flare' : 'text-dim hover:text-mute'
                      }`}
                    >
                      <Estrela cheia={favorito} />
                    </button>
                  )}
                </li>
              )
            })}
          </ul>

          {todos.length > listaBase.length && (
            <button
              type="button"
              onClick={() => setVerTodos((v) => !v)}
              className="w-full border-t border-hair px-3 py-2.5 text-center text-[0.6875rem]
                         text-dim transition-colors duration-200 hover:bg-raise/60 hover:text-mute"
            >
              {verTodos ? 'Mostrar só os favoritos' : `Ver todos os locais (${todos.length})`}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function ChatPanel({ sessao, chargerId, aberto, onFechar, condominioId }) {
  const usuarioId = sessao?.usuario?.id
  const primeiroNome = (sessao?.usuario?.nome || '').split(' ')[0]

  const [mensagens, setMensagens] = useState([])
  const [texto, setTexto] = useState('')
  const [pensando, setPensando] = useState(false)
  const [erro, setErro] = useState('')

  const [locais, setLocais] = useState({ favoritos: [], todos: [], padrao_id: null })
  const [localAtivoId, setLocalAtivoId] = useState(condominioId || null)
  const [salvandoFavorito, setSalvandoFavorito] = useState(false)

  const fimRef = useRef(null)
  const inputRef = useRef(null)

  const localAtivo = locais.todos.find((c) => c.id === localAtivoId) || null

  // Carrega favoritos ao abrir. Uma chamada só traz favoritos, lista completa
  // e qual é o condomínio de moradia.
  const carregarLocais = useCallback(async () => {
    if (!usuarioId) return null
    try {
      const res = await fetch(`${API_URL}/usuarios/${usuarioId}/locais`)
      if (!res.ok) return null
      const data = await res.json()
      setLocais(data)
      return data
    } catch {
      return null
    }
  }, [usuarioId])

  useEffect(() => {
    if (!aberto) {
      setMensagens([])
      setTexto('')
      setErro('')
      setPensando(false)
      return
    }

    inputRef.current?.focus()

    carregarLocais().then((data) => {
      if (!data) return
      // Preferência de local, em ordem: o que já estava escolhido no chat ->
      // o local aberto no Dashboard (se for favorito) -> a moradia -> o
      // primeiro favorito. Assim o chat abre falando do lugar certo sem o
      // usuário precisar tocar em nada.
      const permitidos = new Set((data.favoritos || []).map((c) => c.id))
      if (data.padrao_id) permitidos.add(data.padrao_id)

      setLocalAtivoId((atual) => {
        if (atual && permitidos.has(atual)) return atual
        if (condominioId && permitidos.has(condominioId)) return condominioId
        if (data.padrao_id) return data.padrao_id
        return data.favoritos?.[0]?.id || null
      })
    })
  }, [aberto, condominioId, carregarLocais])

  useEffect(() => {
    fimRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [mensagens, pensando])

  useEffect(() => {
    if (!aberto) return
    const onKey = (e) => e.key === 'Escape' && onFechar()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [aberto, onFechar])

  function trocarLocal(c) {
    if (c.id === localAtivoId) return
    setLocalAtivoId(c.id)
    // Zera a conversa: respostas do local anterior não valem para o novo.
    setMensagens([])
    setErro('')
  }

  async function favoritar(condId) {
    setSalvandoFavorito(true)
    try {
      const res = await fetch(`${API_URL}/usuarios/${usuarioId}/favoritos`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ condominio_id: condId }),
      })
      if (res.ok) setLocais(await res.json())
    } catch {
      setErro('Não foi possível salvar o favorito.')
    } finally {
      setSalvandoFavorito(false)
    }
  }

  async function desfavoritar(condId) {
    setSalvandoFavorito(true)
    try {
      const res = await fetch(
        `${API_URL}/usuarios/${usuarioId}/favoritos/${condId}`,
        { method: 'DELETE' },
      )
      if (res.ok) {
        const data = await res.json()
        setLocais(data)
        // Tirou dos favoritos o local que estava ativo: volta para a moradia.
        if (condId === localAtivoId) {
          setLocalAtivoId(data.padrao_id || data.favoritos?.[0]?.id || null)
          setMensagens([])
        }
      } else {
        const data = await res.json().catch(() => ({}))
        setErro(data.detail || 'Não foi possível remover o favorito.')
      }
    } catch {
      setErro('Não foi possível remover o favorito.')
    } finally {
      setSalvandoFavorito(false)
    }
  }

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
          condominio_id: localAtivoId || null,
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
        <header className="border-b border-hair px-5 py-4">
          <div className="flex items-center gap-3">
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
          </div>

          {/* Seletor de local — define o escopo de todas as respostas abaixo */}
          <div className="mt-3">
            <SeletorLocal
              locais={locais}
              ativoId={localAtivoId}
              onEscolher={trocarLocal}
              onFavoritar={favoritar}
              onDesfavoritar={desfavoritar}
              ocupado={salvandoFavorito}
            />
          </div>
        </header>

        {/* Conversa */}
        <div className="scroll-slim flex-1 space-y-3 overflow-y-auto px-5 py-5">
          {mensagens.length === 0 && (
            <Balao
              de="bot"
              texto={
                `Olá${primeiroNome ? `, ${primeiroNome}` : ''}. ` +
                (localAtivo
                  ? `Estou respondendo sobre o ${localAtivo.nome}. `
                  : '') +
                'Posso consultar carregadores disponíveis, tarifa por kWh, fila, ' +
                'e o tempo, a potência e o custo da sua recarga.'
              }
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
