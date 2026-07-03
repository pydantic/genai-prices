import { describe, expect, it } from 'vitest'

import type { ModelInfo, ModelPrice, Provider, ProviderConditionalPrice } from '../types'

import { getActiveModelPrice } from '../engine'

const TS = new Date('2025-01-01T00:00:00Z')

function provider(prices: ModelPrice | ProviderConditionalPrice[] | undefined): Provider {
  return { api_pattern: 'testing', id: 'testing', models: [], name: 'Testing', prices }
}

function model(id: string, prices: ModelInfo['prices']): ModelInfo {
  return { id, match: { equals: id }, prices }
}

describe('provider-level prices', () => {
  it('inherits provider price for units the model does not define', () => {
    const p = provider({ input_mtok: 7 })
    const m = model('gpt-x', { output_mtok: 3 })
    expect(getActiveModelPrice(m, TS, {}, p)).toEqual({ input_mtok: 7, output_mtok: 3 })
  })

  it('lets the model price override the provider price', () => {
    const p = provider({ input_mtok: 7, output_mtok: 9 })
    const m = model('gpt-x', { input_mtok: 2 })
    expect(getActiveModelPrice(m, TS, {}, p)).toEqual({ input_mtok: 2, output_mtok: 9 })
  })

  it('matches provider prices on the model parameter', () => {
    const prices: ProviderConditionalPrice[] = [
      { values: { input_mtok: 25 }, when: { model: { starts_with: 'gpt-5' } } },
      { values: { input_mtok: 10 } },
    ]
    const p = provider(prices)
    expect(getActiveModelPrice(model('gpt-5-turbo', { output_mtok: 1 }), TS, {}, p)).toEqual({
      input_mtok: 25,
      output_mtok: 1,
    })
    expect(getActiveModelPrice(model('gpt-4o', { output_mtok: 1 }), TS, {}, p)).toEqual({
      input_mtok: 10,
      output_mtok: 1,
    })
  })

  it('is unchanged when the provider has no prices', () => {
    const p = provider(undefined)
    const m = model('gpt-x', { input_mtok: 2, output_mtok: 4 })
    expect(getActiveModelPrice(m, TS, {}, p)).toEqual({ input_mtok: 2, output_mtok: 4 })
  })
})
