/**
 * Cliente HTTP do painel do gestor. Fala SÓ com a API administrativa.
 *
 * O token administrativo vive nesta variável e em nenhum outro lugar: não vai
 * para localStorage, sessionStorage nem cookie. Fechou ou recarregou a aba,
 * acabou a sessão - num painel de administração isso é o comportamento certo.
 */

import { API_URL } from '../config.js'

let token = null
let aoExpirar = () => {}

export function definirToken(novo) { token = novo || null }
export function temToken() { return Boolean(token) }
export function definirAoExpirar(fn) { aoExpirar = fn || (() => {}) }

export class ErroApi extends Error {
  constructor(mensagem, status, dados) {
    super(mensagem)
    this.status = status
    this.dados = dados
  }
}

export async function api(caminho, { method = 'GET', body, anonimo = false } = {}) {
  let resposta
  try {
    resposta = await fetch(`${API_URL}${caminho}`, {
      method,
      // Sem cookies e sem cache: nada do painel fica guardado pelo navegador.
      credentials: 'omit',
      cache: 'no-store',
      referrerPolicy: 'no-referrer',
      headers: {
        'Content-Type': 'application/json',
        ...(token && !anonimo ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ErroApi('Não foi possível falar com o servidor do painel.', 0)
  }

  const texto = await resposta.text()
  let dados = null
  try { dados = texto ? JSON.parse(texto) : null } catch { /* resposta não-JSON */ }

  if (resposta.status === 401 && !anonimo) {
    aoExpirar()
    throw new ErroApi('Sua sessão expirou. Entre novamente.', 401)
  }
  if (!resposta.ok) {
    throw new ErroApi(dados?.detail && typeof dados.detail === 'string'
      ? dados.detail : 'Não foi possível concluir a operação.', resposta.status, dados)
  }
  return dados
}

export const get = (caminho) => api(caminho)
export const post = (caminho, body) => api(caminho, { method: 'POST', body })
export const patch = (caminho, body) => api(caminho, { method: 'PATCH', body })
export const del = (caminho) => api(caminho, { method: 'DELETE' })
