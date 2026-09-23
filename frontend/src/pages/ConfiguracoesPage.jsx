import { useCallback, useEffect, useState } from 'react'
import { del, get, post } from '../lib/api.js'
import { potencia } from '../lib/formato.js'
import { useTema } from '../lib/tema.js'

/**
 * Configurações.
 *
 * O que já funciona de verdade hoje: vincular um cartão RFID, usando o
 * endpoint que já existe no backend (POST /usuarios/{id}/vincular-rfid).
 * É o mesmo cartão que o leitor físico do Arduino vai ler — ou seja, esta
 * tela é a ponte entre o cadastro e o hardware.
 *
 * O resto do perfil aparece em leitura. Editar nome, bloco e tipo depende de
 * um PATCH /usuarios/{id} que ainda não existe no main.py — quando ele
 * existir, os campos abaixo viram inputs e ganham um botão de salvar.
 */

function Secao({ titulo, descricao, children }) {
  return (
    <section className="rounded-panel border border-line bg-panel p-6">
      <h3 className="font-medium text-ink">{titulo}</h3>
      {descricao && <p className="mt-1 text-sm leading-relaxed text-dim">{descricao}</p>}
      <div className="mt-5">{children}</div>
    </section>
  )
}

function Campo({ label, valor, mono }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-hair py-3 last:border-0">
      <span className="text-sm text-dim">{label}</span>
      <span className={`text-sm text-ink ${mono ? 'num' : ''}`}>{valor || '—'}</span>
    </div>
  )
}

const OPCOES_TEMA = [
  {
    id: 'escuro',
    nome: 'Escuro',
    descricao: 'Contraste alto, pensado para garagem e uso noturno.',
    amostra: 'linear-gradient(160deg, #07080a 0%, #131720 55%, #212630 100%)',
  },
  {
    id: 'claro',
    nome: 'Prata',
    descricao: 'Superfície metálica clara, para ambientes bem iluminados.',
    amostra: 'linear-gradient(160deg, #b8cad4 0%, #d3d3d3 52%, #a9a9a9 100%)',
  },
]

