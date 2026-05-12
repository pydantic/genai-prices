import { describe, expect, it } from 'vitest'

import type { RawFamiliesDict } from '../types'

import { unitFamiliesData } from '../dataUnits'
import {
  getActiveRegistry,
  getAllPriceKeys,
  getAllUsageKeys,
  getFamily,
  getUnit,
  getUnitForPriceKey,
  getUsageKeyForPriceKey,
  setActiveRegistry,
  UnitRegistry,
} from '../units'

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

const tokenPriceKeys = [
  'input_mtok',
  'output_mtok',
  'cache_read_mtok',
  'cache_write_mtok',
  'input_text_mtok',
  'output_text_mtok',
  'cache_text_read_mtok',
  'cache_text_write_mtok',
  'input_audio_mtok',
  'output_audio_mtok',
  'cache_audio_read_mtok',
  'cache_audio_write_mtok',
  'input_image_mtok',
  'output_image_mtok',
  'cache_image_read_mtok',
  'cache_image_write_mtok',
  'input_video_mtok',
  'output_video_mtok',
  'cache_video_read_mtok',
  'cache_video_write_mtok',
]

describe('UnitRegistry', () => {
  it('constructs generated unit families into indexed runtime objects', () => {
    const registry = new UnitRegistry(unitFamiliesData)
    const tokenFamily = registry.families.tokens
    const requestFamily = registry.families.requests
    expect(tokenFamily).toBeDefined()
    expect(requestFamily).toBeDefined()
    if (!tokenFamily || !requestFamily) throw new Error('Expected generated unit families')

    expect(tokenFamily).toMatchObject({
      description: 'Token counts',
      id: 'tokens',
      per: 1_000_000,
    })
    expect(new Set(Object.keys(tokenFamily.units))).toEqual(new Set(tokenUsageKeys))
    expect(requestFamily.units.requests?.priceKey).toBe('requests_kcount')
    expect(registry.units.get('input_tokens')).toBe(tokenFamily.units.input_tokens)
    expect(registry.units.size).toBe(21)
    expect(registry.unitsByPriceKey.get('input_mtok')).toBe(tokenFamily.units.input_tokens)
    expect(registry.unitsByPriceKey.get('cache_image_write_mtok')?.usageKey).toBe('cache_image_write_tokens')
    expect(registry.allUsageKeys).toContain('input_tokens')
    expect(registry.allPriceKeys).toContain('input_mtok')
    expect(registry.reportedUsageKeys).toContain('input_tokens')
    expect(registry.reportedUsageKeys).not.toContain('requests')
  })

  it('defaults missing price keys to the usage key', () => {
    const registry = new UnitRegistry({
      widgets: {
        description: 'Widget counts',
        per: 1,
        units: {
          widgets: {
            dimensions: {},
          },
        },
      },
    })

    expect(registry.families.widgets?.units.widgets?.priceKey).toBe('widgets')
    expect(registry.unitsByPriceKey.get('widgets')).toBe(registry.units.get('widgets'))
  })

  it('links units back to their family and fills dimension lookup state', () => {
    const registry = new UnitRegistry(unitFamiliesData)
    const tokenFamily = registry.families.tokens
    expect(tokenFamily).toBeDefined()
    if (!tokenFamily) throw new Error('Expected generated token family')

    const inputAudio = tokenFamily.units.input_audio_tokens
    expect(inputAudio).toBeDefined()
    if (!inputAudio) throw new Error('Expected input_audio_tokens')

    expect(inputAudio.family).toBe(tokenFamily)
    expect(inputAudio.familyId).toBe('tokens')
    expect(tokenFamily.unitsByDimension.get('direction=input\0modality=audio')).toBe(inputAudio)
  })

  it('indexes ancestor usage keys', () => {
    const registry = new UnitRegistry(unitFamiliesData)

    expect(registry.ancestorUsageKeys('cache_audio_read_tokens')).toEqual(
      new Set(['cache_read_tokens', 'input_audio_tokens', 'input_tokens'])
    )
    expect(registry.ancestorUsageKeysByUsageKey.get('requests')).toEqual(new Set())
  })

  it('keeps construction independent of generated data fixtures', () => {
    const raw: RawFamiliesDict = {
      calls: {
        description: 'Call counts',
        per: 100,
        units: {
          billable_calls: {
            dimensions: {
              class: 'billable',
            },
            price_key: 'billable_call_count',
          },
        },
      },
    }

    const unit = new UnitRegistry(raw).families.calls?.units.billable_calls
    expect(unit).toMatchObject({
      dimensions: { class: 'billable' },
      familyId: 'calls',
      priceKey: 'billable_call_count',
      usageKey: 'billable_calls',
    })
  })
})

