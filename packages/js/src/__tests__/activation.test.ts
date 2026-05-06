import { describe, expect, it } from 'vitest'

import type { Provider } from '../types'

import { findProvider, updatePrices, waitForUpdate } from '../api'
import { data } from '../data'

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
