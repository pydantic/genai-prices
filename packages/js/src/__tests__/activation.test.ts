import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Provider, ProviderDataValue, WireProvider } from '../types'

import { calcPrice, findProvider, updatePrices, waitForUpdate } from '../api'
import { data } from '../data'
import { unitData } from '../dataUnits'
import { extractUsage } from '../extractUsage'
import { activateRuntimeData, bundledRuntimeData, getRuntimeData } from '../runtimeState'
import { getActiveRegistry } from '../units'

afterEach(() => {
  activateRuntimeData(bundledRuntimeData)
  vi.restoreAllMocks()
})

describe('provider activation', () => {
  it('passes the wrapped v2 URL to the storage factory', () => {
    let remoteDataUrl: string | undefined

    updatePrices((options) => {
      remoteDataUrl = options.remoteDataUrl
    })

    expect(remoteDataUrl).toBe('https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/data_v2.json')
  })

  it('validates embedded provider data during startup and keeps it active', () => {
    expect(findProvider({ providerId: 'anthropic' })?.id).toBe('anthropic')
  })

  it('warns for unsupported synchronous extractor destinations and activates the data', async () => {
    const registry = getActiveRegistry()
    const validProvider = providerFixture('valid-provider')
    updatePrices(({ setProviderData }) => {
      setProviderData([validProvider])
    })
    await expect(waitForUpdate()).resolves.toEqual([validProvider])
    expect(findProvider({ providerId: 'valid-provider' })?.id).toBe('valid-provider')

    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const provider = providerFixture('future-provider', 'future_tokens')
    updatePrices(({ setProviderData }) => {
      setProviderData([provider])
    })
    const projected = await waitForUpdate()
    expect(projected[0]?.extractors?.[0]?.mappings).toEqual([])
    expect(warn).toHaveBeenCalledWith('Unsupported extractor destination for standard extraction: future_tokens')
    expect(findProvider({ providerId: 'future-provider' })?.id).toBe('future-provider')
    const activeProvider = findProvider({ providerId: 'future-provider' })
    if (!activeProvider) throw new Error('Expected active future provider')
    expect(extractUsage(activeProvider, { model: 'future-model', usage: {} })).toEqual({
      model: 'future-model',
      usage: {},
    })
    expect(warn).toHaveBeenCalledTimes(1)
    expect(getActiveRegistry()).toBe(registry)
    warn.mockRestore()

    updatePrices(({ setProviderData }) => {
      setProviderData(data)
    })
  })

  it('warns for unsupported asynchronous extractor destinations and activates the data', async () => {
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

    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const provider = providerFixture('future-async-provider', 'future_tokens')
    updatePrices(({ setProviderData }) => {
      setProviderData(Promise.resolve([provider]))
    })
    const projected = await waitForUpdate()
    expect(projected[0]?.extractors?.[0]?.mappings).toEqual([])
    expect(warn).toHaveBeenCalledWith('Unsupported extractor destination for standard extraction: future_tokens')
    expect(findProvider({ providerId: 'future-async-provider' })?.id).toBe('future-async-provider')
    warn.mockRestore()

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

  it('lets a later null update supersede an older pending update without replacing state', async () => {
    const stableProvider = providerFixture('stable-provider')
    updatePrices(({ setProviderData }) => {
      setProviderData([stableProvider])
    })
    const stableState = getRuntimeData()

    let resolveStale!: (data: ProviderDataValue) => void
    const staleUpdate = new Promise<ProviderDataValue>((resolve) => {
      resolveStale = resolve
    })
    updatePrices(({ setProviderData }) => {
      setProviderData(staleUpdate)
    })
    const stalePromise = waitForUpdate()

    updatePrices(({ setProviderData }) => {
      setProviderData(null)
    })
    await expect(waitForUpdate()).resolves.toEqual([stableProvider])

    resolveStale([providerFixture('stale-provider')])
    await expect(stalePromise).resolves.toEqual([stableProvider])
    expect(getRuntimeData()).toBe(stableState)
  })

  it('lets a later failed update supersede an older pending update without replacing state', async () => {
    const stableProvider = providerFixture('stable-provider')
    updatePrices(({ setProviderData }) => {
      setProviderData([stableProvider])
    })
    const stableState = getRuntimeData()

    let resolveStale!: (data: ProviderDataValue) => void
    let rejectNewer!: (error: Error) => void
    const staleUpdate = new Promise<ProviderDataValue>((resolve) => {
      resolveStale = resolve
    })
    const newerUpdate = new Promise<ProviderDataValue>((_resolve, reject) => {
      rejectNewer = reject
    })
    updatePrices(({ setProviderData }) => {
      setProviderData(staleUpdate)
    })
    const stalePromise = waitForUpdate()
    updatePrices(({ setProviderData }) => {
      setProviderData(newerUpdate)
    })
    const newerPromise = waitForUpdate()

    rejectNewer(new Error('newer update failed'))
    await expect(newerPromise).rejects.toThrow('newer update failed')
    resolveStale([providerFixture('stale-provider')])
    await expect(stalePromise).resolves.toEqual([stableProvider])
    expect(getRuntimeData()).toBe(stableState)
  })

  it('activates a wrapped registry and matching providers as one state', async () => {
    const units = {
      ...unitData,
      widgets: {
        dimensions: { family: 'widgets' },
        per: 1_000,
        price_key: 'widget_kcount',
      },
    }
    const provider: WireProvider = {
      api_pattern: 'testing',
      id: 'testing',
      models: [
        {
          id: 'widget-model',
          match: { equals: 'widget-model' },
          prices: { widget_kcount: 2 },
        },
      ],
      name: 'Testing',
    }

    updatePrices(({ setProviderData }) => {
      setProviderData({ providers: [provider], units })
    })

    await expect(waitForUpdate()).resolves.toEqual([provider])
    const state = getRuntimeData()
    expect(state.registry.getUnit('widgets')?.priceKey).toBe('widget_kcount')
    expect(state.providers[0]?.id).toBe('testing')
    expect(calcPrice({ widgets: 2_000 }, 'widget-model', { providerId: 'testing' })?.total_price).toBe(4)
  })

  it('preserves provider-array update compatibility and the generated unit registry', async () => {
    const beforeState = getRuntimeData()
    const beforeRegistry = getActiveRegistry()
    const beforeInputUnit = beforeRegistry.getUnit('input_tokens')
    const arrayProvider = providerFixture('array-provider')

    updatePrices(({ setProviderData }) => {
      setProviderData([arrayProvider])
    })

    await expect(waitForUpdate()).resolves.toEqual([arrayProvider])
    expect(getRuntimeData()).not.toBe(beforeState)
    expect(getRuntimeData()).toEqual({ providers: [arrayProvider], registry: beforeRegistry })
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
    }).toThrow('Expected v2 payload to be an object')
    expect(findProvider({ providerId: 'stable-provider' })?.id).toBe('stable-provider')
    expect(getActiveRegistry()).toBe(registry)

    updatePrices(({ setProviderData }) => {
      setProviderData(data)
    })
  })

  it('rejects providers with invalid recognized price coverage before activation', () => {
    const before = getRuntimeData()
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

    expect(() => {
      updatePrices(({ setProviderData }) => {
        setProviderData([provider])
      })
    }).toThrow('Invalid price coverage for invalid-price-provider/bad-model: Missing ancestor price key input_mtok for cache_read_mtok')
    expect(getRuntimeData()).toBe(before)
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
