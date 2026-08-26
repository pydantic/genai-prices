import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ModelInfo, Provider } from '../types'

import { activateProviderData, calcPrice, updatePrices, waitForUpdate } from '../api'
import { data } from '../data'
import { getActiveModelPrice } from '../engine'
import { parseProviderData } from '../providerData'

afterEach(() => {
  updatePrices(({ setProviderData }) => {
    setProviderData(data)
  })
})

describe('provider array integration', () => {
  it('calculates a dynamic price key with bundled units', async () => {
    updatePrices(({ setProviderData }) => {
      setProviderData(providerArray())
    })
    await expect(waitForUpdate()).resolves.toEqual(providerArray())

    const price = calcPrice(
      {
        cache_image_read_tokens: 1_000_000,
        cache_read_tokens: 1_000_000,
        input_image_tokens: 1_000_000,
        input_tokens: 1_000_000,
      },
      'image-cache',
      {
        providerId: 'testing',
      }
    )

    expect(price?.input_price).toBe(4)
    expect(price?.output_price).toBe(0)
    expect(price?.total_price).toBe(4)
  })

  it.each([
    ['start-date', { start_date: '2025-01-01' }, '2025-01-02T00:00:00Z'],
    ['time-of-day', { end_time: '16:00:00Z', start_time: '08:00:00Z' }, '2025-01-01T12:00:00Z'],
  ])('calculates prices from downloaded %s constraints', async (_name, constraint, timestamp) => {
    const downloadedData: Promise<unknown> = Promise.resolve(downloadedConditionalProviderArray(constraint))
    updatePrices(({ setProviderData }) => {
      setProviderData(downloadedData.then(parseProviderData))
    })
    await waitForUpdate()

    expect(
      calcPrice({ input_tokens: 1_000_000 }, 'conditional-model', {
        providerId: 'testing',
        timestamp: new Date(timestamp),
      })?.input_price
    ).toBe(2)
  })

  it.each([
    ['non-record constraint', 'not-an-object'],
    ['empty constraint', {}],
    ['malformed start_date shape', { start_date: 'not-a-date' }],
    ['impossible calendar date', { start_date: '2025-02-30' }],
    ['out-of-range time-of-day', { end_time: '26:00:00Z', start_time: '25:00:00Z' }],
    ['missing timezone on time-of-day', { end_time: '16:00:00', start_time: '08:00:00' }],
    ['discriminated form with malformed values', { start_date: 'not-a-date', type: 'start_date' }],
    ['mixed start-date/time-of-day constraint', { end_time: '16:00:00Z', start_date: '2025-01-01', start_time: '08:00:00Z' }],
    ['constraint with unknown extra fields', { start_date: '2025-01-01', tz: 'UTC' }],
    ['year-zero start date', { start_date: '0000-01-01' }],
  ])('rejects %s without replacing active data', (_name, constraint) => {
    const stableProviders = providerArray()
    updatePrices(({ setProviderData }) => {
      setProviderData(stableProviders)
    })

    expect(() => activateProviderData(downloadedConditionalProviderArray(constraint))).toThrow(
      "Expected a start-date or time-of-day price constraint for provider 'testing' model 'conditional-model'"
    )
    expect(calcPrice({ input_tokens: 1_000_000 }, 'image-cache', { providerId: 'testing' })?.input_price).toBe(1)
  })

  it('keeps active data and warns when an async update carries malformed constraints', async () => {
    const stableProviders = providerArray()
    updatePrices(({ setProviderData }) => {
      setProviderData(stableProviders)
    })
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    try {
      const malformedData: Promise<unknown> = Promise.resolve(downloadedConditionalProviderArray({}))
      updatePrices(({ setProviderData }) => {
        setProviderData(malformedData.then(parseProviderData))
      })
      await expect(waitForUpdate()).rejects.toThrow('Expected a start-date or time-of-day price constraint')

      expect(calcPrice({ input_tokens: 1_000_000 }, 'image-cache', { providerId: 'testing' })?.input_price).toBe(1)
      expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('keeping previously active data'))
    } finally {
      warnSpy.mockRestore()
    }
  })

  it('normalizes wire-format constraints at activation', () => {
    const [provider] = activateProviderData(downloadedConditionalProviderArray({ start_date: '2025-01-01' }))
    if (provider === undefined) throw new Error('Expected a provider')

    expect(
      calcPrice({ input_tokens: 1_000_000 }, 'conditional-model', {
        provider,
        timestamp: new Date('2025-01-02T00:00:00Z'),
      })?.input_price
    ).toBe(2)
  })

  it('rejects malformed wire-format constraints at activation', () => {
    expect(() => activateProviderData(downloadedConditionalProviderArray({ start_date: 'not-a-date' }))).toThrow(
      "Expected a start-date or time-of-day price constraint for provider 'testing' model 'conditional-model'"
    )
  })

  it('rejects nested malformed provider data', () => {
    expect(() => parseProviderData([{ api_pattern: 'testing', id: 'testing', models: null, name: 'Testing' }])).toThrow(
      'providers[0].models must be an array'
    )
  })

  it('rejects invalid regular expressions before provider activation', () => {
    expect(() => parseProviderData(downloadedProviderArray({ input_mtok: 1 }, { regex: '(' }))).toThrow(
      'providers[0].models[0].match.regex must be a valid regular expression'
    )
  })

  it.each([
    ['negative flat price', -1, 'prices.input_mtok must be a finite non-negative number'],
    ['non-finite flat price', Number.POSITIVE_INFINITY, 'prices.input_mtok must be a finite non-negative number'],
    ['negative tier base', { base: -1, tiers: [] }, 'prices.input_mtok.base must be a finite non-negative number'],
    [
      'negative tier price',
      { base: 1, tiers: [{ price: -1, start: 1 }] },
      'prices.input_mtok.tiers[0].price must be a finite non-negative number',
    ],
    [
      'negative tier start',
      { base: 1, tiers: [{ price: 1, start: -1 }] },
      'prices.input_mtok.tiers[0].start must be a non-negative safe integer',
    ],
    [
      'fractional tier start',
      { base: 1, tiers: [{ price: 1, start: 0.5 }] },
      'prices.input_mtok.tiers[0].start must be a non-negative safe integer',
    ],
  ])('rejects %s before provider activation', (_name, price, message) => {
    expect(() => parseProviderData(downloadedProviderArray({ input_mtok: price }))).toThrow(message)
  })

  it.each([
    ['provider', Array<unknown>(1), 'providers[0] must not be empty'],
    [
      'model',
      [{ api_pattern: 'testing', id: 'testing', models: Array<unknown>(1), name: 'Testing' }],
      'providers[0].models[0] must not be empty',
    ],
    ['conditional price', downloadedProviderArray(Array<unknown>(1)), 'providers[0].models[0].prices[0] must not be empty'],
  ])('rejects a sparse %s array before provider activation', (_name, providerData, message) => {
    expect(() => parseProviderData(providerData)).toThrow(message)
  })

  it('re-activates the bundled data unchanged (round-trips already-discriminated constraints)', async () => {
    updatePrices(({ setProviderData }) => {
      setProviderData(data)
    })
    await expect(waitForUpdate()).resolves.toEqual(data)
  })

  it('activates every conditional price in the published v2 data', () => {
    const v2Data: unknown = JSON.parse(readFileSync(new URL('../../../../prices/new_data/v2/data.json', import.meta.url), 'utf8'))
    const activeData = activateProviderData(v2Data)
    const conditionalModels: ModelInfo[] = []
    for (const provider of activeData) {
      for (const model of provider.models) {
        if (Array.isArray(model.prices)) conditionalModels.push(model)
      }
    }

    expect(conditionalModels.length).toBeGreaterThan(0)
    for (const model of conditionalModels) {
      // Reaching into engine internals is deliberate here: it is the cheapest
      // way to sweep every conditional model in the published artifact.
      expect(() => getActiveModelPrice(model, new Date('2026-08-01T12:00:00Z'))).not.toThrow()
    }
  })
})

function providerArray(): Provider[] {
  return [
    {
      api_pattern: 'testing',
      id: 'testing',
      models: [
        {
          id: 'image-cache',
          match: { equals: 'image-cache' },
          prices: {
            cache_image_read_mtok: 4,
            cache_read_mtok: 2,
            input_image_mtok: 3,
            input_mtok: 1,
          },
        },
      ],
      name: 'Testing',
    },
  ]
}

function downloadedConditionalProviderArray(constraint: unknown) {
  return [
    {
      api_pattern: 'testing',
      id: 'testing',
      models: [
        {
          id: 'conditional-model',
          match: { equals: 'conditional-model' },
          prices: [
            { prices: { input_mtok: 1 } },
            {
              constraint,
              prices: { input_mtok: 2 },
            },
          ],
        },
      ],
      name: 'Testing',
    },
  ]
}

function downloadedProviderArray(prices: unknown, match: unknown = { equals: 'downloaded-model' }) {
  return [
    {
      api_pattern: 'testing',
      id: 'testing',
      models: [
        {
          id: 'downloaded-model',
          match,
          prices,
        },
      ],
      name: 'Testing',
    },
  ]
}
