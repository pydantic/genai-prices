import { describe, expect, it } from 'vitest'

import type { PriceContext, PriceVariant, Provider } from '../types'

import { calcPrice } from '../api'

const USAGE = { input_tokens: 1_000_000, output_tokens: 1_000_000 }
// below the 272K-token long-context tier OpenAI's models price separately
const SHORT_CONTEXT_USAGE = { input_tokens: 100_000, output_tokens: 100_000 }

const FLEX = { prices: { input_mtok: 1, output_mtok: 4 }, when: { service_tier: 'flex' } }
const FAST = { prices: { input_mtok: 4, output_mtok: 16 }, when: { service_tier: ['priority', 'fast'] } }

// Wire format, as the published feed and caller-supplied providers carry it: constraints have no `type`.
function provider(priceVariants: unknown[]): Provider {
  return {
    api_pattern: 'testing',
    id: 'testing',
    models: [
      {
        id: 'model',
        match: { equals: 'model' },
        price_variants: priceVariants as PriceVariant[],
        prices: { input_mtok: 2, output_mtok: 8, requests_kcount: 1000 },
      },
    ],
    name: 'Testing',
  }
}

function total(priceVariants: unknown[], priceContext?: PriceContext, timestamp?: Date): number | undefined {
  return calcPrice(USAGE, 'model', { priceContext, provider: provider(priceVariants), timestamp })?.total_price
}

describe('price variants', () => {
  it('override only the keys they list and are reported', () => {
    // a null price, which the build never publishes, leaves the standard rate in place like an omitted one
    const flex = { ...FLEX, prices: { ...FLEX.prices, requests_kcount: null } }
    const result = calcPrice(USAGE, 'model', { priceContext: { service_tier: 'flex' }, provider: provider([flex]) })

    expect(result?.total_price).toBe(6)
    expect(result?.price_variant?.when).toEqual({ service_tier: 'flex' })
  })

  it.each(['priority', 'fast'])('match any value of a list: %s', (tier) => {
    expect(total([FLEX, FAST], { service_tier: tier })).toBe(21)
  })

  it.each([undefined, {}, { service_tier: null }, { service_tier: 'default' }, { service_tier: 'auto' }, { speed: 'flex' }])(
    'charge standard prices for an unmatched context: %j',
    (priceContext) => {
      const result = calcPrice(USAGE, 'model', { priceContext, provider: provider([FLEX, FAST]) })

      expect(result?.total_price).toBe(11)
      expect(result).not.toHaveProperty('price_variant')
    }
  )

  // The build rejects variants that can match the same request, but newer data may have them: the last active wins.
  it('are resolved together like prices when several match', () => {
    const laterFlex = { prices: { input_mtok: 0.5 }, when: { service_tier: ['flex', 'other'] } }

    expect(total([FLEX, laterFlex], { service_tier: 'flex' })).toBe(9.5)
  })

  it('apply from their first start date when every entry is dated', () => {
    const variants = [
      { ...FLEX, constraint: { start_date: '2026-01-01' } },
      { ...FLEX, constraint: { start_date: '2026-06-01' }, prices: { input_mtok: 0.5 } },
    ]
    const at = (day: string) => total(variants, { service_tier: 'flex' }, new Date(`${day}T00:00:00Z`))

    expect(at('2025-12-31')).toBe(11)
    expect(at('2026-01-01')).toBe(6)
    // the later entry replaces the whole variant, so output falls back to the standard rate
    expect(at('2026-06-01')).toBe(9.5)
  })

  it.each([
    ['unknown-parameter', { service_tier: 'flex', speed: 'fast' }],
    ['bool-value', { service_tier: true }],
    ['object-value', { service_tier: { any_of: ['flex'] } }],
    ['non-string-list', { service_tier: [1, null] }],
    ['empty', {}],
    ['missing', undefined],
    ['null', null],
  ])('never match a `when` shape from newer data: %s', (_name, when) => {
    expect(total([{ prices: { input_mtok: 1 }, when }], { service_tier: 'flex' })).toBe(11)
  })
})

describe('OpenAI service tiers', () => {
  it.each([
    // gpt-5.4 per 1M tokens: $2.50 in / $15 out standard, flex $1.25 / $7.50, fast $5 / $30
    ['gpt-5.4', undefined, 1.75],
    ['gpt-5.4', { service_tier: 'flex' }, 0.875],
    ['gpt-5.4', { service_tier: 'priority' }, 3.5],
    ['gpt-5.4', { service_tier: 'fast' }, 3.5],
    ['gpt-5.4', { service_tier: 'default' }, 1.75],
    // gpt-5.4-nano has no fast rates
    ['gpt-5.4-nano', { service_tier: 'priority' }, 0.145],
  ])('%s with %j', (model, priceContext, expected) => {
    const result = calcPrice(SHORT_CONTEXT_USAGE, model, { priceContext, providerId: 'openai' })

    expect(result?.total_price).toBeCloseTo(expected, 10)
  })

  it('start with the current standard rates', () => {
    const at = (timestamp: string) =>
      calcPrice(SHORT_CONTEXT_USAGE, 'gpt-5.6-sol', {
        priceContext: { service_tier: 'flex' },
        providerId: 'openai',
        timestamp: new Date(timestamp),
      })?.total_price

    expect(at('2026-08-20T00:00:00Z')).toBeCloseTo(3.5, 10)
    expect(at('2026-08-21T00:00:00Z')).toBeCloseTo(1.2, 10)
  })

  it('do not apply to models borrowed through fallback', () => {
    const result = calcPrice(SHORT_CONTEXT_USAGE, 'gpt-5.4', { priceContext: { service_tier: 'flex' }, providerId: 'azure' })

    expect(result?.model.id).toBe('gpt-5.4')
    expect(result?.total_price).toBeCloseTo(1.75, 10)
    expect(result).not.toHaveProperty('price_variant')
  })
})
