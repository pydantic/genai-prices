import { describe, it, expect, beforeAll, vi, beforeEach } from 'vitest'
import { calcPriceSync, calcPriceAsync, enableAutoUpdate, Usage } from '../index.js'
import * as dataLoader from '../dataLoader.js'

// Mock data for sync tests
const mockProviders = [
  {
    id: 'openai',
    name: 'OpenAI',
    apiPattern: 'https://api.openai.com',
    pricingUrls: ['https://openai.com/pricing'],
    description: 'OpenAI API',
    priceComments: '',
    modelMatch: { or: [{ starts_with: 'gpt-' }, { equals: 'o1' }] },
    models: [
      {
        id: 'gpt-3.5-turbo',
        match: { equals: 'gpt-3.5-turbo' },
        name: 'GPT-3.5 Turbo',
        description: 'GPT-3.5 Turbo model',
        contextWindow: 16385,
        priceComments: '',
        prices: {
          inputMtok: 0.5,
          outputMtok: 1.5,
          requestsKcount: 0.002,
        },
      },
      {
        id: 'gpt-4o',
        match: { equals: 'gpt-4o' },
        name: 'GPT-4o',
        description: 'GPT-4o model',
        contextWindow: 128000,
        priceComments: '',
        prices: {
          inputMtok: 5,
          outputMtok: 15,
          requestsKcount: 0.01,
        },
      },
      {
        id: 'o1',
        match: { equals: 'o1' },
        name: 'O1',
        description: 'O1 model',
        contextWindow: 32768,
        priceComments: '',
        prices: {
          inputMtok: 15,
          outputMtok: 60,
          requestsKcount: 0.05,
        },
      },
    ],
  },
  {
    id: 'google',
    name: 'Google',
    apiPattern: 'https://generativelanguage.googleapis.com',
    pricingUrls: ['https://ai.google.dev/pricing'],
    description: 'Google AI',
    priceComments: '',
    modelMatch: { starts_with: 'gemini' },
    models: [
      {
        id: 'gemini-1.5-pro',
        match: { equals: 'gemini-1.5-pro' },
        name: 'Gemini 1.5 Pro',
        description: 'Gemini 1.5 Pro model',
        contextWindow: 1000000,
        priceComments: '',
        prices: {
          inputMtok: { base: 3.5, tiers: [{ start: 1000000, price: 1.75 }] },
          outputMtok: 10.5,
          requestsKcount: 0.007,
        },
      },
    ],
  },
]

describe('calcPriceSync', () => {
  beforeEach(() => {
    // Mock getProvidersSync for sync tests
    vi.spyOn(dataLoader, 'getProvidersSync').mockReturnValue(mockProviders)
  })

  it('calculates price for gpt-3.5-turbo (sync, local only)', () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 }
    const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
    expect(result.price).toBeGreaterThanOrEqual(0)
    expect(result.provider.name).toMatch(/OpenAI/i)
    expect(result.model.name?.toLowerCase()).toContain('gpt')
  })

  it('calculates tiered pricing for Gemini 1.5 Pro (Google)', () => {
    const usage: Usage = { inputTokens: 2_000_000, outputTokens: 1000 }
    const result = calcPriceSync(usage, 'gemini-1.5-pro', { providerId: 'google' })
    expect(result.price).toBeGreaterThan(0)
    expect(result.provider.name).toMatch(/Google/i)
    expect(result.model.name?.toLowerCase()).toContain('gemini')
  })

  it('throws error for invalid provider', () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 }
    expect(() => calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'notaprovider' })).toThrow(/Provider not found/)
  })

  it('throws error for invalid model', () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 }
    expect(() => calcPriceSync(usage, 'not-a-real-model', { providerId: 'openai' })).toThrow(/Model not found/)
  })

  it('calculates historic pricing for gpt-4o (OpenAI)', () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 }
    const result = calcPriceSync(usage, 'gpt-4o', {
      providerId: 'openai',
      timestamp: new Date('2024-01-01T12:00:00Z'),
    })
    expect(result.price).toBeGreaterThanOrEqual(0)
    expect(result.provider.name).toMatch(/OpenAI/i)
    expect(result.model.name?.toLowerCase()).toContain('gpt')
  })

  it('calculates prices for multiple models (sync)', () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 }
    const models = ['gpt-3.5-turbo', 'gpt-4o', 'o1']
    const results = models.map((model) =>
      calcPriceSync(usage, model, { providerId: model === 'o1' ? 'openai' : undefined }),
    )
    expect(results.length).toBe(models.length)
    for (const result of results) {
      expect(result.price).toBeGreaterThanOrEqual(0)
      expect(result.provider.name).toBeTruthy()
      expect(result.model.name).toBeTruthy()
    }
  })
})

describe('calcPriceAsync', () => {
  beforeAll(() => {
    enableAutoUpdate()
  })

  it('calculates price for gpt-3.5-turbo (async, fetches remote)', async () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 }
    const result = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
    expect(result.price).toBeGreaterThanOrEqual(0)
    expect(result.provider.name).toMatch(/OpenAI/i)
    expect(result.model.name?.toLowerCase()).toContain('gpt')
  })

  it('calculates tiered pricing for Gemini 1.5 Pro (Google)', async () => {
    const usage: Usage = { inputTokens: 2_000_000, outputTokens: 1000 }
    const result = await calcPriceAsync(usage, 'gemini-1.5-pro', { providerId: 'google' })
    expect(result.price).toBeGreaterThan(0)
    expect(result.provider.name).toMatch(/Google/i)
    expect(result.model.name?.toLowerCase()).toContain('gemini')
  })

  it('throws error for invalid provider', async () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 }
    await expect(calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'notaprovider' })).rejects.toThrow(
      /Provider not found/,
    )
  })

  it('throws error for invalid model', async () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 }
    await expect(calcPriceAsync(usage, 'not-a-real-model', { providerId: 'openai' })).rejects.toThrow(
      /Model not found/,
    )
  })

  it('calculates historic pricing for gpt-4o (OpenAI)', async () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 }
    const result = await calcPriceAsync(usage, 'gpt-4o', {
      providerId: 'openai',
      timestamp: new Date('2024-01-01T12:00:00Z'),
    })
    expect(result.price).toBeGreaterThanOrEqual(0)
    expect(result.provider.name).toMatch(/OpenAI/i)
    expect(result.model.name?.toLowerCase()).toContain('gpt')
  })

  it('returns a Promise and uses cache on subsequent calls', async () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 }
    const first = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
    const second = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
    expect(second.price).toBe(first.price)
    expect(second.provider.name).toBe(first.provider.name)
  })

  it('calculates prices for multiple models (async)', async () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 }
    const models = ['gpt-3.5-turbo', 'gpt-4o', 'o1']
    const results = await Promise.all(
      models.map((model) => calcPriceAsync(usage, model, { providerId: model === 'o1' ? 'openai' : undefined })),
    )
    expect(results.length).toBe(models.length)
    for (const result of results) {
      expect(result.price).toBeGreaterThanOrEqual(0)
      expect(result.provider.name).toBeTruthy()
      expect(result.model.name).toBeTruthy()
    }
  })
})
