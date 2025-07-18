import { defineConfig } from 'vite'
import dts from 'vite-plugin-dts'
import { builtinModules } from 'module'

export default defineConfig({
  build: {
    lib: {
      entry: './src/index.ts',
      name: 'genai-prices',
      formats: ['es', 'cjs'],
      fileName: (format) => `index.${format === 'es' ? 'js' : 'cjs'}`,
    },
    rollupOptions: {
      external: [...builtinModules, ...builtinModules.map((m) => `node:${m}`)],
    },
  },
  plugins: [dts()],
})
