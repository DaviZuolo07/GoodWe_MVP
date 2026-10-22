import { useCallback, useEffect, useState } from 'react'
import GraficoSessao from '../components/GraficoSessao.jsx'
import { get } from '../lib/api.js'
import { brl, dataHora, duracao, energia, num, potencia } from '../lib/formato.js'

/**
 * Sessões de recarga - todas as que esta conta pode ver (admin da plataforma:
 * todos os locais; operador: o condomínio dele, filtrado no backend).
 * Clicar numa linha abre o detalhe: local, usuário, veículo/celular, demanda
 * (limite, liberado, fração), energia (entregue, na bateria, da tomada),
 * conta, de onde vêm os números e o gráfico. Atualiza a cada 5 s.
 */

const ROTULO_STATUS = {
  carregando: 'Carregando', finalizada: 'Finalizada', recusada: 'Recusada', cancelada: 'Cancelada',
  aguardando_rfid: 'Aguardando cartão', aguardando_energia: 'Fila de energia', expirada: 'Expirada',
}
const COR_STATUS = { carregando: 'text-live', aguardando_energia: 'text-queue', aguardando_rfid: 'text-queue',
                     recusada: 'text-flux', finalizada: 'text-mute' }
const ORIGEM_PCT = { informado: 'informado no app', estimado: 'estimado', celular: 'lido do celular' }

function Linha({ rotulo, valor, sub }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-hair py-1.5 last:border-0">
      <dt className="text-sm text-mute">{rotulo}</dt>
      <dd className="num text-right text-sm text-ink">{valor}{sub && <span className="block text-xs text-dim">{sub}</span>}</dd>
    </div>
  )
}

function Bloco({ titulo, children }) {
  return (
    <section className="rounded-panel border border-line bg-panel p-4">
      <h4 className="mb-2 text-xs font-medium uppercase tracking-wider text-dim">{titulo}</h4>
      <dl>{children}</dl>
    </section>
  )
}

