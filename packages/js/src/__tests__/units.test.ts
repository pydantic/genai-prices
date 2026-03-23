import { describe, expect, it } from 'vitest'

import { FIELD_TO_UNIT, getFamily, getUnit, TOKENS_FAMILY } from '../units'

describe('Unit Registry', () => {
  it('should load the tokens family', () => {
    const family = getFamily('tokens')
    expect(family.id).toBe('tokens')
    expect(family.per).toBe(1_000_000)
  })

  it('should have 20 token units', () => {
    const family = getFamily('tokens')
    expect(Object.keys(family.units)).toHaveLength(20)
  })

  it('should look up a unit by ID', () => {
    const unit = getUnit('input_mtok')
    expect(unit.familyId).toBe('tokens')
    expect(unit.usageKey).toBe('input_tokens')
    expect(unit.dimensions).toEqual({ direction: 'input' })
  })

  it('should throw on unknown unit', () => {
    expect(() => getUnit('nonexistent')).toThrow()
  })

  it('should throw on unknown family', () => {
    expect(() => getFamily('nonexistent')).toThrow()
  })

  it('should have all 7 currently-used units', () => {
    for (const unitId of [
      'input_mtok',
      'output_mtok',
      'cache_read_mtok',
      'cache_write_mtok',
      'input_audio_mtok',
      'cache_read_audio_mtok',
      'output_audio_mtok',
    ]) {
      expect(TOKENS_FAMILY.units[unitId]).toBeDefined()
    }
  })

  it('should map cache_audio_read_mtok field to cache_read_audio_mtok unit', () => {
    expect(FIELD_TO_UNIT.cache_audio_read_mtok).toBe('cache_read_audio_mtok')
  })

  it('should have correct usage_key for cache_read_audio_mtok', () => {
    const unit = getUnit('cache_read_audio_mtok')
    expect(unit.usageKey).toBe('cache_audio_read_tokens')
  })

  it('should validate all unit dimensions against family dimensions', () => {
    const family = getFamily('tokens')
    for (const unit of Object.values(family.units)) {
      for (const [dimKey, dimVal] of Object.entries(unit.dimensions)) {
        expect(family.dimensions[dimKey]).toBeDefined()
        expect(family.dimensions[dimKey]).toContain(dimVal)
      }
    }
  })
})
