import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    coverage: {
      // Ratcheted, not aspirational. The JS package had no coverage tooling at all until #533, while
      // the Python package is held to 100% across five interpreters. Raise these as they improve;
      // never lower them.
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
