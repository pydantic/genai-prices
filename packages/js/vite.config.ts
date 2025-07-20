import { defineConfig } from 'vite'
import dts from 'vite-plugin-dts'
import { builtinModules } from 'module'

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        index: './src/index.ts',
        cli: './src/cli.ts',
      },
      external: (id) => {
        // Externalize Node.js built-ins
        return [...builtinModules, ...builtinModules.map((m) => `node:${m}`)].includes(id)
      },
      output: {
        entryFileNames: (chunkInfo) => {
          if (chunkInfo.name === 'cli') {
            return 'cli.js'
          }
          return 'index.js'
        },
        chunkFileNames: '[name].js',
        format: 'esm',
      },
      preserveEntrySignatures: 'strict',
    },
    lib: false,
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
