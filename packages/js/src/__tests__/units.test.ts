import { describe, expect, it } from 'vitest'

import type { RawFamiliesDict } from '../types'

import { unitFamiliesData } from '../dataUnits'
import { parseFamilies } from '../units'

describe('parseFamilies', () => {
  it('parses generated unit families into runtime objects', () => {
    const families = parseFamilies(unitFamiliesData)
    const tokenFamily = families.tokens
    const requestFamily = families.requests
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
  })

  it('defaults missing price keys to the usage key', () => {
    const families = parseFamilies({
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

    expect(families.widgets?.units.widgets?.priceKey).toBe('widgets')
  })

  it('links units back to their family and fills dimension lookup state', () => {
    const families = parseFamilies(unitFamiliesData)
    const tokenFamily = families.tokens
    expect(tokenFamily).toBeDefined()
    if (!tokenFamily) throw new Error('Expected generated token family')

    const inputAudio = tokenFamily.units.input_audio_tokens
    expect(inputAudio).toBeDefined()
    if (!inputAudio) throw new Error('Expected input_audio_tokens')

    expect(inputAudio.family).toBe(tokenFamily)
    expect(inputAudio.familyId).toBe('tokens')
    expect(tokenFamily.unitsByDimension.get('direction=input\0modality=audio')).toBe(inputAudio)
  })

  it('keeps parsing independent of generated data fixtures', () => {
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

    const unit = parseFamilies(raw).calls?.units.billable_calls
    expect(unit).toMatchObject({
      dimensions: { class: 'billable' },
      familyId: 'calls',
      priceKey: 'billable_call_count',
      usageKey: 'billable_calls',
    })
  })

  it('rejects duplicate usage keys across families', () => {
    expect(() =>
      parseFamilies({
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

  it('rejects duplicate price keys across families', () => {
    expect(() =>
      parseFamilies({
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

  it('rejects duplicate dimension sets in one family', () => {
    expect(() =>
      parseFamilies({
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
})
