import { defineConfig } from 'vite'
import dts from 'vite-plugin-dts'
import { builtinModules } from 'module'

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        index: './src/index.ts',
        cli: './src/cli.ts',
        browser: './src/index.browser.ts', // browser-only entry
      },
      external: (id) => {
        // For browser entry, don't externalize Node.js modules since they don't exist in browser
        if (id === './src/index.browser.ts' || id.includes('browser')) {
          return false
        }
        // For Node.js entries, externalize Node.js built-ins
        return [...builtinModules, ...builtinModules.map((m) => `node:${m}`)].includes(id)
      },
      output: {
        entryFileNames: (chunkInfo) => {
          if (chunkInfo.name === 'cli') {
            return 'cli.js'
          }
          if (chunkInfo.name === 'browser') {
            return 'browser.js'
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
    target: 'esnext', // browser bundle should target modern browsers
    minify: false,
  },
  plugins: [dts()],
  json: {
    stringify: true,
  },
})
