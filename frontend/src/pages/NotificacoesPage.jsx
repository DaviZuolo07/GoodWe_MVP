import { useCallback, useEffect, useState } from 'react'
import { supabase } from '../supabaseClient.js'

/**
 * Notificações do usuário logado.
 *
 * A tabela `notificacoes` já está publicada no realtime (ver 01_schema.sql),
 * então o que o backend criar aparece aqui na hora, sem recarregar a página.
 *
 * Marcar como lida é um update direto no Supabase. É a única escrita que este
 * frontend faz sem passar pelo backend — vale a exceção porque não há regra de
 * negócio envolvida, só um flag de leitura. Se vocês criarem um endpoint
 * depois, é trocar as duas chamadas `marcar*` por um fetch.
 */

function tempoRelativo(iso) {
  if (!iso) return ''
  const seg = Math.floor((Date.now() - new Date(iso)) / 1000)

  if (seg < 60) return 'agora'
  if (seg < 3600) return `há ${Math.floor(seg / 60)} min`
  if (seg < 86400) return `há ${Math.floor(seg / 3600)} h`
  if (seg < 604800) return `há ${Math.floor(seg / 86400)} d`

  return new Date(iso).toLocaleDateString('pt-BR')
}

function NotificacoesPage({ sessao }) {
  const usuarioId = sessao.usuario.id

  const [itens, setItens] = useState([])
  const [carregando, setCarregando] = useState(true)

  const carregar = useCallback(async () => {
    const { data } = await supabase
      .from('notificacoes')
      .select('*')
      .eq('usuario_id', usuarioId)
      .order('criado_em', { ascending: false })
      .limit(50)

    setItens(data || [])
    setCarregando(false)
  }, [usuarioId])

  useEffect(() => {
    carregar()

    const canal = supabase
      .channel('notificacoes-page')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'notificacoes' }, carregar)
      .subscribe()

    return () => {
      supabase.removeChannel(canal)
    }
  }, [carregar])

  async function marcarUma(id) {
    // Atualização otimista: a interface responde antes do banco confirmar.
    setItens((lista) => lista.map((n) => (n.id === id ? { ...n, lida: true } : n)))
    await supabase.from('notificacoes').update({ lida: true }).eq('id', id)
  }

  async function marcarTodas() {
    setItens((lista) => lista.map((n) => ({ ...n, lida: true })))
    await supabase
      .from('notificacoes')
      .update({ lida: true })
      .eq('usuario_id', usuarioId)
      .eq('lida', false)
  }

  const naoLidas = itens.filter((n) => !n.lida).length

  return (
    <div>
      <div className="mb-8 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-semibold tracking-tight text-ink lg:text-[1.375rem]">
              Notificações
            </h2>
            {naoLidas > 0 && (
              <span className="num rounded-md border border-flux/30 bg-flux/10 px-2 py-0.5 text-xs font-semibold text-flux">
                {naoLidas}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-dim">
            Avisos sobre suas recargas, saldo e carregadores do condomínio.
          </p>
        </div>

        {naoLidas > 0 && (
          <button
            type="button"
            onClick={marcarTodas}
            className="rounded-chip border border-line bg-panel px-4 py-2 text-sm text-mute
                       transition-colors duration-200 hover:border-flux/40 hover:bg-flux/10 hover:text-flux"
          >
            Marcar todas como lidas
          </button>
        )}
      </div>

      {carregando ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="skeleton h-20 rounded-panel" />
          ))}
        </div>
      ) : itens.length === 0 ? (
        <div className="rounded-panel border border-dashed border-line bg-panel/40 px-6 py-16 text-center">
          <p className="font-medium text-ink">Nenhuma notificação</p>
          <p className="mx-auto mt-1.5 max-w-[40ch] text-sm leading-relaxed text-dim">
            Quando uma recarga terminar ou o saldo ficar baixo, o aviso aparece aqui.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {itens.map((n) => (
            <button
              key={n.id}
              type="button"
              onClick={() => !n.lida && marcarUma(n.id)}
              disabled={n.lida}
              className={`sweep group relative flex w-full items-start gap-4 overflow-hidden rounded-panel border
                          p-5 text-left transition duration-200 ${
                            n.lida
                              ? 'cursor-default border-hair bg-panel/50'
                              : 'border-line bg-panel hover:-translate-y-0.5 hover:border-flux/40 hover:shadow-lift'
                          }`}
            >
              <span
                className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                  n.lida ? 'bg-off' : 'bg-flux dot-live'
                }`}
                style={n.lida ? undefined : { color: 'var(--color-flux)' }}
              />

              <div className="min-w-0 flex-1">
                <p className={`leading-relaxed ${n.lida ? 'text-mute' : 'text-ink'}`}>
                  {n.mensagem}
                </p>
                <p className="num mt-1.5 text-xs text-dim">{tempoRelativo(n.criado_em)}</p>
              </div>

              {!n.lida && (
                <span className="shrink-0 self-center text-xs text-dim opacity-0 transition-opacity duration-200 group-hover:opacity-100">
                  Marcar como lida
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default NotificacoesPage
