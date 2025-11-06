/* eslint-disable @typescript-eslint/no-non-null-assertion */
/* eslint-disable @typescript-eslint/no-unsafe-assignment */
import { readFileSync } from 'fs'
import path from 'path'
import { describe, expect, it } from 'vitest'

import { calcPrice, extractUsage, findProvider, Usage } from '../index'

const USAGES_FILE = path.join(__dirname, '../../../../tests/dataset/usages.json')
const USAGES_STRING = readFileSync(USAGES_FILE, 'utf-8')
const USAGES: UsageRow[] = JSON.parse(USAGES_STRING)

/*
example usage:

  {
    "body": {
      "model": "gpt-5-2025-08-07",
      "usage": {
        "input_tokens": 45,
        "input_tokens_details": {
          "cached_tokens": 0
        },
        "output_tokens": 1719,
        "output_tokens_details": {
          "reasoning_tokens": 1408
        },
        "total_tokens": 1764
      }
    },
    "extracted": [
      {
        "extractors": [
          {
            "api_flavor": "default",
            "provider_id": "anthropic"
          },
          {
            "api_flavor": "anthropic",
            "provider_id": "google"
          },
          {
            "api_flavor": "responses",
            "input_price": "0.00005625",
            "output_price": "0.01719",
            "provider_id": "openai"
          }
        ],
        "usage": {
          "input_tokens": 45,
          "output_tokens": 1719
        }
      }
    ],
    "model": "gpt-5-2025-08-07"
  },

 */

interface UsageRow {
  body: unknown
  extracted: ExtractedUsage[]
  model?: string
}

interface ExtractedUsage {
  extractors: ExtractorInfo[]
  usage: Usage
}

interface ExtractorInfo {
  api_flavor: string
  input_price?: string
  output_price?: string
  provider_id: string
}

describe('dataset', () => {
  USAGES.forEach((usage, index) => {
    it(`should handle row ${(index + 1).toString()}`, () => {
      for (const extracted of usage.extracted) {
        for (const extractor of extracted.extractors) {
          const provider = findProvider({ providerId: extractor.provider_id })!
          const { model, usage: extractedUsage } = extractUsage(provider, usage.body, extractor.api_flavor)
          if (!model) {
            expect(usage.model).toBeUndefined()
          } else {
            expect(model).toBe(usage.model)
            const price = calcPrice(extracted.usage, model, { provider })
            if (price) {
              expect(price.input_price).toBeCloseTo(parseFloat(extractor.input_price!))
              expect(price.output_price).toBeCloseTo(parseFloat(extractor.output_price!))
            } else {
              expect(extractor.input_price).toBeUndefined()
              expect(extractor.output_price).toBeUndefined()
            }
          }
          for (const key of Object.keys(extracted.usage)) {
            const k = key as keyof Usage
            expect(extractedUsage[k]).toBe(extracted.usage[k])
          }
        }
      }
    })
  })
})
