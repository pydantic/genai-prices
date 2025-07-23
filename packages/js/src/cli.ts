import yargs from 'yargs'
import { hideBin } from 'yargs/helpers'
import { calcPriceSync, calcPriceAsync, enableAutoUpdate } from './index.js'
import type { Provider } from './types.js'

interface Argv {
  _: (string | number)[]
  $0: string
  'auto-update'?: boolean
  autoUpdate?: boolean
  provider?: string
  model?: string | string[]
  'input-tokens'?: number
  'cache-write-tokens'?: number
  'cache-read-tokens'?: number
  'output-tokens'?: number
  'input-audio-tokens'?: number
  'cache-audio-read-tokens'?: number
  'output-audio-tokens'?: number
  requests?: number
  timestamp?: string
}

const argv = yargs(hideBin(process.argv))
  .scriptName('genai-prices')
  .command('list [provider]', 'List providers and models', (y) =>
    y.positional('provider', { type: 'string', describe: 'Provider ID to filter' }),
  )
  .command('calc <model...>', 'Calculate price', (y) =>
    y
      .positional('model', { type: 'string', describe: 'Model(s) (optionally provider:model)', array: true })
      .option('input-tokens', { type: 'number' })
      .option('cache-write-tokens', { type: 'number' })
      .option('cache-read-tokens', { type: 'number' })
      .option('output-tokens', { type: 'number' })
      .option('input-audio-tokens', { type: 'number' })
      .option('cache-audio-read-tokens', { type: 'number' })
      .option('output-audio-tokens', { type: 'number' })
      .option('requests', { type: 'number' })
      .option('provider', { type: 'string' })
      .option('auto-update', { type: 'boolean', default: false })
      .option('timestamp', { type: 'string', describe: 'RFC3339 timestamp' }),
  )
  .option('auto-update', { type: 'boolean', describe: 'Enable auto-update from GitHub' })
  .option('input-tokens', { type: 'number' })
  .option('cache-write-tokens', { type: 'number' })
  .option('cache-read-tokens', { type: 'number' })
  .option('output-tokens', { type: 'number' })
  .option('input-audio-tokens', { type: 'number' })
  .option('cache-audio-read-tokens', { type: 'number' })
  .option('output-audio-tokens', { type: 'number' })
  .option('requests', { type: 'number' })
  .option('provider', { type: 'string' })
  .option('timestamp', { type: 'string', describe: 'RFC3339 timestamp' })
  .version('0.1.0')
  .help()
  .parseSync() as Argv

async function main() {
  if (argv['auto-update']) enableAutoUpdate()

  // Handle list command
  if (argv._[0] === 'list') {
    if (argv['auto-update']) {
      const { getProvidersAsync } = await import('./dataLoader.js')
      const providers: Provider[] = await getProvidersAsync()
      if (argv.provider) {
        const p = providers.find((p: Provider) => p.id === argv.provider)
        if (!p) {
          console.error(`Provider ${argv.provider} not found.`)
          process.exit(1)
        }
        console.log(`${p.name}: (${p.models.length} models)`)
        for (const m of p.models) {
          console.log(`  ${p.id}:${m.id}${m.name ? ': ' + m.name : ''}`)
        }
      } else {
        for (const p of providers) {
          console.log(`${p.name}: (${p.models.length} models)`)
          for (const m of p.models) {
            console.log(`  ${p.id}:${m.id}${m.name ? ': ' + m.name : ''}`)
          }
        }
      }
    } else {
      const { getProvidersSync } = await import('./dataLoader.js')
      const providers: Provider[] = getProvidersSync()
      if (argv.provider) {
        const p = providers.find((p: Provider) => p.id === argv.provider)
        if (!p) {
          console.error(`Provider ${argv.provider} not found.`)
          process.exit(1)
        }
        console.log(`${p.name}: (${p.models.length} models)`)
        for (const m of p.models) {
          console.log(`  ${p.id}:${m.id}${m.name ? ': ' + m.name : ''}`)
        }
      } else {
        for (const p of providers) {
          console.log(`${p.name}: (${p.models.length} models)`)
          for (const m of p.models) {
            console.log(`  ${p.id}:${m.id}${m.name ? ': ' + m.name : ''}`)
          }
        }
      }
    }
    process.exit(0)
  }

  // Handle calc command or direct model names
  const isCalcCommand = argv._[0] === 'calc'
  const models = isCalcCommand
    ? Array.isArray(argv.model)
      ? argv.model
      : [argv.model]
    : (argv._.filter((arg) => typeof arg === 'string') as string[])

  if (models.length > 0) {
    const usage = {
      input_tokens: argv['input-tokens'] !== undefined ? Number(argv['input-tokens']) : undefined,
      cache_write_tokens: argv['cache-write-tokens'] !== undefined ? Number(argv['cache-write-tokens']) : undefined,
      cache_read_tokens: argv['cache-read-tokens'] !== undefined ? Number(argv['cache-read-tokens']) : undefined,
      output_tokens: argv['output-tokens'] !== undefined ? Number(argv['output-tokens']) : undefined,
      input_audio_tokens: argv['input-audio-tokens'] !== undefined ? Number(argv['input-audio-tokens']) : undefined,
      cache_audio_read_tokens:
        argv['cache-audio-read-tokens'] !== undefined ? Number(argv['cache-audio-read-tokens']) : undefined,
      output_audio_tokens: argv['output-audio-tokens'] !== undefined ? Number(argv['output-audio-tokens']) : undefined,
      requests: argv['requests'] !== undefined ? Number(argv['requests']) : undefined,
    }
    const timestamp = argv.timestamp ? new Date(String(argv.timestamp)) : undefined
    const fn = argv['auto-update'] ? calcPriceAsync : calcPriceSync
    let hadError = false
    for (const modelArg of models) {
      let providerId: string | undefined
      let modelRef = modelArg as string
      if (modelRef.includes(':')) {
        ;[providerId, modelRef] = modelRef.split(':', 2)
      }
      try {
        const result = await fn(usage, modelRef, { providerId, timestamp })
        if (!result) {
          hadError = true
          console.error(`No price found for model ${modelArg}`)
          continue
        }
        const w = result.model.context_window
        const output: [string, string | number | undefined][] = [
          ['Provider', result.provider.name],
          ['Model', result.model.name || result.model.id],
          ['Model Prices', JSON.stringify(result.model_price)],
          ['Context Window', w !== undefined ? w.toLocaleString() : undefined],
          ['Price', `$${result.price}`],
        ]
        for (const [key, value] of output) {
          if (value !== undefined) {
            console.log(`${key.padStart(14)}: ${value}`)
          }
        }
        console.log('')
      } catch (e: any) {
        hadError = true
        console.error(`Error for model ${modelArg}:`, e.message)
      }
    }
    process.exit(hadError ? 1 : 0)
  }

  // If no command matched
  yargs().showHelp()
  process.exit(1)
}

main()
