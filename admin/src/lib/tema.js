import { useCallback, useEffect, useState } from 'react'

/**
 * Tema da interface.
 *
 * O tema vive num atributo do <html> (`data-tema`), e todo o resto decorre
 * disso: os tokens de cor em index.css são reescritos por seletor CSS, sem
 * nenhum componente precisar saber que existe mais de um tema.
 *
 * A preferência fica em localStorage. Na primeira visita, seguimos o que o
 * sistema operacional do usuário já pede — quem usa o computador no claro
 * provavelmente quer o app no claro também.
 */

const CHAVE = 'goodwe:tema'
export const TEMAS = ['escuro', 'claro']

function temaDoSistema() {
  if (typeof window === 'undefined' || !window.matchMedia) return 'escuro'
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'claro' : 'escuro'
}

export function lerTema() {
  try {
    const salvo = localStorage.getItem(CHAVE)
    if (TEMAS.includes(salvo)) return salvo
  } catch {
    // localStorage bloqueado (aba privada, política do navegador):
    // o tema simplesmente não persiste, o app continua funcionando.
  }
  return temaDoSistema()
}

export function aplicarTema(tema) {
  const valido = TEMAS.includes(tema) ? tema : 'escuro'
  document.documentElement.dataset.tema = valido

  try {
    localStorage.setItem(CHAVE, valido)
  } catch {
    /* sem persistência, sem drama */
  }

  return valido
}

/** Hook para quem precisa ler e trocar o tema. */
export function useTema() {
  const [tema, setTemaEstado] = useState(() => lerTema())

  useEffect(() => {
    aplicarTema(tema)
  }, [tema])

  const trocarTema = useCallback((novo) => {
    setTemaEstado(TEMAS.includes(novo) ? novo : 'escuro')
  }, [])

  return { tema, trocarTema }
}
