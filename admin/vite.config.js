import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { csp } from './scripts/csp.js'

// PAINEL DO GESTOR. Projeto separado do app do morador (../frontend): outro
// build, outra porta, outro endereço quando publicado, outra API.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  return {
  // A página só pode conversar com a API administrativa. Nada de Supabase,
  // nada da API do morador.
  plugins: [react(), tailwindcss(), csp({ conectar: [env.VITE_ADMIN_API_URL] })],
  // 127.0.0.1 de propósito: em desenvolvimento o painel não fica exposto na
  // rede local (o app do morador usa --host para o celular; este não).
  server: { port: 5174, strictPort: true, host: '127.0.0.1' },
  preview: { port: 5174, strictPort: true, host: '127.0.0.1' },
  build: { sourcemap: false },
  }
})
