import { describe, expect, it } from 'vitest'

import * as providerDataModule from '../data'
import { unitFamiliesData } from '../dataUnits'

describe('generated data split', () => {
  it('keeps generated provider data separate from generated unit data', () => {
    expect(Object.keys(providerDataModule)).toEqual(['data'])
    expect(providerDataModule.data.length).toBeGreaterThan(0)
    expect(providerDataModule).not.toHaveProperty('unitFamiliesData')
  })

  it('exposes current JavaScript unit families without the provider list', () => {
    expect(Object.keys(unitFamiliesData)).toEqual(['requests', 'tokens'])
    const tokenFamily = unitFamiliesData.tokens
    const requestFamily = unitFamiliesData.requests
    expect(tokenFamily).toBeDefined()
    expect(requestFamily).toBeDefined()
    if (!tokenFamily || !requestFamily) throw new Error('Expected generated token and request families')

    expect(Object.keys(tokenFamily.units)).toEqual([
      'cache_audio_read_tokens',
      'cache_read_tokens',
      'cache_write_tokens',
      'input_audio_tokens',
      'input_tokens',
      'output_audio_tokens',
      'output_tokens',
    ])
    expect(Object.keys(requestFamily.units)).toEqual(['requests'])
    const requestsUnit = requestFamily.units.requests
    expect(requestsUnit).toBeDefined()
    if (!requestsUnit) throw new Error('Expected generated requests unit')
    expect(requestsUnit.price_key).toBe('requests_kcount')
  })
})
