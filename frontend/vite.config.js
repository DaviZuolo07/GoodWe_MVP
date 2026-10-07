import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { csp } from './scripts/csp.js'

// App do MORADOR. O painel do gestor é outro projeto (../admin), com build e
// endereço próprios - nada dele entra aqui (ver scripts/verificar-isolamento.mjs).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  return {
  plugins: [
    react(),
    tailwindcss(),
    // A página só pode conversar com a API do morador e com o Supabase.
    csp({ conectar: [env.VITE_API_URL, env.VITE_SUPABASE_URL] }),
  ],
  server: { port: 5173, strictPort: true },
  preview: { port: 5173, strictPort: true },
  build: {
    // Sem mapas de código-fonte em produção: o que vai para o navegador é só
    // o pacote minificado.
    sourcemap: false,
    rolldownOptions: {
      output: {
        // Bibliotecas num arquivo à parte: mudam pouco, ficam no cache do
        // celular entre uma publicação e outra.
        advancedChunks: {
          groups: [
            { name: 'react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ },
            { name: 'supabase', test: /node_modules[\\/]@supabase[\\/]/ },
          ],
        },
      },
    },
  },
  }
})
