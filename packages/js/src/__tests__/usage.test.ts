import { describe, expect, it } from 'vitest'

import { setActiveRegistry, UnitRegistry } from '../units'
import { getUsageValue, normalizeUsage } from '../usage'

describe('normalizeUsage', () => {
  it('normalizes current token keys from plain objects', () => {
    expect(
      normalizeUsage({
        cache_read_tokens: 20,
        input_tokens: 100,
        output_tokens: 50,
      })
    ).toEqual({
      cache_read_tokens: 20,
      input_tokens: 100,
      output_tokens: 50,
    })
  })

  it('ignores unknown extras', () => {
    expect(
      normalizeUsage({
        imaginary_tokens: 999,
        input_tokens: 100,
      })
    ).toEqual({
      input_tokens: 100,
    })
  })

  it('skips pricing-only requests', () => {
    expect(
      normalizeUsage({
        input_tokens: 100,
        requests: 500,
      })
    ).toEqual({
      input_tokens: 100,
    })
  })

  it('preserves explicit zero values', () => {
    expect(
      normalizeUsage({
        input_tokens: 0,
      })
    ).toEqual({
      input_tokens: 0,
    })
  })

  it('rejects invalid numeric values for registered usage keys', () => {
    for (const value of [Number.NaN, Number.POSITIVE_INFINITY, -1]) {
      expect(() =>
        normalizeUsage({
          input_tokens: value,
        })
      ).toThrow('Invalid usage value for input_tokens: expected a finite non-negative number')
    }
  })

  it('does not materialize missing keys or undefined values', () => {
    const usage = normalizeUsage({
      input_tokens: undefined,
      output_tokens: 10,
    })
    expect(usage).toEqual({
      output_tokens: 10,
    })
    expect(usage).not.toHaveProperty('input_tokens')
  })

  it('normalizes against the active registry reported usage keys', () => {
    const registry = new UnitRegistry({
      widgets: {
        dimensions: { family: 'widgets' },
        per: 1,
      },
    })

    try {
      setActiveRegistry(registry)
      expect(
        normalizeUsage({
          input_tokens: 100,
          widgets: 7,
        })
      ).toEqual({
        widgets: 7,
      })
    } finally {
      setActiveRegistry(null)
    }
  })
})

describe('getUsageValue', () => {
  it('returns stored values', () => {
    const usage = normalizeUsage({
      input_tokens: 100,
    })
    expect(getUsageValue(usage, 'input_tokens')).toBe(100)
  })

  it('rejects invalid stored values when reading registered usage keys', () => {
    expect(() => getUsageValue({ input_tokens: Number.NaN }, 'input_tokens')).toThrow(
      'Invalid usage value for input_tokens: expected a finite non-negative number'
    )
    expect(() => getUsageValue({ input_audio_tokens: -1 }, 'input_tokens')).toThrow(
      'Invalid usage value for input_audio_tokens: expected a finite non-negative number'
    )
  })

  it('returns stored zero values', () => {
    const usage = normalizeUsage({
      input_tokens: 0,
    })
    expect(getUsageValue(usage, 'input_tokens')).toBe(0)
  })

  it('returns zero for missing registered values without materializing them', () => {
    const usage = normalizeUsage({
      output_tokens: 10,
    })
    expect(getUsageValue(usage, 'input_tokens')).toBe(0)
    expect(usage).not.toHaveProperty('input_tokens')
  })

  it('raises for unknown usage keys', () => {
    expect(() => getUsageValue({}, 'imaginary_tokens')).toThrow('Unknown unit usage key: imaginary_tokens')
  })

  it('ignores unknown positive extras when checking missing registered values', () => {
    const usage = {
      imaginary_tokens: 999,
      output_tokens: 10,
    }

    expect(getUsageValue(usage, 'input_tokens')).toBe(0)
  })

  it('returns one for pricing-only requests regardless of caller values', () => {
    expect(getUsageValue({}, 'requests')).toBe(1)
    expect(getUsageValue({ requests: 500 }, 'requests')).toBe(1)
  })

  it('returns one for pricing-only requests when the active registry has no requests unit', () => {
    const registry = new UnitRegistry({
      input_tokens: {
        dimensions: { direction: 'input', family: 'tokens' },
        per: 1_000_000,
        price_key: 'input_mtok',
      },
    })

    try {
      setActiveRegistry(registry)
      expect(getUsageValue({}, 'requests')).toBe(1)
    } finally {
      setActiveRegistry(null)
    }
  })

  it('raises for missing ancestors with positive reported descendants', () => {
    const usage = normalizeUsage({
      input_audio_tokens: 100,
    })
    expect(() => getUsageValue(usage, 'input_tokens')).toThrow(
      'Missing usage value for input_tokens with positive reported descendant input_audio_tokens'
    )
  })

  it('returns stored ancestors directly even when descendants are contradictory', () => {
    const usage = normalizeUsage({
      input_audio_tokens: 200,
      input_tokens: 100,
    })
    expect(getUsageValue(usage, 'input_tokens')).toBe(100)
  })

  it('returns zero for missing descendants of reported ancestors', () => {
    const usage = normalizeUsage({
      input_tokens: 100,
    })
    expect(getUsageValue(usage, 'cache_read_tokens')).toBe(0)
    expect(usage).not.toHaveProperty('cache_read_tokens')
  })

  it('raises for missing overlap joins with positive reported incomparable units', () => {
    const usage = normalizeUsage({
      cache_read_tokens: 60,
      input_audio_tokens: 40,
    })
    expect(() => getUsageValue(usage, 'cache_audio_read_tokens')).toThrow(
      'Missing usage value for cache_audio_read_tokens with positive reported overlap cache_read_tokens and input_audio_tokens'
    )
  })

  it('returns stored overlap joins directly when present', () => {
    const usage = normalizeUsage({
      cache_audio_read_tokens: 10,
      cache_read_tokens: 60,
      input_audio_tokens: 40,
    })
    expect(getUsageValue(usage, 'cache_audio_read_tokens')).toBe(10)
  })

  it('returns zero when unrelated reported units do not imply the missing value', () => {
    const usage = normalizeUsage({
      input_audio_tokens: 40,
      output_tokens: 50,
    })
    expect(getUsageValue(usage, 'cache_audio_read_tokens')).toBe(0)
  })

  it('reads values from the active registry indexes', () => {
    const registry = new UnitRegistry({
      premium_widgets: {
        dimensions: {
          class: 'premium',
          family: 'widgets',
        },
        per: 1,
      },
      widgets: {
        dimensions: {
          family: 'widgets',
        },
        per: 1,
      },
    })

    try {
      setActiveRegistry(registry)
      const usage = normalizeUsage({
        premium_widgets: 3,
        widgets: 10,
      })

      expect(getUsageValue(usage, 'widgets')).toBe(10)
      expect(getUsageValue(usage, 'premium_widgets')).toBe(3)
    } finally {
      setActiveRegistry(null)
    }
  })
})
