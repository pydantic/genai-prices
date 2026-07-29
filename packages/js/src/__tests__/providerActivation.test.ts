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
        setProviderData('garbage' as unknown as ProviderDataValue)
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
      setProviderData(Promise.resolve('garbage' as unknown as ProviderDataValue))
    })

    await expect(waitForUpdate()).rejects.toThrow('Expected null or Provider[]')
    expect(findProvider({ providerId: 'stable-provider' })?.id).toBe('stable-provider')
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