function SeletorTema() {
  const { tema, trocarTema } = useTema()

  return (
    <div className="grid grid-cols-2 gap-3">
      {OPCOES_TEMA.map((opcao) => {
        const ativo = tema === opcao.id
        return (
          <button
            key={opcao.id}
            type="button"
            onClick={() => trocarTema(opcao.id)}
            aria-pressed={ativo}
            className={`group overflow-hidden rounded-panel border p-3 text-left transition duration-200
                        hover:-translate-y-0.5 ${
                          ativo
                            ? 'border-flux/70 shadow-flux'
                            : 'border-line hover:border-flux/40'
                        }`}
          >
            <span
              className="block h-16 w-full rounded-chip border border-hair"
              style={{ background: opcao.amostra }}
              aria-hidden="true"
            >
              {/* o vermelho da marca não muda entre temas — a amostra mostra isso */}
              <span className="m-2 block h-1.5 w-8 rounded-full bg-flux" />
            </span>

            <span className="mt-3 flex items-center gap-2">
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${ativo ? 'bg-flux' : 'bg-off'}`}
              />
              <span className={`text-sm font-medium ${ativo ? 'text-ink' : 'text-mute'}`}>
                {opcao.nome}
              </span>
            </span>

            <span className="mt-1 block text-xs leading-relaxed text-dim">{opcao.descricao}</span>
          </button>
        )
      })}
    </div>
  )
}

function ConfiguracoesPage({ sessao, condominio, onUsuarioAtualizado }) {
  const { usuario, veiculo } = sessao

  const [uid, setUid] = useState('')
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState('')
  const [ok, setOk] = useState('')
  const [cartoes, setCartoes] = useState({ pessoais: [], compartilhados: [] })

  const carregarCartoes = useCallback(async () => {
    try {
      setCartoes(await get('/me/cartoes'))
    } catch { /* a seção fica vazia; o resto da página continua */ }
  }, [])

  useEffect(() => { carregarCartoes() }, [carregarCartoes])

  async function vincularRfid(e) {
    e.preventDefault()
    setErro(''); setOk('')

    const valor = uid.trim().toUpperCase()
    if (!valor) return

    setSalvando(true)
    try {
      // /me/cartao cadastra um cartão PESSOAL para o dono do token. Não há
      // id na URL: era por ali que dava para pendurar o próprio cartão na
      // conta de outro morador e carregar com o saldo dele.
      await post('/me/cartao', { rfid_uid: valor })
      await carregarCartoes()
      onUsuarioAtualizado?.({})
      setOk('Cartão pessoal cadastrado. Ele autoriza só as suas recargas.')
      setUid('')
    } catch (e) {
      setErro(e.message)
    } finally {
      setSalvando(false)
    }
  }

  async function removerCartao(valor) {
    setErro(''); setOk('')
    try {
      await del(`/me/cartao/${valor}`)
      await carregarCartoes()
      setOk('Cartão removido.')
    } catch (e) {
      setErro(e.message)
    }
  }

  const inputClass =
    'w-full rounded-chip border border-line bg-raise/50 px-4 py-2.5 text-sm text-ink placeholder-dim transition-colors duration-200 focus:border-flux/50 focus:outline-none'

  return (
    <div>
      <div className="mb-8">
        <h2 className="text-xl font-semibold tracking-tight text-ink lg:text-[1.375rem]">
          Configurações
        </h2>
        <p className="mt-1 text-sm text-dim">Seus dados, seu cartão de acesso e o local ativo.</p>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* ---------------- Cartões RFID ---------------- */}
        <Secao
          titulo="Cartões RFID"
          descricao="O cartão diz que você está no ponto. Quem paga é quem preparou a recarga no app."
        >
          {erro && (
            <p className="mb-3 rounded-chip border border-flux/30 bg-flux/10 px-3 py-2 text-xs text-flux">
              {erro}
            </p>
          )}
          {ok && (
            <p className="mb-3 rounded-chip border border-live/30 bg-live/10 px-3 py-2 text-xs text-live">
              {ok}
            </p>
          )}

          {/* Cartão do condomínio: um plástico só, que atende todo mundo. */}
          {cartoes.compartilhados?.length > 0 && (
            <div className="mb-4 rounded-chip border border-hair bg-raise/40 px-4 py-3">
              <p className="text-sm text-ink">Cartão do condomínio</p>
              <p className="mt-0.5 text-xs leading-relaxed text-dim">
                Já existe um cartão compartilhado no seu condomínio
                {cartoes.compartilhados.map((c) => ` (${c.uid})`).join('')}. Você pode usá-lo sem
                cadastrar nada: prepare a recarga no app e aproxime. A cobrança sai da SUA carteira,
                porque a recarga é sua.
              </p>
            </div>
          )}

          <p className="mb-2 text-xs uppercase tracking-wider text-dim">Meus cartões pessoais</p>
          {cartoes.pessoais?.length > 0 ? (
            <ul className="mb-4 space-y-2">
              {cartoes.pessoais.map((c) => (
                <li key={c.uid}
                    className="flex items-center justify-between gap-3 rounded-chip border border-hair
                               bg-raise/40 px-4 py-2.5">
                  <div className="min-w-0">
                    <p className="num truncate text-sm text-ink">{c.uid}</p>
                    <p className="truncate text-xs text-dim">{c.apelido || 'Cartão pessoal'}</p>
                  </div>
                  <button onClick={() => removerCartao(c.uid)}
                          className="shrink-0 text-xs text-dim transition-colors hover:text-flux">
                    remover
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mb-4 rounded-chip border border-dashed border-line px-4 py-3 text-xs
                          leading-relaxed text-dim">
              Nenhum cartão pessoal. Cadastre um se quiser que só o SEU cartão libere as suas
              recargas — é a trava mais forte, e dispensa o cartão do condomínio.
            </p>
          )}

          <form onSubmit={vincularRfid} className="space-y-3">
            <div>
              <label className="mb-1.5 block text-xs text-dim">UID do cartão</label>
              <input
                className={`${inputClass} num`}
                value={uid}
                onChange={(e) => setUid(e.target.value)}
                placeholder="A1B2C3D4"
              />
            </div>
            <button
              type="submit"
              disabled={salvando || !uid.trim()}
              className="w-full rounded-chip bg-flux px-5 py-2.5 text-sm font-medium text-white
                         transition-all duration-200 hover:bg-flare hover:shadow-flux
                         disabled:cursor-not-allowed disabled:opacity-40"
            >
              {salvando ? 'Cadastrando...' : 'Cadastrar cartão pessoal'}
            </button>
          </form>

          <p className="mt-3 text-xs leading-relaxed text-dim">
            Não sabe o UID? Prepare uma recarga no ponto físico e aproxime o cartão: a tela de espera
            mostra o número lido e oferece o cadastro ali mesmo.
          </p>
        </Secao>

        {/* ---------------- Aparência ---------------- */}
        <Secao
          titulo="Aparência"
          descricao="A escolha fica salva neste navegador e vale para todas as telas."
        >
          <SeletorTema />
        </Secao>

        {/* ---------------- Perfil (leitura) ---------------- */}
        <Secao
          titulo="Perfil"
          descricao="Edição destes campos depende de um endpoint que ainda não existe no backend."
        >
          <Campo label="Nome" valor={usuario.nome} />
          <Campo label="Tipo de usuário" valor={usuario.tipo_usuario || usuario.papel} />
          <Campo label="Bloco / Apto" valor={usuario.bloco_apto} />
          <Campo
            label="Saldo"
            valor={typeof usuario.saldo === 'number' ? `R$ ${usuario.saldo.toFixed(2)}` : '—'}
            mono
          />

          <div className="mt-5 rounded-chip border border-dashed border-line px-4 py-3">
            <p className="text-xs leading-relaxed text-dim">
              Para editar aqui, o backend precisa de um <span className="num">PATCH /usuarios/{'{id}'}</span>.
              Enquanto isso, os dados nascem no cadastro.
            </p>
          </div>
        </Secao>

        {/* ---------------- Veículo ---------------- */}
        <Secao titulo="Veículo principal" descricao="Cadastre mais veículos na aba Meus Veículos.">
          <Campo label="Modelo" valor={veiculo?.modelo} />
          <Campo label="Placa" valor={veiculo?.placa} mono />
          <Campo
            label="Capacidade da bateria"
            valor={veiculo?.capacidade_bateria_kwh ? `${veiculo.capacidade_bateria_kwh} kWh` : null}
            mono
          />
          <Campo
            label="Potência aceita"
            valor={veiculo?.potencia_carro_kw ? potencia(veiculo.potencia_carro_kw) : null}
            mono
          />
        </Secao>

        {/* ---------------- Local ---------------- */}
        <Secao
          titulo="Local ativo"
          descricao="A troca entre condomínios chega quando houver mais de um local cadastrado."
        >
          <Campo label="Condomínio" valor={condominio?.nome} />
          <Campo label="Endereço" valor={condominio?.endereco} />
          <Campo
            label="Limite de potência"
            valor={condominio?.limite_potencia_kw ? potencia(condominio.limite_potencia_kw) : null}
            mono
          />
        </Secao>
      </div>
    </div>
  )
}

export default ConfiguracoesPage
