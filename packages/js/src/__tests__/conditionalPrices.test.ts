import { describe, expect, it } from 'vitest'

import type { ConditionalPrice, ModelInfo, ModelPrice } from '../types'

import { getActiveModelPrice } from '../engine'

function model(prices: ConditionalPrice[] | ModelPrice): ModelInfo {
  return { id: 'cond', match: { equals: 'cond' }, prices }
}

const TS = new Date('2025-01-01T00:00:00Z')

describe('getActiveModelPrice when/values', () => {
  it('selects the matching when entry', () => {
    const prices: ConditionalPrice[] = [
      { values: { input_mtok: 1, output_mtok: 2 }, when: { service_tier: 'batch' } },
      { values: { input_mtok: 2, output_mtok: 4 } },
    ]
    expect(getActiveModelPrice(model(prices), TS, { service_tier: 'batch' })).toEqual({ input_mtok: 1, output_mtok: 2 })
    expect(getActiveModelPrice(model(prices), TS, { service_tier: 'standard' })).toEqual({ input_mtok: 2, output_mtok: 4 })
    expect(getActiveModelPrice(model(prices), TS)).toEqual({ input_mtok: 2, output_mtok: 4 })
  })

  it('falls through per-unit for undefined keys', () => {
    const prices: ConditionalPrice[] = [
      { values: { output_mtok: 1 }, when: { service_tier: 'batch' } },
      { values: { input_mtok: 2, output_mtok: 4 } },
    ]
    // output from the batch entry, input from the default entry
    expect(getActiveModelPrice(model(prices), TS, { service_tier: 'batch' })).toEqual({ input_mtok: 2, output_mtok: 1 })
  })

  it('supports in and range operators', () => {
    const prices: ConditionalPrice[] = [
      { values: { input_mtok: 1 }, when: { region: { in: ['us-east-1', 'us-west-2'] } } },
      { values: { input_mtok: 9 }, when: { inference_geo: { gte: 10, lte: 20 } } },
      { values: { input_mtok: 5 } },
    ]
    expect(getActiveModelPrice(model(prices), TS, { region: 'us-east-1' })).toEqual({ input_mtok: 1 })
    expect(getActiveModelPrice(model(prices), TS, { inference_geo: 15 })).toEqual({ input_mtok: 9 })
    expect(getActiveModelPrice(model(prices), TS, { inference_geo: 25 })).toEqual({ input_mtok: 5 })
  })

  it('is type-strict for boolean conditions', () => {
    const prices: ConditionalPrice[] = [{ values: { input_mtok: 1 }, when: { batch: true } }, { values: { input_mtok: 5 } }]
    expect(getActiveModelPrice(model(prices), TS, { batch: true })).toEqual({ input_mtok: 1 })
    expect(getActiveModelPrice(model(prices), TS, { batch: 1 })).toEqual({ input_mtok: 5 })
  })

  it('honours date constraints alongside when', () => {
    const prices: ConditionalPrice[] = [
      { constraint: { start_date: '2025-06-01', type: 'start_date' }, values: { input_mtok: 2 } },
      { values: { input_mtok: 8 } },
    ]
    expect(getActiveModelPrice(model(prices), new Date('2025-07-01T00:00:00Z'))).toEqual({ input_mtok: 2 })
    expect(getActiveModelPrice(model(prices), new Date('2025-01-01T00:00:00Z'))).toEqual({ input_mtok: 8 })
  })

  it('returns unconditional ModelPrice unchanged', () => {
    expect(getActiveModelPrice(model({ input_mtok: 3 }), TS, { service_tier: 'batch' })).toEqual({ input_mtok: 3 })
  })
})
