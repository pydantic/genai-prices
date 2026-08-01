import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it } from 'vitest'

import type { ModelInfo, Provider } from '../types'

import { calcPrice, updatePrices, waitForUpdate } from '../api'
import { data } from '../data'
import { getActiveModelPrice } from '../engine'

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
    updatePrices(({ setProviderData }) => {
      setProviderData(downloadedConditionalProviderArray(constraint))
    })
    await waitForUpdate()

    expect(
      calcPrice({ input_tokens: 1_000_000 }, 'conditional-model', {
        providerId: 'testing',
        timestamp: new Date(timestamp),
      })?.input_price
    ).toBe(2)
  })

  it('rejects malformed downloaded constraints without replacing active data', () => {
    const stableProviders = providerArray()
    updatePrices(({ setProviderData }) => {
      setProviderData(stableProviders)
    })

    expect(() => {
      updatePrices(({ setProviderData }) => {
        setProviderData(downloadedConditionalProviderArray({}))
      })
    }).toThrow('Expected a start-date or time-of-day price constraint')
    expect(calcPrice({ input_tokens: 1_000_000 }, 'image-cache', { providerId: 'testing' })?.input_price).toBe(1)
  })

  it('activates every conditional price in the published v2 data', async () => {
    const v2Data = JSON.parse(readFileSync(new URL('../../../../prices/new_data/v2/data.json', import.meta.url), 'utf8')) as Provider[]
    updatePrices(({ setProviderData }) => {
      setProviderData(v2Data)
    })

    const activeData = await waitForUpdate()
    if (activeData === null) throw new Error('Expected v2 provider data to be active')
    const conditionalModels: ModelInfo[] = []
    for (const provider of activeData) {
      for (const model of provider.models) {
        if (Array.isArray(model.prices)) conditionalModels.push(model)
      }
    }

    expect(conditionalModels.length).toBeGreaterThan(0)
    for (const model of conditionalModels) {
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

function downloadedConditionalProviderArray(constraint: Record<string, string>): Provider[] {
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
  ] as unknown as Provider[]
}
