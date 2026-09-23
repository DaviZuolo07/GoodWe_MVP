import { num, potencia } from '../lib/formato.js'

/**
 * "Como funciona" - a página que responde, dentro do próprio app, o que a
 * banca apontou como pouco claro: gestão de demanda, cobrança e valor para
 * cada lado. Os números vêm do condomínio aberto na tela, não de exemplo.
 */

function Bloco({ titulo, subtitulo, children }) {
  return (
    <section className="rounded-panel border border-line bg-panel p-6">
      <h3 className="font-medium text-ink">{titulo}</h3>
      {subtitulo && <p className="mt-1 text-sm leading-relaxed text-dim">{subtitulo}</p>}
      <div className="mt-4 space-y-3 text-sm leading-relaxed text-mute">{children}</div>
    </section>
  )
}

function Passo({ n, titulo, children }) {
  return (
    <div className="flex gap-3">
      <span className="num mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-chip
                       bg-flux/12 text-xs font-semibold text-flux ring-1 ring-flux/25">{n}</span>
      <p><span className="text-ink">{titulo}</span> {children}</p>
    </div>
  )
}

function ComoFuncionaPage({ condominio }) {
  const limite = condominio?.limite_potencia_kw
  const ini = String(condominio?.ponta_inicio || '18:00').slice(0, 5)
  const fim = String(condominio?.ponta_fim || '21:00').slice(0, 5)
  const fator = Number(condominio?.ponta_fator_limite || 0.6)
  const mult = Number(condominio?.ponta_multiplicador_tarifa || 1.5)

  return (
    <div>
      <div className="mb-8">
        <h2 className="text-xl font-semibold tracking-tight text-ink lg:text-[1.375rem]">Como funciona</h2>
        <p className="mt-1 text-sm text-dim">
          O que o ChargeOps resolve, para quem mora, para quem administra e para quem vende.
        </p>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Bloco titulo="Gestão de demanda"
               subtitulo={`O quadro do ${condominio?.nome || 'condomínio'} aguenta ${potencia(limite)} para a garagem.`}>
          <p>
            Quatro carros de 7,4 kW pedem 29,6 kW ao mesmo tempo. Se o prédio não tem essa folga, o disjuntor geral
            desarma — e fica sem luz o prédio inteiro, não só a garagem.
          </p>
          <p>
            Por isso existe um alocador só: a cada 10 segundos ele soma o que cada ponto está pedindo e divide a
            potência disponível. Quem está no fim da carga precisa de menos e libera sobra para os outros. O ponto do
            ESP32 entra primeiro na conta, porque relé liga e desliga, não regula corrente.
          </p>
          <p>
            Em dias úteis, das {ini} às {fim}, a garagem fica com {num(fator * 100, 0)}% do limite: é quando o prédio
            todo consome mais. Se liberar mais um carro deixaria alguém abaixo de 1,4 kW (o mínimo que a norma
            permite sinalizar), a recarga não começa e o morador entra na fila com aviso — em vez de uma recarga que
            não anda.
          </p>
        </Bloco>

        <Bloco titulo="Cobrança" subtitulo="Reserva, medição, teto e estorno — nessa ordem.">
          <Passo n="1" titulo="Reserva.">
            Ao aproximar o cartão, o custo estimado fica reservado no saldo. Sem saldo, a recarga não começa: o app
            avisa e você adiciona crédito sem perder a vez no ponto.
          </Passo>
          <Passo n="2" titulo="Medição.">
            Cada kWh é contado pela tarifa do horário em que foi entregue. Na ponta, a energia custa {num(mult, 2)}x —
            uma recarga que começa às 17h e termina às 19h paga cada parte pelo preço da sua hora.
          </Passo>
          <Passo n="3" titulo="Teto.">
            Se o consumo alcançar o valor reservado, a recarga para sozinha. Ninguém paga mais do que autorizou.
          </Passo>
          <Passo n="4" titulo="Estorno.">
            No fim, cobramos o consumo real e a diferença volta na hora. Tudo aparece no extrato da Carteira.
          </Passo>
        </Bloco>

        <Bloco titulo="Para o morador">
          <p>
            Sabe antes de começar quanto vai custar, quanto vai demorar e por que — inclusive quando a potência foi
            reduzida pela demanda do prédio ou pela temperatura do equipamento.
          </p>
          <p>
            Durante a recarga, acompanha energia, potência, tensão e corrente medidas de verdade pelo sensor, e não
            um número estimado. E paga só o que usou.
          </p>
          <p>
            O assistente responde sobre a própria conta em linguagem simples, sem acesso a dado de vizinho: identidade
            vem do login, nunca do que se digita no chat.
          </p>
        </Bloco>

        <Bloco titulo="Para o gestor e para a empresa">
          <p>
            <span className="text-ink">Síndico:</span> vê a carga em tempo real contra o limite do quadro, a curva do
            dia, o faturamento, os estornos e o consumo por morador para rateio. Muda o limite e a janela de ponta na
            própria tela, sem chamar ninguém.
          </p>
          <p>
            <span className="text-ink">Administradora e revenda:</span> a mesma instalação atende vários condomínios,
            cada um com seus pontos, tarifas e limites. Pontos simulados e pontos físicos convivem: dá para operar
            antes de o hardware chegar e trocar sem mexer no aplicativo.
          </p>
          <p>
            <span className="text-ink">Fabricante:</span> a série medida fica gravada sessão a sessão, na mesma base
            que o app já usa. É o insumo para diagnóstico de equipamento, previsão de demanda e, no passo seguinte,
            priorizar recarga quando houver excedente solar do inversor.
          </p>
        </Bloco>
      </div>

      <p className="mt-5 rounded-panel border border-dashed border-line px-5 py-4 text-xs leading-relaxed text-dim">
        Projeto acadêmico FIAP + GoodWe. Os dados de moradores e condomínios são simulados; a medição de energia do
        ponto marcado como ESP32 é real, vinda do sensor da placa.
      </p>
    </div>
  )
}

export default ComoFuncionaPage
