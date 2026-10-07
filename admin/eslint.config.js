import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      // O app busca dados ao montar a tela (`useEffect(() => { carregar() })`)
      // e reage ao Realtime com a mesma função. A regra nova do React Compiler
      // marca esse padrão em toda tela; reescrever 10 telas para um cache de
      // dados não cabe antes do Next. Desligada de propósito, não esquecida.
      'react-hooks/set-state-in-effect': 'off',
      // Hooks pequenos moram ao lado do componente que os usa (useCondominios).
      'react-refresh/only-export-components': 'warn',
    },
  },
  {
    // Arquivos que rodam no Node (build e verificação), não no navegador.
    files: ['vite.config.js', 'scripts/**/*.{js,mjs}'],
    languageOptions: { globals: globals.node },
  },
])
