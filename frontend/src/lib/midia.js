/**
 * Camada de mídia — de onde vem a imagem de um carregador e de um carro.
 *
 * CARREGADOR: arquivo local. São dois ou três modelos no produto inteiro,
 * não compensa rede. Uma foto padrão atende todos, com override por modelo.
 *
 * CARRO: imagem cinza única, também local. Ver a seção CARROS abaixo para o
 * motivo de não usarmos um CDN de render por modelo.
 */

/* ===========================================================================
   CARREGADORES — arquivos em /public/carregadores/
   =========================================================================== */

/** Vale para qualquer carregador que não tenha foto própria. */
export const CARREGADOR_PADRAO = '/carregadores/CG.webp'

/** Override por modelo. A chave é o slug do campo `modelo` do banco. */
export const FOTOS_CARREGADOR = {
  // 'goodwe-ac-22kw': '/carregadores/CG-22kw.webp',
}

export function fotoCarregador(modelo) {
  return FOTOS_CARREGADOR[slugModelo(modelo)] || CARREGADOR_PADRAO
}

/* ===========================================================================
   CARROS
   ---------------------------------------------------------------------------
   Uma imagem cinza única para todo veículo em recarga.

   A alternativa era buscar o render de cada modelo num CDN. Testamos: a chave
   pública de demonstração carimba marca d'água na imagem, e manter um catálogo
   modelo a modelo não escala. Uma silhueta neutra comunica a mesma coisa - "há
   um carro conectado aqui" - sem depender de rede nem de licença de imagem.

   Salve o arquivo em: frontend/public/veiculos/padrao.webp
   Se ele não existir, o componente desenha a silhueta vetorial.
   =========================================================================== */

export const CARRO_PADRAO = '/veiculos/padrao.webp'

/* ===========================================================================
   Utilitários
   =========================================================================== */

/** "BMW X6" -> "bmw-x6" | "GWM Ora 03" -> "gwm-ora-03" */
export function slugModelo(texto) {
  if (!texto) return ''
  return texto
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/** Só decide qual silhueta desenhar quando não existe imagem. */
const PALAVRAS_SUV = ['suv', 'x1', 'x3', 'x5', 'x6', 'x7', 'tucson', 'compass', 'creta', 'kicks', 'song', 'yuan', 'atto', 'haval', 'ex30', 'q3', 'q5', 'tiguan', 'cross', 'territory', 'model y']

export function porteVeiculo(modelo) {
  const nome = (modelo || '').toLowerCase()
  return PALAVRAS_SUV.some((p) => nome.includes(p)) ? 'suv' : 'hatch'
}
