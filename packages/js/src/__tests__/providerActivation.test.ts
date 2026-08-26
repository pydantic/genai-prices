import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Provider, ProviderDataValue } from '../types'

import { findProvider, updatePrices, waitForUpdate } from '../api'
import { data } from '../data'
import { getActiveRegistry } from '../units'

afterEach(() => {
  updatePrices(({ setProviderData }) => {
    setProviderData(data)
  })
  vi.restoreAllMocks()
})

describe('provider activation', () => {
  it('warns for unsupported synchronous extractor destinations and preserves the registry', async () => {
    const registry = getActiveRegistry()
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const provider = providerFixture('future-provider', 'future_tokens')

    updatePrices(({ setProviderData }) => {
      setProviderData([provider])
    })

    await expect(waitForUpdate()).resolves.toEqual([provider])
    expect(warn).toHaveBeenCalledWith('Unsupported extractor destination for standard extraction: future_tokens')
    expect(findProvider({ providerId: 'future-provider' })?.id).toBe('future-provider')
    expect(getActiveRegistry()).toBe(registry)
  })

  it('warns for unsupported asynchronous extractor destinations and preserves the registry', async () => {
    const registry = getActiveRegistry()
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const provider = providerFixture('future-async-provider', 'future_tokens')

    updatePrices(({ setProviderData }) => {
      setProviderData(Promise.resolve([provider]))
    })

    await expect(waitForUpdate()).resolves.toEqual([provider])
    expect(warn).toHaveBeenCalledWith('Unsupported extractor destination for standard extraction: future_tokens')
    expect(findProvider({ providerId: 'future-async-provider' })?.id).toBe('future-async-provider')
    expect(getActiveRegistry()).toBe(registry)
  })

  it('rejects invalid synchronous provider data without changing active providers', () => {
    const stableProvider = providerFixture('stable-provider')
    updatePrices(({ setProviderData }) => {
      setProviderData([stableProvider])
    })

    expect(() => {
      updatePrices(({ setProviderData }) => {
        setProviderData('garbage')
      })
    }).toThrow('Expected null or Provider[]')
    expect(findProvider({ providerId: 'stable-provider' })?.id).toBe('stable-provider')
  })

  it('rejects invalid asynchronous provider data without changing active providers', async () => {
    const stableProvider = providerFixture('stable-provider')
    updatePrices(({ setProviderData }) => {
      setProviderData([stableProvider])
    })

    updatePrices(({ setProviderData }) => {
      setProviderData(Promise.resolve('garbage'))
    })

    await expect(waitForUpdate()).rejects.toThrow('Expected null or Provider[]')
    expect(findProvider({ providerId: 'stable-provider' })?.id).toBe('stable-provider')
  })

  it('keeps active providers when an asynchronous update returns null', async () => {
    const stableProvider = providerFixture('stable-provider')
    updatePrices(({ setProviderData }) => {
      setProviderData([stableProvider])
    })

    updatePrices(({ setProviderData }) => {
      setProviderData(Promise.resolve(null))
    })

    await expect(waitForUpdate()).resolves.toEqual([stableProvider])
    expect(findProvider({ providerId: 'stable-provider' })?.id).toBe('stable-provider')
  })

  it('recovers waitForUpdate after the latest asynchronous update rejects', async () => {
    const stableProvider = providerFixture('stable-provider')
    updatePrices(({ setProviderData }) => {
      setProviderData([stableProvider])
    })

    updatePrices(({ setProviderData }) => {
      setProviderData(Promise.reject(new Error('update failed')))
    })
    const failedWait = waitForUpdate()

    await expect(failedWait).rejects.toThrow('update failed')
    await expect(waitForUpdate()).resolves.toEqual([stableProvider])
  })

  it('does not let a stale rejected update hide a newer in-flight update', async () => {
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
    const staleWait = waitForUpdate()
    updatePrices(({ setProviderData }) => {
      setProviderData(newerUpdate)
    })
    const newerWait = waitForUpdate()

    rejectStale(new Error('stale update failed'))
    await expect(staleWait).rejects.toThrow('stale update failed')
    expect(waitForUpdate()).toBe(newerWait)

    const newerProvider = providerFixture('newer-provider')
    resolveNewer([newerProvider])
    await expect(newerWait).resolves.toEqual([newerProvider])
    expect(findProvider({ providerId: 'newer-provider' })?.id).toBe('newer-provider')
  })

  it('handles a stale rejected update when no caller waited for it', async () => {
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
    updatePrices(({ setProviderData }) => {
      setProviderData(newerUpdate)
    })
    const newerWait = waitForUpdate()

    rejectStale(new Error('unobserved stale update failed'))
    await new Promise<void>((resolve) => {
      setTimeout(resolve, 0)
    })

    const newerProvider = providerFixture('newer-provider')
    resolveNewer([newerProvider])
    await expect(newerWait).resolves.toEqual([newerProvider])
  })

  it('does not let a stale successful update overwrite newer provider data', async () => {
    let resolveStale!: (data: ProviderDataValue) => void
    let resolveNewer!: (data: ProviderDataValue) => void
    const staleUpdate = new Promise<ProviderDataValue>((resolve) => {
      resolveStale = resolve
    })
    const newerUpdate = new Promise<ProviderDataValue>((resolve) => {
      resolveNewer = resolve
    })

    updatePrices(({ setProviderData }) => {
      setProviderData(staleUpdate)
    })
    const staleWait = waitForUpdate()
    updatePrices(({ setProviderData }) => {
      setProviderData(newerUpdate)
    })
    const newerWait = waitForUpdate()

    const newerProvider = providerFixture('newer-provider')
    resolveNewer([newerProvider])
    await expect(newerWait).resolves.toEqual([newerProvider])

    resolveStale([providerFixture('stale-provider')])
    await expect(staleWait).resolves.toEqual([newerProvider])
    expect(waitForUpdate()).toBe(newerWait)
    expect(findProvider({ providerId: 'newer-provider' })?.id).toBe('newer-provider')
    expect(findProvider({ providerId: 'stale-provider' })).toBeUndefined()
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
