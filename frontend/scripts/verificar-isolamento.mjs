/**
 * verificar-isolamento.mjs - o app do morador NÃO conhece o painel do gestor.
 * ===========================================================================
 * Roda sozinho depois de `npm run build` (script "postbuild") e também pode
 * ser chamado direto:  node scripts/verificar-isolamento.mjs
 *
 * Falha (código 1, build quebrado) se encontrar, no CÓDIGO-FONTE ou no PACOTE
 * GERADO do app do morador:
 *   - qualquer chamada ou referência às rotas administrativas;
 *   - nome de tela, componente ou arquivo do painel;
 *   - o endereço do painel ou da API administrativa;
 *   - uma chave que não é pública (service_role, sb_secret_, chave privada).
 *
 * É a regra do ADR-023 transformada em teste: separar os aplicativos não pode
 * depender de alguém lembrar.
 */
import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs'
import { join, relative, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), '..')

const PROIBIDO = [
  [/\/gestor\//, 'rota do painel do gestor'],
  [/\/admin\/(login|me|mfa|auditoria)/, 'rota da API administrativa'],
  [/["'`]\/(gestor|admin)["'`/]/, 'rota administrativa'],
  [/GestorPage|PainelPage|SegurancaPage|SimuladorDemanda|GraficoDemanda/, 'tela do painel do gestor'],
  [/somenteGestor|ehGestor|gestor_logado|main_admin/, 'lógica do painel do gestor'],
  [/tipo_usuario\s*===?\s*["']gestor["']/, 'decisão de papel de gestor no navegador'],
  [/VITE_ADMIN|ADMIN_API|chargeops-admin/, 'configuração da API administrativa'],
  [/:8001\b|:5174\b/, 'porta do painel ou da API administrativa'],
  // Segredos pelo FORMATO do valor, não pela palavra: a biblioteca do Supabase
  // cita "sb_secret_" numa mensagem de aviso, e isso não é um vazamento.
  [/sb_secret_[A-Za-z0-9_-]{16,}/, 'chave secreta do Supabase'],
  [/SUPABASE_SERVICE|JWT_PRIVATE_JWK|DEVICE_MASTER_KEY|ADMIN_MFA_KEY|DEVICE_KEY_HEX/, 'nome de segredo do backend'],
  [/"kty"\s*:\s*"EC"[^}]{0,200}"d"\s*:/, 'chave privada (JWK)'],
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----/, 'chave privada'],
]

/** Um JWT do Supabase com papel service_role é a chave-mestra do banco. */
function jwtDeServico(texto) {
  for (const m of texto.matchAll(/eyJ[A-Za-z0-9_-]{8,}\.(eyJ[A-Za-z0-9_-]{8,})\.[A-Za-z0-9_-]{8,}/g)) {
    try {
      const corpo = JSON.parse(Buffer.from(m[1], 'base64url').toString('utf8'))
      if (corpo.role === 'service_role') return m[0].slice(0, 24) + '...'
    } catch { /* não era um JWT */ }
  }
  return null
}
// Endereços do painel informados no ambiente do build (opcional): se algum
// aparecer no pacote do morador, também reprova.
for (const nome of ['ENDERECO_DO_PAINEL', 'ENDERECO_DA_API_ADMIN']) {
  const v = (process.env[nome] || '').trim()
  if (v) PROIBIDO.push([new RegExp(v.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), `endereço em ${nome}`])
}

const EXT = /\.(jsx?|mjs|css|html|json|map|webmanifest)$/
function arquivos(pasta) {
  if (!existsSync(pasta)) return []
  return readdirSync(pasta).flatMap((nome) => {
    const caminho = join(pasta, nome)
    if (statSync(caminho).isDirectory()) return arquivos(caminho)
    return EXT.test(nome) ? [caminho] : []
  })
}

const alvos = [
  ...arquivos(join(RAIZ, 'src')),
  ...arquivos(join(RAIZ, 'public')),
  ...arquivos(join(RAIZ, 'dist')),
  join(RAIZ, 'index.html'),
]

const achados = []
for (const arquivo of alvos) {
  const texto = readFileSync(arquivo, 'utf8')
  for (const [padrao, oQue] of PROIBIDO) {
    const m = texto.match(padrao)
    if (m) achados.push(`${relative(RAIZ, arquivo)}: ${oQue}  ->  "${m[0].slice(0, 40)}"`)
  }
  const servico = jwtDeServico(texto)
  if (servico) achados.push(`${relative(RAIZ, arquivo)}: chave service_role do Supabase  ->  "${servico}"`)
}

// Arquivos do painel que não podem voltar para dentro do app do morador.
for (const sobra of ['src/pages/GestorPage.jsx', 'src/components/GraficoDemanda.jsx',
  'src/components/SimuladorDemanda.jsx']) {
  if (existsSync(join(RAIZ, sobra))) {
    achados.push(`${sobra}: arquivo do painel dentro do app do morador (apague; ele vive em admin/)`)
  }
}

const temDist = existsSync(join(RAIZ, 'dist'))
if (achados.length) {
  console.error('\n[isolamento] REPROVADO: o app do morador contém referência ao painel do gestor ou a segredo:\n')
  for (const a of achados) console.error('  - ' + a)
  console.error('\nO painel do gestor é outro aplicativo (admin/). Ver docs/decisoes/ADR-023.\n')
  process.exit(1)
}
console.log(`[isolamento] ok: ${alvos.length} arquivos conferidos` +
  `${temDist ? ' (código-fonte e pacote gerado)' : ' (só código-fonte; rode depois do build para conferir o pacote)'}` +
  ', nenhuma referência ao painel do gestor nem a segredo.')
