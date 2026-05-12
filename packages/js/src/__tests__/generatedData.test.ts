import { describe, expect, it } from 'vitest'

import * as providerDataModule from '../data'
import { unitFamiliesData } from '../dataUnits'
import { UnitRegistry } from '../units'

const tokenUsageKeys = [
  'input_tokens',
  'output_tokens',
  'cache_read_tokens',
  'cache_write_tokens',
  'input_text_tokens',
  'output_text_tokens',
  'cache_text_read_tokens',
  'cache_text_write_tokens',
  'input_audio_tokens',
  'output_audio_tokens',
  'cache_audio_read_tokens',
  'cache_audio_write_tokens',
  'input_image_tokens',
  'output_image_tokens',
  'cache_image_read_tokens',
  'cache_image_write_tokens',
  'input_video_tokens',
  'output_video_tokens',
  'cache_video_read_tokens',
  'cache_video_write_tokens',
]

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

    expect(new Set(Object.keys(tokenFamily.units))).toEqual(new Set(tokenUsageKeys))
    expect(new Set(Object.keys(requestFamily.units))).toEqual(new Set(['requests']))
    const requestsUnit = requestFamily.units.requests
    expect(requestsUnit).toBeDefined()
    if (!requestsUnit) throw new Error('Expected generated requests unit')
    expect(requestsUnit.price_key).toBe('requests_kcount')
  })

  it('constructs a runtime UnitRegistry from generated raw unit data', () => {
    const registry = new UnitRegistry(unitFamiliesData)

    expect(registry.units.get('input_tokens')?.priceKey).toBe('input_mtok')
    expect(registry.units.size).toBe(21)
    expect(registry.unitsByPriceKey.get('cache_image_write_mtok')?.usageKey).toBe('cache_image_write_tokens')
    expect(registry.unitsByPriceKey.get('requests_kcount')?.usageKey).toBe('requests')
  })
})