describe('active unit registry', () => {
  it('initializes from generated unit data', () => {
    const active = getActiveRegistry()
    expect(active.families.tokens?.units.input_tokens?.priceKey).toBe('input_mtok')
    expect(active.families.requests?.units.requests?.priceKey).toBe('requests_kcount')
  })

  it('sets custom registries and resets to the generated registry', () => {
    const generated = getActiveRegistry()
    const custom = new UnitRegistry({
      widgets: {
        description: 'Widget counts',
        per: 1,
        units: {
          widgets: {
            dimensions: {},
          },
        },
      },
    })

    setActiveRegistry(custom)
    expect(getActiveRegistry()).toBe(custom)
    expect(getActiveRegistry().families.widgets?.units.widgets?.priceKey).toBe('widgets')

    setActiveRegistry(null)
    expect(getActiveRegistry()).toBe(generated)
    expect(getActiveRegistry().families.tokens?.units.input_tokens?.priceKey).toBe('input_mtok')
  })

  it('looks up generated families and usage keys', () => {
    setActiveRegistry(null)
    expect(getFamily('tokens').per).toBe(1_000_000)
    expect(getFamily('requests').per).toBe(1_000)
    expect(getUnit('input_tokens')).toBe(getFamily('tokens').units.input_tokens)
    expect(getUnit('requests')).toBe(getFamily('requests').units.requests)
  })

  it('raises specific errors for unknown family ids and usage keys', () => {
    expect(() => getFamily('imaginary')).toThrow('Unknown unit family: imaginary')
    expect(() => getUnit('imaginary_tokens')).toThrow('Unknown unit usage key: imaginary_tokens')
  })

  it('looks up generated price keys', () => {
    setActiveRegistry(null)
    expect(getUnitForPriceKey('input_mtok')).toBe(getUnit('input_tokens'))
    expect(getUnitForPriceKey('output_mtok')).toBe(getUnit('output_tokens'))
    expect(getUnitForPriceKey('requests_kcount')).toBe(getUnit('requests'))
    expect(getUsageKeyForPriceKey('requests_kcount')).toBe('requests')
  })

  it('raises specific errors for unknown price keys', () => {
    expect(() => getUnitForPriceKey('imaginary_mtok')).toThrow('Unknown unit price key: imaginary_mtok')
    expect(() => getUsageKeyForPriceKey('imaginary_mtok')).toThrow('Unknown unit price key: imaginary_mtok')
  })

  it('returns the generated full usage-key set', () => {
    setActiveRegistry(null)
    expect(getAllUsageKeys()).toEqual(new Set(['requests', ...tokenUsageKeys]))
  })

  it('returns the generated full price-key set', () => {
    setActiveRegistry(null)
    expect(getAllPriceKeys()).toEqual(new Set(['requests_kcount', ...tokenPriceKeys]))
  })

  it('returns externally reported usage keys without pricing-only requests', () => {
    setActiveRegistry(null)
    expect(getAllUsageKeys()).toContain('requests')
    expect(getActiveRegistry().reportedUsageKeys).toEqual(new Set(tokenUsageKeys))
    expect(getActiveRegistry().reportedUsageKeys).not.toContain('requests')
  })
})
