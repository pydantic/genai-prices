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
  setUnitFamilies,
  UnitRegistry,
  validateUnitFamilies,
} from '../units'

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
    expect(Object.keys(tokenFamily.units)).toEqual([
      'cache_audio_read_tokens',
      'cache_read_tokens',
      'cache_write_tokens',
      'input_audio_tokens',
      'input_tokens',
      'output_audio_tokens',
      'output_tokens',
    ])
    expect(requestFamily.units.requests?.priceKey).toBe('requests_kcount')
    expect(registry.units.get('input_tokens')).toBe(tokenFamily.units.input_tokens)
    expect(registry.unitsByPriceKey.get('input_mtok')).toBe(tokenFamily.units.input_tokens)
    expect(registry.allUsageKeys).toContain('input_tokens')
    expect(registry.allPriceKeys).toContain('input_mtok')
    expect(registry.reportedUsageKeys).toContain('input_tokens')
    expect(registry.reportedUsageKeys).not.toContain('requests')
  })

  it('accepts the generated unit registry interval closure', () => {
    expect(() => validateUnitFamilies(unitFamiliesData)).not.toThrow()
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

  it('validates duplicate usage keys across families', () => {
    expect(() =>
      validateUnitFamilies({
        audio: {
          description: 'Audio counts',
          per: 1,
          units: {
            seconds: {
              dimensions: {
                modality: 'audio',
              },
            },
          },
        },
        video: {
          description: 'Video counts',
          per: 1,
          units: {
            seconds: {
              dimensions: {
                modality: 'video',
              },
            },
          },
        },
      })
    ).toThrow('Duplicate unit usage key: seconds')
  })

  it('validates duplicate price keys across families', () => {
    expect(() =>
      validateUnitFamilies({
        images: {
          description: 'Image counts',
          per: 1,
          units: {
            input_images: {
              dimensions: {
                direction: 'input',
              },
              price_key: 'image_count',
            },
          },
        },
        video: {
          description: 'Video counts',
          per: 1,
          units: {
            input_frames: {
              dimensions: {
                direction: 'input',
              },
              price_key: 'image_count',
            },
          },
        },
      })
    ).toThrow('Duplicate unit price key: image_count')
  })

  it('validates duplicate dimension sets in one family', () => {
    expect(() =>
      validateUnitFamilies({
        tokens: {
          description: 'Token counts',
          per: 1_000_000,
          units: {
            input_chars: {
              dimensions: {
                direction: 'input',
              },
              price_key: 'input_chars_mcount',
            },
            input_tokens: {
              dimensions: {
                direction: 'input',
              },
              price_key: 'input_mtok',
            },
          },
        },
      })
    ).toThrow('Duplicate dimensions in unit family tokens: input_chars and input_tokens')
  })

  it('validates missing intermediate dimensions between ancestors and descendants', () => {
    expect(() =>
      validateUnitFamilies({
        tokens: {
          description: 'Token counts',
          per: 1_000_000,
          units: {
            cache_audio_read_tokens: {
              dimensions: {
                cache: 'read',
                direction: 'input',
                modality: 'audio',
              },
              price_key: 'cache_audio_read_mtok',
            },
            input_tokens: {
              dimensions: {
                direction: 'input',
              },
              price_key: 'input_mtok',
            },
          },
        },
      })
    ).toThrow(
      'Missing intermediate unit dimensions in family tokens between input_tokens and cache_audio_read_tokens: cache=read, direction=input'
    )
  })

  it('validates public usage and price keys', () => {
    expect(() =>
      validateUnitFamilies({
        tokens: {
          description: 'Token counts',
          per: 1_000_000,
          units: {
            _private_name: {
              dimensions: { direction: 'input' },
              price_key: 'private_mtok',
            },
          },
        },
      })
    ).toThrow('Invalid unit usage key: _private_name must not start with "_"')

    expect(() =>
      validateUnitFamilies({
        tokens: {
          description: 'Token counts',
          per: 1_000_000,
          units: {
            input_tokens: {
              dimensions: { direction: 'input' },
              price_key: 'class',
            },
          },
        },
      })
    ).toThrow('Invalid unit price key: class is a reserved keyword')
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

    setUnitFamilies(custom)
    expect(getActiveRegistry()).toBe(custom)
    expect(getActiveRegistry().families.widgets?.units.widgets?.priceKey).toBe('widgets')

    setUnitFamilies(null)
    expect(getActiveRegistry()).toBe(generated)
    expect(getActiveRegistry().families.tokens?.units.input_tokens?.priceKey).toBe('input_mtok')
  })

  it('looks up generated families and usage keys', () => {
    setUnitFamilies(null)
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
    setUnitFamilies(null)
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
    setUnitFamilies(null)
    expect(getAllUsageKeys()).toEqual(
      new Set([
        'cache_audio_read_tokens',
        'cache_read_tokens',
        'cache_write_tokens',
        'input_audio_tokens',
        'input_tokens',
        'output_audio_tokens',
        'output_tokens',
        'requests',
      ])
    )
  })

  it('returns the generated full price-key set', () => {
    setUnitFamilies(null)
    expect(getAllPriceKeys()).toEqual(
      new Set([
        'cache_audio_read_mtok',
        'cache_read_mtok',
        'cache_write_mtok',
        'input_audio_mtok',
        'input_mtok',
        'output_audio_mtok',
        'output_mtok',
        'requests_kcount',
      ])
    )
  })

  it('returns externally reported usage keys without pricing-only requests', () => {
    setUnitFamilies(null)
    expect(getAllUsageKeys()).toContain('requests')
    expect(getActiveRegistry().reportedUsageKeys).toEqual(
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
    expect(getActiveRegistry().reportedUsageKeys).not.toContain('requests')
  })
})
