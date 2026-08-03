import { describe, expect, it } from 'vitest'

import type { ConditionalPrice, ModelInfo, Provider } from '../types'

import { calcPrice } from '../api'
import { getActiveModelPrice } from '../engine'

const MILLION = 1_000_000
const TIMESTAMP = new Date('2026-08-03T00:00:00Z')

describe('batch prices', () => {
  it.each([
    ['anthropic', 'claude-opus-5', 0.5],
    ['openai', 'gpt-5.6-terra', 0.5],
    ['google', 'gemini-3.6-flash', 0.5],
    ['mistral', 'mistral-large-2512', 0.5],
    ['groq', 'llama-3.3-70b-versatile', 0.5],
    // xAI discounts batch by 20%, not 50%
    ['x-ai', 'grok-4.3', 0.8],
  ])('discounts %s/%s by the published ratio', (providerId, modelId, ratio) => {
    const usage = { input_tokens: MILLION, output_tokens: MILLION / 10 }
    const standard = calcPrice(usage, modelId, { providerId, timestamp: TIMESTAMP })
    const batch = calcPrice(usage, modelId, { batch: true, providerId, timestamp: TIMESTAMP })

    expect(batch?.total_price).toBeCloseTo((standard?.total_price ?? 0) * ratio, 10)
  })

  it('prices a real Anthropic batch response', () => {
    // claude-haiku-4-5 batch request that wrote 7082 tokens to the cache
    const usage = {
      cache_write_5m_tokens: 7082,
      cache_write_tokens: 7082,
      input_tokens: 7099,
      output_tokens: 5,
    }
    const batch = calcPrice(usage, 'claude-haiku-4-5-20251001', {
      batch: true,
      providerId: 'anthropic',
      timestamp: TIMESTAMP,
    })

    expect(batch?.total_price).toBeCloseTo(0.00444725, 12)
  })

  it('leaves units without a batch rate at the standard rate', () => {
    const batch = calcPrice({ input_tokens: MILLION, web_searches: 1000 }, 'claude-opus-5', {
      batch: true,
      providerId: 'anthropic',
      timestamp: TIMESTAMP,
    })

    expect(batch?.model_price.input_mtok).toBe(2.5)
    expect(batch?.model_price.web_searches_kcount).toBe(10)
    expect(batch?.total_price).toBe(12.5)
  })

  it('falls back to standard prices when a model has no batch prices', () => {
    const usage = { input_tokens: 1000, output_tokens: 1000 }
    const standard = calcPrice(usage, 'deepseek-v4-pro', { providerId: 'deepseek', timestamp: TIMESTAMP })
    const batch = calcPrice(usage, 'deepseek-v4-pro', { batch: true, providerId: 'deepseek', timestamp: TIMESTAMP })

    expect(batch?.total_price).toBe(standard?.total_price)
  })

  it('overrides standard prices key by key', () => {
    const model: ModelInfo = {
      batch_prices: { output_mtok: 5 },
      id: 'test',
      match: { equals: 'test' },
      prices: { input_mtok: 10, output_mtok: 20, requests_kcount: 1 },
    }

    expect(getActiveModelPrice(model, TIMESTAMP, true)).toEqual({ input_mtok: 10, output_mtok: 5, requests_kcount: 1 })
    expect(getActiveModelPrice(model, TIMESTAMP)).toEqual({ input_mtok: 10, output_mtok: 20, requests_kcount: 1 })
  })

  it('resolves batch conditional prices independently of standard ones', () => {
    const model: ModelInfo = {
      batch_prices: [
        { prices: { input_mtok: 5 } },
        { constraint: { start_date: '2026-06-01', type: 'start_date' }, prices: { input_mtok: 8 } },
      ],
      id: 'test',
      match: { equals: 'test' },
      prices: [
        { prices: { input_mtok: 10 } },
        { constraint: { start_date: '2026-01-01', type: 'start_date' }, prices: { input_mtok: 20 } },
      ],
    }

    expect(getActiveModelPrice(model, new Date('2025-06-01T00:00:00Z'), true)).toEqual({ input_mtok: 5 })
    expect(getActiveModelPrice(model, new Date('2026-03-01T00:00:00Z'), true)).toEqual({ input_mtok: 5 })
    expect(getActiveModelPrice(model, new Date('2026-08-01T00:00:00Z'), true)).toEqual({ input_mtok: 8 })
    expect(getActiveModelPrice(model, new Date('2026-08-01T00:00:00Z'))).toEqual({ input_mtok: 20 })
  })

  it('normalizes wire-format constraints in caller-supplied batch prices', () => {
    // The published feed identifies a constraint structurally, without the internal `type` discriminator.
    const wirePrices = [
      { prices: { input_mtok: 5 } },
      { constraint: { start_date: '2026-06-01' }, prices: { input_mtok: 8 } },
    ] as unknown as ConditionalPrice[]
    const provider: Provider = {
      api_pattern: '.*',
      id: 'test',
      models: [{ batch_prices: wirePrices, id: 'test', match: { equals: 'test' }, prices: { input_mtok: 10 } }],
      name: 'Test',
    }

    const batch = calcPrice({ input_tokens: MILLION }, 'test', { batch: true, provider, timestamp: TIMESTAMP })

    expect(batch?.total_price).toBe(8)
  })
})
