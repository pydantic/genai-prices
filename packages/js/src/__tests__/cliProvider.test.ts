import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { calcPrice, findProvider } from '../index'

const timestamp = '2026-10-16T00:00:00Z'
const usage = { input_tokens: 1_000_000, output_tokens: 1_000_000 }
const cliPath = fileURLToPath(new URL('../cli.ts', import.meta.url))

function runCli(args: string[]) {
  const result = spawnSync(process.execPath, ['--import', 'tsx', cliPath, ...args], {
    encoding: 'utf8',
    env: { ...process.env, TSX_DISABLE_CACHE: '1' },
    timeout: 10_000,
  })
  expect(result.error).toBeUndefined()
  expect(result.signal).toBeNull()
  return result
}

function calculate(args: string[]) {
  return runCli([...args, '--input-tokens', '1000000', '--output-tokens', '1000000', '--timestamp', timestamp])
}

function expectPrices(result: ReturnType<typeof runCli>, providers: string[], totals: number[]) {
  expect(result.status).toBe(0)
  expect(result.stderr).toBe('')
  expect([...result.stdout.matchAll(/Provider: (.+)/g)].map((match) => match[1])).toEqual(providers)
  expect([...result.stdout.matchAll(/Total Price: \$(.+)/g)].map((match) => Number(match[1]))).toEqual(totals)
}

describe('CLI default provider', () => {
  it('pins the bundled Arcee price through the public API', () => {
    // Arcee has no model_match, so inference cannot substitute for the flag.
    expect(findProvider({ providerId: 'arcee' })?.model_match).toBeUndefined()
    expect(calcPrice(usage, 'trinity-large-thinking', { timestamp: new Date(timestamp) })).toBeNull()
    expect(calcPrice(usage, 'trinity-large-thinking', { providerId: 'arcee', timestamp: new Date(timestamp) })).toMatchObject({
      input_price: 0.25,
      model: { id: 'trinity-large-thinking' },
      output_price: 0.8,
      provider: { id: 'arcee' },
      total_price: 1.05,
    })
  })

  it.each([['calc', 'trinity-large-thinking'], ['trinity-large-thinking']])('uses --provider with %j', (...args) => {
    const result = calculate([...args, '--provider', 'arcee'])
    expectPrices(result, ['Arcee'], [1.05])
    expect(result.stdout).toContain('Input Price: $0.25')
    expect(result.stdout).toContain('Output Price: $0.8')
  })

  it('uses the selected catalog for a model with a slash in its ID', () => {
    const result = calculate(['calc', 'deepseek/deepseek-v4-flash-latest', '--provider', 'arcee'])
    expect(result.status).toBe(0)
    expect(result.stderr).toBe('')
    expect(result.stdout).toContain('Provider: Arcee')
    expect(result.stdout).toContain('Input Price: $0.14')
    expect(result.stdout).toContain('Output Price: $0.28')
    const total = Number(/Total Price: \$(.+)/.exec(result.stdout)?.[1])
    expect(total).toBeCloseTo(0.42, 12)
  })

  it.each(['unknown-provider-xyz', 'arcee'])('does not infer OpenAI when --provider is %s', (provider) => {
    const result = calculate(['calc', 'gpt-4o-mini', '--provider', provider])
    expect(result.status).toBe(1)
    expect(result.stdout).toBe('')
    expect(result.stderr).toBe('No price found for model gpt-4o-mini\n')
  })

  it.each(['openai:gpt-4o-mini', 'custom-openai:gpt-4o-mini', 'litellm:openai/gpt-4o-mini'])(
    'preserves the qualified provider in %s over a conflicting flag',
    (model) => {
      expectPrices(calculate(['calc', model, '--provider', 'arcee']), ['OpenAI'], [0.75])
    }
  )

  it('lets a qualified provider override an unknown default', () => {
    expectPrices(calculate(['calc', 'arcee:trinity-large-thinking', '--provider', 'unknown-provider-xyz']), ['Arcee'], [1.05])
  })

  it('rejects an unknown qualified provider despite a valid default', () => {
    const result = calculate(['calc', 'unknown-provider-xyz:trinity-large-thinking', '--provider', 'arcee'])
    expect(result.status).toBe(1)
    expect(result.stdout).toBe('')
    expect(result.stderr).toBe('No price found for model unknown-provider-xyz:trinity-large-thinking\n')
  })

  it('restores the default for a bare model after a qualified model', () => {
    expectPrices(
      calculate(['calc', 'trinity-large-thinking', 'openai:gpt-4o-mini', 'trinity-large-thinking', '--provider', 'arcee']),
      ['Arcee', 'OpenAI', 'Arcee'],
      [1.05, 0.75, 1.05]
    )
  })

  it('keeps model inference when no default is supplied', () => {
    expectPrices(calculate(['calc', 'gpt-4o-mini']), ['OpenAI'], [0.75])
  })

  it('passes a LiteLLM default to the existing API resolver', () => {
    expectPrices(calculate(['calc', 'openai/gpt-4o-mini', '--provider', 'litellm']), ['OpenAI'], [0.75])
  })

  it('keeps provider help available', () => {
    const result = runCli(['--help'])
    expect(result.status).toBe(0)
    expect(result.stderr).toBe('')
    expect(result.stdout).toContain('--provider <id>')
    expect(result.stdout).toContain('genai-prices calc <model...>')
  })

  it('keeps list provider selection and flag precedence', () => {
    const positional = runCli(['list', 'arcee'])
    const flagged = runCli(['list', 'openai', '--provider', 'arcee'])
    expect(positional.status).toBe(0)
    expect(flagged.status).toBe(0)
    expect(positional.stderr).toBe('')
    expect(flagged.stderr).toBe('')
    expect(flagged.stdout).toBe(positional.stdout)
    expect(flagged.stdout).toContain('arcee:trinity-large-thinking')
  })
})
