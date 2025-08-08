import { readFileSync } from 'node:fs'
import { chmod, writeFile } from 'node:fs/promises'
import { builtinModules } from 'node:module'
import { defineConfig } from 'vite'

export default defineConfig({
  build: {
    emptyOutDir: false,

    lib: {
      entry: ['./src/cli.ts'],
      fileName: 'cli',
      formats: ['es'],
    },
    minify: true,
    outDir: 'dist',
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
    target: 'esnext',
  },
  plugins: [
    {
      name: 'make-executable',
      async writeBundle() {
        const outputPath = 'dist/cli.js'
        const content = readFileSync(outputPath, 'utf-8')
        await writeFile(outputPath, `#!/usr/bin/env node\n${content}`)

        await chmod(outputPath, 0o755)
      },
    },
  ],
})
