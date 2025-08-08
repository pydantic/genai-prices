/* eslint-disable @typescript-eslint/no-unnecessary-type-conversion */
/* eslint-disable @typescript-eslint/restrict-template-expressions */
import yargs from 'yargs'
import { hideBin } from 'yargs/helpers'

import type { Provider } from './types'

import { data as embeddedData } from './data'
import { calcPrice } from './index'

interface Argv {
  $0: string
  _: (number | string)[]
  'auto-update'?: boolean
  autoUpdate?: boolean
  'cache-audio-read-tokens'?: number
  'cache-read-tokens'?: number
  'cache-write-tokens'?: number
  'input-audio-tokens'?: number
  'input-tokens'?: number
  model?: string | string[]
  'output-audio-tokens'?: number
  'output-tokens'?: number
  provider?: string
  requests?: number
  timestamp?: string
}

const argv = yargs(hideBin(process.argv))
  .scriptName('genai-prices')
  .command('list [provider]', 'List providers and models', (y) =>
    y.positional('provider', { describe: 'Provider ID to filter', type: 'string' })
  )
  .command('calc <model...>', 'Calculate price', (y) =>
    y
      .positional('model', { array: true, describe: 'Model(s) (optionally provider:model)', type: 'string' })
      .option('input-tokens', { type: 'number' })
      .option('cache-write-tokens', { type: 'number' })
      .option('cache-read-tokens', { type: 'number' })
      .option('output-tokens', { type: 'number' })
      .option('input-audio-tokens', { type: 'number' })
      .option('cache-audio-read-tokens', { type: 'number' })
      .option('output-audio-tokens', { type: 'number' })
      .option('requests', { type: 'number' })
      .option('provider', { type: 'string' })
      .option('auto-update', { default: false, type: 'boolean' })
      .option('timestamp', { describe: 'RFC3339 timestamp', type: 'string' })
  )
  .option('auto-update', { describe: 'Enable auto-update from GitHub', type: 'boolean' })
  .option('input-tokens', { type: 'number' })
  .option('cache-write-tokens', { type: 'number' })
  .option('cache-read-tokens', { type: 'number' })
  .option('output-tokens', { type: 'number' })
  .option('input-audio-tokens', { type: 'number' })
  .option('cache-audio-read-tokens', { type: 'number' })
  .option('output-audio-tokens', { type: 'number' })
  .option('requests', { type: 'number' })
  .option('provider', { type: 'string' })
  .option('timestamp', { describe: 'RFC3339 timestamp', type: 'string' })
  .version('0.1.0')
  .help()
  .parseSync() as Argv

function main() {
  // Handle list command
  if (argv._[0] === 'list') {
    const providers = embeddedData
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
    process.exit(0)
  }

  // Handle calc command or direct model names
  const isCalcCommand = argv._[0] === 'calc'
  const models = isCalcCommand ? (Array.isArray(argv.model) ? argv.model : [argv.model]) : argv._.filter((arg) => typeof arg === 'string')

  if (models.length > 0) {
    const usage = {
      cache_audio_read_tokens: argv['cache-audio-read-tokens'] !== undefined ? Number(argv['cache-audio-read-tokens']) : undefined,
      cache_read_tokens: argv['cache-read-tokens'] !== undefined ? Number(argv['cache-read-tokens']) : undefined,
      cache_write_tokens: argv['cache-write-tokens'] !== undefined ? Number(argv['cache-write-tokens']) : undefined,
      input_audio_tokens: argv['input-audio-tokens'] !== undefined ? Number(argv['input-audio-tokens']) : undefined,
      input_tokens: argv['input-tokens'] !== undefined ? Number(argv['input-tokens']) : undefined,
      output_audio_tokens: argv['output-audio-tokens'] !== undefined ? Number(argv['output-audio-tokens']) : undefined,
      output_tokens: argv['output-tokens'] !== undefined ? Number(argv['output-tokens']) : undefined,
      requests: argv.requests !== undefined ? Number(argv.requests) : undefined,
    }
    const timestamp = argv.timestamp ? new Date(String(argv.timestamp)) : undefined
    let hadError = false
    for (const modelArg of models) {
      let providerId: string | undefined
      // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
      let modelId = modelArg!
      if (modelId.includes(':')) {
        ;[providerId, modelId] = modelId.split(':', 2) as [string, string]
      }
      try {
        const result = calcPrice(usage, modelId, { providerId, timestamp })
        if (!result) {
          hadError = true
          console.error(`No price found for model ${modelArg}`)
          continue
        }
        const w = result.model.context_window
        const output: [string, number | string | undefined][] = [
          ['Provider', result.provider.name],
          ['Model', result.model.name ?? result.model.id],
          ['Model Prices', JSON.stringify(result.model_price)],
          ['Context Window', w !== undefined ? w.toLocaleString() : undefined],
          ['Total Price', `$${result.total_price}`],
          ['Input Price', `$${result.input_price}`],
          ['Output Price', `$${result.output_price}`],
        ]
        for (const [key, value] of output) {
          if (value !== undefined) {
            console.log(`${key.padStart(14)}: ${value}`)
          }
        }
        console.log('')
      } catch (e: unknown) {
        hadError = true
        if (e instanceof Error) {
          console.error(`Error for model ${modelArg}:`, e.message)
        }
      }
    }
    process.exit(hadError ? 1 : 0)
  }

  // If no command matched
  yargs().showHelp()
  process.exit(1)
}

main()
