import { describe, expect, it } from 'vitest'

import { isDescendantOrSelf } from '../decompose'
import { getUnit } from '../units'

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
