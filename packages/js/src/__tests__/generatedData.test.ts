import { describe, expect, it } from 'vitest'

import * as providerDataModule from '../data'
import { unitFamiliesData } from '../dataUnits'
import { UnitRegistry } from '../units'

describe('generated data split', () => {
  it('keeps generated provider data separate from generated unit data', () => {
    expect(providerDataModule).toHaveProperty('data')
    expect(providerDataModule.data.length).toBeGreaterThan(0)
    expect(providerDataModule).not.toHaveProperty('unitFamiliesData')
  })

  it('exposes current JavaScript unit families without the provider list', () => {
    expect(new Set(Object.keys(unitFamiliesData))).toEqual(new Set(['requests', 'tokens']))
    const tokenFamily = unitFamiliesData.tokens
    const requestFamily = unitFamiliesData.requests
    expect(tokenFamily).toBeDefined()
    expect(requestFamily).toBeDefined()
    if (!tokenFamily || !requestFamily) throw new Error('Expected generated token and request families')

    expect(new Set(Object.keys(tokenFamily.units))).toEqual(
      new Set([
        'cache_audio_read_tokens',
        'cache_read_tokens',
        'cache_write_tokens',
        'input_audio_tokens',
        'input_tokens',
        'output_audio_tokens',
        'output_tokens',
      ])
    )
    expect(new Set(Object.keys(requestFamily.units))).toEqual(new Set(['requests']))
    const requestsUnit = requestFamily.units.requests
    expect(requestsUnit).toBeDefined()
    if (!requestsUnit) throw new Error('Expected generated requests unit')
    expect(requestsUnit.price_key).toBe('requests_kcount')
  })

  it('constructs a runtime UnitRegistry from generated raw unit data', () => {
    const registry = new UnitRegistry(unitFamiliesData)

    expect(registry.units.get('input_tokens')?.priceKey).toBe('input_mtok')
    expect(registry.unitsByPriceKey.get('requests_kcount')?.usageKey).toBe('requests')
  })
})
