import { describe, expect, it } from 'vitest'

import type { WrappedProviderData } from '../types'

import { calcPrice, updatePrices, waitForUpdate } from '../api'
import { data } from '../data'
import { setActiveRegistry } from '../units'

describe('wrapped payload integration', () => {
  it('calculates a dynamic price key from wrapped provider data', async () => {
    try {
      updatePrices(({ setProviderData }) => {
        setProviderData(wrappedPayload())
      })
      await expect(waitForUpdate()).resolves.toEqual(wrappedPayload().providers)

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
      setActiveRegistry(null)
      updatePrices(({ setProviderData }) => {
        setProviderData(data)
      })
    }
  })
})

function wrappedPayload(): WrappedProviderData {
  return {
    providers: [
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
    ],
    units: {
      cache_image_read_tokens: {
        dimensions: { cache: 'read', direction: 'input', family: 'tokens', modality: 'image' },
        per: 1_000_000,
        price_key: 'cache_image_read_mtok',
      },
      cache_read_tokens: {
        dimensions: { cache: 'read', direction: 'input', family: 'tokens' },
        per: 1_000_000,
        price_key: 'cache_read_mtok',
      },
      input_image_tokens: {
        dimensions: { direction: 'input', family: 'tokens', modality: 'image' },
        per: 1_000_000,
        price_key: 'input_image_mtok',
      },
      input_tokens: {
        dimensions: { direction: 'input', family: 'tokens' },
        per: 1_000_000,
        price_key: 'input_mtok',
      },
    },
  }
}
