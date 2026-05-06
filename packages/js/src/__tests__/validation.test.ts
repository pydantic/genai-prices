import { describe, expect, it } from 'vitest'

import { validateAncestorCoverage, validatePriceKeys } from '../validation'

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

describe('validateAncestorCoverage', () => {
  it('accepts parent and child prices together', () => {
    expect(() => {
      validateAncestorCoverage(['input_mtok', 'cache_read_mtok'])
    }).not.toThrow()
  })

  it('rejects child prices without registered ancestor prices', () => {
    expect(() => {
      validateAncestorCoverage(['cache_read_mtok'])
    }).toThrow('Missing ancestor price key input_mtok for cache_read_mtok')
  })
})
