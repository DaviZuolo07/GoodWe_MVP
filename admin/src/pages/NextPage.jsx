import { useCallback, useEffect, useState } from 'react'
import { get, patch } from '../lib/api.js'
import { brl, dataHora, duracao, num } from '../lib/formato.js'
import { DetalheSessao } from './SessoesPage.jsx'

/**
 * Sala Next - o estande do totem, em unidades REAIS (W e Wh do USB; o resto
 * do sistema mostra a escala 1:1000 de produto). Quatro blocos:
 *   vagas ao vivo (com a fração de tempo da divisão), quem se cadastrou,
 *   celulares, e todas as recargas do estande. Atualiza a cada 5 s.
 * A chave "Divisão por tempo" de cada vaga é o Modbus 10025 (backend).
 */

const ROTULO = { carregando: 'Carregando', finalizada: 'Finalizada', recusada: 'Recusada', cancelada: 'Cancelada',
                 aguardando_energia: 'Fila de energia', aguardando_rfid: 'Aguardando cartão', expirada: 'Expirada' }
const ORIGEM_PCT = { informado: 'app', estimado: 'estimado', celular: 'celular' }
const W = (v, casas = 2) => (v == null ? '—' : `${num(v, casas)} W`)
const WH = (v) => (v == null ? '—' : `${num(v, 2)} Wh`)

