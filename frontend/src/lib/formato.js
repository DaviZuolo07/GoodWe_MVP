/**
 * Formatação em padrão brasileiro, com UNIDADE ADAPTATIVA.
 *
 * Por que adaptativa: o ponto do ESP32 é uma bancada USB de 25 W carregando
 * um celular de 15 Wh. Mostrar "0,01 kWh" e "0,01 kW" transformaria a
 * demonstração de energia real numa tela de zeros. Abaixo de 1, kWh vira Wh
 * e kW vira W - o número volta a ter informação.
 */

export function brl(valor) {
  if (valor == null || Number.isNaN(Number(valor))) return '—'
  return Number(valor).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

export function num(valor, casas = 2) {
  if (valor == null || Number.isNaN(Number(valor))) return '—'
  return Number(valor).toLocaleString('pt-BR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: casas,
  })
}

export function energia(kwh, casas = 2) {
  if (kwh == null) return '—'
  const v = Number(kwh)
  return Math.abs(v) < 1 ? `${num(v * 1000, 1)} Wh` : `${num(v, casas)} kWh`
}

export function potencia(kw, casas = 2) {
  if (kw == null) return '—'
  const v = Number(kw)
  return Math.abs(v) < 1 ? `${num(v * 1000, 1)} W` : `${num(v, casas)} kW`
}

/** 72 -> "1h 12m" | 58 -> "58 min" */
export function duracao(min) {
  if (min == null) return '—'
  const m = Math.max(0, Math.round(min))
  if (m < 60) return `${m} min`
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`
}

export function horaCurta(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
}

export function dataHora(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}
