import { describe, expect, it } from 'vitest'

import type { ModelPrice, Usage } from '../types'

import { calcPrice, getActiveModelPrice } from '../engine'

const MILLION = 1_000_000

function mtok(rate: number, tokens: number): number {
  return (rate * tokens) / MILLION
}

describe('Core Price Calculation Function', () => {
  describe('calcPrice with separated input/output prices', () => {
    it('should calculate input and output prices separately', () => {
      const usage: Usage = {
        input_tokens: 1000,
        output_tokens: 500,
      }
      const modelPrice: ModelPrice = {
        input_mtok: 1.5, // $1.50 per million input tokens
        output_mtok: 2.0, // $2.00 per million output tokens
      }

      const result = calcPrice(usage, modelPrice)

      expect(result).toMatchObject({
        input_price: 0.0015, // 1000 * 1.5 / 1_000_000
        output_price: 0.001, // 500 * 2.0 / 1_000_000
        total_price: 0.0025, // 0.0015 + 0.001
      })
    })

    it('should handle cache tokens as input costs', () => {
      const usage: Usage = {
        cache_read_tokens: 100,
        cache_write_tokens: 200,
        input_tokens: 1000,
        output_tokens: 500,
      }
      const modelPrice: ModelPrice = {
        cache_read_mtok: 0.1,
        cache_write_mtok: 0.5,
        input_mtok: 1.0,
        output_mtok: 2.0,
      }

      const result = calcPrice(usage, modelPrice)

      const uncachedInputTokens = 1000 - 200 - 100
      const uncachedInputPrice = (uncachedInputTokens * 1.0) / 1_000_000
      const cacheWritePrice = (200 * 0.5) / 1_000_000
      const cacheReadPrice = (100 * 0.1) / 1_000_000
      const inputPrice = uncachedInputPrice + cacheWritePrice + cacheReadPrice
      const outputPrice = (500 * 2.0) / 1_000_000
      const totalPrice = inputPrice + outputPrice
      expect(result).toMatchObject({
        input_price: inputPrice,
        output_price: outputPrice,
        total_price: totalPrice,
      })
    })

    it('should handle audio tokens correctly', () => {
      const usage: Usage = {
        input_audio_tokens: 100,
        input_tokens: 100,
        output_audio_tokens: 50,
        output_tokens: 50,
      }
      const modelPrice: ModelPrice = {
        input_audio_mtok: 10.0,
        output_audio_mtok: 20.0,
      }

      const result = calcPrice(usage, modelPrice)

      expect(result).toMatchObject({
        input_price: 0.001, // 100 * 10.0 / 1_000_000
        output_price: 0.001, // 50 * 20.0 / 1_000_000
        total_price: 0.002,
      })
    })

    it('should charge unpriced descendant tokens through parent prices', () => {
      const usage: Usage = {
        input_audio_tokens: 200,
        input_tokens: 700,
        output_audio_tokens: 20,
        output_tokens: 70,
      }
      const modelPrice: ModelPrice = {
        input_mtok: 5.0,
        output_mtok: 10.0,
      }

      const result = calcPrice(usage, modelPrice)

      const inputPrice = mtok(5.0, 700)
      const outputPrice = mtok(10.0, 70)
      expect(result).toMatchObject({
        input_price: inputPrice,
        output_price: outputPrice,
        total_price: inputPrice + outputPrice,
      })
    })

    it('should charge unpriced cache-audio overlap through one parent bucket', () => {
      const usage: Usage = {
        cache_audio_read_tokens: 100,
        cache_read_tokens: 400,
        input_audio_tokens: 300,
        input_tokens: 1000,
      }
      const modelPrice: ModelPrice = {
        cache_read_mtok: 2.0,
        input_audio_mtok: 3.0,
        input_mtok: 1.0,
      }

      const result = calcPrice(usage, modelPrice)

      const inputPrice = mtok(1.0, 400) + mtok(2.0, 400) + mtok(3.0, 200)
      expect(result).toMatchObject({
        input_price: inputPrice,
        output_price: 0,
        total_price: inputPrice,
      })
    })

    it('should use provided input tokens for output tier thresholds', () => {
      const usage: Usage = {
        input_audio_tokens: 200000,
        input_tokens: 100000,
        output_tokens: 10000,
      }
      const modelPrice: ModelPrice = {
        output_mtok: {
          base: 1.0,
          tiers: [{ price: 2.0, start: 100000 }],
        },
      }

      const result = calcPrice(usage, modelPrice)

      const outputPrice = mtok(1.0, 10000)
      expect(result).toMatchObject({
        input_price: 0,
        output_price: outputPrice,
        total_price: outputPrice,
      })
    })

    it('should handle requests as total cost', () => {
      const usage: Usage = {
        input_tokens: 1000,
        output_tokens: 500,
      }
      const modelPrice: ModelPrice = {
        input_mtok: 1.0,
        output_mtok: 2.0,
        requests_kcount: 0.5, // $0.50 per request
      }

      const result = calcPrice(usage, modelPrice)

      expect(result).toMatchObject({
        input_price: 0.001, // input tokens only
        output_price: 0.001, // output tokens only
        total_price: 0.001 + 0.001 + 0.0005, // add requests (0.5 / 1000) to total only
      })
    })

    it('should handle tiered pricing with threshold model', () => {
      const usage: Usage = {
        input_tokens: 150000, // 150k tokens
        output_tokens: 50000, // 50k tokens
      }
      const modelPrice: ModelPrice = {
        input_mtok: {
          base: 1.0,
          tiers: [
            { price: 0.5, start: 100000 }, // $0.50 per million after 100k (threshold)
          ],
        },
        output_mtok: 2.0,
      }

      const result = calcPrice(usage, modelPrice)

      // Threshold pricing: 150k tokens crosses 100k threshold, so ALL tokens at $0.5
      // Input: 150k at $0.5 = 0.075
      // Output: 50k at $2.0 = 0.1
      expect(result).toMatchObject({
        input_price: 0.075,
        output_price: 0.1,
        total_price: 0.175,
      })
    })

    it.each([
      {
        expected: { input_price: 0, output_price: 0, total_price: 0 },
        modelPrice: { input_mtok: 1.0, output_mtok: 2.0 } as ModelPrice,
        name: 'zero tokens',
        usage: { input_tokens: 0, output_tokens: 0 } as Usage,
      },
      {
        expected: { input_price: 0, output_price: 0, total_price: 0 },
        modelPrice: { input_mtok: 1.0, output_mtok: 2.0 } as ModelPrice,
        name: 'undefined tokens',
        usage: {} as Usage,
      },
      {
        expected: { input_price: 0, output_price: 0, total_price: 0 },
        modelPrice: {} as ModelPrice,
        name: 'absent prices',
        usage: { input_tokens: 1000, output_tokens: 500 } as Usage,
      },
      {
        expected: { input_price: 0.001, output_price: 0, total_price: 0.001 },
        modelPrice: { input_mtok: 1.0, output_mtok: 2.0 } as ModelPrice,
        name: 'mixed zero and defined tokens',
        usage: { input_tokens: 1000, output_tokens: 0 } as Usage,
      },
    ])('should handle $name', ({ expected, modelPrice, usage }) => {
      const result = calcPrice(usage, modelPrice)
      expect(result).toMatchObject(expected)
    })

    it('should apply request-level price modifiers', () => {
      const modelPrice = getActiveModelPrice(
        {
          id: 'test-model',
          match: { equals: 'test-model' },
          prices: {
            input_mtok: 10,
            modifiers: [{ match: { service_tier: 'batch' }, multiplier: 0.5 }],
            output_mtok: 20,
          },
        },
        new Date(),
        { service_tier: 'batch' }
      )

      const result = calcPrice({ input_tokens: 1000, output_tokens: 100 }, modelPrice)

      expect(modelPrice).toEqual({ input_mtok: 5, output_mtok: 10 })
      expect(result).toMatchObject({
        input_price: 0.005,
        output_price: 0.001,
        total_price: 0.006,
      })
    })

    it('should stack request-level price modifiers in order', () => {
      const modelPrice = getActiveModelPrice(
        {
          id: 'test-model',
          match: { equals: 'test-model' },
          prices: {
            input_mtok: 10,
            modifiers: [
              {
                match: { speed: 'fast' },
                not_match: { service_tier: 'batch' },
                price_overrides: { input_mtok: 30, output_mtok: 150 },
              },
              { match: { inference_geo: 'us' }, multiplier: 1.1 },
            ],
            output_mtok: 20,
          },
        },
        new Date(),
        { inference_geo: 'us', speed: 'fast' }
      )

      const result = calcPrice({ input_tokens: 1000, output_tokens: 100 }, modelPrice)

      expect(modelPrice).toEqual({ input_mtok: 33, output_mtok: 165 })
      expect(result).toMatchObject({
        input_price: 0.033,
        output_price: 0.0165,
        total_price: 0.0495,
      })
    })
  })
})
