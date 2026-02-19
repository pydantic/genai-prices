import { describe, expect, it } from 'vitest'

import type { ModelPrice, Usage } from '../types'

import { calcPrice } from '../engine'

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

    it('should handle web search requests as total cost', () => {
      const usage: Usage = {
        input_tokens: 1000,
        output_tokens: 500,
        tool_use: { web_search: 3 },
      }
      const modelPrice: ModelPrice = {
        input_mtok: 3.0,
        output_mtok: 15.0,
        tool_use_kcount: { web_search: 10 }, // $10 per 1000 web searches
      }

      const result = calcPrice(usage, modelPrice)

      expect(result).toMatchObject({
        input_price: 0.003, // 1000 * 3.0 / 1_000_000
        output_price: 0.0075, // 500 * 15.0 / 1_000_000
        total_price: 0.003 + 0.0075 + (10 * 3) / 1000, // add web search cost to total only
      })
    })

    it('should handle file search requests as total cost', () => {
      const usage: Usage = {
        input_tokens: 1000,
        output_tokens: 500,
        tool_use: { file_search: 4 },
      }
      const modelPrice: ModelPrice = {
        input_mtok: 2.5,
        output_mtok: 10.0,
        tool_use_kcount: { file_search: 2.5 }, // $2.50 per 1000 file searches
      }

      const result = calcPrice(usage, modelPrice)

      expect(result).toMatchObject({
        input_price: 0.0025, // 1000 * 2.5 / 1_000_000
        output_price: 0.005, // 500 * 10.0 / 1_000_000
        total_price: 0.0025 + 0.005 + (2.5 * 4) / 1000, // add file search cost to total only
      })
    })

    it('should not add file search cost when requests is zero', () => {
      const usage: Usage = {
        input_tokens: 1000,
        output_tokens: 500,
        tool_use: { file_search: 0 },
      }
      const modelPrice: ModelPrice = {
        input_mtok: 2.5,
        output_mtok: 10.0,
        tool_use_kcount: { file_search: 2.5 },
      }

      const result = calcPrice(usage, modelPrice)

      expect(result).toMatchObject({
        input_price: 0.0025,
        output_price: 0.005,
        total_price: 0.0025 + 0.005,
      })
    })

    it('should not add web search cost when requests is zero', () => {
      const usage: Usage = {
        input_tokens: 1000,
        output_tokens: 500,
        tool_use: { web_search: 0 },
      }
      const modelPrice: ModelPrice = {
        input_mtok: 3.0,
        output_mtok: 15.0,
        tool_use_kcount: { web_search: 10 },
      }

      const result = calcPrice(usage, modelPrice)

      expect(result).toMatchObject({
        input_price: 0.003,
        output_price: 0.0075,
        total_price: 0.003 + 0.0075,
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
        expected: { input_price: 0.001, output_price: 0, total_price: 0.001 },
        modelPrice: { input_mtok: 1.0, output_mtok: 2.0 } as ModelPrice,
        name: 'mixed zero and defined tokens',
        usage: { input_tokens: 1000, output_tokens: 0 } as Usage,
      },
    ])('should handle $name', ({ expected, modelPrice, usage }) => {
      const result = calcPrice(usage, modelPrice)
      expect(result).toMatchObject(expected)
    })
  })
})
