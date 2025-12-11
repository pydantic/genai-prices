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
