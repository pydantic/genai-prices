import { describe, expect, it } from 'vitest'

import type { Provider, ProviderDataValue } from '../types'

import { calcPrice, findProvider, updatePrices, waitForUpdate } from '../api'
import { data } from '../data'
import { getActiveRegistry } from '../units'

describe('provider activation', () => {
  it('passes the v2 provider-array URL to the storage factory', () => {
    let remoteDataUrl: string | undefined

    updatePrices((options) => {
      remoteDataUrl = options.remoteDataUrl
    })

    expect(remoteDataUrl).toBe('https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/data_v2.json')
  })

  it('validates embedded provider data during startup and keeps it active', () => {
    expect(findProvider({ providerId: 'anthropic' })?.id).toBe('anthropic')
  })

  it('validates synchronous custom provider data before replacing active data', async () => {
    const registry = getActiveRegistry()
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
    expect(getActiveRegistry()).toBe(registry)

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

  it('does not let a stale rejected async update hide a newer in-flight update', async () => {
    let rejectStale!: (error: Error) => void
    let resolveNewer!: (data: ProviderDataValue) => void
    const staleUpdate = new Promise<ProviderDataValue>((_resolve, reject) => {
      rejectStale = reject
    })
    const newerUpdate = new Promise<ProviderDataValue>((resolve) => {
      resolveNewer = resolve
    })

    updatePrices(({ setProviderData }) => {
      setProviderData(staleUpdate)
    })
    const stalePromise = waitForUpdate()

    updatePrices(({ setProviderData }) => {
      setProviderData(newerUpdate)
    })
    const newerPromise = waitForUpdate()

    rejectStale(new Error('stale update failed'))
    await expect(stalePromise).rejects.toThrow('stale update failed')
    expect(waitForUpdate()).toBe(newerPromise)

    const newerProvider = providerFixture('newer-provider')
    resolveNewer([newerProvider])
    await expect(newerPromise).resolves.toEqual([newerProvider])
    expect(findProvider({ providerId: 'newer-provider' })?.id).toBe('newer-provider')

    updatePrices(({ setProviderData }) => {
      setProviderData(data)
    })
  })

  it('preserves provider-array update compatibility and the generated unit registry', async () => {
    const beforeRegistry = getActiveRegistry()
    const beforeInputUnit = beforeRegistry.getUnit('input_tokens')
    const arrayProvider = providerFixture('array-provider')

    updatePrices(({ setProviderData }) => {
      setProviderData([arrayProvider])
    })

    await expect(waitForUpdate()).resolves.toEqual([arrayProvider])
    expect(findProvider({ providerId: 'array-provider' })?.id).toBe('array-provider')
    expect(getActiveRegistry()).toBe(beforeRegistry)
    expect(getActiveRegistry().getUnit('input_tokens')).toBe(beforeInputUnit)
    expect(getActiveRegistry().getUnit('requests')?.priceKey).toBe('requests_kcount')

    updatePrices(({ setProviderData }) => {
      setProviderData(data)
    })
  })

  it('keeps providers and the generated registry unchanged when provider data is null', () => {
    const stableProvider = providerFixture('stable-provider')
    updatePrices(({ setProviderData }) => {
      setProviderData([stableProvider])
    })
    const registry = getActiveRegistry()

    updatePrices(({ setProviderData }) => {
      setProviderData(null)
    })

    expect(findProvider({ providerId: 'stable-provider' })?.id).toBe('stable-provider')
    expect(getActiveRegistry()).toBe(registry)

    updatePrices(({ setProviderData }) => {
      setProviderData(data)
    })
  })

  it('throws for invalid provider data payload shapes', () => {
    const stableProvider = providerFixture('stable-provider')
    updatePrices(({ setProviderData }) => {
      setProviderData([stableProvider])
    })
    const registry = getActiveRegistry()

    expect(() => {
      updatePrices(({ setProviderData }) => {
        setProviderData('garbage' as unknown as ProviderDataValue)
      })
    }).toThrow('Expected null or Provider[]')
    expect(findProvider({ providerId: 'stable-provider' })?.id).toBe('stable-provider')
    expect(getActiveRegistry()).toBe(registry)

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
