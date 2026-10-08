import { useCallback, useEffect, useMemo, useState } from 'react'
import { get, patch, post } from '../lib/api.js'
import { brl, dataHora, energia, num, potencia } from '../lib/formato.js'

/**
 * Visão geral - a plataforma inteira, para quem está em `admins_globais`.
 *
 * O painel "Operação" responde pelo condomínio do gestor; aqui entram TODOS
 * os locais: cadastros, carteira, recargas, notificações e chamados. Tudo
 * vem pronto do backend (rotas_geral.py); a tela só filtra e apresenta.
 *
 * Atualiza a cada 10 s - o mesmo ritmo do alocador de demanda.
 */

const ABAS = [
  { id: 'resumo', rotulo: 'Resumo' },
  { id: 'chamados', rotulo: 'Chamados' },
  { id: 'recargas', rotulo: 'Recargas' },
  { id: 'usuarios', rotulo: 'Cadastros' },
  { id: 'pagamentos', rotulo: 'Pagamentos' },
  { id: 'notificacoes', rotulo: 'Notificações' },
]

const ROTULO_STATUS = {
  carregando: 'Carregando', finalizada: 'Finalizada', recusada: 'Recusada', cancelada: 'Cancelada',
  aguardando_cartao: 'Aguardando cartão', pendente: 'Pendente', expirada: 'Expirada',
  aberto: 'Aberto', em_andamento: 'Em andamento', resolvido: 'Resolvido',
  disponivel: 'Disponível', em_uso: 'Em uso', ocupado: 'Ocupado', offline: 'Offline', manutencao: 'Manutenção',
}
const COR_STATUS = {
  carregando: 'text-live', finalizada: 'text-mute', recusada: 'text-flux', cancelada: 'text-dim',
  aguardando_cartao: 'text-queue', aberto: 'text-flux', em_andamento: 'text-queue', resolvido: 'text-live',
}
const ROTULO_MOV = {
  credito: 'Crédito', bonus: 'Bônus', estorno: 'Estorno', ajuste: 'Ajuste',
  pre_autorizacao: 'Pré-autorização', ajuste_debito: 'Ajuste (débito)',
}

function Status({ valor }) {
  return <span className={`text-xs font-medium ${COR_STATUS[valor] || 'text-mute'}`}>{ROTULO_STATUS[valor] || valor}</span>
}

function Cartao({ rotulo, valor, sub, cor }) {
  return (
    <div className="realce relative rounded-panel border border-line bg-panel p-5">
      <p className="text-sm text-mute">{rotulo}</p>
      <p className={`num mt-2 text-2xl font-semibold ${cor || 'text-ink'}`}>{valor}</p>
      {sub && <p className="mt-1 text-xs text-dim">{sub}</p>}
    </div>
  )
}

