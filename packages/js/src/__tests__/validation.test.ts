import { describe, expect, it } from 'vitest'

import type { Provider, UsageExtractorMapping } from '../types'

import { data } from '../data'
import { getActiveRegistry, UnitRegistry } from '../units'
import {
  validateAncestorCoverage,
  validateExtractorDestinations,
  validateJoinCoverage,
  validateModelPrice,
  validatePricedUnits,
  validatePriceKeys,
} from '../validation'

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

  it('accepts price keys from an explicit registry argument', () => {
    const registry = new UnitRegistry({
      widgets: {
        dimensions: { family: 'widgets' },
        per: 1,
      },
    })

    expect(() => {
      validatePriceKeys(['widgets'], registry)
    }).not.toThrow()
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

  it('rejects child prices from a single-pass iterable without registered ancestor prices', () => {
    expect(() => {
      validateAncestorCoverage(oneShotPriceKeys(['cache_read_mtok']))
    }).toThrow('Missing ancestor price key input_mtok for cache_read_mtok')
  })
})

describe('validateJoinCoverage', () => {
  it('rejects compatible priced units when their registered join is not priced', () => {
    expect(() => {
      validateJoinCoverage(['input_mtok', 'cache_read_mtok', 'input_audio_mtok'])
    }).toThrow('Missing join price key cache_audio_read_mtok for cache_read_mtok and input_audio_mtok')
  })

  it('rejects compatible priced units from a single-pass iterable when their registered join is not priced', () => {
    expect(() => {
      validateJoinCoverage(oneShotPriceKeys(['input_mtok', 'cache_read_mtok', 'input_audio_mtok']))
    }).toThrow('Missing join price key cache_audio_read_mtok for cache_read_mtok and input_audio_mtok')
  })

  it('rejects compatible priced units when their join is absent from the current registry', () => {
    expect(() => {
      validateJoinCoverage(['input_mtok', 'cache_write_mtok', 'input_audio_mtok'])
    }).toThrow('Missing join price key cache_audio_write_mtok for cache_write_mtok and input_audio_mtok')
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

  it('materializes single-pass price keys once', () => {
    expect(() => {
      validateModelPrice(oneShotPriceKeys(['input_mtok', 'cache_read_mtok']))
    }).not.toThrow()
  })
})

describe('validatePricedUnits', () => {
  it('accepts valid resolved units including request-only pricing', () => {
    const registry = getActiveRegistry()

    expect(() => {
      validatePricedUnits(
        [requiredUnit(registry, 'input_mtok'), requiredUnit(registry, 'cache_read_mtok'), requiredUnit(registry, 'requests_kcount')],
        registry
      )
    }).not.toThrow()
    expect(() => {
      validatePricedUnits([requiredUnit(registry, 'requests_kcount')], registry)
    }).not.toThrow()
  })

  it('rejects missing ancestor and join prices with key-based error parity', () => {
    const registry = getActiveRegistry()
    const missingAncestorKeys = ['cache_read_mtok']
    const missingJoinKeys = ['input_mtok', 'cache_read_mtok', 'input_audio_mtok']

    expect(
      validationError(() => {
        validatePricedUnits(resolveUnits(registry, missingAncestorKeys), registry)
      })
    ).toBe(
      validationError(() => {
        validateModelPrice(missingAncestorKeys, registry)
      })
    )
    expect(
      validationError(() => {
        validatePricedUnits(resolveUnits(registry, missingJoinKeys), registry)
      })
    ).toBe(
      validationError(() => {
        validateModelPrice(missingJoinKeys, registry)
      })
    )
  })

  it('validates units from an explicit custom registry', () => {
    const registry = new UnitRegistry({
      widgets: {
        dimensions: { family: 'widgets' },
        per: 1,
      },
    })

    expect(() => {
      validatePricedUnits([requiredUnit(registry, 'widgets')], registry)
    }).not.toThrow()
  })
})

describe('validateExtractorDestinations', () => {
  it('accepts current generated extractor destinations', () => {
    expect(() => {
      validateExtractorDestinations(data)
    }).not.toThrow()
  })

  it('rejects price-key destinations', () => {
    expect(() => {
      validateExtractorDestinations([providerWithDestination('input_mtok')])
    }).toThrow('Invalid extractor destination for test-provider/default mapping 0: input_mtok')
  })

  it('rejects arbitrary destinations', () => {
    expect(() => {
      validateExtractorDestinations([providerWithDestination('imaginary_tokens')])
    }).toThrow('Invalid extractor destination for test-provider/default mapping 0: imaginary_tokens')
  })

  it('rejects pricing-only request destinations', () => {
    expect(() => {
      validateExtractorDestinations([providerWithDestination('requests')])
    }).toThrow('Invalid extractor destination for test-provider/default mapping 0: requests')
  })

  it('validates extractor destinations against an explicit registry argument', () => {
    const registry = new UnitRegistry({
      widgets: {
        dimensions: { family: 'widgets' },
        per: 1,
      },
    })

    expect(() => {
      validateExtractorDestinations([providerWithDestination('widgets')], registry)
    }).not.toThrow()
    expect(() => {
      validateExtractorDestinations([providerWithDestination('input_tokens')], registry)
    }).toThrow('Invalid extractor destination for test-provider/default mapping 0: input_tokens')
  })
})

function providerWithDestination(dest: string): Provider {
  const mapping: UsageExtractorMapping = {
    dest,
    path: 'usage',
    required: true,
  }
  return {
    api_pattern: 'https://example.com',
    extractors: [
      {
        api_flavor: 'default',
        mappings: [mapping],
        model_path: 'model',
        root: 'usage',
      },
    ],
    id: 'test-provider',
    models: [],
    name: 'Test Provider',
  }
}

function oneShotPriceKeys(keys: string[]): Iterable<string> {
  let used = false
  return {
    [Symbol.iterator]: () => {
      if (used) return [][Symbol.iterator]()
      used = true
      return keys[Symbol.iterator]()
    },
  }
}

function requiredUnit(registry: UnitRegistry, priceKey: string) {
  const unit = registry.unitsByPriceKey.get(priceKey)
  if (!unit) throw new Error(`Missing test unit for ${priceKey}`)
  return unit
}

function resolveUnits(registry: UnitRegistry, priceKeys: string[]) {
  return priceKeys.map((priceKey) => requiredUnit(registry, priceKey))
}

function validationError(validate: () => void): string {
  try {
    validate()
  } catch (error) {
    if (error instanceof Error) return error.message
    throw error
  }
  throw new Error('Expected validation to fail')
}