export function DetalheSessao({ id, onFechar }) {
  const [d, setD] = useState(null)
  const [erro, setErro] = useState('')

  const carregar = useCallback(async () => {
    try { setD(await get(`/gestor/sessoes/${id}`)); setErro('') } catch (e) { setErro(e.message) }
  }, [id])

  useEffect(() => {
    carregar()
    const t = setInterval(carregar, 5000)
    return () => clearInterval(t)
  }, [carregar])

  const s = d?.sessao
  const fator = d?.energia?.fator_escala || 1
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-void/70 backdrop-blur-sm" onClick={onFechar}>
      <aside className="h-full w-full max-w-3xl overflow-y-auto border-l border-line bg-void p-5 sm:p-7"
             onClick={(e) => e.stopPropagation()} aria-label="Detalhe da sessão">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <p className="text-xs text-dim">Sessão de recarga</p>
            <h3 className="text-xl font-semibold text-ink">
              {d ? `${d.local.nome} · ponto ${d.carregador.numero}` : 'Carregando…'}
            </h3>
            {s && <p className={`mt-1 text-sm ${COR_STATUS[s.status] || 'text-mute'}`}>{ROTULO_STATUS[s.status] || s.status}</p>}
          </div>
          <button type="button" onClick={onFechar} className="rounded-chip border border-line px-3 py-1.5 text-sm text-mute hover:text-ink">Fechar</button>
        </div>
        {erro && <p className="mb-4 rounded-chip border border-flux/40 bg-flux/10 px-4 py-3 text-sm text-flux">{erro}</p>}
        {d && (
          <div className="space-y-4">
            <p className="rounded-chip border border-hair bg-raise/40 px-4 py-3 text-sm text-mute">
              <span className="font-medium text-ink">De onde vêm os números: </span>{d.fonte_dos_dados.texto}
            </p>
            <GraficoSessao serie={d.serie} />
            <div className="grid gap-4 md:grid-cols-2">
              <Bloco titulo="Quem e onde">
                <Linha rotulo="Usuário" valor={d.usuario.nome || '—'} sub={d.usuario.tipo} />
                <Linha rotulo="Local" valor={d.local.nome} sub={d.local.endereco} />
                <Linha rotulo="Ponto" valor={d.carregador.numero} sub={d.carregador.modelo} />
                <Linha rotulo={d.veiculo?.tipo === 'celular' ? 'Celular' : 'Veículo'} valor={d.veiculo?.modelo || '—'}
                       sub={d.veiculo ? `bateria ${fator === 1 ? energia(d.veiculo.capacidade_bateria_kwh)
                         : `${num(d.veiculo.capacidade_bateria_kwh * 1000 / fator, 1)} Wh`}` : null} />
                <Linha rotulo="Temperatura do ponto"
                       valor={d.carregador.temperatura_c != null ? `${num(d.carregador.temperatura_c, 1)} °C` : '—'}
                       sub={d.carregador.temperatura_texto} />
              </Bloco>
              <Bloco titulo="Agora">
                <Linha rotulo="Bateria" valor={`${num(s.percentual_bateria_inicial, 0)}% → ${num(s.percentual_bateria_atual, 1)}%`}
                       sub={`alvo ${num(s.alvo_percentual, 0)}% · ${ORIGEM_PCT[s.percentual_origem] || s.percentual_origem || ''}`} />
                <Linha rotulo="Potência" valor={potencia(s.potencia_atual_kw)} sub={s.potencia_media_kw ? `média ${potencia(s.potencia_media_kw)}` : null} />
                <Linha rotulo="Previsão de término" valor={s.status === 'carregando' ? duracao(s.tempo_estimado_min) : '—'} />
                <Linha rotulo="Início" valor={dataHora(s.iniciado_em || s.criado_em)} sub={s.finalizado_em ? `fim ${dataHora(s.finalizado_em)}` : null} />
              </Bloco>
              <Bloco titulo="Demanda do local (água no balde)">
                <Linha rotulo="Limite agora" valor={potencia(d.demanda.limite_kw)}
                       sub={d.demanda.em_ponta ? `horário de ponta (contratado ${potencia(d.demanda.limite_nominal_kw)})` : 'fora da ponta'} />
                <Linha rotulo="A bateria pede" valor={potencia(d.demanda.pedida_kw)} />
                <Linha rotulo="Liberado" valor={d.demanda.alocado_kw != null ? potencia(d.demanda.alocado_kw) : '—'} />
                <Linha rotulo={d.carregador.divisao_por_tempo ? 'Tempo de relé fechado' : 'Fração da potência'}
                       valor={`${num(d.demanda.fracao * 100, 0)}%`}
                       sub={d.carregador.divisao_por_tempo ? 'divisão por tempo no ESP32 (rodízio de 30 s)' : null} />
              </Bloco>
              <Bloco titulo="Energia e conta">
                <Linha rotulo="Entregue no ponto" valor={energia(d.energia.entregue_kwh)}
                       sub={d.energia.real_wh != null ? `${num(d.energia.real_wh, 2)} Wh reais (escala 1:${num(fator, 0)})` : null} />
                <Linha rotulo="Chegou à bateria" valor={energia(d.energia.na_bateria_kwh)} sub="~8% vira calor" />
                {d.energia.da_tomada_kwh != null && (
                  <Linha rotulo="Saiu da tomada" valor={energia(d.energia.da_tomada_kwh)} sub="derivado: fonte de 5 V a 85%" />
                )}
                <Linha rotulo="Valor" valor={s.custo_final != null ? brl(s.custo_final) : brl(d.custo?.total)}
                       sub={s.custo_final != null ? `reservado ${brl(s.valor_pre_autorizado)} · estornado ${brl(s.valor_estornado)}` : 'parcial'} />
                {s.encerrado_por && <Linha rotulo="Encerrada por" valor={s.encerrado_por} />}
              </Bloco>
            </div>
          </div>
        )}
      </aside>
    </div>
  )
}

