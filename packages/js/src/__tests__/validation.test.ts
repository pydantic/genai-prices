import { describe, expect, it } from 'vitest'

import { validateAncestorCoverage, validateJoinCoverage, validateModelPrice, validatePriceKeys } from '../validation'

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

describe('validateJoinCoverage', () => {
  it('rejects compatible priced units when their registered join is not priced', () => {
    expect(() => {
      validateJoinCoverage(['input_mtok', 'cache_read_mtok', 'input_audio_mtok'])
    }).toThrow('Missing join price key cache_audio_read_mtok for cache_read_mtok and input_audio_mtok')
  })

  it('rejects compatible priced units when their join is absent from the current registry', () => {
    expect(() => {
      validateJoinCoverage(['input_mtok', 'cache_write_mtok', 'input_audio_mtok'])
    }).toThrow('Missing registered join unit for cache_write_mtok and input_audio_mtok')
  })

  it('accepts compatible priced units when the join is priced', () => {
    expect(() => {
      validateJoinCoverage(['input_mtok', 'cache_read_mtok', 'input_audio_mtok', 'cache_audio_read_mtok'])
    }).not.toThrow()
  })
})

describe('validateModelPrice', () => {
  it('accepts valid current model price key sets', () => {
    expect(() => {
      validateModelPrice(['input_mtok', 'output_mtok', 'requests_kcount'])
    }).not.toThrow()
    expect(() => {
      validateModelPrice(['input_mtok', 'cache_read_mtok', 'input_audio_mtok', 'cache_audio_read_mtok'])
    }).not.toThrow()
  })

  it('rejects unknown price keys through the composed helper', () => {
    expect(() => {
      validateModelPrice(['inptu_mtok'])
    }).toThrow('Unknown price key: inptu_mtok')
  })

  it('rejects missing ancestors through the composed helper', () => {
    expect(() => {
      validateModelPrice(['cache_read_mtok'])
    }).toThrow('Missing ancestor price key input_mtok for cache_read_mtok')
  })

  it('rejects missing joins through the composed helper', () => {
    expect(() => {
      validateModelPrice(['input_mtok', 'cache_read_mtok', 'input_audio_mtok'])
    }).toThrow('Missing join price key cache_audio_read_mtok for cache_read_mtok and input_audio_mtok')
  })
})
