import { useEffect, useState } from 'react'
import { get } from '../lib/api.js'
import { brl, dataHora, duracao, energia, num } from '../lib/formato.js'

/**
 * Recibo de uma recarga — GET /recargas/{sessao_id}/recibo.
 *
 * Esta tela NÃO faz conta. Cada número vem do backend, já arredondado no
 * centavo, e `subtotal_fora_ponta + subtotal_ponta === total` é garantido lá
 * (e coberto por teste). Arredondar de novo aqui é exatamente o que faria a
 * soma deixar de bater na frente do morador.
 *
 * Só o dono da sessão abre o recibo: para outra pessoa o backend responde 404.
 */

const MOVIMENTO = {
  pre_autorizacao: { texto: 'Reservado do saldo', sinal: '−', cor: 'text-flux' },
  estorno: { texto: 'Devolvido à carteira', sinal: '+', cor: 'text-live' },
  credito: { texto: 'Crédito adicionado', sinal: '+', cor: 'text-live' },
  ajuste: { texto: 'Ajuste', sinal: '', cor: 'text-mute' },
}

const STATUS = {
  finalizada: 'Concluída',
  cancelada: 'Cancelada',
  recusada: 'Recusada',
  carregando: 'Em andamento',
}

/** Linha com pontilhado entre o rótulo e o valor, como num cupom. */
function Pontilhada({ rotulo, detalhe, valor, forte, cor }) {
  return (
    <div className="flex items-baseline gap-2 py-1">
      <span className={`shrink-0 text-sm ${forte ? 'font-semibold text-ink' : 'text-mute'}`}>
        {rotulo}
        {detalhe && <span className="num ml-1.5 text-xs text-dim">{detalhe}</span>}
      </span>
      <span aria-hidden="true" className="min-w-4 flex-1 translate-y-[-3px] border-b border-dotted border-line" />
      <span className={`num shrink-0 text-sm ${forte ? 'font-semibold' : ''} ${cor || 'text-ink'}`}>{valor}</span>
    </div>
  )
}

function Secao({ titulo, children }) {
  return (
    <section className="border-t border-dashed border-line px-5 py-4 sm:px-6">
      <h4 className="mb-2 text-xs font-medium text-dim">{titulo}</h4>
      {children}
    </section>
  )
}

function Esqueleto() {
  return (
    <div className="space-y-3 px-6 py-6">
      <div className="skeleton h-6 w-2/3 rounded-md" />
      <div className="skeleton h-4 w-1/3 rounded-md" />
      <div className="skeleton mt-6 h-24 w-full rounded-md" />
      <div className="skeleton h-24 w-full rounded-md" />
    </div>
  )
}

