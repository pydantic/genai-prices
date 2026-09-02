import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Provider, ProviderDataValue, WrappedProviderData } from '../types'

import { findProvider, updatePrices, waitForUpdate } from '../api'
import { data } from '../data'
import { unitData } from '../dataUnits'
import { getActiveRegistry, setActiveRegistry } from '../units'

afterEach(() => {
  setActiveRegistry()
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
        setProviderData('garbage' as unknown as ProviderDataValue)
      })
    }).toThrow('genai-prices: invalid data: root must be a wrapped object or provider array')
    expect(findProvider({ providerId: 'stable-provider' })?.id).toBe('stable-provider')
  })

  it('rejects invalid asynchronous provider data without changing active providers', async () => {
    const stableProvider = providerFixture('stable-provider')
    updatePrices(({ setProviderData }) => {
      setProviderData([stableProvider])
    })

    updatePrices(({ setProviderData }) => {
      setProviderData(Promise.resolve('garbage' as unknown as ProviderDataValue))
    })

    await expect(waitForUpdate()).rejects.toThrow('genai-prices: invalid data: root must be a wrapped object or provider array')
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

  it.each(['direct', 'promised'])('activates %s wrapped providers and units together', async (delivery) => {
    const wrapped = wrappedFixture('wrapped-provider')

    updatePrices(({ setProviderData }) => {
      setProviderData(delivery === 'direct' ? wrapped : Promise.resolve(wrapped))
    })

    await expect(waitForUpdate()).resolves.toEqual(wrapped.providers)
    expect(findProvider({ providerId: 'wrapped-provider' })?.id).toBe('wrapped-provider')
    expect(getActiveRegistry().getUnit('remote_events')?.priceKey).toBe('remote_event_price')
  })

  it('changes only providers when a legacy array follows a wrapped activation', async () => {
    updatePrices(({ setProviderData }) => {
      setProviderData(wrappedFixture('wrapped-provider'))
    })
    const wrappedRegistry = getActiveRegistry()
    const legacyProvider = providerFixture('legacy-provider', 'remote_events')

    updatePrices(({ setProviderData }) => {
      setProviderData([legacyProvider])
    })

    await expect(waitForUpdate()).resolves.toEqual([legacyProvider])
    expect(getActiveRegistry()).toBe(wrappedRegistry)
    expect(findProvider({ providerId: 'legacy-provider' })?.id).toBe('legacy-provider')
  })

  it('leaves the active pair and update promise unchanged after a synchronous contract failure', () => {
    updatePrices(({ setProviderData }) => {
      setProviderData(wrappedFixture('stable-wrapped-provider'))
    })
    const stableRegistry = getActiveRegistry()
    const stableWait = waitForUpdate()
    const invalid = wrappedFixture('invalid-provider')
    delete invalid.units.input_tokens

    expect(() => {
      updatePrices(({ setProviderData }) => {
        setProviderData(invalid)
      })
    }).toThrow('genai-prices: invalid data: removed published unit: input_tokens')
    expect(waitForUpdate()).toBe(stableWait)
    expect(getActiveRegistry()).toBe(stableRegistry)
    expect(findProvider({ providerId: 'stable-wrapped-provider' })?.id).toBe('stable-wrapped-provider')
  })

  it('rejects a wrapped model missing match without changing the active pair', () => {
    updatePrices(({ setProviderData }) => {
      setProviderData(wrappedFixture('stable-wrapped-provider'))
    })
    const stableRegistry = getActiveRegistry()
    const invalid = wrappedFixture('invalid-provider')
    const invalidProvider = invalid.providers[0] as unknown as Record<string, unknown>
    invalidProvider.models = [{ id: 'broken-model', prices: { remote_event_price: 1 } }]

    expect(() => {
      updatePrices(({ setProviderData }) => {
        setProviderData(invalid)
      })
    }).toThrow('genai-prices: invalid data: providers[0].models[0].match is required')
    expect(getActiveRegistry()).toBe(stableRegistry)
    expect(findProvider({ providerId: 'stable-wrapped-provider' })?.id).toBe('stable-wrapped-provider')
  })

  it('leaves the active pair unchanged after an asynchronous contract failure', async () => {
    updatePrices(({ setProviderData }) => {
      setProviderData(wrappedFixture('stable-wrapped-provider'))
    })
    const stableRegistry = getActiveRegistry()
    const invalid = wrappedFixture('invalid-provider')
    delete invalid.units.input_tokens
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    updatePrices(({ setProviderData }) => {
      setProviderData(Promise.resolve(invalid))
    })

    await expect(waitForUpdate()).rejects.toThrow('genai-prices: invalid data: removed published unit: input_tokens')
    expect(getActiveRegistry()).toBe(stableRegistry)
    expect(findProvider({ providerId: 'stable-wrapped-provider' })?.id).toBe('stable-wrapped-provider')
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('keeping previously active data'))
  })

  it('emits compatibility warnings only after the wrapped pair activates', () => {
    const wrapped = wrappedFixture('compatible-subset-provider')
    wrapped.providers[0] = { ...wrapped.providers[0], provider_match: { future_match: 'provider' } } as unknown as Provider
    const observedState: boolean[] = []
    const warn = vi.spyOn(console, 'warn').mockImplementation((message: unknown) => {
      if (String(message).startsWith('Unsupported match variant')) {
        observedState.push(
          findProvider({ providerId: 'compatible-subset-provider' })?.id === 'compatible-subset-provider' &&
            getActiveRegistry().getUnit('remote_events') !== undefined
        )
      }
    })

    updatePrices(({ setProviderData }) => {
      setProviderData(wrapped)
    })

    expect(observedState).toEqual([true])
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('Unsupported match variant at providers[0].provider_match'))
  })

  it('does not decode, activate, or warn for a stale successful wrapped update', async () => {
    let resolveStale!: (data: ProviderDataValue) => void
    let resolveNewer!: (data: ProviderDataValue) => void
    const staleUpdate = new Promise<ProviderDataValue>((resolve) => {
      resolveStale = resolve
    })
    const newerUpdate = new Promise<ProviderDataValue>((resolve) => {
      resolveNewer = resolve
    })
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

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
    const staleWrapped = wrappedFixture('stale-provider')
    staleWrapped.providers[0] = { ...staleWrapped.providers[0], provider_match: { future_match: 'provider' } } as unknown as Provider
    resolveStale(staleWrapped)

    await expect(staleWait).resolves.toEqual([newerProvider])
    expect(getActiveRegistry().getUnit('remote_events')).toBeUndefined()
    expect(findProvider({ providerId: 'stale-provider' })).toBeUndefined()
    expect(warn).not.toHaveBeenCalledWith(expect.stringContaining('Unsupported match variant'))
  })

  it('does not let direct null supersede a pending update', async () => {
    let resolvePending!: (data: ProviderDataValue) => void
    const pending = new Promise<ProviderDataValue>((resolve) => {
      resolvePending = resolve
    })
    updatePrices(({ setProviderData }) => {
      setProviderData(pending)
    })
    const pendingWait = waitForUpdate()

    updatePrices(({ setProviderData }) => {
      setProviderData(null)
    })

    expect(waitForUpdate()).toBe(pendingWait)
    const provider = providerFixture('pending-provider')
    resolvePending([provider])
    await expect(pendingWait).resolves.toEqual([provider])
  })

  it('lets promised null supersede an older pending wrapped update', async () => {
    let resolveStale!: (data: ProviderDataValue) => void
    const stale = new Promise<ProviderDataValue>((resolve) => {
      resolveStale = resolve
    })
    const stableProvider = providerFixture('stable-provider')
    updatePrices(({ setProviderData }) => {
      setProviderData([stableProvider])
      setProviderData(stale)
    })
    const staleWait = waitForUpdate()

    updatePrices(({ setProviderData }) => {
      setProviderData(Promise.resolve(null))
    })
    const nullWait = waitForUpdate()

    await expect(nullWait).resolves.toEqual([stableProvider])
    resolveStale(wrappedFixture('stale-provider'))
    await expect(staleWait).resolves.toEqual([stableProvider])
    expect(getActiveRegistry().getUnit('remote_events')).toBeUndefined()
  })

  it('preserves a caller rejection reason and warns fire-and-forget callers', async () => {
    const reason = { code: 'offline' }
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    updatePrices(({ setProviderData }) => {
      // Deliberately verify the public boundary preserves non-Error rejection reasons.
      // eslint-disable-next-line @typescript-eslint/prefer-promise-reject-errors
      setProviderData(Promise.reject(reason))
    })
    const rejectedWait = waitForUpdate()

    await expect(rejectedWait).rejects.toBe(reason)
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('[object Object]'))
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

function wrappedFixture(providerId: string): WrappedProviderData {
  return {
    providers: [providerFixture(providerId, 'remote_events')],
    units: {
      ...structuredClone(unitData),
      remote_events: {
        dimensions: { family: 'remote_events' },
        per: 1,
        price_key: 'remote_event_price',
      },
    },
  }
}
