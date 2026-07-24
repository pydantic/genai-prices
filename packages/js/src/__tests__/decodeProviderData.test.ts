import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { decodeV2Payload } from '../decodeProviderData'
import { TieredPrices } from '../types'

const publishedPayload = JSON.parse(readFileSync(new URL('../../../../prices/data_v2.json', import.meta.url), 'utf8')) as unknown

describe('decodeV2Payload', () => {
  it('strictly decodes the complete published wrapped payload', () => {
    const decoded = decodeV2Payload(publishedPayload)

    expect(decoded.providers.length).toBeGreaterThan(0)
    expect(Object.keys(decoded.units).length).toBeGreaterThan(0)
    expect(decoded.units.input_tokens?.price_key).toBe('input_mtok')
    const tieredPrice = decoded.providers
      .flatMap((provider) => provider.models)
      .flatMap((model) => (Array.isArray(model.prices) ? model.prices.map(({ prices }) => prices) : [model.prices]))
      .flatMap((prices) => Object.values(prices))
      .find((price) => price instanceof TieredPrices)
    expect(tieredPrice).toBeInstanceOf(TieredPrices)
  })

  it('normalizes wire constraints to runtime discriminators', () => {
    const decoded = decodeV2Payload(publishedPayload)
    const constraints = decoded.providers
      .flatMap((provider) => provider.models)
      .flatMap((model) => (Array.isArray(model.prices) ? model.prices : []))
      .map(({ constraint }) => constraint)
      .filter((constraint) => constraint !== undefined)

    expect(constraints.some((constraint) => constraint.type === 'start_date')).toBe(true)
    expect(constraints.some((constraint) => constraint.type === 'time_of_date')).toBe(true)
  })

  it('rejects unknown fields at every structural level', () => {
    const raw = structuredClone(publishedPayload) as {
      providers: { models: { prices: Record<string, unknown> }[] }[]
    }
    const firstModel = raw.providers[0]?.models[0]
    if (!firstModel) throw new Error('Expected published provider model fixture')
    firstModel.prices = { input_mtok: { base: 1, extra: true, tiers: [] } }

    expect(() => decodeV2Payload(raw)).toThrow('Unknown fields')
  })

  it.each([
    null,
    [],
    { providers: [] },
    { extra: true, providers: [], units: {} },
    { providers: [{ api_pattern: 'testing', extra: true, id: 'testing', models: [], name: 'Testing' }], units: {} },
    {
      providers: [
        {
          api_pattern: 'testing',
          id: 'testing',
          models: [{ id: 'model', match: { equals: 'model' }, prices: { input_mtok: '1' } }],
          name: 'Testing',
        },
      ],
      units: {},
    },
  ])('rejects malformed wrapped payload %#', (raw) => {
    expect(() => decodeV2Payload(raw)).toThrow()
  })
})
