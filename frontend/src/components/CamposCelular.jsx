import { CELULARES, CELULAR_OUTRO, MARCAS, acharCelular, mahParaKwh } from '../lib/celulares.js'
import { energia } from '../lib/formato.js'

/**
 * Campos de cadastro de um celular (bancada do Totem).
 *
 * Em vez de pedir o mAh — que ninguém sabe de cor — a pessoa escolhe o modelo
 * e a energia vem da base local (lib/celulares.js). "Outro" abre os campos
 * manuais. O celular não tem placa, então ela não aparece aqui.
 *
 * É o mesmo bloco no cadastro (Login) e em Meus Veículos: um só componente
 * para as duas telas não divergirem.
 */
function CamposCelular({ inputClass, labelClass, modelo, onModelo, nome, onNome, mah, onMah, ehBancada }) {
  const outro = modelo === CELULAR_OUTRO
  const escolhido = outro ? null : acharCelular(modelo)
  const capacidade = escolhido ? escolhido.capacidade_kwh : mahParaKwh(mah)

  return (
    <div className="space-y-3">
      <div>
        <label className={labelClass}>Modelo do celular</label>
        <select className={inputClass} value={modelo} onChange={(e) => onModelo(e.target.value)}>
          {MARCAS.map((marca) => (
            <optgroup key={marca} label={marca}>
              {CELULARES.filter((c) => c.marca === marca).map((c) => (
                <option key={c.modelo} value={c.modelo}>{c.modelo}</option>
              ))}
            </optgroup>
          ))}
          <option value={CELULAR_OUTRO}>Outro (informar manualmente)</option>
        </select>
      </div>

      {outro ? (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelClass}>Qual celular?</label>
            <input className={inputClass} value={nome} onChange={(e) => onNome(e.target.value)}
                   placeholder="Marca e modelo" maxLength={60} />
          </div>
          <div>
            <label className={labelClass}>Bateria (mAh)</label>
            <input className={inputClass} type="number" min="100" max="50000" step="50"
                   value={mah} onChange={(e) => onMah(e.target.value)} placeholder="4000" />
          </div>
        </div>
      ) : null}

      <p className="text-xs text-dim">
        {ehBancada ? 'Totem Next: recarga de celular. ' : ''}
        Energia da bateria: <span className="num text-mute">{energia(capacidade, 3)}</span>
        {escolhido ? ` (${escolhido.mah} mAh, da ficha do fabricante)` : ' (calculada do mAh informado)'}.
        É com ela que o app estima a % e o tempo da recarga.
      </p>
    </div>
  )
}

export default CamposCelular
