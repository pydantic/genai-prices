import { describe, expect, it, vi } from 'vitest'

import type { Provider } from '../types'

import { projectProviderData, validateProviderPriceCoverage } from '../providerData'
import { UnitRegistry } from '../unitRegistry'

const registry = new UnitRegistry({
  cache_read_tokens: {
    dimensions: { cache: 'read', direction: 'input', family: 'tokens' },
    per: 1_000_000,
    price_key: 'cache_read_mtok',
  },
  input_tokens: {
    dimensions: { direction: 'input', family: 'tokens' },
    per: 1_000_000,
    price_key: 'input_mtok',
  },
})

describe('remote provider preparation', () => {
  it('warns and omits unsupported prices and extractor destinations without mutating input', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const providers = [providerFixture()]

    const projected = projectProviderData(providers, registry)

    expect(warn.mock.calls).toEqual([
      ['Unsupported price key for standard pricing: future_conditional_mtok, future_mtok'],
      ['Unsupported extractor destination for standard extraction: future_tokens'],
    ])
    expect(providers[0]?.models[0]?.prices).toEqual({ future_mtok: 3, input_mtok: 1 })
    expect(providers[0]?.extractors?.[0]?.mappings).toHaveLength(2)
    expect(projected[0]?.models[0]?.prices).toEqual({ input_mtok: 1 })
    expect(projected[0]?.models[1]?.prices).toEqual([{ prices: { cache_read_mtok: 2, input_mtok: 1 } }])
    expect(projected[0]?.extractors?.[0]?.mappings.map(({ dest }) => dest)).toEqual(['input_tokens'])
  })

  it('validates every recognized conditional price set eagerly', () => {
    const providers = projectProviderData([providerFixture()], registry)

    validateProviderPriceCoverage(providers, registry)
    const conditionalPrices = providers[0]?.models[1]?.prices
    if (!Array.isArray(conditionalPrices)) throw new Error('Expected conditional prices fixture')
    conditionalPrices[0] = { prices: { cache_read_mtok: 2 } }

    expect(() => {
      validateProviderPriceCoverage(providers, registry)
    }).toThrow('Invalid price coverage for testing/conditional: Missing ancestor price key input_mtok for cache_read_mtok')
  })
})

function providerFixture(): Provider {
  return {
    api_pattern: 'testing',
    extractors: [
      {
        api_flavor: 'default',
        mappings: [
          { dest: 'input_tokens', path: 'input_tokens', required: true },
          { dest: 'future_tokens', path: 'future_tokens', required: false },
        ],
        model_path: 'model',
        root: 'usage',
      },
    ],
    id: 'testing',
    models: [
      {
        id: 'direct',
        match: { equals: 'direct' },
        prices: { future_mtok: 3, input_mtok: 1 },
      },
      {
        id: 'conditional',
        match: { equals: 'conditional' },
        prices: [{ prices: { cache_read_mtok: 2, future_conditional_mtok: 4, input_mtok: 1 } }],
      },
    ],
    name: 'Testing',
  }
}
