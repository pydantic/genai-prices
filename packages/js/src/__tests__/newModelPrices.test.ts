import { describe, expect, it } from 'vitest'

import { calcPrice } from '../api'

const mtok = (rate: number, tokens: number) => (rate * tokens) / 1_000_000

describe('GPT-6 published prices', () => {
  const models = [
    ['gpt-6-astra', 10, 1, 12.5, 50],
    ['gpt-6-sol', 2, 0.2, 2.5, 10],
    ['gpt-6-luna', 0.1, 0.01, 0.125, 0.5],
  ] as const
  for (const [model, input, read, write, output] of models) {
    for (const tokens of [271_999, 272_000, 272_001, 1_000_000]) {
      for (const suffix of ['', '-2026-09-22']) {
        it(`${model}${suffix} at ${String(tokens)} input tokens prices fresh/read/write and reasoning once`, () => {
          const price = calcPrice(
            {
              cache_read_tokens: 20_000,
              cache_write_tokens: 10_000,
              input_tokens: tokens,
              output_reasoning_tokens: 700,
              output_tokens: 1_000,
            },
            model + suffix,
            { providerId: 'openai' }
          )
          const inputFactor = tokens > 272_000 ? 2 : 1
          const outputFactor = tokens > 272_000 ? 1.5 : 1
          const expectedInput = inputFactor * (mtok(input, tokens - 30_000) + mtok(read, 20_000) + mtok(write, 10_000))
          const expectedOutput = outputFactor * mtok(output, 1_000)
          expect(price?.model.id).toBe(model)
          expect(price?.input_price).toBeCloseTo(expectedInput, 12)
          expect(price?.output_price).toBeCloseTo(expectedOutput, 12)
          expect(price?.total_price).toBeCloseTo(expectedInput + expectedOutput, 12)
        })
      }
    }
  }
})

describe('Opus 5.5 specific matching and cache durations', () => {
  for (const model of ['claude-opus-5-5', 'claude-opus-5-5-20260922', 'claude-opus-5.5']) {
    for (const tokens of [100_000, 1_000_000]) {
      it(`${model} at ${String(tokens)} input tokens has no context surcharge`, () => {
        const price = calcPrice(
          {
            cache_read_tokens: 50_000,
            cache_write_1h_tokens: 10_000,
            cache_write_5m_tokens: 40_000,
            cache_write_tokens: 50_000,
            input_tokens: tokens,
            output_tokens: 1_000,
          },
          model,
          { providerId: 'anthropic' }
        )
        const expectedInput = mtok(4, tokens - 100_000) + mtok(0.2, 50_000) + mtok(5, 40_000) + mtok(8, 10_000)
        expect(price?.model.id).toBe('claude-opus-5-5')
        expect(price?.input_price).toBeCloseTo(expectedInput, 12)
        expect(price?.output_price).toBeCloseTo(mtok(20, 1_000), 12)
      })
    }
  }
})

describe('Gemini introductory price expiry', () => {
  for (const model of ['gemini-3.7-flash', 'gemini-3.8-flash']) {
    for (const [timestamp, factor] of [
      ['2026-12-31T23:59:59.999Z', 1],
      ['2027-01-01T00:00:00.000Z', 2],
    ] as const) {
      it(`${model} at ${timestamp} keeps the historical request rates`, () => {
        const price = calcPrice({ cache_read_tokens: 100_000, input_tokens: 1_000_000, output_tokens: 100_000 }, model, {
          providerId: 'google',
          timestamp: new Date(timestamp),
        })
        expect(price?.input_price).toBeCloseTo(factor * (mtok(0.75, 900_000) + mtok(0.075, 100_000)), 12)
        expect(price?.output_price).toBeCloseTo(factor * mtok(3.75, 100_000), 12)
      })
    }
  }
})

it.each([
  'claude-opus-5',
  'claude-opus-5-latest',
  'claude-opus-5-20260729',
  'claude-opus-5-2026-07-29',
  'claude-opus-5@20260729',
  'claude-opus-5.0',
  'claude-5-opus',
  'claude-5.0-opus',
])('older %s keeps its original Opus 5 prices', (model) => {
  const price = calcPrice({ input_tokens: 1_000_000, output_tokens: 1_000_000 }, model, { providerId: 'anthropic' })
  expect(price?.model.id).toBe('claude-opus-5')
  expect(price?.input_price).toBe(5)
  expect(price?.output_price).toBe(25)
})
