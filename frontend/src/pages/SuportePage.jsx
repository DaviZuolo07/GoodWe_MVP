import { useState } from 'react'

/**
 * Suporte — conteúdo estático. Não toca no banco nem no backend.
 *
 * As perguntas foram escritas a partir do comportamento real do sistema
 * (derating térmico, saldo, trava de veículo duplicado). Se o comportamento
 * mudar, esta página precisa mudar junto.
 */

const FAQ = [
  {
    p: 'Por que o tempo estimado muda durante a recarga?',
    r: 'O carregador reduz a potência entregue quando esquenta, para proteger a eletrônica de potência. Acima de 35 °C essa perda entra no cálculo, então a estimativa se ajusta sozinha. A temperatura atual aparece no painel de detalhe de cada carregador.',
  },
  {
    p: 'O valor é cobrado quando?',
    r: 'No momento em que você confirma a recarga. O custo estimado é descontado do seu saldo de uma vez, com base na energia necessária para chegar a 100% e na tarifa do carregador.',
  },
  {
    p: 'Meu saldo acabou no meio da demonstração.',
    r: 'Vá em Carteira e adicione saldo. É um crédito simulado, sem gateway de pagamento real por trás — existe justamente para não travar testes e gravações.',
  },
  {
    p: 'Não consigo iniciar recarga em dois carregadores ao mesmo tempo.',
    r: 'É proposital. O mesmo veículo não pode ocupar dois pontos simultaneamente, então encerre a recarga ativa antes de começar outra. A trava vale por veículo e também impede cadastrar a mesma placa duas vezes.',
  },
  {
    p: 'Para que serve o cartão RFID?',
    r: 'É o que autoriza a recarga no leitor físico. Vincule o UID do seu cartão em Configurações — o mesmo cartão passa a liberar o carregador quando o hardware estiver conectado.',
  },
  {
    p: 'Os dados atualizam sozinhos?',
    r: 'Sim. O indicador "Tempo real" no topo mostra a conexão ativa com o banco. Energia, bateria e status mudam na tela sem recarregar a página.',
  },
]

function Item({ p, r, aberto, onToggle }) {
  return (
    <div className="border-b border-hair last:border-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={aberto}
        className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left transition-colors duration-200 hover:bg-raise/40"
      >
        <span className={`text-sm font-medium ${aberto ? 'text-ink' : 'text-mute'}`}>{p}</span>
        <svg
          viewBox="0 0 24 24"
          className={`h-4 w-4 shrink-0 text-dim transition-transform duration-200 ${aberto ? 'rotate-180' : ''}`}
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
        <p className="rise px-5 pb-5 text-sm leading-relaxed text-mute">{r}</p>
      )}
    </div>
  )
}

function SuportePage({ onAbrirChat }) {
  const [abertoIdx, setAbertoIdx] = useState(0)

  return (
    <div>
      <div className="mb-8">
        <h2 className="text-xl font-semibold tracking-tight text-ink lg:text-[1.375rem]">Suporte</h2>
        <p className="mt-1 text-sm text-dim">Dúvidas comuns sobre recarga, cobrança e cartão.</p>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <div className="overflow-hidden rounded-panel border border-line bg-panel">
          {FAQ.map((f, i) => (
            <Item
              key={f.p}
              p={f.p}
              r={f.r}
              aberto={abertoIdx === i}
              onToggle={() => setAbertoIdx(abertoIdx === i ? -1 : i)}
            />
          ))}
        </div>

        <aside className="h-fit rounded-panel border border-line bg-panel p-6">
          <span className="flex h-10 w-10 items-center justify-center rounded-chip bg-flux/12 text-flux ring-1 ring-flux/25">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M13 2.5 4.8 13.8H11l-1 7.7 8.2-11.3H12l1-7.7Z" />
            </svg>
          </span>

          <h3 className="mt-4 font-medium text-ink">Não achou sua resposta?</h3>
          <p className="mt-1.5 text-sm leading-relaxed text-dim">
            O assistente consulta os dados da sua recarga em tempo real e responde na hora.
          </p>

          <button
            type="button"
            onClick={onAbrirChat}
            className="mt-5 w-full rounded-chip bg-flux px-5 py-2.5 text-sm font-medium text-white
                       transition-all duration-200 hover:bg-flare hover:shadow-flux active:scale-[0.99]"
          >
            Falar com o assistente
          </button>

          <div className="mt-5 border-t border-hair pt-5">
            <p className="eyebrow mb-2">Projeto</p>
            <p className="text-xs leading-relaxed text-dim">
              GoodWe ChargeOps AI Assistant — MVP acadêmico FIAP + GoodWe.
            </p>
          </div>
        </aside>
      </div>
    </div>
  )
}

export default SuportePage
