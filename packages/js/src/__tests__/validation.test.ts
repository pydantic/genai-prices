import { describe, expect, it } from 'vitest'

import { validatePriceKeys } from '../validation'

describe('validatePriceKeys', () => {
  it('accepts registered current price keys', () => {
    expect(() => {
      validatePriceKeys(['input_mtok', 'output_mtok', 'requests_kcount'])
    }).not.toThrow()
  })

  it('rejects unknown price keys', () => {
    expect(() => {
      validatePriceKeys(['inptu_mtok'])
    }).toThrow('Unknown price key: inptu_mtok')
  })
})