function SessoesPage() {
  const [lista, setLista] = useState(null)
  const [filtro, setFiltro] = useState('')
  const [aberta, setAberta] = useState(null)
  const [erro, setErro] = useState('')

  const carregar = useCallback(async () => {
    try {
      setLista(await get(`/gestor/sessoes${filtro ? `?status=${filtro}` : ''}`))
      setErro('')
    } catch (e) { setErro(e.message) }
  }, [filtro])

  useEffect(() => {
    carregar()
    const t = setInterval(carregar, 5000)
    return () => clearInterval(t)
  }, [carregar])

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-ink">Sessões de recarga</h2>
          <p className="mt-1 text-sm text-mute">Clique numa sessão para ver o gráfico e os detalhes. Atualiza a cada 5 s.</p>
        </div>
        <div className="flex gap-1">
          {[['', 'Todas'], ['carregando', 'Ao vivo'], ['aguardando_energia', 'Fila'], ['finalizada', 'Finalizadas']].map(([id, r]) => (
            <button key={id} type="button" onClick={() => setFiltro(id)}
                    className={`rounded-chip px-3 py-1.5 text-sm ${filtro === id ? 'nav-ativo text-ink' : 'text-mute hover:bg-raise/60'}`}>{r}</button>
          ))}
        </div>
      </div>
      {erro && <p className="mb-4 rounded-chip border border-flux/40 bg-flux/10 px-4 py-3 text-sm text-flux">{erro}</p>}
      {!lista && !erro && <div className="skeleton h-40 rounded-panel" />}
      {lista && !lista.length && (
        <p className="rounded-panel border border-line bg-panel px-5 py-8 text-center text-sm text-mute">Nenhuma sessão aqui.</p>
      )}
      {lista && lista.length > 0 && (
        <div className="overflow-x-auto rounded-panel border border-line bg-panel">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead>
              <tr className="border-b border-hair text-xs text-dim">
                {['Quando', 'Local / ponto', 'Usuário', 'Status', 'Bateria', 'Potência', 'Energia', 'Fim previsto', 'Valor'].map((c, i) => (
                  <th key={c} className={`px-4 py-3 font-normal ${i >= 4 ? 'text-right' : ''}`}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-hair">
              {lista.map((s) => (
                <tr key={s.id} onClick={() => setAberta(s.id)} tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter') setAberta(s.id) }}
                    className="cursor-pointer hover:bg-raise/40 focus:bg-raise/40 focus:outline-none">
                  <td className="num px-4 py-2.5 text-mute">{dataHora(s.iniciado_em || s.criado_em)}</td>
                  <td className="px-4 py-2.5">{s.local || '—'} · {s.carregador_numero ?? '—'}</td>
                  <td className="px-4 py-2.5 text-ink">{s.usuario || '—'}
                    <span className="block text-xs text-dim">{s.veiculo}{s.veiculo_tipo ? ` (${s.veiculo_tipo})` : ''}</span></td>
                  <td className={`px-4 py-2.5 text-xs font-medium ${COR_STATUS[s.status] || 'text-mute'}`}>{ROTULO_STATUS[s.status] || s.status}</td>
                  <td className="num px-4 py-2.5 text-right">{num(s.percentual_bateria_inicial, 0)}% → {num(s.percentual_bateria_atual, 0)}%</td>
                  <td className="num px-4 py-2.5 text-right">{s.status === 'carregando' ? potencia(s.potencia_atual_kw) : '—'}</td>
                  <td className="num px-4 py-2.5 text-right">{energia(s.energia_entregue_kwh)}</td>
                  <td className="num px-4 py-2.5 text-right">{s.status === 'carregando' ? duracao(s.tempo_estimado_min) : '—'}</td>
                  <td className="num px-4 py-2.5 text-right">{s.custo_final != null ? brl(s.custo_final) : <span className="text-dim">{brl(s.custo_estimado)} est.</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {aberta && <DetalheSessao id={aberta} onFechar={() => setAberta(null)} />}
    </div>
  )
}

export default SessoesPage
