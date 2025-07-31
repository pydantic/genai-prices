import { describe, it, expect } from 'vitest'
import { calcPrice } from '../priceCalc.js'
import type { Usage, ModelPrice } from '../types.js'

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

      expect(result.input_price).toBe(0.0015) // 1000 * 1.5 / 1_000_000
      expect(result.output_price).toBe(0.001) // 500 * 2.0 / 1_000_000
      expect(result.total_price).toBe(0.0025) // 0.0015 + 0.001
    })

    it('should handle cache tokens as input costs', () => {
      const usage: Usage = {
        input_tokens: 1000,
        cache_write_tokens: 200,
        cache_read_tokens: 100,
        output_tokens: 500,
      }
      const modelPrice: ModelPrice = {
        input_mtok: 1.0,
        cache_write_mtok: 0.5,
        cache_read_mtok: 0.1,
        output_mtok: 2.0,
      }

      const result = calcPrice(usage, modelPrice)

      expect(result.input_price).toBe(0.001 + 0.0001 + 0.00001) // input + cache_write + cache_read
      expect(result.output_price).toBe(0.001) // output only
      expect(result.total_price).toBe(result.input_price + result.output_price)
    })

    it('should handle audio tokens correctly', () => {
      const usage: Usage = {
        input_audio_tokens: 100,
        output_audio_tokens: 50,
      }
      const modelPrice: ModelPrice = {
        input_audio_mtok: 10.0,
        output_audio_mtok: 20.0,
      }

      const result = calcPrice(usage, modelPrice)

      expect(result.input_price).toBe(0.001) // 100 * 10.0 / 1_000_000
      expect(result.output_price).toBe(0.001) // 50 * 20.0 / 1_000_000
      expect(result.total_price).toBe(0.002)
    })

    it('should handle requests as input cost', () => {
      const usage: Usage = {
        input_tokens: 1000,
        output_tokens: 500,
        requests: 2,
      }
      const modelPrice: ModelPrice = {
        input_mtok: 1.0,
        output_mtok: 2.0,
        requests_kcount: 0.5, // $0.50 per thousand requests
      }

      const result = calcPrice(usage, modelPrice)

      expect(result.input_price).toBe(0.001 + 0.001) // input tokens + requests (2 * 0.5 / 1000)
      expect(result.output_price).toBe(0.001) // output tokens only
      expect(result.total_price).toBe(result.input_price + result.output_price)
    })

    it('should handle tiered pricing', () => {
      const usage: Usage = {
        input_tokens: 150000, // 150k tokens
        output_tokens: 50000, // 50k tokens
      }
      const modelPrice: ModelPrice = {
        input_mtok: {
          base: 1.0,
          tiers: [
            { start: 100000, price: 0.5 }, // $0.50 per million after 100k
          ],
        },
        output_mtok: 2.0,
      }

      const result = calcPrice(usage, modelPrice)

      // Input: 100k at $1.0 + 50k at $0.5 = 0.1 + 0.025 = 0.125
      expect(result.input_price).toBe(0.125)
      // Output: 50k at $2.0 = 0.1
      expect(result.output_price).toBe(0.1)
      expect(result.total_price).toBe(0.225)
    })

    it('should handle zero tokens', () => {
      const usage: Usage = {
        input_tokens: 0,
        output_tokens: 0,
      }
      const modelPrice: ModelPrice = {
        input_mtok: 1.0,
        output_mtok: 2.0,
      }

      const result = calcPrice(usage, modelPrice)

      expect(result.input_price).toBe(0)
      expect(result.output_price).toBe(0)
      expect(result.total_price).toBe(0)
    })

    it('should handle undefined tokens', () => {
      const usage: Usage = {}
      const modelPrice: ModelPrice = {
        input_mtok: 1.0,
        output_mtok: 2.0,
      }

      const result = calcPrice(usage, modelPrice)

      expect(result.input_price).toBe(0)
      expect(result.output_price).toBe(0)
      expect(result.total_price).toBe(0)
    })
  })
})