/** Tabela simples e rolável no celular: o painel é usado em notebook, mas abre em qualquer tela. */
function Tabela({ colunas, linhas, vazio }) {
  if (!linhas.length) {
    return <p className="rounded-panel border border-line bg-panel px-5 py-8 text-center text-sm text-mute">{vazio}</p>
  }
  return (
    <div className="overflow-x-auto rounded-panel border border-line bg-panel">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead>
          <tr className="border-b border-hair text-xs text-dim">
            {colunas.map((c) => <th key={c.id} className={`px-4 py-3 font-normal ${c.direita ? 'text-right' : ''}`}>{c.rotulo}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-hair">
          {linhas.map((l, i) => (
            <tr key={l.id || i} className="hover:bg-raise/40">
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

/* ------------------------------------------------------------------------ */

function Resumo({ dados }) {
  if (!dados) return null
  const t = dados.total
  return (
    <>
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Cartao rotulo="Recargas agora" valor={num(t.recargas_ativas, 0)} cor={t.recargas_ativas ? 'text-live' : undefined}
                sub={`${potencia(t.potencia_agora_kw)} em uso`} />
        <Cartao rotulo="Cadastros" valor={num(t.usuarios, 0)}
                sub={`${t.usuarios_por_tipo.morador} moradores · ${t.usuarios_por_tipo.visitante} visitantes · ${t.novos_mes} novos no mês`} />
        <Cartao rotulo="Faturamento do mês" valor={brl(t.faturamento_mes)}
                sub={`${num(t.recargas_mes, 0)} recargas · ${brl(t.creditos_carteira_mes)} em créditos`} />
        <Cartao rotulo="Chamados em aberto" valor={t.chamados_abertos == null ? '—' : num(t.chamados_abertos, 0)}
                cor={t.chamados_abertos ? 'text-flux' : undefined}
                sub={t.chamados_abertos == null ? 'Rode o db/20 para ativar' : 'Aguardando resposta'} />
        <Cartao rotulo="Energia do mês" valor={energia(t.energia_mes_kwh)}
                sub={`${energia(t.energia_ponta_mes_kwh)} na ponta · ${energia(t.energia_solar_mes_kwh)} solar`} />
        <Cartao rotulo="Recargas hoje" valor={num(t.recargas_hoje, 0)} />
        <Cartao rotulo="Recusadas no mês" valor={num(t.recusadas_mes, 0)} sub="Saldo, limite ou cartão" />
        <Cartao rotulo="Carregadores" valor={num(t.carregadores, 0)}
                sub={Object.entries(t.carregadores_por_status).map(([k, v]) => `${v} ${(ROTULO_STATUS[k] || k).toLowerCase()}`).join(' · ')} />
      </div>
      <h3 className="mb-3 text-lg font-semibold tracking-tight text-ink">Por local</h3>
      <Tabela
        vazio="Nenhum local cadastrado."
        linhas={dados.por_local}
        colunas={[
          { id: 'nome', rotulo: 'Local', render: (l) => <span className="font-medium text-ink">{l.nome}</span> },
          { id: 'recargas_ativas', rotulo: 'Agora', direita: true,
            render: (l) => <span className={l.recargas_ativas ? 'text-live' : ''}>{l.recargas_ativas} · {potencia(l.potencia_agora_kw)}</span> },
          { id: 'usuarios', rotulo: 'Cadastros', direita: true },
          { id: 'recargas_mes', rotulo: 'Recargas (mês)', direita: true },
          { id: 'energia', rotulo: 'Energia (mês)', direita: true, render: (l) => energia(l.energia_mes_kwh) },
          { id: 'faturamento', rotulo: 'Faturamento', direita: true, render: (l) => brl(l.faturamento_mes) },
          { id: 'carregadores', rotulo: 'Pontos', direita: true },
        ]}
      />
    </>
  )
}

function Chamados({ lista, onAtualizar }) {
  const [filtro, setFiltro] = useState('abertos')
  const [respondendo, setRespondendo] = useState(null)
  const [texto, setTexto] = useState('')
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)

  const visiveis = lista.filter((c) => filtro === 'todos' || (filtro === 'abertos' ? c.status !== 'resolvido' : c.status === 'resolvido'))

  async function salvar(c, corpo) {
    setSalvando(true)
    setErro('')
    try {
      await patch(`/gestor/geral/chamados/${c.id}`, corpo)
      setRespondendo(null)
      setTexto('')
      onAtualizar()
    } catch (e) {
      setErro(e.message)
    } finally {
      setSalvando(false)
    }
  }

  return (
    <>
      <div className="mb-3 flex gap-1">
        {[['abertos', 'Em aberto'], ['resolvidos', 'Resolvidos'], ['todos', 'Todos']].map(([id, r]) => (
          <button key={id} type="button" onClick={() => setFiltro(id)}
                  className={`rounded-chip px-3 py-1.5 text-sm ${filtro === id ? 'nav-ativo text-ink' : 'text-mute hover:bg-raise/60'}`}>{r}</button>
        ))}
      </div>
      {erro && <p className="mb-3 text-sm text-flux">{erro}</p>}
      {!visiveis.length && (
        <p className="rounded-panel border border-line bg-panel px-5 py-8 text-center text-sm text-mute">Nenhum chamado aqui.</p>
      )}
      <div className="space-y-3">
        {visiveis.map((c) => (
          <article key={c.id} className="rounded-panel border border-line bg-panel p-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h4 className="font-medium text-ink">{c.assunto}</h4>
              <Status valor={c.status} />
            </div>
            <p className="mt-1 text-xs text-dim">
              {c.usuario || '—'}{c.bloco_apto ? ` · ${c.bloco_apto}` : ''}{c.local ? ` · ${c.local}` : ''} · {dataHora(c.criado_em)}
            </p>
            <p className="mt-3 whitespace-pre-wrap text-sm text-mute">{c.mensagem}</p>
            {c.resposta && (
              <div className="mt-3 rounded-chip border border-hair bg-raise/50 px-4 py-3 text-sm">
                <p className="mb-1 text-xs text-dim">Resposta · {dataHora(c.respondido_em)}</p>
                <p className="whitespace-pre-wrap text-ink">{c.resposta}</p>
              </div>
            )}
            {respondendo === c.id ? (
              <div className="mt-3">
                <textarea value={texto} onChange={(e) => setTexto(e.target.value)} rows={3} maxLength={2000}
                          placeholder="Resposta para o usuário (ele recebe no sino e no Suporte)"
                          className="w-full rounded-chip border border-line bg-raise/50 px-3 py-2 text-sm text-ink focus:border-flux focus:outline-none" />
                <div className="mt-2 flex gap-2">
                  <button type="button" disabled={salvando || texto.trim().length < 2}
                          onClick={() => salvar(c, { resposta: texto.trim() })}
                          className="rounded-chip bg-flux px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
                    Responder e resolver
                  </button>
                  <button type="button" onClick={() => setRespondendo(null)} className="rounded-chip px-3 py-2 text-sm text-mute hover:text-ink">
                    Cancelar
                  </button>
                </div>
              </div>
            ) : (
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" onClick={() => { setRespondendo(c.id); setTexto(c.resposta || '') }}
                        className="rounded-chip border border-line px-3 py-1.5 text-sm text-ink hover:border-flux/50">
                  {c.resposta ? 'Editar resposta' : 'Responder'}
                </button>
                {c.status === 'aberto' && (
                  <button type="button" disabled={salvando} onClick={() => salvar(c, { status: 'em_andamento' })}
                          className="rounded-chip px-3 py-1.5 text-sm text-mute hover:text-ink">Marcar em andamento</button>
                )}
                {c.status === 'resolvido' && (
                  <button type="button" disabled={salvando} onClick={() => salvar(c, { status: 'aberto' })}
                          className="rounded-chip px-3 py-1.5 text-sm text-mute hover:text-ink">Reabrir</button>
                )}
              </div>
            )}
          </article>
        ))}
      </div>
    </>
  )
}

function Notificacoes({ lista, locais, usuarios, onAtualizar }) {
  const [mensagem, setMensagem] = useState('')
  const [destino, setDestino] = useState('todos')
  const [alvo, setAlvo] = useState('')
  const [estado, setEstado] = useState({ erro: '', ok: '' })
  const [enviando, setEnviando] = useState(false)

  async function enviar(e) {
    e.preventDefault()
    setEnviando(true)
    setEstado({ erro: '', ok: '' })
    try {
      const r = await post('/gestor/geral/notificacoes', {
        mensagem: mensagem.trim(), destino,
        condominio_id: destino === 'local' ? alvo : undefined,
        usuario_id: destino === 'usuario' ? alvo : undefined,
      })
      setEstado({ erro: '', ok: `Enviada para ${r.enviadas} ${r.enviadas === 1 ? 'pessoa' : 'pessoas'}.` })
      setMensagem('')
      onAtualizar()
    } catch (err) {
      setEstado({ erro: err.message, ok: '' })
    } finally {
      setEnviando(false)
    }
  }

  const campo = 'rounded-chip border border-line bg-raise/50 px-3 py-2 text-sm text-ink focus:border-flux focus:outline-none'
  return (
    <>
      <form onSubmit={enviar} className="mb-5 rounded-panel border border-line bg-panel p-5">
        <h3 className="font-medium text-ink">Enviar notificação</h3>
        <p className="mt-1 text-sm text-dim">Aparece no sino do app na hora. Gestores não recebem.</p>
        <textarea value={mensagem} onChange={(e) => setMensagem(e.target.value)} rows={2} maxLength={300} required
                  placeholder="Ex.: Manutenção no carregador 2 amanhã, das 9h às 11h."
                  className={`${campo} mt-3 w-full`} />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <select value={destino} onChange={(e) => { setDestino(e.target.value); setAlvo('') }} className={campo}>
            <option value="todos">Todos os usuários</option>
            <option value="local">Um local</option>
            <option value="usuario">Uma pessoa</option>
          </select>
          {destino === 'local' && (
            <select value={alvo} onChange={(e) => setAlvo(e.target.value)} required className={campo}>
              <option value="">Escolha o local</option>
              {locais.map((l) => <option key={l.id} value={l.id}>{l.nome}</option>)}
            </select>
          )}
          {destino === 'usuario' && (
            <select value={alvo} onChange={(e) => setAlvo(e.target.value)} required className={campo}>
              <option value="">Escolha a pessoa</option>
              {usuarios.filter((u) => u.tipo_usuario !== 'gestor').map((u) => <option key={u.id} value={u.id}>{u.nome}</option>)}
            </select>
          )}
          <button type="submit" disabled={enviando || mensagem.trim().length < 3}
                  className="rounded-chip bg-flux px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
            {enviando ? 'Enviando…' : 'Enviar'}
          </button>
          {estado.ok && <span className="text-sm text-live">{estado.ok}</span>}
          {estado.erro && <span className="text-sm text-flux">{estado.erro}</span>}
        </div>
      </form>
      <Tabela vazio="Nenhuma notificação." linhas={lista} colunas={[
        { id: 'criado_em', rotulo: 'Quando', render: (n) => <span className="num text-mute">{dataHora(n.criado_em)}</span> },
        { id: 'usuario', rotulo: 'Para' },
        { id: 'mensagem', rotulo: 'Mensagem', render: (n) => <span className="text-ink">{n.mensagem}</span> },
        { id: 'lida', rotulo: 'Lida', render: (n) => (n.lida ? <span className="text-live">sim</span> : <span className="text-dim">não</span>) },
      ]} />
    </>
  )
}

/* ------------------------------------------------------------------------ */

function VisaoGeralPage() {
  const [aba, setAba] = useState('resumo')
  const [dados, setDados] = useState({})
  const [busca, setBusca] = useState('')
  const [erro, setErro] = useState('')
  const [atualizado, setAtualizado] = useState(null)

  // Cada aba busca só o que mostra; o resumo e os usuários vão juntos porque
  // alimentam os seletores de notificação.
  const carregar = useCallback(async () => {
    const pedidos = {
      resumo: ['resumo'], chamados: ['chamados'], recargas: ['recargas'], usuarios: ['usuarios'],
      pagamentos: ['pagamentos'], notificacoes: ['notificacoes', 'usuarios', 'resumo'],
    }[aba]
    try {
      const respostas = await Promise.all(pedidos.map((p) => get(`/gestor/geral/${p}`).catch((e) => ({ __erro: e.message }))))
      const novo = {}
      pedidos.forEach((p, i) => { novo[p] = respostas[i] })
      const falha = respostas.find((r) => r && r.__erro)
      setErro(falha ? falha.__erro : '')
      setDados((d) => ({ ...d, ...Object.fromEntries(Object.entries(novo).filter(([, v]) => !v?.__erro)) }))
      setAtualizado(new Date())
    } catch (e) {
      setErro(e.message)
    }
  }, [aba])

  useEffect(() => {
    carregar()
    const id = setInterval(carregar, 10000)
    return () => clearInterval(id)
  }, [carregar])

  const usuariosFiltrados = useMemo(() => {
    const b = busca.trim().toLowerCase()
    return (dados.usuarios || []).filter((u) => !b || u.nome.toLowerCase().includes(b) || (u.local || '').toLowerCase().includes(b))
  }, [dados.usuarios, busca])

  const abertos = dados.resumo?.total?.chamados_abertos

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-ink">Visão geral</h2>
          <p className="mt-1 text-sm text-mute">Todos os locais, ao vivo. Atualiza a cada 10 s.</p>
        </div>
        <p className="num text-xs text-dim">{atualizado ? `atualizado ${atualizado.toLocaleTimeString('pt-BR')}` : 'carregando…'}</p>
      </div>

      <nav className="mb-5 flex gap-1 overflow-x-auto pb-1" aria-label="Seções da visão geral">
        {ABAS.map((a) => (
          <button key={a.id} type="button" onClick={() => setAba(a.id)} aria-current={aba === a.id ? 'page' : undefined}
                  className={`shrink-0 rounded-chip px-3.5 py-2 text-sm ${aba === a.id ? 'nav-ativo text-ink' : 'text-mute hover:bg-raise/60 hover:text-ink'}`}>
            {a.rotulo}
            {a.id === 'chamados' && abertos > 0 && (
              <span className="num ml-2 rounded-full bg-flux px-1.5 text-[0.6875rem] text-white">{abertos}</span>
            )}
          </button>
        ))}
      </nav>

      {erro && <p className="mb-4 rounded-chip border border-flux/40 bg-flux/10 px-4 py-3 text-sm text-flux">{erro}</p>}

      {aba === 'resumo' && <Resumo dados={dados.resumo} />}
      {aba === 'chamados' && <Chamados lista={dados.chamados || []} onAtualizar={carregar} />}
      {aba === 'recargas' && (
        <Tabela vazio="Nenhuma recarga." linhas={dados.recargas || []} colunas={[
          { id: 'criado_em', rotulo: 'Quando', render: (s) => <span className="num text-mute">{dataHora(s.criado_em)}</span> },
          { id: 'usuario', rotulo: 'Usuário', render: (s) => <span className="text-ink">{s.usuario || '—'}</span> },
          { id: 'local', rotulo: 'Local / ponto', render: (s) => `${s.local || '—'} · nº ${s.carregador_numero ?? '—'}` },
          { id: 'status', rotulo: 'Status', render: (s) => <Status valor={s.status} /> },
          { id: 'bateria', rotulo: 'Bateria', direita: true,
            render: (s) => `${num(s.percentual_bateria_inicial, 0)}% → ${num(s.percentual_bateria_atual, 0)}%` },
          { id: 'energia', rotulo: 'Energia', direita: true, render: (s) => energia(s.energia_entregue_kwh) },
          { id: 'valor', rotulo: 'Valor', direita: true,
            render: (s) => (s.custo_final != null ? brl(s.custo_final) : <span className="text-dim">{brl(s.custo_estimado)} est.</span>) },
        ]} />
      )}
      {aba === 'usuarios' && (
        <>
          <input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Buscar por nome ou local"
                 className="mb-3 w-full max-w-sm rounded-chip border border-line bg-raise/50 px-3 py-2 text-sm text-ink focus:border-flux focus:outline-none" />
          <Tabela vazio="Nenhum cadastro." linhas={usuariosFiltrados} colunas={[
            { id: 'nome', rotulo: 'Nome', render: (u) => <span className="font-medium text-ink">{u.nome}</span> },
            { id: 'tipo_usuario', rotulo: 'Tipo', render: (u) => <span className="capitalize">{u.tipo_usuario}</span> },
            { id: 'local', rotulo: 'Local', render: (u) => `${u.local || '—'}${u.bloco_apto ? ` · ${u.bloco_apto}` : ''}` },
            { id: 'veiculos', rotulo: 'Veículos', render: (u) => <span className="text-mute">{u.veiculos.join(', ') || '—'}</span> },
            { id: 'recargas', rotulo: 'Recargas', direita: true },
            { id: 'saldo', rotulo: 'Saldo', direita: true, render: (u) => brl(u.saldo) },
            { id: 'criado_em', rotulo: 'Desde', render: (u) => <span className="num text-dim">{dataHora(u.criado_em)}</span> },
          ]} />
        </>
      )}
      {aba === 'pagamentos' && (
        <Tabela vazio="Nenhum movimento de carteira." linhas={dados.pagamentos || []} colunas={[
          { id: 'criado_em', rotulo: 'Quando', render: (m) => <span className="num text-mute">{dataHora(m.criado_em)}</span> },
          { id: 'usuario', rotulo: 'Usuário', render: (m) => <span className="text-ink">{m.usuario || '—'}</span> },
          { id: 'tipo', rotulo: 'Tipo', render: (m) => ROTULO_MOV[m.tipo] || m.tipo },
          { id: 'descricao', rotulo: 'Descrição', render: (m) => <span className="text-mute">{m.descricao || '—'}</span> },
          { id: 'valor', rotulo: 'Valor', direita: true,
            render: (m) => <span className={['pre_autorizacao', 'ajuste_debito'].includes(m.tipo) ? 'text-flux' : 'text-live'}>
              {['pre_autorizacao', 'ajuste_debito'].includes(m.tipo) ? '−' : '+'}{brl(Math.abs(m.valor))}</span> },
          { id: 'saldo_apos', rotulo: 'Saldo depois', direita: true, render: (m) => brl(m.saldo_apos) },
        ]} />
      )}
      {aba === 'notificacoes' && (
        <Notificacoes lista={dados.notificacoes || []} locais={dados.resumo?.por_local || []}
                      usuarios={dados.usuarios || []} onAtualizar={carregar} />
      )}
    </div>
  )
}

export default VisaoGeralPage
