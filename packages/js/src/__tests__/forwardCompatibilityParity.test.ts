import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { WrappedProviderData } from '../types'

import { calcPrice, findProvider, updatePrices } from '../api'
import { data } from '../data'
import { extractUsage } from '../extractUsage'
import { getActiveRegistry, setActiveRegistry } from '../units'

type ForwardFixture = Readonly<{
  providers: {
    extractors: unknown[]
    models: { prices: Record<string, unknown>[] }[]
  }[]
  units: Record<string, unknown>
}>

const expectedWarnings = [
  "Unsupported match variant at providers[0].model_match for provider 'future-fixture'; upgrade genai-prices for full support",
  "Unsupported extractor variant at providers[0].extractors[1] for provider 'future-fixture'; upgrade genai-prices for full support",
  "Unsupported price variant at providers[0].models[0].prices[0].prices.cache_read_mtok for provider 'future-fixture', model 'future-model'; upgrade genai-prices for full support",
  "Unsupported constraint variant at providers[0].models[0].prices[1].constraint for provider 'future-fixture', model 'future-model'; upgrade genai-prices for full support",
  "Unsupported match variant at providers[0].models[1].match for provider 'future-fixture', model 'unsupported-model'; upgrade genai-prices for full support",
]

afterEach(() => {
  vi.restoreAllMocks()
  setActiveRegistry()
  updatePrices(({ setProviderData }) => {
    setProviderData(data)
  })
})

describe('forward-compatible shared fixture', () => {
  it('retains understood siblings, warns deterministically, and rejects malformed replacements atomically', () => {
    const wrapped = readFixture('forward-compatible-v3.json') as ForwardFixture
    const malformed = readFixture('malformed-recognized-v3.json') as Record<'constraint' | 'extractor', Record<string, unknown>>
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    updatePrices(({ setProviderData }) => {
      setProviderData(wrapped as unknown as WrappedProviderData)
    })

    expect(warnSpy.mock.calls.map(([warning]) => String(warning))).toEqual(expectedWarnings)
    const activeRegistry = getActiveRegistry()
    const provider = findProvider({ providerId: 'future-alias' })
    expect(provider?.id).toBe('future-fixture')
    expect(provider?.extractors).toHaveLength(1)
    expect(provider?.extractors?.[0]?.mappings).toHaveLength(2)
    expect(provider?.models.map(({ id }) => id)).toEqual(['future-model'])
    expect(findProvider({ modelId: 'future-model' })).toBeUndefined()
    if (provider === undefined) throw new Error('Expected future fixture provider')

    expect(extractUsage(provider, { model: 'future-model', usage: { input: 1_000_000, output: 1_000_000 } })).toEqual({
      model: 'future-model',
      usage: { input_tokens: 1_000_000, output_tokens: 1_000_000 },
    })
    const usage = { input_tokens: 1_000_000, output_tokens: 1_000_000 }
    expect(calcPrice(usage, 'future-model', { providerId: 'future-alias', timestamp: new Date('2025-01-01T00:00:00Z') })).toMatchObject({
      input_price: 1,
      output_price: 2,
      total_price: 3,
    })
    expect(calcPrice(usage, 'future-model', { providerId: 'future-alias', timestamp: new Date('2026-01-01T00:00:00Z') })).toMatchObject({
      input_price: 3,
      output_price: 4,
      total_price: 7,
    })

    const invalidConstraint = structuredClone(wrapped)
    defined(defined(defined(invalidConstraint.providers[0]).models[0]).prices[2]).constraint = malformed.constraint
    expect(() => {
      updatePrices(({ setProviderData }) => {
        setProviderData(invalidConstraint as unknown as WrappedProviderData)
      })
    }).toThrow('genai-prices: invalid data: providers[0].models[0].prices[1] expected a start-date')

    const invalidExtractor = structuredClone(wrapped)
    defined(invalidExtractor.providers[0]).extractors[0] = malformed.extractor
    expect(() => {
      updatePrices(({ setProviderData }) => {
        setProviderData(invalidExtractor as unknown as WrappedProviderData)
      })
    }).toThrow('genai-prices: invalid data: providers[0].extractors[0].mappings must be an array')

    expect(warnSpy).toHaveBeenCalledTimes(expectedWarnings.length)
    expect(getActiveRegistry()).toBe(activeRegistry)
    expect(findProvider({ providerId: 'future-alias' })).toBe(provider)
    expect(calcPrice(usage, 'future-model', { providerId: 'future-alias', timestamp: new Date('2025-01-01T00:00:00Z') })?.total_price).toBe(
      3
    )
  })
})

function readFixture(name: string): unknown {
  return JSON.parse(readFileSync(new URL(`../../../../tests/fixtures/${name}`, import.meta.url), 'utf8')) as unknown
}

function defined<T>(value: T | undefined): T {
  if (value === undefined) throw new Error('Expected fixture value to be defined')
  return value
}
