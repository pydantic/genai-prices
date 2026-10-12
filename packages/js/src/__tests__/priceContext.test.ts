import { readFileSync } from 'node:fs'
import { afterEach, assert, expect, it, vi } from 'vitest'

import type { ModelPrice, PriceContext, Provider, Usage } from '../types'

import { data } from '../data'
import { calcPrice, extractUsage, findProvider, updatePrices } from '../index'

const fixture = JSON.parse(readFileSync(new URL('../../../../tests/fixtures/price_context.json', import.meta.url), 'utf8')) as {
  cases: {
    context?: PriceContext
    input: number
    name: string
    output: number
    timestamp: string
    total: number
    warn?: boolean
  }[]
  providers: Provider[]
  usage: Usage
}

afterEach(() => {
  vi.restoreAllMocks()
  updatePrices(({ setProviderData }) => {
    setProviderData(data)
  })
})

it.each(fixture.cases)('price context: $name', (test) => {
  updatePrices(({ setProviderData }) => {
    setProviderData(fixture.providers)
  })
  const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
  const result = calcPrice(fixture.usage, 'context-model', {
    priceContext: test.context,
    providerId: 'testing',
    timestamp: new Date(test.timestamp),
  })
  expect(result?.input_price).toBe(test.input)
  expect(result?.output_price).toBe(test.output)
  expect(result?.total_price).toBe(test.total)
  expect(warning.mock.calls).toEqual(test.warn ? [["No price variant matched for model 'context-model'; using standard prices"]] : [])
})

it.each([
  ['o3', 'flex', 4.8125],
  ['o3', 'priority', 16.84375],
  ['o4-mini', 'flex', 2.647],
  ['o4-mini', 'priority', 9.625],
  ['gpt-5-mini', 'flex', 1.096875],
  ['gpt-6.1-sol', 'fast', 36.1],
  ['gpt-6.1-sol', 'priority', 36.1],
] as const)('prices OpenAI %s %s', (model, tier, total) => {
  expect(
    calcPrice({ cache_read_tokens: 250_000, input_tokens: 1_000_000, output_tokens: 1_000_000 }, model, {
      priceContext: { service_tier: tier },
      providerId: 'openai',
      timestamp: new Date('2026-10-12T00:00:00Z'),
    })?.total_price
  ).toBeCloseTo(total, 12)
})

it.each([
  ['o4-mini', 100_000, 100_000, 0.0138, 2.2],
  ['gpt-5.4', 272_000, 272_000, 0.03536, 7.5],
  ['gpt-5.4', 272_001, 272_001, 0.06800025, 11.25],
  ['gpt-5.5-pro', 272_000, 0, 4.08, 90],
  ['gpt-5.5-pro', 272_001, 0, 4.080015, 90],
] as const)('uses published Flex rates for %s at %i input tokens', (model, inputTokens, cacheReadTokens, inputPrice, outputPrice) => {
  const result = calcPrice({ cache_read_tokens: cacheReadTokens, input_tokens: inputTokens, output_tokens: 1_000_000 }, model, {
    priceContext: { service_tier: 'flex' },
    providerId: 'openai',
    timestamp: new Date('2026-10-12T00:00:00Z'),
  })
  expect(result?.input_price).toBeCloseTo(inputPrice, 12)
  expect(result?.output_price).toBeCloseTo(outputPrice, 12)
})

it('preserves the shared rate card across extracted flex, default and priority calls', () => {
  const provider = findProvider({ providerId: 'openai' })
  assert(provider)
  const extracted = extractUsage(
    provider,
    {
      model: 'o3',
      service_tier: 'flex',
      usage: { completion_tokens: 1_000_000, prompt_tokens: 1_000_000 },
    },
    'chat'
  )
  assert(extracted.model)
  for (const [tier, total] of [
    ['flex', 5],
    ['default', 10],
    ['priority', 17.5],
    ['flex', 5],
  ] as const) {
    expect(
      calcPrice(extracted.usage, extracted.model, {
        priceContext: { service_tier: tier },
        providerId: 'openai',
        timestamp: new Date('2026-10-12T00:00:00Z'),
      })?.total_price
    ).toBe(total)
  }
})

it.each([{}, { service_tier: null }, { service_tier: true }])('rejects invalid variant conditions %j', (when) => {
  const providers = structuredClone(fixture.providers)
  const provider = providers[0]
  assert(provider)
  const variant = provider.models[0]?.price_variants?.[0]
  assert(variant)
  variant.when = when as unknown as PriceContext
  expect(() => calcPrice({}, 'context-model', { provider })).toThrow('Price variant when')
})

it('warns for unresearched history and unsupported models', () => {
  const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
  for (const [model, timestamp] of [
    ['o3', '2026-10-11'],
    ['text-embedding-3-small', '2026-10-12'],
  ] as const) {
    const options = { providerId: 'openai', timestamp: new Date(timestamp) }
    const standard = calcPrice({ input_tokens: 1_000_000 }, model, options)
    expect(
      calcPrice({ input_tokens: 1_000_000 }, model, {
        ...options,
        priceContext: { service_tier: 'flex' },
      })?.total_price
    ).toBe(standard?.total_price)
  }
  expect(warning).toHaveBeenCalledTimes(2)
})

it('rejects a missing variant price map', () => {
  const provider = structuredClone(fixture.providers[0])
  assert(provider)
  const variant = provider.models[0]?.price_variants?.[0]
  assert(variant)
  variant.prices = null as unknown as ModelPrice
  expect(() => calcPrice({}, 'context-model', { provider })).toThrow('Price variant prices must be an object')
})

it('does not inherit tier rates from a fallback provider', () => {
  const usage = { input_tokens: 1_000_000, output_tokens: 1_000_000 }
  const options = { providerId: 'azure', timestamp: new Date('2026-10-12T00:00:00Z') }
  const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
  const contexts: (PriceContext | undefined)[] = [undefined, {}, { service_tier: 'priority' }]
  for (const priceContext of contexts) {
    const result = calcPrice(usage, 'gpt-5', { ...options, priceContext })
    expect(result?.provider.id).toBe('azure')
    expect(result?.total_price).toBe(11.25)
  }
  expect(warning.mock.calls).toEqual([["No price variant matched for provider 'azure' model 'gpt-5'; using standard prices"]])
})
