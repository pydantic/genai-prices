import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    coverage: {
      // Ratchet: raise as coverage improves; never lower.
      exclude: ['src/examples/**', 'src/__tests__/**', 'src/data.ts', 'src/dataUnits.ts', '**/*.d.ts'],
      include: ['src/**/*.ts'],
      provider: 'v8',
      reporter: ['text-summary', 'html'],
      thresholds: {
        branches: 90,
        functions: 95,
        lines: 82,
        statements: 82,
      },
    },
  },
})
