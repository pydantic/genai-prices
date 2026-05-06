import { describe, expect, it } from 'vitest'

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
})

describe('getUsageValue', () => {
  it('returns stored values', () => {
    const usage = normalizeUsage({
      input_tokens: 100,
    })
    expect(getUsageValue(usage, 'input_tokens')).toBe(100)
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
})
