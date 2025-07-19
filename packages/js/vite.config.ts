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
      external: [...builtinModules, ...builtinModules.map((m) => `node:${m}`)],
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
    },
    lib: false,
    outDir: 'dist',
    emptyOutDir: true,
    target: 'node20',
    minify: false,
  },
  plugins: [dts()],
})
