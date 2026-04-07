import { describe, expect, it } from 'vitest'

import type { Usage } from '../types'

import { computeLeafValues, isDescendantOrSelf, validateAncestorCoverage } from '../decompose'
import { getUnit, TOKENS_FAMILY } from '../units'

describe('Containment', () => {
  it('self is descendant-or-self', () => {
    const unit = getUnit('input_mtok')
    expect(isDescendantOrSelf(unit, unit)).toBe(true)
  })

  it('child is descendant', () => {
    expect(isDescendantOrSelf(getUnit('input_mtok'), getUnit('cache_read_mtok'))).toBe(true)
  })

  it('parent is NOT descendant of child', () => {
    expect(isDescendantOrSelf(getUnit('cache_read_mtok'), getUnit('input_mtok'))).toBe(false)
  })

  it('grandchild is descendant', () => {
    expect(isDescendantOrSelf(getUnit('input_mtok'), getUnit('cache_audio_read_mtok'))).toBe(true)
  })

  it('sibling not descendant', () => {
    expect(isDescendantOrSelf(getUnit('cache_read_mtok'), getUnit('cache_write_mtok'))).toBe(false)
  })

  it('different direction not descendant', () => {
    expect(isDescendantOrSelf(getUnit('input_mtok'), getUnit('output_mtok'))).toBe(false)
  })
})

describe('Leaf Values', () => {
  const family = TOKENS_FAMILY

  it('simple text model', () => {
    const priced = new Set(['input_mtok', 'output_mtok'])
    const usage = { input_tokens: 1000, output_tokens: 500 }
    expect(computeLeafValues(priced, usage, family)).toEqual({ input_mtok: 1000, output_mtok: 500 })
  })

  it('with cache', () => {
    const priced = new Set(['cache_read_mtok', 'cache_write_mtok', 'input_mtok', 'output_mtok'])
    const usage = { cache_read_tokens: 200, cache_write_tokens: 100, input_tokens: 1000, output_tokens: 500 }
    expect(computeLeafValues(priced, usage, family)).toEqual({
      cache_read_mtok: 200,
      cache_write_mtok: 100,
      input_mtok: 700,
      output_mtok: 500,
    })
  })

  it('with audio', () => {
    const priced = new Set(['input_audio_mtok', 'input_mtok', 'output_mtok'])
    const usage = { input_audio_tokens: 300, input_tokens: 1000, output_tokens: 500 }
    expect(computeLeafValues(priced, usage, family)).toEqual({
      input_audio_mtok: 300,
      input_mtok: 700,
      output_mtok: 500,
    })
  })

  it('lattice: cache_read_audio carved from both', () => {
    const priced = new Set(['cache_audio_read_mtok', 'cache_read_mtok', 'input_audio_mtok', 'input_mtok'])
    const usage = {
      cache_audio_read_tokens: 50,
      cache_read_tokens: 200,
      input_audio_tokens: 300,
      input_tokens: 1000,
    }
    expect(computeLeafValues(priced, usage, family)).toEqual({
      cache_audio_read_mtok: 50,
      cache_read_mtok: 150,
      input_audio_mtok: 250,
      input_mtok: 550,
    })
  })

  it('unpriced audio stays in catch-all', () => {
    const priced = new Set(['cache_read_mtok', 'input_mtok', 'output_mtok'])
    const usage = {
      cache_read_tokens: 200,
      input_audio_tokens: 300,
      input_tokens: 1000,
      output_tokens: 500,
    }
    expect(computeLeafValues(priced, usage, family)).toEqual({
      cache_read_mtok: 200,
      input_mtok: 800,
      output_mtok: 500,
    })
  })

  it('unpriced cache stays in catch-all', () => {
    const priced = new Set(['input_mtok', 'output_mtok'])
    const usage = { cache_read_tokens: 200, input_tokens: 1000, output_tokens: 500 }
    expect(computeLeafValues(priced, usage, family)).toEqual({
      input_mtok: 1000,
      output_mtok: 500,
    })
  })

  it('negative leaf raises error', () => {
    const priced = new Set(['cache_read_mtok', 'input_mtok'])
    const usage = { cache_read_tokens: 200, input_tokens: 100 }
    expect(() => computeLeafValues(priced, usage, family)).toThrow(/Negative leaf value.*input_mtok/)
  })

  it('full 7-unit model', () => {
    const priced = new Set([
      'cache_audio_read_mtok',
      'cache_read_mtok',
      'cache_write_mtok',
      'input_audio_mtok',
      'input_mtok',
      'output_audio_mtok',
      'output_mtok',
    ])
    const usage = {
      cache_audio_read_tokens: 50,
      cache_read_tokens: 200,
      cache_write_tokens: 100,
      input_audio_tokens: 300,
      input_tokens: 1000,
      output_audio_tokens: 150,
      output_tokens: 800,
    }
    expect(computeLeafValues(priced, usage, family)).toEqual({
      cache_audio_read_mtok: 50,
      cache_read_mtok: 150,
      cache_write_mtok: 100,
      input_audio_mtok: 250,
      input_mtok: 450,
      output_audio_mtok: 150,
      output_mtok: 650,
    })
  })

  it('accepts Usage object (optional fields)', () => {
    const priced = new Set(['cache_read_mtok', 'input_mtok', 'output_mtok'])
    const usage: Usage = { cache_read_tokens: 200, input_tokens: 1000, output_tokens: 500 }
    expect(computeLeafValues(priced, usage as Record<string, unknown>, family)).toEqual({
      cache_read_mtok: 200,
      input_mtok: 800,
      output_mtok: 500,
    })
  })
})

describe('Ancestor Coverage', () => {
  it('valid: input + output', () => {
    expect(() => {
      validateAncestorCoverage(new Set(['input_mtok', 'output_mtok']), TOKENS_FAMILY)
    }).not.toThrow()
  })

  it('valid: with cache', () => {
    expect(() => {
      validateAncestorCoverage(new Set(['cache_read_mtok', 'input_mtok', 'output_mtok']), TOKENS_FAMILY)
    }).not.toThrow()
  })

  it('missing ancestor: cache_read without input', () => {
    expect(() => {
      validateAncestorCoverage(new Set(['cache_read_mtok', 'output_mtok']), TOKENS_FAMILY)
    }).toThrow(/ancestor.*input_mtok/)
  })

  it('missing intermediate ancestor', () => {
    expect(() => {
      validateAncestorCoverage(new Set(['cache_audio_read_mtok', 'input_mtok', 'output_mtok']), TOKENS_FAMILY)
    }).toThrow(/ancestor/)
  })
})
