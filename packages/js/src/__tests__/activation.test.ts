import { describe, expect, it } from 'vitest'

import type { Provider } from '../types'

import { calcPrice, findProvider, updatePrices, waitForUpdate } from '../api'
import { data } from '../data'
import { getUnit } from '../units'

describe('provider activation', () => {
  it('validates embedded provider data during startup and keeps it active', () => {
    expect(findProvider({ providerId: 'anthropic' })?.id).toBe('anthropic')
  })

  it('validates synchronous custom provider data before replacing active data', async () => {
    const validProvider = providerFixture('valid-provider')
    updatePrices(({ setProviderData }) => {
      setProviderData([validProvider])
    })
    await expect(waitForUpdate()).resolves.toEqual([validProvider])
    expect(findProvider({ providerId: 'valid-provider' })?.id).toBe('valid-provider')

    expect(() => {
      updatePrices(({ setProviderData }) => {
        setProviderData([providerFixture('invalid-provider', 'input_mtok')])
      })
    }).toThrow('Invalid extractor destination for invalid-provider/default mapping 0: input_mtok')
    expect(findProvider({ providerId: 'valid-provider' })?.id).toBe('valid-provider')

    updatePrices(({ setProviderData }) => {
      setProviderData(data)
    })
  })

  it('validates asynchronous custom provider data before replacing active data', async () => {
    const asyncProvider = providerFixture('async-provider')
    updatePrices(({ setProviderData }) => {
      setProviderData(Promise.resolve([asyncProvider]))
    })

    await expect(waitForUpdate()).resolves.toEqual([asyncProvider])
    expect(findProvider({ providerId: 'async-provider' })?.id).toBe('async-provider')

    updatePrices(({ setProviderData }) => {
      setProviderData(Promise.resolve(null))
    })
    await expect(waitForUpdate()).resolves.toEqual([asyncProvider])
    expect(findProvider({ providerId: 'async-provider' })?.id).toBe('async-provider')

    updatePrices(({ setProviderData }) => {
      setProviderData(Promise.resolve([providerFixture('invalid-async-provider', 'requests')]))
    })
    await expect(waitForUpdate()).rejects.toThrow('Invalid extractor destination for invalid-async-provider/default mapping 0: requests')
    expect(findProvider({ providerId: 'async-provider' })?.id).toBe('async-provider')
    await expect(waitForUpdate()).resolves.toEqual([asyncProvider])

    updatePrices(({ setProviderData }) => {
      setProviderData(data)
    })
  })

  it('preserves provider-array update compatibility and the generated unit registry', async () => {
    const beforeInputUnit = getUnit('input_tokens')
    const arrayProvider = providerFixture('array-provider')

    updatePrices(({ setProviderData }) => {
      setProviderData([arrayProvider])
    })

    await expect(waitForUpdate()).resolves.toEqual([arrayProvider])
    expect(findProvider({ providerId: 'array-provider' })?.id).toBe('array-provider')
    expect(getUnit('input_tokens')).toBe(beforeInputUnit)
    expect(getUnit('requests').priceKey).toBe('requests_kcount')

    updatePrices(({ setProviderData }) => {
      setProviderData(data)
    })
  })

  it('activates providers with invalid model prices and rejects them at price time', async () => {
    const provider = providerFixture('invalid-price-provider')
    provider.models = [
      {
        id: 'bad-model',
        match: { equals: 'bad-model' },
        prices: {
          cache_read_mtok: 0.1,
        },
      },
    ]

    updatePrices(({ setProviderData }) => {
      setProviderData([provider])
    })

    await expect(waitForUpdate()).resolves.toEqual([provider])
    expect(findProvider({ providerId: 'invalid-price-provider' })?.id).toBe('invalid-price-provider')
    expect(() => calcPrice({ cache_read_tokens: 100 }, 'bad-model', { providerId: 'invalid-price-provider' })).toThrow(
      'Missing ancestor price key input_mtok for cache_read_mtok'
    )

    updatePrices(({ setProviderData }) => {
      setProviderData(data)
    })
  })
})

function providerFixture(providerId: string, dest = 'input_tokens'): Provider {
  return {
    api_pattern: 'https://example.com',
    extractors: [
      {
        api_flavor: 'default',
        mappings: [
          {
            dest,
            path: 'input_tokens',
            required: true,
          },
        ],
        model_path: 'model',
        root: 'usage',
      },
    ],
    id: providerId,
    models: [],
    name: providerId,
  }
}
