/* eslint-disable @typescript-eslint/restrict-template-expressions */
import { parseArgs } from 'node:util'

import type { Provider } from './types'

import { version } from '../package.json'
import { data as embeddedData } from './data'
import { calcPrice } from './index'

const HELP = `genai-prices <command>

Commands:
  genai-prices list [provider]  List providers and models
  genai-prices calc <model...>  Calculate price

Options:
  --input-tokens <number>
  --cache-write-tokens <number>
  --cache-read-tokens <number>
  --output-tokens <number>
  --input-audio-tokens <number>
  --cache-audio-read-tokens <number>
  --output-audio-tokens <number>
  --provider <id>
  --price-context <key=value>   Select price variants, e.g. service_tier=flex or
                                processing=batch; repeat for several keys
  --auto-update                 Enable auto-update from GitHub
  --timestamp <RFC3339>
  -v, --version                 Show version number
  -h, --help                    Show help`

const PARSE_ARGS_CONFIG = {
  allowPositionals: true,
  options: {
    'auto-update': { type: 'boolean' },
    'cache-audio-read-tokens': { type: 'string' },
    'cache-read-tokens': { type: 'string' },
    'cache-write-tokens': { type: 'string' },
    help: { short: 'h', type: 'boolean' },
    'input-audio-tokens': { type: 'string' },
    'input-tokens': { type: 'string' },
    'output-audio-tokens': { type: 'string' },
    'output-tokens': { type: 'string' },
    'price-context': { multiple: true, type: 'string' },
    provider: { type: 'string' },
    timestamp: { type: 'string' },
    version: { short: 'v', type: 'boolean' },
  },
  strict: true,
} as const

function printHelp(): void {
  console.log(HELP)
}

function parseCliArgs(): ReturnType<typeof parseArgs<typeof PARSE_ARGS_CONFIG>> {
  try {
    return parseArgs(PARSE_ARGS_CONFIG)
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error))
    printHelp()
    process.exit(1)
  }
}

function parsePriceContext(pairs: string[] | undefined): Record<string, string> {
  // A null-prototype object keeps keys such as `__proto__` and `constructor` ordinary own keys.
  const context = Object.create(null) as Record<string, string>
  // Match the Python CLI, which splits list values on commas and trims each item, so both accept `a=1, b=2`.
  for (const pair of (pairs ?? []).flatMap((value) => value.split(',').map((item) => item.trim()))) {
    const separator = pair.indexOf('=')
    const key = pair.slice(0, separator)
    const value = pair.slice(separator + 1)
    if (separator <= 0 || value === '') {
      console.error(`Error: Invalid --price-context '${pair}', expected key=value`)
      process.exit(1)
    }
    if (Object.prototype.hasOwnProperty.call(context, key)) {
      console.error(`Error: Duplicate --price-context '${key}', it was already set to '${context[key]}'`)
      process.exit(1)
    }
    context[key] = value
  }
  return context
}

function main(): never {
  const parsed = parseCliArgs()
  const { positionals, values } = parsed
  if (values.version) {
    console.log(version)
    process.exit(0)
  }
  if (values.help) {
    printHelp()
    process.exit(0)
  }

  if (positionals[0] === 'list') {
    const providers = embeddedData
    const providerId = values.provider ?? positionals[1]
    if (providerId) {
      const p = providers.find((p: Provider) => p.id === providerId)
      if (!p) {
        console.error(`Provider ${providerId} not found.`)
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

  const isCalcCommand = positionals[0] === 'calc'
  const models = isCalcCommand ? positionals.slice(1) : positionals

  if (models.length > 0) {
    const usage = {
      cache_audio_read_tokens: values['cache-audio-read-tokens'] === undefined ? undefined : Number(values['cache-audio-read-tokens']),
      cache_read_tokens: values['cache-read-tokens'] === undefined ? undefined : Number(values['cache-read-tokens']),
      cache_write_tokens: values['cache-write-tokens'] === undefined ? undefined : Number(values['cache-write-tokens']),
      input_audio_tokens: values['input-audio-tokens'] === undefined ? undefined : Number(values['input-audio-tokens']),
      input_tokens: values['input-tokens'] === undefined ? undefined : Number(values['input-tokens']),
      output_audio_tokens: values['output-audio-tokens'] === undefined ? undefined : Number(values['output-audio-tokens']),
      output_tokens: values['output-tokens'] === undefined ? undefined : Number(values['output-tokens']),
    }
    const timestamp = values.timestamp ? new Date(values.timestamp) : undefined
    const priceContext = parsePriceContext(values['price-context'])
    let hadError = false
    for (const modelArg of models) {
      let providerId: string | undefined
      let modelId = modelArg
      if (modelId.includes(':')) {
        ;[providerId, modelId] = modelId.split(':', 2) as [string, string]
      }
      try {
        const result = calcPrice(usage, modelId, { priceContext, providerId, timestamp })
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

  printHelp()
  process.exit(1)
}

main()
