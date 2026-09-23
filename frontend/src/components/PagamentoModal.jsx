import { useCallback, useEffect, useState } from 'react'
import { post } from '../lib/api.js'
import { supabase } from '../supabaseClient.js'
import { brl, duracao, energia, num, potencia } from '../lib/formato.js'
import MonitorRecarga from './MonitorRecarga.jsx'

/**
 * Início de recarga - o fluxo do cartão, de ponta a ponta.
 *
 *   BATERIA    quanto tem, até onde carregar
 *   CONFIRMAR  prévia vinda do backend (a MESMA conta que vai cobrar)
 *   AGUARDANDO "aproxime o cartão": o ESP32 já recebeu o pedido e está
 *              piscando. Se o cartão for recusado por saldo, a espera
 *              CONTINUA e esta tela vira o botão de adicionar saldo - o
 *              morador põe crédito e aproxima de novo, sem recomeçar nada.
 *   MONITOR    recarga rodando, com energia e potência medidas ao vivo
 *   FIM        recusa, prazo esgotado ou recibo da recarga concluída
 *
 * Nada disso depende da resposta de uma requisição: quem lê o cartão é a
 * placa, que conversa com o backend, não com este navegador. A tela escuta a
 * LINHA da sessão pelo Realtime - o banco é o canal de retorno.
 */

const ETAPAS = { BATERIA: 'bateria', CONFIRMAR: 'confirmar', AGUARDANDO: 'aguardando',
                 MONITOR: 'monitor', FIM: 'fim' }

const MOTIVOS = {
  tempo_esgotado: 'O tempo para aproximar o cartão se esgotou.',
  cancelado_pelo_usuario: 'A recarga foi cancelada.',
  saldo_insuficiente: 'Saldo insuficiente para esta recarga.',
  limite_de_potencia: 'O condomínio ficou sem potência disponível agora.',
}

function Linha({ rotulo, valor, cor }) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-dim">{rotulo}</span>
      <span className={`num ${cor || 'text-ink'}`}>{valor}</span>
    </div>
  )
}

