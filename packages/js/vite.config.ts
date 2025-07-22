import { defineConfig } from 'vite'
import dts from 'vite-plugin-dts'
import { builtinModules } from 'module'

export default defineConfig({
  build: {
    lib: {
      entry: './src/index.ts',
      name: 'GenaiPrices',
      fileName: 'index',
    },
    rollupOptions: {
      external: (id) => {
        // Externalize Node.js built-ins
        return [...builtinModules, ...builtinModules.map((m) => `node:${m}`)].includes(id)
      },
      output: {
        format: 'esm',
      },
      preserveEntrySignatures: 'strict',
    },
    outDir: 'dist',
    emptyOutDir: true,
    target: 'esnext',
    minify: false,
  },
  plugins: [dts()],
  json: {
    stringify: true,
  },
})
