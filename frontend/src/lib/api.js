/**
 * Cliente HTTP do backend.
 *
 * Duas coisas moram aqui, e só aqui:
 *   1. O token de sessão vai no header Authorization de TODA chamada. Nenhum
 *      componente manda mais `usuario_id` no corpo - a identidade é do token
 *      (Bloco 2). Enviar um id pelo corpo era o que permitia agir como outro.
 *   2. Token expirado ou inválido (401) derruba a sessão na hora, em vez de
 *      deixar a tela vazia parecendo erro de dados.
 */

import { API_URL } from '../config.js'
import { obterToken } from '../supabaseClient.js'

let aoExpirar = () => {}

export function definirAoExpirar(fn) {
  aoExpirar = fn || (() => {})
}

export class ErroApi extends Error {
  constructor(mensagem, status, dados) {
    super(mensagem)
    this.status = status
    this.dados = dados
  }
}

export async function api(caminho, { method = 'GET', body, sinal } = {}) {
  const token = obterToken()
  let resposta
  try {
    resposta = await fetch(`${API_URL}${caminho}`, {
      method,
      signal: sinal,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ErroApi('Não foi possível falar com o servidor. O backend está rodando?', 0)
  }

  if (resposta.status === 401) {
    aoExpirar()
    throw new ErroApi('Sua sessão expirou. Entre novamente.', 401)
  }

  const texto = await resposta.text()
  const dados = texto ? JSON.parse(texto) : null

  if (!resposta.ok) {
    throw new ErroApi(dados?.detail || 'Não foi possível concluir a operação.', resposta.status, dados)
  }
  return dados
}

export const get = (caminho, opcoes) => api(caminho, opcoes)
export const post = (caminho, body) => api(caminho, { method: 'POST', body })
export const patch = (caminho, body) => api(caminho, { method: 'PATCH', body })
export const del = (caminho) => api(caminho, { method: 'DELETE' })