function Moldura({ titulo, etiqueta, onFechar, children }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-void/80 p-4">
      <div className="max-h-[92vh] w-full max-w-sm overflow-y-auto rounded-panel border border-line bg-panel p-6">
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h3 className="font-semibold text-ink">{titulo}</h3>
            {etiqueta && <p className="eyebrow mt-0.5 text-[0.625rem] text-flux">{etiqueta}</p>}
          </div>
          <button onClick={onFechar} className="text-dim transition-colors hover:text-ink">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

function PagamentoModal({ charger, sessao, veiculos, onClose, onSucesso, onIrParaCarteira, onSaldo }) {
  const { usuario } = sessao

  // Bancada USB só aceita celular; wallbox só aceita carro. A checagem existe
  // também no backend - esta aqui é só para não oferecer o impossível.
  const compativeis = veiculos.filter((v) =>
    charger.perfil === 'bancada' ? v.tipo === 'celular' : v.tipo !== 'celular')
  const [veiculoId, setVeiculoId] = useState(compativeis[0]?.id || '')
  const veiculo = compativeis.find((v) => v.id === veiculoId) || compativeis[0]

  const [etapa, setEtapa] = useState(ETAPAS.BATERIA)
  const [percentual, setPercentual] = useState(20)
  const [alvo, setAlvo] = useState(80)
  const [erro, setErro] = useState('')
  const [enviando, setEnviando] = useState(false)

  const [previa, setPrevia] = useState(null)
  const [calculando, setCalculando] = useState(false)
  const [sessaoPreparada, setSessaoPreparada] = useState(null)
  const [segundos, setSegundos] = useState(0)
  const [semSaldo, setSemSaldo] = useState(false)
  const [creditando, setCreditando] = useState(false)
  const [mensagemFim, setMensagemFim] = useState('')
  const [saldo, setSaldo] = useState(usuario.saldo)

  const temSensor = charger.origem === 'hardware'
  const reserva = Math.max(previa?.custo_estimado || 0, 1)

  // --- Prévia: sempre do backend ------------------------------------------
  useEffect(() => {
    if (etapa !== ETAPAS.CONFIRMAR || !veiculo) return
    let cancelado = false
    setCalculando(true)
    post('/recargas/previa', {
      charger_id: charger.id, veiculo_id: veiculo.id,
      percentual_bateria_atual: Number(percentual), alvo_percentual: Number(alvo),
    })
      .then((d) => { if (!cancelado) setPrevia(d) })
      .catch((e) => { if (!cancelado) setErro(e.message) })
      .finally(() => { if (!cancelado) setCalculando(false) })
    return () => { cancelado = true }
  }, [etapa, veiculo, charger.id, percentual, alvo])

  // --- Escuta a linha da sessão -------------------------------------------
  useEffect(() => {
    if (!sessaoPreparada?.id || (etapa !== ETAPAS.AGUARDANDO && etapa !== ETAPAS.MONITOR)) return

    const canal = supabase
      .channel(`espera-cartao-${sessaoPreparada.id}`)
      .on('postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'sessoes_recarga', filter: `id=eq.${sessaoPreparada.id}` },
        (evento) => {
          const nova = evento.new
          if (nova.status === 'carregando') {
            setSemSaldo(false)
            setEtapa(ETAPAS.MONITOR)
            onSaldo?.()
          } else if (nova.status === 'aguardando_rfid' && nova.motivo_recusa === 'saldo_insuficiente') {
            setSemSaldo(true)          // cartão lido, saldo curto: espera continua
          } else if (nova.status === 'recusada' || nova.status === 'cancelada') {
            setMensagemFim(MOTIVOS[nova.motivo_recusa] || 'A recarga não foi autorizada.')
            setEtapa(ETAPAS.FIM)
          }
        })
      .subscribe()

    return () => supabase.removeChannel(canal)
  }, [sessaoPreparada, etapa, onSaldo])

  useEffect(() => {
    if (etapa !== ETAPAS.AGUARDANDO) return
    const t = setInterval(() => setSegundos((s) => Math.max(0, s - 1)), 1000)
    return () => clearInterval(t)
  }, [etapa])

  // --- Ações ---------------------------------------------------------------
  async function preparar() {
    setErro(''); setEnviando(true)
    try {
      const d = await post('/recargas/preparar', {
        charger_id: charger.id, veiculo_id: veiculo.id,
        percentual_bateria_atual: Number(percentual), alvo_percentual: Number(alvo),
      })
      setSessaoPreparada(d.sessao)
      if (d.aguardando_cartao) {
        setSegundos(d.segundos_para_aproximar || 120)
        setSemSaldo(d.saldo_suficiente === false)
        setEtapa(ETAPAS.AGUARDANDO)
      } else {
        setEtapa(ETAPAS.MONITOR)      // ponto simulado: o app é o cartão
        onSaldo?.()
      }
    } catch (e) {
      setErro(e.message)
    } finally {
      setEnviando(false)
    }
  }

  async function adicionarSaldo(valor) {
    setCreditando(true)
    try {
      const d = await post('/me/carteira/creditar', { valor })
      setSaldo(d.saldo_atual)
      setSemSaldo(false)
      onSaldo?.(d.saldo_atual)
    } catch (e) {
      setErro(e.message)
    } finally {
      setCreditando(false)
    }
  }

  const cancelar = useCallback(async () => {
    if (sessaoPreparada?.id) {
      try { await post(`/recargas/${sessaoPreparada.id}/cancelar`) } catch { /* expira sozinho */ }
    }
    onClose()
  }, [sessaoPreparada, onClose])

  const fechar = etapa === ETAPAS.AGUARDANDO ? cancelar : onClose

  if (!veiculo) {
    return (
      <Moldura titulo={`Carregador ${charger.numero}`} onFechar={onClose}>
        <p className="mb-4 text-sm leading-relaxed text-mute">
          {charger.perfil === 'bancada'
            ? 'Este ponto é a bancada USB do ESP32 e só aceita dispositivos do tipo celular. Cadastre um em Meus Veículos.'
            : 'Você ainda não tem nenhum veículo cadastrado.'}
        </p>
        <button onClick={onClose} className="w-full rounded-chip bg-raise py-2.5 text-mute hover:text-ink">
          Fechar
        </button>
      </Moldura>
    )
  }

  return (
    <Moldura titulo={`Carregador ${charger.numero}`} onFechar={fechar}
             etiqueta={charger.perfil === 'bancada' ? 'Bancada USB · ESP32' : null}>
      {erro && (
        <div className="mb-4 rounded-chip border border-flux/40 bg-flux/10 px-3 py-2 text-sm text-flux">{erro}</div>
      )}

      {etapa === ETAPAS.BATERIA && (
        <div>
          {compativeis.length > 1 && (
            <div className="mb-4">
              <label className="mb-1 block text-sm text-mute">Qual dispositivo?</label>
              <select className="w-full rounded-chip border border-line bg-raise px-3 py-2 text-ink"
                      value={veiculoId} onChange={(e) => setVeiculoId(e.target.value)}>
                {compativeis.map((v) => (
                  <option key={v.id} value={v.id}>{v.modelo}{v.placa ? ` · ${v.placa}` : ''}</option>
                ))}
              </select>
            </div>
          )}

          <p className="mb-2 text-sm text-mute">Bateria atual do {veiculo.modelo}</p>
          <input type="range" min="0" max="99" value={percentual} className="w-full accent-[var(--color-flux)]"
                 onChange={(e) => setPercentual(Number(e.target.value))} />
          <p className="num mb-4 text-center text-2xl font-semibold text-ink">{percentual}%</p>

          <p className="mb-2 text-sm text-mute">Carregar até</p>
          <div className="mb-2 flex gap-2">
            {[60, 80, 100].map((v) => (
              <button key={v} onClick={() => setAlvo(v)}
                      className={`flex-1 rounded-chip py-2 text-sm transition ${
                        Number(alvo) === v ? 'bg-flux text-white' : 'bg-raise text-mute hover:bg-line'}`}>
                {v}%
              </button>
            ))}
          </div>
          <p className="mb-4 text-xs leading-relaxed text-dim">
            Parar em 80% carrega bem mais rápido: acima disso a bateria aceita cada vez menos potência.
          </p>

          <button
            onClick={() => {
              if (Number(alvo) <= Number(percentual)) return setErro('O alvo precisa ser maior que a bateria atual.')
              setErro(''); setEtapa(ETAPAS.CONFIRMAR)
            }}
            className="w-full rounded-chip bg-flux py-2.5 font-medium text-white transition hover:bg-flare">
            Continuar
          </button>
        </div>
      )}

      {etapa === ETAPAS.CONFIRMAR && (
        <div>
          <div className="mb-4 space-y-2 rounded-panel bg-raise/50 p-4">
            <Linha rotulo="Dispositivo" valor={veiculo.modelo} />
            <Linha rotulo="Carga" valor={`${percentual}% → ${alvo}%`} />
            <Linha rotulo="Energia necessária" valor={energia(previa?.energia_necessaria_kwh)} />
            <Linha rotulo="Tempo estimado" valor={duracao(previa?.tempo_estimado_min)} />
            <Linha rotulo="Potência liberada" valor={potencia(previa?.potencia_efetiva_kw)} />
            <hr className="border-line" />
            <Linha rotulo={`Tarifa${previa?.em_ponta ? ' (ponta)' : ''}`}
                   valor={`${brl(previa?.tarifa_kwh)} / kWh`} cor={previa?.em_ponta ? 'text-queue' : undefined} />
            <Linha rotulo="Custo estimado" valor={brl(previa?.custo_estimado)} />
            <Linha rotulo="Seu saldo" valor={brl(saldo)}
                   cor={previa && saldo < reserva ? 'text-flux' : 'text-live'} />
          </div>

          {previa?.em_ponta && (
            <p className="mb-3 rounded-chip border border-queue/30 bg-queue/10 px-3 py-2 text-xs leading-relaxed text-queue">
              Horário de ponta: a tarifa está {num(previa.multiplicador_ponta, 2)}x maior e o condomínio libera menos
              potência. Fora da ponta, a mesma energia sairia por{' '}
              {brl(previa.energia_necessaria_kwh * previa.tarifa_base_kwh)}.
            </p>
          )}
          {previa?.limitado_pela_demanda && (
            <p className="mb-3 rounded-chip border border-queue/30 bg-queue/10 px-3 py-2 text-xs leading-relaxed text-queue">
              A gestão de demanda liberou {potencia(previa.potencia_prevista_kw)} para este ponto agora, por causa das
              outras recargas em andamento. O tempo acima já considera isso.
            </p>
          )}
          {previa && !previa.admissao?.ok && (
            <p className="mb-3 rounded-chip border border-flux/30 bg-flux/10 px-3 py-2 text-xs leading-relaxed text-flux">
              {previa.admissao.mensagem}
            </p>
          )}

          {calculando && !previa ? (
            <p className="py-2 text-center text-sm text-dim">Calculando...</p>
          ) : (
            <button onClick={preparar} disabled={enviando || !previa || !previa.admissao?.ok}
                    className="w-full rounded-chip bg-flux py-2.5 font-medium text-white transition
                               hover:bg-flare disabled:opacity-40">
              {enviando ? 'Preparando...' : temSensor ? 'Confirmar e aproximar cartão' : 'Confirmar e iniciar'}
            </button>
          )}
        </div>
      )}

      {etapa === ETAPAS.AGUARDANDO && (
        <div className="py-2 text-center">
          <div className="relative mx-auto mb-5 flex h-20 w-20 items-center justify-center">
            <span className="absolute inset-0 rounded-full border-2 border-flux/40"
                  style={{ animation: 'gw-ping 1.6s ease-out infinite' }} />
            <span className="flex h-16 w-16 items-center justify-center rounded-full border-2 border-flux text-flux">
              <svg viewBox="0 0 24 24" className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                <rect x="3" y="6" width="18" height="12" rx="2" />
                <path d="M14 10.5a3 3 0 0 1 0 3M16.5 8.5a6 6 0 0 1 0 7" />
              </svg>
            </span>
          </div>

          <p className="mb-1 font-medium text-ink">Aproxime seu cartão do leitor</p>
          <p className="mb-5 text-xs leading-relaxed text-dim">
            O leitor do carregador {charger.numero} já está pedindo o cartão. A recarga só começa na leitura.
          </p>

          {semSaldo ? (
            <div className="mb-4 rounded-panel border border-flux/40 bg-flux/10 p-4 text-left">
              <p className="mb-1 text-sm font-medium text-flux">Saldo insuficiente</p>
              <p className="mb-3 text-xs leading-relaxed text-mute">
                Você tem {brl(saldo)} e esta recarga reserva {brl(reserva)}. Adicione saldo e aproxime o cartão de
                novo — a espera continua valendo.
              </p>
              <div className="flex gap-2">
                {[5, 20, 50].map((v) => (
                  <button key={v} disabled={creditando} onClick={() => adicionarSaldo(v)}
                          className="flex-1 rounded-chip bg-flux py-2 text-sm font-medium text-white
                                     transition hover:bg-flare disabled:opacity-40">
                    + {brl(v)}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mb-5 space-y-1 rounded-panel bg-raise/50 px-4 py-3">
              <Linha rotulo="Será reservado" valor={brl(reserva)} />
              <Linha rotulo="Tempo para aproximar"
                     valor={`${Math.floor(segundos / 60)}:${String(segundos % 60).padStart(2, '0')}`}
                     cor={segundos <= 20 ? 'text-flux' : 'text-mute'} />
            </div>
          )}

          <button onClick={cancelar}
                  className="w-full rounded-chip bg-raise py-2.5 font-medium text-mute transition hover:bg-line hover:text-ink">
            Cancelar
          </button>
        </div>
      )}

      {etapa === ETAPAS.MONITOR && (
        <div>
          <p className="mb-3 flex items-center gap-2 text-sm font-medium text-live">
            <span className="h-2 w-2 rounded-full bg-live dot-live" /> Recarregando
          </p>
          <MonitorRecarga
            sessaoId={sessaoPreparada?.id}
            temSensor={temSensor}
            compacto
            onEncerrada={(s) => {
              onSaldo?.()
              setMensagemFim(
                s.custo_final != null
                  ? `Recarga concluída: ${energia(s.energia_entregue_kwh)} por ${brl(s.custo_final)}`
                    + (Number(s.valor_estornado) > 0 ? `, com ${brl(s.valor_estornado)} estornados na carteira.` : '.')
                  : 'Recarga encerrada.')
              setEtapa(ETAPAS.FIM)
            }}
          />
          <button onClick={() => { onSucesso?.(); onClose() }}
                  className="mt-4 w-full rounded-chip bg-raise py-2.5 font-medium text-mute transition hover:bg-line hover:text-ink">
            Acompanhar pelo painel
          </button>
        </div>
      )}

      {etapa === ETAPAS.FIM && (
        <div className="py-3 text-center">
          <p className="mb-1 font-medium text-ink">Recarga encerrada</p>
          <p className="mb-5 text-sm leading-relaxed text-dim">{mensagemFim}</p>
          <div className="flex gap-2">
            <button onClick={() => { onSucesso?.(); onClose() }}
                    className="flex-1 rounded-chip bg-raise py-2.5 font-medium text-mute transition hover:bg-line hover:text-ink">
              Fechar
            </button>
            <button onClick={onIrParaCarteira}
                    className="flex-1 rounded-chip bg-flux py-2.5 font-medium text-white transition hover:bg-flare">
              Ver carteira
            </button>
          </div>
        </div>
      )}
    </Moldura>
  )
}

export default PagamentoModal
