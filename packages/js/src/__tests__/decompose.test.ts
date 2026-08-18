import { describe, expect, it } from 'vitest'

import type { UnitDef } from '../types'

import { computeLeafValues } from '../decompose'
import { getActiveRegistry, isDescendantOrSelf, UnitRegistry } from '../units'
import { normalizeUsage } from '../usage'

describe('isDescendantOrSelf', () => {
  it('accepts the same unit', () => {
    const input = getUnit('input_tokens')
    expect(isDescendantOrSelf(input, input)).toBe(true)
  })

  it('accepts parent and child units', () => {
    expect(isDescendantOrSelf(getUnit('input_tokens'), getUnit('cache_read_tokens'))).toBe(true)
    expect(isDescendantOrSelf(getUnit('input_tokens'), getUnit('input_audio_tokens'))).toBe(true)
  })

  it('rejects siblings', () => {
    expect(isDescendantOrSelf(getUnit('cache_read_tokens'), getUnit('input_audio_tokens'))).toBe(false)
  })

  it('rejects cross-family units', () => {
    expect(isDescendantOrSelf(getUnit('requests'), getUnit('input_tokens'))).toBe(false)
  })

  it('rejects incompatible units', () => {
    expect(isDescendantOrSelf(getUnit('input_tokens'), getUnit('output_tokens'))).toBe(false)
  })
})

describe('computeLeafValues', () => {
  it('handles parent/child decomposition', () => {
    expect(
      computeLeafValues(
        new Set(['cache_read_tokens', 'input_tokens']),
        normalizeUsage({
          cache_read_tokens: 250,
          input_tokens: 1_000,
        }),
        getActiveRegistry()
      )
    ).toEqual({
      cache_read_tokens: 250,
      input_tokens: 750,
    })
  })

  it('handles cached-audio overlap decomposition', () => {
    expect(
      computeLeafValues(
        new Set(['cache_audio_read_tokens', 'cache_read_tokens', 'input_audio_tokens', 'input_tokens']),
        normalizeUsage({
          cache_audio_read_tokens: 100,
          cache_read_tokens: 400,
          input_audio_tokens: 300,
          input_tokens: 1_000,
        }),
        getActiveRegistry()
      )
    ).toEqual({
      cache_audio_read_tokens: 100,
      cache_read_tokens: 300,
      input_audio_tokens: 200,
      input_tokens: 400,
    })
  })

  it('handles a conditional-dimension chain', () => {
    expect(
      computeLeafValues(
        new Set(['cache_write_1h_tokens', 'cache_write_tokens', 'input_tokens']),
        normalizeUsage({
          cache_write_1h_tokens: 100,
          cache_write_tokens: 300,
          input_tokens: 400,
        }),
        getActiveRegistry()
      )
    ).toEqual({
      cache_write_1h_tokens: 100,
      cache_write_tokens: 200,
      input_tokens: 100,
    })
  })

  it('handles output audio decomposition', () => {
    expect(
      computeLeafValues(
        new Set(['output_audio_tokens', 'output_tokens']),
        normalizeUsage({
          output_audio_tokens: 200,
          output_tokens: 700,
        }),
        getActiveRegistry()
      )
    ).toEqual({
      output_audio_tokens: 200,
      output_tokens: 500,
    })
  })

  it('handles reasoning-modality overlap decomposition', () => {
    expect(
      computeLeafValues(
        new Set(['output_reasoning_tokens', 'output_text_reasoning_tokens', 'output_text_tokens', 'output_tokens']),
        normalizeUsage({
          output_reasoning_tokens: 30,
          output_text_reasoning_tokens: 20,
          output_text_tokens: 60,
          output_tokens: 100,
        }),
        getActiveRegistry()
      )
    ).toEqual({
      output_reasoning_tokens: 10,
      output_text_reasoning_tokens: 20,
      output_text_tokens: 40,
      output_tokens: 30,
    })
  })

  it('handles conditional-dimension chains without parity assumptions', () => {
    const registry = new UnitRegistry({
      cache_write_1h_tokens: {
        dimensions: {
          cache_ttl: '1h',
          direction: 'input',
          family: 'tokens',
          token_type: 'cache_write',
        },
        per: 1,
      },
      cache_write_tokens: {
        dimensions: {
          direction: 'input',
          family: 'tokens',
          token_type: 'cache_write',
        },
        per: 1,
      },
      input_tokens: {
        dimensions: {
          direction: 'input',
          family: 'tokens',
        },
        per: 1,
      },
    })

    expect(
      computeLeafValues(
        new Set(['cache_write_1h_tokens', 'cache_write_tokens', 'input_tokens']),
        normalizeUsage(
          {
            cache_write_1h_tokens: 20,
            cache_write_tokens: 60,
            input_tokens: 100,
          },
          registry
        ),
        registry
      )
    ).toEqual({
      cache_write_1h_tokens: 20,
      cache_write_tokens: 40,
      input_tokens: 40,
    })
  })

  it('normalizes negligible floating-point residuals to zero', () => {
    expect(
      computeLeafValues(
        new Set(['input_audio_tokens', 'input_image_tokens', 'input_tokens']),
        normalizeUsage({
          input_audio_tokens: 0.2,
          input_image_tokens: 0.1,
          input_tokens: 0.3,
        }),
        getActiveRegistry()
      )
    ).toEqual({
      input_audio_tokens: 0.2,
      input_image_tokens: 0.1,
      input_tokens: 0,
    })
  })

  it('rejects fractional descendants that exceed their parent', () => {
    expect(() =>
      computeLeafValues(
        new Set(['cache_read_tokens', 'input_tokens']),
        normalizeUsage({
          cache_read_tokens: 0.2,
          input_tokens: 0.1,
        }),
        getActiveRegistry()
      )
    ).toThrow('Invalid usage data: cache_read_tokens (0.2) cannot exceed input_tokens (0.1)')
  })

  it('ignores unpriced reported descendants when priced ancestors cover them', () => {
    expect(
      computeLeafValues(
        new Set(['input_tokens']),
        normalizeUsage({
          cache_read_tokens: 80,
          input_tokens: 100,
        }),
        getActiveRegistry()
      )
    ).toEqual({
      input_tokens: 100,
    })
  })

  it('rejects direct descendants that exceed their parent', () => {
    expect(() =>
      computeLeafValues(
        new Set(['cache_read_tokens', 'input_tokens']),
        normalizeUsage({
          cache_read_tokens: 200,
          input_tokens: 100,
        }),
        getActiveRegistry()
      )
    ).toThrow('Invalid usage data: cache_read_tokens (200) cannot exceed input_tokens (100)')
  })

  it('rejects overlapping descendant totals that exceed their parent', () => {
    expect(() =>
      computeLeafValues(
        new Set(['cache_audio_read_tokens', 'cache_read_tokens', 'input_audio_tokens', 'input_tokens']),
        normalizeUsage({
          cache_audio_read_tokens: 0,
          cache_read_tokens: 80,
          input_audio_tokens: 80,
          input_tokens: 100,
        }),
        getActiveRegistry()
      )
    ).toThrow(
      'Invalid usage data: more-specific usage for cache_read_tokens, input_audio_tokens totals 160, which exceeds input_tokens (100)'
    )
  })
})

function getUnit(usageKey: string): UnitDef {
  const unit = getActiveRegistry().getUnit(usageKey)
  if (!unit) throw new Error(`Missing test unit for ${usageKey}`)
  return unit
}
