import { describe, expect, it } from 'vitest'

import type { Provider } from '../types'

import { calcPrice, updatePrices, waitForUpdate } from '../api'
import { data } from '../data'

describe('provider array integration', () => {
  it('calculates a dynamic price key with bundled units', async () => {
    try {
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
    } finally {
      updatePrices(({ setProviderData }) => {
        setProviderData(data)
      })
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