function ReciboModal({ sessaoId, onFechar }) {
  const [recibo, setRecibo] = useState(null)
  const [erro, setErro] = useState('')

  useEffect(() => {
    let cancelado = false
    get(`/recargas/${sessaoId}/recibo`)
      .then((d) => { if (!cancelado) setRecibo(d) })
      .catch((e) => {
        if (cancelado) return
        setErro(e.status === 404 ? 'Recibo não encontrado para esta recarga.' : e.message)
      })
    return () => { cancelado = true }
  }, [sessaoId])

  // Esc fecha, como qualquer diálogo.
  useEffect(() => {
    const tecla = (e) => { if (e.key === 'Escape') onFechar() }
    window.addEventListener('keydown', tecla)
    return () => window.removeEventListener('keydown', tecla)
  }, [onFechar])

  const l = recibo?.linhas
  const temPonta = l && Number(l.energia_ponta_kwh) > 0
  const devolvido = Number(recibo?.valor_estornado) > 0
  const pi = recibo?.percentual_inicial
  const pf = recibo?.percentual_final

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-void/80 p-0 backdrop-blur-sm sm:items-center sm:p-4"
      onClick={onFechar}
      role="dialog"
      aria-modal="true"
      aria-label="Recibo da recarga"
    >
      <div
        className="rise max-h-[94vh] w-full max-w-md overflow-y-auto rounded-t-panel border border-line bg-panel shadow-lift
                   scroll-slim sm:rounded-panel"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Cabeçalho */}
        <div className="flex items-start justify-between gap-4 px-5 pb-4 pt-5 sm:px-6">
          <div className="min-w-0">
            <p className="text-xs text-dim">Recibo da recarga</p>
            <h3 className="mt-1 text-lg font-semibold tracking-tight text-ink">
              {recibo ? `Ponto ${recibo.carregador}` : 'Carregando…'}
            </h3>
            {recibo && (
              <p className="mt-1 text-sm text-mute">
                <span className="num">{dataHora(recibo.iniciado_em)}</span>
                {recibo.motivo_legivel && <>, {recibo.motivo_legivel}</>}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onFechar}
            aria-label="Fechar recibo"
            className="rounded-md p-1.5 text-dim transition-colors hover:bg-raise hover:text-ink"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        {erro && (
          <p className="mx-5 mb-5 rounded-chip border border-flux/40 bg-flux/10 px-3 py-2.5 text-sm text-flux sm:mx-6">
            {erro}
          </p>
        )}

        {!recibo && !erro && <Esqueleto />}

        {recibo && (
          <>
            {/* Bateria */}
            {pi != null && pf != null && (
              <div className="px-5 pb-4 sm:px-6">
                <div className="flex items-baseline justify-between text-sm">
                  <span className="text-mute">Bateria</span>
                  <span className="num text-ink">{Math.round(pi)}% → {Math.round(pf)}%</span>
                </div>
                <div className="relative mt-2 h-1.5 overflow-hidden rounded-full bg-raise">
                  <div className="absolute inset-y-0 left-0 bg-line" style={{ width: `${Math.min(100, pi)}%` }} />
                  <div
                    className="absolute inset-y-0 bg-flux"
                    style={{ left: `${Math.min(100, pi)}%`, width: `${Math.max(0, Math.min(100, pf) - Math.min(100, pi))}%` }}
                  />
                </div>
                <div className="mt-2 flex justify-between text-xs text-dim">
                  <span>{STATUS[recibo.status] || recibo.status}</span>
                  {recibo.duracao_min != null && <span className="num">{duracao(recibo.duracao_min)}</span>}
                </div>
              </div>
            )}

            {/* A conta da energia */}
            <Secao titulo="Energia consumida">
              <Pontilhada
                rotulo={`${energia(l.energia_fora_ponta_kwh)} fora da ponta`}
                detalhe={`× ${brl(l.tarifa_kwh)}/kWh`}
                valor={brl(l.subtotal_fora_ponta)}
              />
              <Pontilhada
                rotulo={`${energia(l.energia_ponta_kwh)} na ponta`}
                detalhe={`× ${brl(l.tarifa_ponta_kwh)}/kWh`}
                valor={brl(l.subtotal_ponta)}
                cor={temPonta ? 'text-queue' : undefined}
              />
              <div className="mt-2 border-t border-line pt-2">
                <Pontilhada rotulo="Total consumido" valor={brl(l.total)} forte />
              </div>
              {Number(l.multiplicador_ponta) > 1 && (
                <p className="mt-2 text-xs leading-relaxed text-dim">
                  Na ponta a tarifa é {num(l.multiplicador_ponta, 2)}× a normal. Cada parte da energia é cobrada pela
                  tarifa do horário em que foi entregue.
                </p>
              )}
            </Secao>

            {/* O que aconteceu na carteira */}
            <Secao titulo="Na sua carteira">
              <Pontilhada rotulo="Reservado no início" valor={brl(recibo.valor_reservado)} />
              <Pontilhada rotulo="Cobrado" valor={brl(recibo.valor_cobrado)} />
              <Pontilhada
                rotulo="Devolvido à carteira"
                valor={brl(recibo.valor_estornado)}
                cor={devolvido ? 'text-live' : undefined}
                forte={devolvido}
              />
              {recibo.preco_medio_kwh != null && (
                <p className="mt-2 text-xs text-dim">
                  Preço médio pago: <span className="num text-mute">{brl(recibo.preco_medio_kwh)}/kWh</span>
                </p>
              )}
            </Secao>

            {recibo.limitado_pela_reserva && (
              <div className="mx-5 mb-4 rounded-chip border border-queue/40 bg-queue/10 px-3 py-2.5 sm:mx-6">
                <p className="text-xs font-medium text-queue">A recarga parou no valor reservado</p>
                <p className="mt-1 text-xs leading-relaxed text-mute">
                  A bateria não chegou ao alvo: a recarga foi encerrada ao atingir o valor reservado do seu saldo.
                  Você nunca paga mais do que reservou.
                </p>
              </div>
            )}

            {/* Extrato desta recarga */}
            {recibo.movimentacoes?.length > 0 && (
              <Secao titulo="Movimentações desta recarga">
                <ol className="relative ml-1.5 border-l border-line">
                  {recibo.movimentacoes.map((m, i) => {
                    const r = MOVIMENTO[m.tipo] || MOVIMENTO.ajuste
                    return (
                      <li key={i} className="relative pb-3 pl-4 last:pb-0">
                        <span className={`absolute -left-[5px] top-[7px] h-[9px] w-[9px] rounded-full ring-[3px] ring-panel ${
                          r.cor === 'text-live' ? 'bg-live' : r.cor === 'text-flux' ? 'bg-flux' : 'bg-off'}`} />
                        <div className="flex items-baseline justify-between gap-3">
                          <p className="text-sm text-ink">{r.texto}</p>
                          <p className={`num shrink-0 text-sm ${r.cor}`}>{r.sinal} {brl(m.valor)}</p>
                        </div>
                        <div className="mt-0.5 flex items-baseline justify-between gap-3 text-xs text-dim">
                          <span className="min-w-0 truncate">{m.descricao}</span>
                          {m.saldo_apos != null && <span className="num shrink-0">saldo {brl(m.saldo_apos)}</span>}
                        </div>
                      </li>
                    )
                  })}
                </ol>
              </Secao>
            )}

            <div className="border-t border-dashed border-line px-5 py-4 sm:px-6">
              <p className="text-xs leading-relaxed text-dim">
                A tarifa foi fixada no início da recarga: mudanças de preço depois disso não alteram esta conta.
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default ReciboModal
