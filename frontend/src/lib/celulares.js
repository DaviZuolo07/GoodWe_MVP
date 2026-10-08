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

// Por marca: [modelo, mAh, potência de carga em W]. Mais novos primeiro.
// iPhone: versão com bandeja de chip (a vendida no Brasil); a só-eSIM dos EUA
// tem bateria um pouco maior. Capacidades da Apple vêm das páginas europeias
// (regra da UE obriga a publicar mAh); a potência é o carregador indicado.
const POR_MARCA = {
  Apple: [
    ['iPhone 18 Pro Max', 5391, 40],   // set/2026; potência ainda não divulgada: a da linha 17 Pro
    ['iPhone 18 Pro', 4056, 40],
    ['iPhone 17 Pro Max', 4823, 40],
    ['iPhone 17 Pro', 3988, 40],
    ['iPhone 17', 3692, 40],
    ['iPhone Air', 3149, 20],
    ['iPhone 17e / 16e', 4005, 20],
    ['iPhone 16 Pro Max', 4685, 30],
    ['iPhone 16 Pro', 3582, 30],
    ['iPhone 16 Plus', 4674, 30],
    ['iPhone 16', 3561, 30],
    ['iPhone 15 Pro Max', 4441, 27],
    ['iPhone 15 Pro', 3274, 27],
    ['iPhone 15 Plus', 4383, 27],
    ['iPhone 15', 3349, 27],
    ['iPhone 14 Pro Max', 4323, 27],
    ['iPhone 14 Pro', 3200, 27],
    ['iPhone 14 Plus', 4325, 20],
    ['iPhone 14', 3279, 20],
    ['iPhone 13 Pro Max', 4352, 27],
    ['iPhone 13 Pro', 3095, 20],
    ['iPhone 13', 3240, 20],
    ['iPhone 13 mini', 2406, 20],
    ['iPhone SE (2022)', 2018, 20],
    ['iPhone 12 Pro Max', 3687, 20],
    ['iPhone 12 / 12 Pro', 2815, 20],
    ['iPhone 12 mini', 2227, 20],
    ['iPhone SE (2020)', 1821, 18],
    ['iPhone 11 Pro Max', 3969, 18],
    ['iPhone 11 Pro', 3046, 18],
    ['iPhone 11', 3110, 18],
    ['iPhone XS Max', 3174, 18],
    ['iPhone XS', 2658, 18],
    ['iPhone XR', 2942, 18],
    ['iPhone X', 2716, 15],
  ],
  // Os Galaxy mais vendidos de 2023 a 2026: a linha A puxa o volume no Brasil
  // (A15 liderou 2025), a S e as dobráveis completam.
  Samsung: [
    ['Galaxy S26 Ultra', 5000, 60],
    ['Galaxy S26+', 4900, 45],
    ['Galaxy S26', 4300, 25],
    ['Galaxy S25 Ultra', 5000, 45],
    ['Galaxy S25+', 4900, 45],
    ['Galaxy S25', 4000, 25],
    ['Galaxy S25 FE', 4900, 45],
    ['Galaxy S24 Ultra', 5000, 45],
    ['Galaxy S24+', 4900, 45],
    ['Galaxy S24', 4000, 25],
    ['Galaxy S24 FE', 4700, 25],
    ['Galaxy S23 Ultra', 5000, 45],
    ['Galaxy S23', 3900, 25],
    ['Galaxy S23 FE', 4500, 25],
    ['Galaxy S22', 3700, 25],
    ['Galaxy Z Fold7', 4400, 25],
    ['Galaxy Z Flip7', 4300, 25],
    ['Galaxy Z Flip6', 4000, 25],
    ['Galaxy A56', 5000, 45],
    ['Galaxy A55', 5000, 25],
    ['Galaxy A54', 5000, 25],
    ['Galaxy A36', 5000, 45],
    ['Galaxy A35', 5000, 25],
    ['Galaxy A34', 5000, 25],
    ['Galaxy A26', 5000, 25],
    ['Galaxy A25', 5000, 25],
    ['Galaxy A17', 5000, 25],
    ['Galaxy A16', 5000, 25],
    ['Galaxy A15', 5000, 25],
    ['Galaxy A06', 5000, 25],
    ['Galaxy A05s', 5000, 25],
    ['Galaxy M55', 5000, 45],
    ['Galaxy M35', 6000, 25],
    ['Galaxy M15', 6000, 25],
    ['Galaxy M54', 6000, 25],
  ],
  'Xiaomi / Redmi / POCO': [
    ['Xiaomi 14', 4610, 90],
    ['Xiaomi 13', 4500, 67],
    ['Redmi Note 13 Pro', 5100, 67],
    ['Redmi Note 13', 5000, 33],
    ['Redmi Note 12', 5000, 33],
    ['POCO X6 Pro', 5000, 67],
    ['Xiaomi Redmi 13C', 5000, 18],
  ],
  Motorola: [
    ['Motorola Edge 50', 5000, 68],
    ['Motorola Moto G84', 5000, 33],
    ['Motorola Moto G54', 5000, 33],
    ['Motorola Moto G34', 5000, 18],
    ['Motorola Moto E13', 5000, 10],
  ],
  Google: [
    ['Google Pixel 8 Pro', 5050, 30],
    ['Google Pixel 8', 4575, 27],
    ['Google Pixel 7', 4355, 20],
  ],
  'Outras marcas': [
    ['Realme 12 Pro', 5000, 67],
    ['Asus Zenfone 10', 4300, 30],
    ['Nokia G22', 5050, 20],
    ['Infinix Hot 40', 5000, 18],
  ],
}

/** Lista pronta para o <select>: cada item com a marca e a capacidade já em kWh. */
export const CELULARES = Object.entries(POR_MARCA).flatMap(([marca, modelos]) =>
  modelos.map(([modelo, mah, potenciaW]) => ({
    marca,
    modelo,
    mah,
    capacidade_kwh: mahParaKwh(mah),
    potencia_kw: Math.round((potenciaW / 1000) * 1e3) / 1e3,
  })))

/** Marcas na ordem da lista (para os <optgroup> do select). */
export const MARCAS = Object.keys(POR_MARCA)

export const CELULAR_OUTRO = 'Outro'

/** Busca um modelo pelo nome exato (o value do select). */
export function acharCelular(modelo) {
  return CELULARES.find((c) => c.modelo === modelo) || null
}

/** mAh padrão quando a pessoa escolhe "Outro" e ainda não digitou nada. */
export const MAH_PADRAO = 4000
