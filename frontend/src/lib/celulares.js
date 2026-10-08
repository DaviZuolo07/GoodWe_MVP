/**
 * Base local de celulares: modelo -> capacidade da bateria e potência de carga.
 * ============================================================================
 * ADR-022 / mudança do estande: na bancada o "veículo" é um celular, e ninguém
 * decora o mAh do próprio aparelho. Em vez de pedir o número, a pessoa escolhe
 * o modelo e o app preenche a energia.
 *
 * Por que uma base EMBARCADA e não uma API externa (webhook): o estande pode
 * ficar sem internet na hora da banca, e uma chamada que falha deixaria o
 * cadastro travado. Esta lista vai junto com o app, funciona offline e não
 * depende de chave de ninguém. Para "Outro", a pessoa informa o mAh.
 *
 * Conversão: Wh = mAh × tensão_nominal / 1000; kWh = Wh / 1000.
 * A tensão nominal de uma célula Li-ion de celular é ~3,85 V.
 * Potência de carga = o pico anunciado pelo fabricante (o nosso carregador de
 * bancada ainda limita abaixo disso; quem for menor manda na conta).
 *
 * Fonte dos números: fichas técnicas públicas dos fabricantes (GSMArena).
 * Todos ficam bem abaixo do teto de 0,2 kWh / 0,2 kW que o backend exige para
 * o tipo "celular".
 */

export const TENSAO_NOMINAL_V = 3.85

/** mAh -> kWh (capacidade de energia). */
export function mahParaKwh(mah, tensaoV = TENSAO_NOMINAL_V) {
  return Math.round((Number(mah) * tensaoV) / 1e6 * 1e5) / 1e5
}

// [modelo, mAh, potência de carga em W]
const BRUTO = [
  // Apple
  ['iPhone 15 Pro Max', 4441, 27],
  ['iPhone 15 Pro', 3274, 27],
  ['iPhone 15 / 15 Plus', 3349, 27],
  ['iPhone 14 Pro Max', 4323, 27],
  ['iPhone 14 / 13', 3240, 27],
  ['iPhone 13 Pro Max', 4352, 27],
  ['iPhone 12 / 12 Pro', 2815, 20],
  ['iPhone 11', 3110, 18],
  ['iPhone SE (2022)', 2018, 20],
  // Samsung
  ['Samsung Galaxy S24 Ultra', 5000, 45],
  ['Samsung Galaxy S24', 4000, 25],
  ['Samsung Galaxy S23 Ultra', 5000, 45],
  ['Samsung Galaxy S23', 3900, 25],
  ['Samsung Galaxy S22', 3700, 25],
  ['Samsung Galaxy A55 / A54', 5000, 25],
  ['Samsung Galaxy A35 / A34', 5000, 25],
  ['Samsung Galaxy A15', 5000, 25],
  ['Samsung Galaxy M54', 6000, 25],
  // Xiaomi / Redmi / POCO
  ['Xiaomi 14', 4610, 90],
  ['Xiaomi 13', 4500, 67],
  ['Redmi Note 13 Pro', 5100, 67],
  ['Redmi Note 13', 5000, 33],
  ['Redmi Note 12', 5000, 33],
  ['POCO X6 Pro', 5000, 67],
  ['Xiaomi Redmi 13C', 5000, 18],
  // Motorola
  ['Motorola Edge 50', 5000, 68],
  ['Motorola Moto G84', 5000, 33],
  ['Motorola Moto G54', 5000, 33],
  ['Motorola Moto G34', 5000, 18],
  ['Motorola Moto E13', 5000, 10],
  // Google
  ['Google Pixel 8 Pro', 5050, 30],
  ['Google Pixel 8', 4575, 27],
  ['Google Pixel 7', 4355, 20],
  // Outras marcas comuns no BR
  ['Realme 12 Pro', 5000, 67],
  ['Asus Zenfone 10', 4300, 30],
  ['Nokia G22', 5050, 20],
  ['Infinix Hot 40', 5000, 18],
]

/** Lista pronta para o <select>: cada item com capacidade já em kWh. */
export const CELULARES = BRUTO.map(([modelo, mah, potenciaW]) => ({
  modelo,
  mah,
  capacidade_kwh: mahParaKwh(mah),
  potencia_kw: Math.round((potenciaW / 1000) * 1e3) / 1e3,
}))

export const CELULAR_OUTRO = 'Outro'

/** Busca um modelo pelo nome exato (o value do select). */
export function acharCelular(modelo) {
  return CELULARES.find((c) => c.modelo === modelo) || null
}

/** mAh padrão quando a pessoa escolhe "Outro" e ainda não digitou nada. */
export const MAH_PADRAO = 4000
