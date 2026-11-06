import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { assert, describe, expect, it } from 'vitest'

import { calcPrice } from '../index'

const timestamp = '2026-10-15T00:00:00Z'
const usage = { input_tokens: 1000, output_tokens: 100 }
const fineTunedModel = 'ft:gpt-4o-2024-08-06:org:custom:id'

function runCli(...args: string[]) {
  const result = spawnSync(process.execPath, ['--import', 'tsx', fileURLToPath(new URL('../cli.ts', import.meta.url)), ...args], {
    cwd: fileURLToPath(new URL('../../', import.meta.url)),
    encoding: 'utf8',
    timeout: 10_000,
  })
  expect(result.error).toBeUndefined()
  expect(result.signal).toBeNull()
  return result
}

function calculate(...args: string[]) {
  return runCli(...args, '--input-tokens', '1000', '--output-tokens', '100', '--timestamp', timestamp)
}

function expectQuote(args: string[], providerId: string, modelId: string, total: number) {
  // Verify the independent price expectation against the public API and bundled data.
  const expected = calcPrice(usage, modelId, { providerId, timestamp: new Date(timestamp) })
  assert(expected)
  expect(expected.total_price).toBeCloseTo(total, 12)

  const result = calculate(...args)
  expect(result.status).toBe(0)
  expect(result.stderr).toBe('')
  expect(result.stdout).toContain(`Provider: ${expected.provider.name}\n`)
  expect(result.stdout).toContain(`Model: ${expected.model.name ?? expected.model.id}\n`)
  expect(Number(/Total Price: \$(.*)/.exec(result.stdout)?.[1])).toBeCloseTo(total, 12)
}

describe.each(['calc', 'direct'])('%s invocation', (syntax) => {
  const command = syntax === 'calc' ? ['calc'] : []

  it('retains automatic provider selection', () => {
    expectQuote([...command, 'gpt-4o'], 'openai', 'gpt-4o', 0.0035)
  })

  it('retains the complete model ID after the provider prefix', () => {
    expectQuote([...command, 'openai:gpt-4o:extended'], 'openai', 'gpt-4o:extended', 0.0078)
  })

  it('preserves every colon in a qualified fine-tuned model ID', () => {
    expectQuote([...command, `openai:${fineTunedModel}`], 'openai', fineTunedModel, 0.00525)
  })

  it('retains qualified Bedrock references whose matching already tolerates version suffixes', () => {
    expectQuote([...command, 'aws:amazon.nova-pro-v1:0'], 'aws', 'amazon.nova-pro-v1:0', 0.00112)
  })
})

it.each(['', 'openai'])('retains provider aliases with --provider "%s"', (providerOption) => {
  const options = providerOption ? ['--provider', providerOption] : []
  expectQuote(['calc', 'BEDROCK:amazon.nova-pro-v1:0', ...options], 'aws', 'amazon.nova-pro-v1:0', 0.00112)
})

it.each(['', 'aws'])('retains the special litellm provider prefix with --provider "%s"', (providerOption) => {
  const options = providerOption ? ['--provider', providerOption] : []
  expectQuote(['calc', 'litellm:openai/gpt-4o', ...options], 'openai', 'gpt-4o', 0.0035)
})

it('preserves colon-containing IDs when calculating multiple providers and models', () => {
  const result = calculate('calc', 'openai:gpt-4o:extended', `openai:${fineTunedModel}`, 'aws:amazon.nova-pro-v1:0')
  expect(result.status).toBe(0)
  expect(result.stderr).toBe('')
  expect([...result.stdout.matchAll(/Provider: (.*)/g)].map((match) => match[1])).toEqual(['OpenAI', 'OpenAI', 'AWS Bedrock'])
  expect([...result.stdout.matchAll(/ {9}Model: (.*)/g)].map((match) => match[1])).toEqual(['GPT-4o (extended)', 'ft:gpt-4o', 'Nova Pro'])
  const totals = [...result.stdout.matchAll(/Total Price: \$(.*)/g)].map((match) => Number(match[1]))
  expect(totals).toHaveLength(3)
  for (const [index, total] of [0.0078, 0.00525, 0.00112].entries()) {
    expect(totals[index]).toBeCloseTo(total, 12)
  }
})

it('continues after an unknown model and returns failure alongside successful prices', () => {
  const result = calculate('calc', 'openai:unknown-model', 'openai:gpt-4o:extended')
  expect(result.status).toBe(1)
  expect(result.stderr).toBe('No price found for model openai:unknown-model\n')
  expect(result.stdout).toContain('Model: GPT-4o (extended)\n')
  expect(result.stdout).toContain('Total Price: $0.0078\n')
})

it.each(['unknown-provider:gpt-4o', 'openai:unknown-model', 'openai:'])('retains lookup failure for %s', (model) => {
  const result = calculate('calc', model)
  expect(result.status).toBe(1)
  expect(result.stdout).toBe('')
  expect(result.stderr).toBe(`No price found for model ${model}\n`)
})

it.each([[], ['calc']])('requires a model for arguments %j', (...args) => {
  const result = runCli(...args)
  expect(result.status).toBe(1)
  expect(result.stderr).toBe('')
  expect(result.stdout).toContain('genai-prices <command>\n')
})

it('requires a value for --provider', () => {
  const result = runCli('calc', 'gpt-4o', '--provider')
  expect(result.status).toBe(1)
  expect(result.stderr).toContain("Option '--provider <value>' argument missing")
  expect(result.stdout).toContain('genai-prices <command>\n')
})

it('retains help and version output', () => {
  const help = runCli('--help')
  expect(help.status).toBe(0)
  expect(help.stderr).toBe('')
  expect(help.stdout).toContain('genai-prices calc <model...>  Calculate price\n')
  expect(help.stdout).toContain('--provider <id>\n')

  const version = runCli('--version')
  expect(version.status).toBe(0)
  expect(version.stderr).toBe('')
  expect(version.stdout).toMatch(/^\d+\.\d+\.\d+.*\n$/)
})

it('retains positional and option provider selection for list', () => {
  const positional = runCli('list', 'aws')
  const option = runCli('list', '--provider', 'aws')
  expect(positional.status).toBe(0)
  expect(option.status).toBe(0)
  expect(positional.stderr).toBe('')
  expect(option.stderr).toBe('')
  expect(option.stdout).toBe(positional.stdout)
  expect(positional.stdout).toContain('AWS Bedrock: (')
  expect(positional.stdout).toContain('aws:amazon.nova-pro-v1:0: Nova Pro\n')

  const unknown = runCli('list', 'unknown-provider')
  expect(unknown.status).toBe(1)
  expect(unknown.stdout).toBe('')
  expect(unknown.stderr).toBe('Provider unknown-provider not found.\n')
})
