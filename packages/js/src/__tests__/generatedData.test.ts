import { describe, expect, it } from 'vitest'

import * as providerDataModule from '../data'
import { unitData } from '../dataUnits'

describe('generated unit data', () => {
  it('keeps provider and unit data separate', () => {
    expect(providerDataModule).toHaveProperty('data')
    expect(providerDataModule).not.toHaveProperty('unitData')
    expect(Object.keys(unitData)).toHaveLength(21)
    expect(unitData.requests).toEqual({
      dimensions: { family: 'requests' },
      per: 1000,
      price_key: 'requests_kcount',
    })
  })
})
