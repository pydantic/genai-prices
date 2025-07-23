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
        // Externalize Node.js built-ins and node-fetch
        const nodeModules = [...builtinModules, ...builtinModules.map((m) => `node:${m}`)]
        const externalModules = ['node-fetch', 'yargs']
        return nodeModules.includes(id) || externalModules.includes(id)
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
