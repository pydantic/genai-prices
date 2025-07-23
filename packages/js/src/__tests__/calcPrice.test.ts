import { describe, it, expect, beforeAll, vi, beforeEach } from 'vitest'
import * as dataLoader from '../dataLoader.js'
import { calcPriceSync } from '../sync/calcPriceSync.js'
import { calcPriceAsync } from '../async/calcPriceAsync.js'
import { enableAutoUpdate } from '../dataLoader.js'
import type { Usage } from '../types.js'

// Mock data for sync tests
const mockProviders = [
  {
    id: 'openai',
    name: 'OpenAI',
    api_pattern: '',
    pricing_urls: [],
    description: '',
    price_comments: '',
    models: [
      {
        id: 'gpt-3.5-turbo',
        match: { equals: 'gpt-3.5-turbo' },
        name: 'gpt 3.5 turbo',
        description: '',
        context_window: 16385,
        price_comments: '',
        prices: { input_mtok: 0.0005, output_mtok: 0.0015 },
      },
      {
        id: 'gpt-4o',
        match: { equals: 'gpt-4o' },
        name: 'gpt-4o',
        description: '',
        context_window: 128000,
        price_comments: '',
        prices: { input_mtok: 0.0005, output_mtok: 0.0015 },
      },
      {
        id: 'o1',
        match: { equals: 'o1' },
        name: 'O1',
        description: '',
        context_window: 32768,
        price_comments: '',
        prices: { input_mtok: 0.001, output_mtok: 0.002 },
      },
    ],
  },
  {
    id: 'google',
    name: 'Google',
    api_pattern: '',
    pricing_urls: [],
    description: '',
    price_comments: '',
    models: [
      {
        id: 'gemini-1.5-pro',
        match: { equals: 'gemini-1.5-pro' },
        name: 'Gemini 1.5 Pro',
        description: '',
        context_window: 1000000,
        price_comments: '',
        prices: { input_mtok: 0.00025, output_mtok: 0.0005 },
      },
    ],
  },
]

beforeEach(() => {
  vi.spyOn(dataLoader, 'getProvidersSync').mockImplementation(() => mockProviders)
})

describe('calcPriceSync', () => {
  beforeEach(() => {
    // Mock getProvidersSync for sync tests
    vi.spyOn(dataLoader, 'getProvidersSync').mockReturnValue(mockProviders)
  })

  it('calculates price for gpt-3.5-turbo (sync, local only)', () => {
    const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
    const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
    expect(result).not.toBeNull()
    expect(result!.price).toBeGreaterThanOrEqual(0)
    expect(result!.provider.name).toMatch(/OpenAI/i)
    expect(result!.model.name?.toLowerCase()).toContain('gpt')
  })

  it('calculates tiered pricing for Gemini 1.5 Pro (Google)', () => {
    const usage: Usage = { input_tokens: 2_000_000, output_tokens: 1000 }
    const result = calcPriceSync(usage, 'gemini-1.5-pro', { providerId: 'google' })
    expect(result).not.toBeNull()
    expect(result!.price).toBeGreaterThan(0)
    expect(result!.provider.name).toMatch(/Google/i)
    expect(result!.model.name?.toLowerCase()).toContain('gemini')
  })

  it('returns null for invalid provider', () => {
    const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
    const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'notaprovider' })
    expect(result).toBeNull()
  })

  it('returns null for invalid model', () => {
    const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
    const result = calcPriceSync(usage, 'not-a-real-model', { providerId: 'openai' })
    expect(result).toBeNull()
  })

  it('calculates historic pricing for gpt-4o (OpenAI)', () => {
    const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
    const result = calcPriceSync(usage, 'gpt-4o', {
      providerId: 'openai',
      timestamp: new Date('2024-01-01T12:00Z'),
    })
    expect(result).not.toBeNull()
    expect(result!.price).toBeGreaterThanOrEqual(0)
    expect(result!.provider.name).toMatch(/OpenAI/i)
    expect(result!.model.name?.toLowerCase()).toContain('gpt')
  })

  it('calculates prices for multiple models (sync)', () => {
    const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
    const models = ['gpt-3.5-turbo', 'gpt-4o', 'o1']
    const results = models.map((model) => calcPriceSync(usage, model, { providerId: 'openai' }))
    expect(results.length).toBe(models.length)
    for (const result of results) {
      expect(result).not.toBeNull()
      expect(result!.price).toBeGreaterThanOrEqual(0)
      expect(result!.provider.name).toBeTruthy()
      expect(result!.model.name).toBeTruthy()
    }
  })
})

describe('calcPriceAsync', () => {
  beforeAll(() => {
    enableAutoUpdate()
  })

  it('calculates price for gpt-3.5-turbo (async, fetches remote)', async () => {
    const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
    const result = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
    expect(result).not.toBeNull()
    expect(result!.price).toBeGreaterThanOrEqual(0)
    expect(result!.provider.name).toMatch(/OpenAI/i)
    expect(result!.model.name?.toLowerCase()).toContain('gpt')
  })

  it('calculates tiered pricing for Gemini 1.5 Pro (Google)', async () => {
    const usage: Usage = { input_tokens: 2_000_000, output_tokens: 1000 }
    const result = await calcPriceAsync(usage, 'gemini-1.5-pro', { providerId: 'google' })
    expect(result).not.toBeNull()
    expect(result!.price).toBeGreaterThan(0)
    expect(result!.provider.name).toMatch(/Google/i)
    expect(result!.model.name?.toLowerCase()).toContain('gemini')
  })

  it('returns null for invalid provider', async () => {
    const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
    const result = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'notaprovider' })
    expect(result).toBeNull()
  })

  it('returns null for invalid model', async () => {
    const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
    const result = await calcPriceAsync(usage, 'not-a-real-model', { providerId: 'openai' })
    expect(result).toBeNull()
  })

  it('calculates historic pricing for gpt-4o (OpenAI)', async () => {
    const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
    const result = await calcPriceAsync(usage, 'gpt-4o', {
      providerId: 'openai',
      timestamp: new Date('2024-01-01T12:00:00Z'),
    })
    expect(result).not.toBeNull()
    expect(result!.price).toBeGreaterThanOrEqual(0)
    expect(result!.provider.name).toMatch(/OpenAI/i)
    expect(result!.model.name?.toLowerCase()).toContain('gpt')
  })

  it('returns a Promise and uses cache on subsequent calls', async () => {
    const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
    const first = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
    const second = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
    expect(first).not.toBeNull()
    expect(second).not.toBeNull()
    expect(second!.price).toBe(first!.price)
    expect(second!.provider.name).toBe(first!.provider.name)
  })

  it('calculates prices for multiple models (async)', async () => {
    const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
    const models = ['gpt-3.5-turbo', 'gpt-4o', 'o1']
    const results = await Promise.all(
      models.map((model) => calcPriceAsync(usage, model, { providerId: model === 'o1' ? 'openai' : undefined })),
    )
    expect(results.length).toBe(models.length)
    for (const result of results) {
      expect(result).not.toBeNull()
      expect(result!.price).toBeGreaterThanOrEqual(0)
      expect(result!.provider.name).toBeTruthy()
      expect(result!.model.name).toBeTruthy()
    }
  })
})