function Tabela({ colunas, linhas, vazio, onClicar }) {
  if (!linhas.length) return <p className="rounded-panel border border-line bg-panel px-5 py-8 text-center text-sm text-mute">{vazio}</p>
  return (
    <div className="overflow-x-auto rounded-panel border border-line bg-panel">
      <table className="w-full min-w-[680px] text-left text-sm">
        <thead><tr className="border-b border-hair text-xs text-dim">
          {colunas.map((c) => <th key={c.id} className={`px-4 py-3 font-normal ${c.direita ? 'text-right' : ''}`}>{c.rotulo}</th>)}
        </tr></thead>
        <tbody className="divide-y divide-hair">
          {linhas.map((l, i) => (
            <tr key={l.id || i} onClick={onClicar ? () => onClicar(l) : undefined}
                className={onClicar ? 'cursor-pointer hover:bg-raise/40' : 'hover:bg-raise/40'}>
              {colunas.map((c) => (
                <td key={c.id} className={`px-4 py-2.5 align-top ${c.direita ? 'num text-right' : ''}`}>
                  {c.render ? c.render(l) : (l[c.id] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function NextPage() {
  const [d, setD] = useState(null)
  const [erro, setErro] = useState('')
  const [aberta, setAberta] = useState(null)

  const carregar = useCallback(async () => {
    try { setD(await get('/gestor/next')); setErro('') } catch (e) { setErro(e.message) }
  }, [])

  useEffect(() => {
    carregar()
    const t = setInterval(carregar, 5000)
    return () => clearInterval(t)
  }, [carregar])

  const [limite, setLimite] = useState('')

  async function mudarDemanda(corpo) {
    try { await patch('/gestor/next/demanda', corpo); setLimite(''); carregar() } catch (e) { setErro(e.message) }
  }

  async function alternar(v) {
    try {
      await patch(`/gestor/carregadores/${v.carregador_id}/divisao`, { ligada: !v.divisao_por_tempo })
      carregar()
    } catch (e) { setErro(e.message) }
  }

  if (!d) return erro ? <p className="rounded-chip border border-flux/40 bg-flux/10 px-4 py-3 text-sm text-flux">{erro}</p>
                      : <div className="skeleton h-60 rounded-panel" />

  const t = d.totais
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-ink">Sala Next</h2>
          <p className="mt-1 text-sm text-mute">
            {d.estande.nome} · limite agora {W(d.estande.limite_w, 1)}{d.estande.em_ponta ? ' (horário de ponta)' : ''} ·
            placa {d.placa.online ? <span className="text-live">online</span> : <span className="text-flux">offline</span>}
            {d.placa.firmware ? ` · ${d.placa.firmware}` : ''}
          </p>
        </div>
        {erro && <p className="text-sm text-flux">{erro}</p>}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {[['Cadastros', num(t.cadastros, 0)], ['Carregando agora', num(t.ativas, 0)], ['Recargas concluídas', num(t.recargas, 0)],
          ['Energia entregue', WH(t.energia_wh)], ['Faturamento', brl(t.faturamento)]].map(([r, v]) => (
          <div key={r} className="realce relative rounded-panel border border-line bg-panel p-4">
            <p className="text-sm text-mute">{r}</p><p className="num mt-1 text-2xl font-semibold text-ink">{v}</p>
          </div>
        ))}
      </div>

      <section className="rounded-panel border border-line bg-panel p-4">
        <h3 className="text-lg font-semibold text-ink">Demanda do estande</h3>
        <p className="mt-1 text-sm text-mute">
          Limite contratado {num(d.estande.limite_kw, 2)} kW na escala 1:{num(d.fator_escala, 0)} ({W(d.estande.limite_w, 1)} reais).
          Na ponta, o limite cai pela metade. O alocador relê em até 10 s e o ESP32 refaz o rodízio dos relés.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input type="number" min="1" step="0.5" value={limite} onChange={(e) => setLimite(e.target.value)}
                 placeholder="limite (kW)" aria-label="Novo limite em kW"
                 className="w-36 rounded-chip border border-line bg-raise/50 px-3 py-2 text-sm text-ink focus:border-flux focus:outline-none" />
          <button type="button" disabled={!(Number(limite) > 0)} onClick={() => mudarDemanda({ limite_potencia_kw: Number(limite) })}
                  className="rounded-chip border border-line px-3 py-2 text-sm text-ink hover:border-flux/50 disabled:opacity-50">Aplicar limite</button>
          {[['30 kW (4 cheios)', 30], ['22,5 kW (75%)', 22.5], ['15 kW (50%)', 15]].map(([r, v]) => (
            <button key={v} type="button" onClick={() => mudarDemanda({ limite_potencia_kw: v })}
                    className="rounded-chip px-3 py-2 text-sm text-mute hover:bg-raise/60 hover:text-ink">{r}</button>
          ))}
          <span className="mx-1 h-6 w-px bg-line" aria-hidden />
          {d.estande.em_ponta ? (
            <button type="button" onClick={() => mudarDemanda({ pico: 'sem_pico' })}
                    className="rounded-chip border border-queue/50 px-3 py-2 text-sm text-queue">Encerrar pico</button>
          ) : (
            <button type="button" onClick={() => mudarDemanda({ pico: 'pico_agora' })}
                    className="rounded-chip bg-flux px-3 py-2 text-sm font-medium text-white">Simular pico agora (2 h)</button>
          )}
        </div>
      </section>

      <section>
        <h3 className="mb-1 text-lg font-semibold text-ink">Vagas do totem</h3>
        <p className="mb-3 text-sm text-mute">
          Sem sensor de corrente: a potência é o modelo de carga do ESP32. "Tempo fechado" é a fatia da janela de 30 s que o
          water-filling deu à vaga - abaixo de 100%, os relés revezam.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {d.vagas.map((v) => (
            <article key={v.carregador_id} className="rounded-panel border border-line bg-panel p-4">
              <div className="flex items-baseline justify-between">
                <p className="text-lg font-semibold text-ink">{v.numero}</p>
                <span className={`text-xs ${v.sessao_id ? 'text-live' : 'text-dim'}`}>{v.sessao_id ? 'carregando' : v.status}</span>
              </div>
              {v.sessao_id ? (
                <button type="button" onClick={() => setAberta(v.sessao_id)} className="mt-2 block w-full text-left">
                  <p className="text-sm text-ink">{v.usuario}</p>
                  <p className="num mt-1 text-2xl text-ink">{num(v.percentual, 1)}%
                    <span className="ml-1 text-xs text-dim">{ORIGEM_PCT[v.percentual_origem] || ''}</span></p>
                  <dl className="num mt-2 space-y-0.5 text-xs text-mute">
                    <div className="flex justify-between"><dt>Potência</dt><dd>{W(v.potencia_w)}</dd></div>
                    <div className="flex justify-between"><dt>Liberado</dt><dd>{W(v.liberado_w)}</dd></div>
                    <div className="flex justify-between"><dt>Tempo fechado</dt><dd>{v.fracao != null ? `${num(v.fracao * 100, 0)}%` : '—'}</dd></div>
                    <div className="flex justify-between"><dt>Energia</dt><dd>{WH(v.energia_wh)}</dd></div>
                    <div className="flex justify-between"><dt>Fim previsto</dt><dd>{duracao(v.tempo_min)}</dd></div>
                  </dl>
                </button>
              ) : <p className="mt-2 text-sm text-dim">Livre</p>}
              <label className="mt-3 flex items-center justify-between gap-2 border-t border-hair pt-3 text-xs text-mute">
                Divisão por tempo
                <input type="checkbox" checked={v.divisao_por_tempo} onChange={() => alternar(v)} className="h-4 w-4 accent-flux" />
              </label>
            </article>
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-3 text-lg font-semibold text-ink">Quem se cadastrou</h3>
        <Tabela vazio="Ninguém se cadastrou no estande ainda." linhas={d.cadastros} colunas={[
          { id: 'nome', rotulo: 'Nome', render: (u) => <span className="font-medium text-ink">{u.nome}</span> },
          { id: 'tipo', rotulo: 'Tipo', render: (u) => <span className="uppercase">{u.tipo}</span> },
          { id: 'celulares', rotulo: 'Celular', render: (u) => (u.celulares.length
            ? u.celulares.map((c) => <span key={c.modelo} className="block text-mute">{c.modelo} · {WH(c.bateria_wh)} · até {W(c.potencia_w, 1)}</span>)
            : <span className="text-dim">—</span>) },
          { id: 'tags', rotulo: 'Tags', direita: true },
          { id: 'recargas', rotulo: 'Recargas', direita: true },
          { id: 'energia_wh', rotulo: 'Energia', direita: true, render: (u) => WH(u.energia_wh) },
          { id: 'gasto', rotulo: 'Gasto', direita: true, render: (u) => brl(u.gasto) },
          { id: 'saldo', rotulo: 'Saldo', direita: true, render: (u) => brl(u.saldo) },
          { id: 'desde', rotulo: 'Desde', render: (u) => <span className="num text-dim">{dataHora(u.desde)}</span> },
        ]} />
      </section>

      <section>
        <h3 className="mb-3 text-lg font-semibold text-ink">Recargas do estande</h3>
        <Tabela vazio="Nenhuma recarga ainda." linhas={d.recargas} onClicar={(r) => setAberta(r.id)} colunas={[
          { id: 'inicio', rotulo: 'Início', render: (r) => <span className="num text-mute">{dataHora(r.inicio)}</span> },
          { id: 'usuario', rotulo: 'Usuário', render: (r) => <span className="text-ink">{r.usuario || '—'}</span> },
          { id: 'vaga', rotulo: 'Vaga' },
          { id: 'status', rotulo: 'Status', render: (r) => ROTULO[r.status] || r.status },
          { id: 'pct', rotulo: 'Bateria', direita: true,
            render: (r) => `${num(r.percentual_inicial, 0)}% → ${num(r.percentual, 0)}%` },
          { id: 'energia_wh', rotulo: 'Energia', direita: true, render: (r) => WH(r.energia_wh) },
          { id: 'valor', rotulo: 'Valor', direita: true, render: (r) => brl(r.valor) },
          { id: 'encerrado_por', rotulo: 'Encerrada por', render: (r) => <span className="text-mute">{r.encerrado_por || '—'}</span> },
        ]} />
      </section>

      {aberta && <DetalheSessao id={aberta} onFechar={() => setAberta(null)} />}
    </div>
  )
}

export default NextPage
