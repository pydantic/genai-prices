import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it } from 'vitest'

import type { WrappedProviderData } from '../types'

import { calcPrice, findProvider, updatePrices, waitForUpdate } from '../api'
import { data } from '../data'
import { extractUsage } from '../extractUsage'
import { getActiveRegistry, setActiveRegistry } from '../units'

afterEach(() => {
  setActiveRegistry()
  updatePrices(({ setProviderData }) => {
    setProviderData(data)
  })
})

describe('remote unit parity fixture', () => {
  it('activates, extracts, prices, matches, and rejects an invalid replacement atomically', async () => {
    const wrapped = readFixture()

    updatePrices(({ setProviderData }) => {
      setProviderData(wrapped)
    })
    await expect(waitForUpdate()).resolves.toHaveLength(1)

    const provider = findProvider({ providerId: 'remote-alias' })
    expect(provider?.id).toBe('remote-fixture')
    if (provider === undefined) throw new Error('Expected remote fixture provider')
    const extracted = extractUsage(provider, { model: 'remote-model', usage: { events: 500 } })
    expect(extracted).toEqual({ model: 'remote-model', usage: { remote_events: 500 } })

    const calculation = calcPrice({ remote_events: 500 }, 'remote-model', { providerId: 'remote-alias' })
    expect(calculation?.provider.id).toBe('remote-fixture')
    expect(calculation?.model.id).toBe('remote-model')
    expect(calculation?.input_price).toBe(1)
    expect(calculation?.output_price).toBe(0)
    expect(calculation?.total_price).toBe(1)

    const activeRegistry = getActiveRegistry()
    const invalid = structuredClone(wrapped)
    delete invalid.units.input_tokens
    expect(() => {
      updatePrices(({ setProviderData }) => {
        setProviderData(invalid)
      })
    }).toThrow('genai-prices: invalid data: removed published unit: input_tokens')

    expect(getActiveRegistry()).toBe(activeRegistry)
    expect(findProvider({ providerId: 'remote-alias' })).toBe(provider)
    expect(calcPrice({ remote_events: 500 }, 'remote-model', { providerId: 'remote-alias' })?.total_price).toBe(1)
  })
})

function readFixture(): WrappedProviderData {
  return JSON.parse(readFileSync(new URL('../../../../tests/fixtures/remote-unit-v3.json', import.meta.url), 'utf8')) as WrappedProviderData
}
