import { describe, expect, it } from 'vitest'

import type { ModelPrice, Usage } from '../types'

import { calcPrice } from '../engine'

describe('Threshold-based Tiered Pricing', () => {
  describe('Claude Sonnet 4.5 pricing model', () => {
    const claudeInputPrice: ModelPrice = {
      input_mtok: {
        base: 3.0,
        tiers: [{ price: 6.0, start: 200000 }],
      },
    }

    it('should charge base rate for tokens below threshold (100K)', () => {
      const usage: Usage = { input_tokens: 100000 }
      const result = calcPrice(usage, claudeInputPrice)

      // 100,000 tokens at $3/MTok = $0.30
      expect(result.input_price).toBe(0.3)
      expect(result.total_price).toBe(0.3)
    })

    it('should charge base rate at exactly threshold (200K)', () => {
      const usage: Usage = { input_tokens: 200000 }
      const result = calcPrice(usage, claudeInputPrice)

      // Threshold is "> 200000", so exactly 200K uses base rate
      // 200,000 tokens at $3/MTok = $0.60
      expect(result.input_price).toBe(0.6)
      expect(result.total_price).toBe(0.6)
    })

    it('should charge tier rate for ALL tokens just above threshold (200,001)', () => {
      const usage: Usage = { input_tokens: 200001 }
      const result = calcPrice(usage, claudeInputPrice)

      // Crossing threshold: ALL tokens at $6/MTok
      // 200,001 tokens at $6/MTok = $1.200006
      expect(result.input_price).toBeCloseTo(1.200006, 6)
      expect(result.total_price).toBeCloseTo(1.200006, 6)
    })

    it('should charge tier rate for ALL tokens well above threshold (1M)', () => {
      const usage: Usage = { input_tokens: 1000000 }
      const result = calcPrice(usage, claudeInputPrice)

      // 1,000,000 tokens at $6/MTok = $6.00
      expect(result.input_price).toBe(6.0)
      expect(result.total_price).toBe(6.0)
    })
  })

  describe('Google Gemini pricing model', () => {
    const geminiInputPrice: ModelPrice = {
      input_mtok: {
        base: 0.075,
        tiers: [{ price: 0.15, start: 128000 }],
      },
    }

    it('should charge base rate for tokens below threshold (100K)', () => {
      const usage: Usage = { input_tokens: 100000 }
      const result = calcPrice(usage, geminiInputPrice)

      // 100,000 tokens at $0.075/MTok = $0.0075
      expect(result.input_price).toBe(0.0075)
      expect(result.total_price).toBe(0.0075)
    })

    it('should charge tier rate for ALL tokens above threshold (500K)', () => {
      const usage: Usage = { input_tokens: 500000 }
      const result = calcPrice(usage, geminiInputPrice)

      // Crossing threshold: ALL tokens at $0.15/MTok
      // 500,000 tokens at $0.15/MTok = $0.075
      expect(result.input_price).toBe(0.075)
      expect(result.total_price).toBe(0.075)
    })
  })

  describe('Multiple tier levels', () => {
    it('should apply highest crossed tier to ALL tokens', () => {
      const multiTierPrice: ModelPrice = {
        input_mtok: {
          base: 1.0,
          tiers: [
            { price: 0.8, start: 100000 },
            { price: 0.6, start: 500000 },
            { price: 0.4, start: 1000000 },
          ],
        },
      }

      // Below first tier: all at base
      expect(calcPrice({ input_tokens: 50000 }, multiTierPrice).input_price).toBe(0.05)

      // Between tier 1 and 2: all at tier 1
      expect(calcPrice({ input_tokens: 300000 }, multiTierPrice).input_price).toBe(0.24)

      // Between tier 2 and 3: all at tier 2
      expect(calcPrice({ input_tokens: 750000 }, multiTierPrice).input_price).toBe(0.45)

      // Above tier 3: all at tier 3
      expect(calcPrice({ input_tokens: 2000000 }, multiTierPrice).input_price).toBe(0.8)
    })
  })

  describe('Comprehensive multi-tier pricing model', () => {
    /**
     * Mock multi-tier model with different tier structures for input vs output:
     *
     * Input tokens:
     * - Base: $1/MTok (<=100K)
     * - Tier 1: $2/MTok (>100K, <=500K)
     * - Tier 2: $3/MTok (>500K, <=1M)
     * - Tier 3: $5/MTok (>1M)
     *
     * Output tokens (different thresholds and prices to test independent tier calculation):
     * - Base: $3/MTok (<=200K)
     * - Tier 1: $5/MTok (>200K, <=1M)
     * - Tier 2: $8/MTok (>1M)
     */
    const multiTierPrice: ModelPrice = {
      input_mtok: {
        base: 1.0,
        tiers: [
          { price: 2.0, start: 100000 },
          { price: 3.0, start: 500000 },
          { price: 5.0, start: 1000000 },
        ],
      },
      output_mtok: {
        base: 3.0,
        tiers: [
          { price: 5.0, start: 200000 },
          { price: 8.0, start: 1000000 },
        ],
      },
    }

    it('should charge base pricing for tokens below first tier (50K)', () => {
      // Pricing: Base $1/MTok (<=100K)
      // Calculation: (1 * 50,000) / 1,000,000 = $0.05
      const usage: Usage = { input_tokens: 50000 }
      const result = calcPrice(usage, multiTierPrice)

      expect(result.input_price).toBe(0.05)
      expect(result.output_price).toBe(0)
      expect(result.total_price).toBe(0.05)
    })

    it('should charge base rate exactly at first threshold (100K)', () => {
      // Pricing: Threshold is '> 100000', so exactly 100K uses base
      // Calculation: (1 * 100,000) / 1,000,000 = $0.10
      const usage: Usage = { input_tokens: 100000 }
      const result = calcPrice(usage, multiTierPrice)

      expect(result.input_price).toBe(0.1)
      expect(result.output_price).toBe(0)
      expect(result.total_price).toBe(0.1)
    })

    it('should charge first tier for ALL tokens in range (200K)', () => {
      // Pricing: Tier 1 $2/MTok (>100K, <=500K)
      // Calculation: ALL tokens at tier 1: (2 * 200,000) / 1,000,000 = $0.40
      const usage: Usage = { input_tokens: 200000 }
      const result = calcPrice(usage, multiTierPrice)

      expect(result.input_price).toBe(0.4)
      expect(result.output_price).toBe(0)
      expect(result.total_price).toBe(0.4)
    })

    it('should charge first tier exactly at second threshold (500K)', () => {
      // Pricing: Threshold is '> 500000', so exactly 500K uses tier 1
      // Calculation: (2 * 500,000) / 1,000,000 = $1.00
      const usage: Usage = { input_tokens: 500000 }
      const result = calcPrice(usage, multiTierPrice)

      expect(result.input_price).toBe(1.0)
      expect(result.output_price).toBe(0)
      expect(result.total_price).toBe(1.0)
    })

    it('should charge second tier for ALL tokens in range (750K)', () => {
      // Pricing: Tier 2 $3/MTok (>500K, <=1M)
      // Calculation: ALL tokens at tier 2: (3 * 750,000) / 1,000,000 = $2.25
      const usage: Usage = { input_tokens: 750000 }
      const result = calcPrice(usage, multiTierPrice)

      expect(result.input_price).toBe(2.25)
      expect(result.output_price).toBe(0)
      expect(result.total_price).toBe(2.25)
    })

    it('should charge second tier exactly at third threshold (1M)', () => {
      // Pricing: Threshold is '> 1000000', so exactly 1M uses tier 2
      // Calculation: (3 * 1,000,000) / 1,000,000 = $3.00
      const usage: Usage = { input_tokens: 1000000 }
      const result = calcPrice(usage, multiTierPrice)

      expect(result.input_price).toBe(3.0)
      expect(result.output_price).toBe(0)
      expect(result.total_price).toBe(3.0)
    })

    it('should charge third tier for ALL tokens above threshold (2M)', () => {
      // Pricing: Tier 3 $5/MTok (>1M)
      // Calculation: ALL tokens at tier 3: (5 * 2,000,000) / 1,000,000 = $10.00
      const usage: Usage = { input_tokens: 2000000 }
      const result = calcPrice(usage, multiTierPrice)

      expect(result.input_price).toBe(10.0)
      expect(result.output_price).toBe(0)
      expect(result.total_price).toBe(10.0)
    })

    it('should charge base tier for input and output tokens (50K input + 10K output)', () => {
      // Input: 50K tokens (base tier for input)
      // Output: 10K tokens (base tier for output)
      //
      // Pricing:
      // - Input base: $1/MTok (tier determined by 50K <= 100K)
      // - Output base: $3/MTok (tier determined by 50K <= 200K)
      //
      // Calculation:
      // - Input: (1 * 50,000) / 1,000,000 = $0.05
      // - Output: (3 * 10,000) / 1,000,000 = $0.03
      // - Total: $0.05 + $0.03 = $0.08
      const usage: Usage = { input_tokens: 50000, output_tokens: 10000 }
      const result = calcPrice(usage, multiTierPrice)

      expect(result.input_price).toBe(0.05)
      expect(result.output_price).toBe(0.03)
      expect(result.total_price).toBe(0.08)
    })

    it('should charge different tiers for input and output (600K input + 250K output)', () => {
      // Input: 600K tokens (input tier 2: >500K, <=1M)
      // Output: 250K tokens (output tier 1: >200K, <=1M)
      //
      // Pricing:
      // - Input tier 2: $3/MTok (determined by 600K > 500K)
      // - Output tier 1: $5/MTok (determined by 600K > 200K but <= 1M)
      //
      // Calculation:
      // - Input: (3 * 600,000) / 1,000,000 = $1.80
      // - Output: (5 * 250,000) / 1,000,000 = $1.25
      // - Total: $1.80 + $1.25 = $3.05
      const usage: Usage = { input_tokens: 600000, output_tokens: 250000 }
      const result = calcPrice(usage, multiTierPrice)

      expect(result.input_price).toBe(1.8)
      expect(result.output_price).toBe(1.25)
      expect(result.total_price).toBe(3.05)
    })

    it('should charge highest tier for input and output tokens (1.5M input + 500K output)', () => {
      // Input: 1.5M tokens (input tier 3: >1M)
      // Output: 500K tokens (output tier 2: >1M)
      //
      // Pricing:
      // - Input tier 3: $5/MTok (determined by 1.5M > 1M)
      // - Output tier 2: $8/MTok (determined by 1.5M > 1M, output has only 2 tiers)
      //
      // Calculation:
      // - Input: (5 * 1,500,000) / 1,000,000 = $7.50
      // - Output: (8 * 500,000) / 1,000,000 = $4.00
      // - Total: $7.50 + $4.00 = $11.50
      const usage: Usage = { input_tokens: 1500000, output_tokens: 500000 }
      const result = calcPrice(usage, multiTierPrice)

      expect(result.input_price).toBe(7.5)
      expect(result.output_price).toBe(4.0)
      expect(result.total_price).toBe(11.5)
    })

    it('should transition at tier boundaries (100,001 tokens)', () => {
      // Test with 100,001 tokens (just above first threshold).
      // Should use tier 1 pricing for ALL tokens.
      //
      // Calculation: (2 * 100,001) / 1,000,000 = $0.200002
      const usage: Usage = { input_tokens: 100001 }
      const result = calcPrice(usage, multiTierPrice)

      expect(result.input_price).toBeCloseTo(0.200002, 6)
      expect(result.output_price).toBe(0)
      expect(result.total_price).toBeCloseTo(0.200002, 6)
    })
  })

  describe('Edge cases', () => {
    it('should handle zero tokens', () => {
      const price: ModelPrice = {
        input_mtok: { base: 3.0, tiers: [{ price: 6.0, start: 200000 }] },
      }
      const result = calcPrice({ input_tokens: 0 }, price)
      expect(result.input_price).toBe(0)
    })

    it('should handle undefined tokens', () => {
      const price: ModelPrice = {
        input_mtok: { base: 3.0, tiers: [{ price: 6.0, start: 200000 }] },
      }
      const result = calcPrice({}, price)
      expect(result.input_price).toBe(0)
    })
  })
})
