/**
 * Plugin do Vite: escreve a Content-Security-Policy dentro do index.html
 * GERADO PELO BUILD, com os endereços reais das variáveis de ambiente.
 *
 * Por que no HTML e não só no cabeçalho da hospedagem: a lista de endereços
 * com que a página pode falar (connect-src) depende de VITE_API_URL e
 * VITE_SUPABASE_URL, que só existem na hora do build. Assim a política vai
 * junto com o app para qualquer hospedagem, sem editar arquivo na mão.
 *
 * O que ela garante no navegador de quem usa:
 *   - só roda JavaScript servido pelo próprio app (nada inline, nada de CDN);
 *   - a página só conversa com a API e o Supabase configurados;
 *   - não carrega plugin, não muda o <base>, não envia formulário para fora.
 *
 * `frame-ancestors` (impedir que embutam o app num iframe) não funciona em
 * <meta>: vai como cabeçalho, em vercel.json e public/_headers.
 */
export function csp({ conectar = [], imagens = [] } = {}) {
  return {
    name: 'chargeops-csp',
    apply: 'build',
    transformIndexHtml(html) {
      const origens = new Set()
      for (const bruto of conectar.filter(Boolean)) {
        try {
          const u = new URL(bruto)
          origens.add(u.origin)
          // Realtime do Supabase: mesma origem, via WebSocket.
          if (u.protocol === 'https:') origens.add(`wss://${u.host}`)
          if (u.protocol === 'http:') origens.add(`ws://${u.host}`)
        } catch {
          throw new Error(`[csp] endereço inválido nas variáveis de ambiente: "${bruto}"`)
        }
      }
      const politica = [
        "default-src 'self'",
        "script-src 'self'",
        // React escreve estilos em atributo (style="width: 40%"): precisa do inline SÓ para estilo.
        "style-src 'self' 'unsafe-inline'",
        `img-src 'self' data: blob: ${imagens.join(' ')}`.trim(),
        "font-src 'self'",
        `connect-src 'self' ${[...origens].join(' ')}`.trim(),
        "manifest-src 'self'",
        "worker-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
      ].join('; ')
      return html.replace(
        '<meta charset="UTF-8" />',
        `<meta charset="UTF-8" />\n    <meta http-equiv="Content-Security-Policy" content="${politica}" />`,
      )
    },
  }
}
