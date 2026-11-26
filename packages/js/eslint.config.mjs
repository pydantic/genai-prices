import pluginJs from '@eslint/js'
import eslintConfigPrettier from 'eslint-config-prettier/flat'
import perfectionist from 'eslint-plugin-perfectionist'
import eslintPluginPrettierRecommended from 'eslint-plugin-prettier/recommended'
import turboPlugin from 'eslint-plugin-turbo'
import { defineConfig } from 'eslint/config'
import globals from 'globals'
import neostandard from 'neostandard'
import tseslint from 'typescript-eslint'

export default defineConfig(
  pluginJs.configs.recommended,
  tseslint.configs.strictTypeChecked,
  tseslint.configs.stylisticTypeChecked,
  perfectionist.configs['recommended-natural'],
  neostandard({ noJsx: true, noStyle: true }),
  eslintPluginPrettierRecommended,
  eslintConfigPrettier,
  { files: ['src/*.{js,mjs,cjs,ts}', 'eslint.config.mjs', 'vite.config.ts'] },
  {
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
  },
  {
    plugins: {
      turbo: turboPlugin,
    },
    rules: {
      'perfectionist/sort-modules': 'off',
      'turbo/no-undeclared-env-vars': 'off',
    },
  },
  {
    // Tests pass tiered prices as plain objects, the shape callers and the JSON data use.
    // The engine validates them and rebuilds them as TieredPrices instances.
    files: ['src/__tests__/**'],
    rules: {
      '@typescript-eslint/no-unsafe-class-instance-assignment': 'off',
    },
  },
  { ignores: ['coverage', 'dist', 'src/data.ts'] },
  {
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  }
)
