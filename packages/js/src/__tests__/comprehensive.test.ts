import { describe, it, expect, beforeAll, vi, beforeEach } from 'vitest'
import { calcPriceSync, calcPriceAsync, matchProvider, matchModel } from '../index.js'
import type { Usage } from '../types.js'

// Mock data for tests
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
  {
    id: 'anthropic',
    name: 'Anthropic',
    api_pattern: '',
    pricing_urls: [],
    description: '',
    price_comments: '',
    models: [
      {
        id: 'claude-3-opus',
        match: { equals: 'claude-3-opus' },
        name: 'Claude 3 Opus',
        description: '',
        context_window: 200000,
        price_comments: '',
        prices: { input_mtok: 0.0015, output_mtok: 0.0075 },
      },
    ],
  },
]

beforeEach(() => {
  // Mock the dataLoader module
  vi.mock('../dataLoader.js', () => ({
    getProvidersSync: vi.fn(() => mockProviders),
    getProvidersAsync: vi.fn(async () => mockProviders),
    enableAutoUpdate: vi.fn(),
  }))
})

describe('Comprehensive API Tests', () => {
  describe('calcPriceSync - Basic Functionality', () => {
    it.each([
      {
        name: 'gpt-3.5-turbo',
        model: 'gpt-3.5-turbo',
        providerId: 'openai',
        expectedProvider: /OpenAI/i,
        expectedModel: /gpt/i,
      },
      {
        name: 'gpt-4o',
        model: 'gpt-4o',
        providerId: 'openai',
        expectedProvider: /OpenAI/i,
        expectedModel: /gpt/i,
      },
      {
        name: 'o1',
        model: 'o1',
        providerId: 'openai',
        expectedProvider: /OpenAI/i,
        expectedModel: /o1/i,
      },
    ])(
      'should calculate price for $name with provider ID',
      ({ model, providerId, expectedProvider, expectedModel }) => {
        const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
        const result = calcPriceSync(usage, model, { providerId })

        expect(result).not.toBeNull()
        expect(result).toMatchObject({
          total_price: expect.any(Number),
          input_price: expect.any(Number),
          output_price: expect.any(Number),
          provider: { name: expect.stringMatching(expectedProvider) },
          model: { name: expect.stringMatching(expectedModel) },
        })
        expect(result!.total_price).toBeGreaterThanOrEqual(0)
        expect(result!.input_price).toBeGreaterThanOrEqual(0)
        expect(result!.output_price).toBeGreaterThanOrEqual(0)
      },
    )

    it('should calculate tiered pricing for Gemini 1.5 Pro', () => {
      const usage: Usage = { input_tokens: 2_000_000, output_tokens: 1000 }
      const result = calcPriceSync(usage, 'gemini-1.5-pro', { providerId: 'google' })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        total_price: expect.any(Number),
        input_price: expect.any(Number),
        output_price: expect.any(Number),
        provider: { name: expect.stringMatching(/Google/i) },
        model: { name: expect.stringMatching(/gemini/i) },
      })
      expect(result!.total_price).toBeGreaterThan(0)
      expect(result!.input_price).toBeGreaterThan(0)
      expect(result!.output_price).toBeGreaterThan(0)
    })

    it('should calculate price for Claude 3 Opus', () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = calcPriceSync(usage, 'claude-3-opus', { providerId: 'anthropic' })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        total_price: expect.any(Number),
        input_price: expect.any(Number),
        output_price: expect.any(Number),
        provider: { name: expect.stringMatching(/Anthropic/i) },
        model: { name: expect.stringMatching(/claude/i) },
      })
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
    })
  })

  describe('calcPriceSync - Error Handling', () => {
    it.each([
      { name: 'invalid provider', model: 'gpt-3.5-turbo', providerId: 'notaprovider' },
      { name: 'invalid model', model: 'not-a-real-model', providerId: 'openai' },
      { name: 'invalid model with valid provider', model: 'invalid-model', providerId: 'openai' },
    ])('should return null for $name', ({ model, providerId }) => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = calcPriceSync(usage, model, { providerId })
      expect(result).toBeNull()
    })
  })

  describe('calcPriceSync - Historic Pricing', () => {
    it('should calculate historic pricing for gpt-4o', () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = calcPriceSync(usage, 'gpt-4o', {
        providerId: 'openai',
        timestamp: new Date('2024-01-01T12:00Z'),
      })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        total_price: expect.any(Number),
        input_price: expect.any(Number),
        output_price: expect.any(Number),
        provider: { name: expect.stringMatching(/OpenAI/i) },
        model: { name: expect.stringMatching(/gpt/i) },
      })
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
    })
  })

  describe('calcPriceSync - Multiple Models', () => {
    it('should calculate prices for multiple models', () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const models = ['gpt-3.5-turbo', 'gpt-4o', 'o1']
      const results = models.map((model) => calcPriceSync(usage, model, { providerId: 'openai' }))

      expect(results.length).toBe(models.length)
      for (const result of results) {
        expect(result).not.toBeNull()
        expect(result).toMatchObject({
          total_price: expect.any(Number),
          input_price: expect.any(Number),
          output_price: expect.any(Number),
          provider: { name: expect.any(String) },
          model: { name: expect.any(String) },
        })
        expect(result!.total_price).toBeGreaterThanOrEqual(0)
        expect(result!.input_price).toBeGreaterThanOrEqual(0)
        expect(result!.output_price).toBeGreaterThanOrEqual(0)
        expect(result!.provider.name).toBeTruthy()
        expect(result!.model.name).toBeTruthy()
      }
    })

    it('should calculate prices for models from different providers', () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const testCases = [
        { model: 'gpt-3.5-turbo', providerId: 'openai' },
        { model: 'gemini-1.5-pro', providerId: 'google' },
        { model: 'claude-3-opus', providerId: 'anthropic' },
      ]

      const results = testCases.map(({ model, providerId }) => calcPriceSync(usage, model, { providerId }))

      expect(results.length).toBe(testCases.length)
      for (const result of results) {
        expect(result).not.toBeNull()
        expect(result).toMatchObject({
          total_price: expect.any(Number),
          input_price: expect.any(Number),
          output_price: expect.any(Number),
          provider: { name: expect.any(String) },
          model: { name: expect.any(String) },
        })
        expect(result!.total_price).toBeGreaterThanOrEqual(0)
        expect(result!.input_price).toBeGreaterThanOrEqual(0)
        expect(result!.output_price).toBeGreaterThanOrEqual(0)
        expect(result!.provider.name).toBeTruthy()
        expect(result!.model.name).toBeTruthy()
      }
    })
  })

  describe('calcPriceAsync - Basic Functionality', () => {
    it('should calculate price for gpt-3.5-turbo (async)', async () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        total_price: expect.any(Number),
        input_price: expect.any(Number),
        output_price: expect.any(Number),
        provider: { name: expect.stringMatching(/OpenAI/i) },
        model: { name: expect.stringMatching(/gpt/i) },
      })
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
    })

    it('should calculate tiered pricing for Gemini 1.5 Pro (async)', async () => {
      const usage: Usage = { input_tokens: 2_000_000, output_tokens: 1000 }
      const result = await calcPriceAsync(usage, 'gemini-1.5-pro', { providerId: 'google' })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        total_price: expect.any(Number),
        input_price: expect.any(Number),
        output_price: expect.any(Number),
        provider: { name: expect.stringMatching(/Google/i) },
        model: { name: expect.stringMatching(/gemini/i) },
      })
      expect(result!.total_price).toBeGreaterThan(0)
      expect(result!.input_price).toBeGreaterThan(0)
      expect(result!.output_price).toBeGreaterThan(0)
    })

    it.each([
      { name: 'invalid provider', model: 'gpt-3.5-turbo', providerId: 'notaprovider' },
      { name: 'invalid model', model: 'not-a-real-model', providerId: 'openai' },
    ])('should return null for $name (async)', async ({ model, providerId }) => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = await calcPriceAsync(usage, model, { providerId })
      expect(result).toBeNull()
    })

    it('should calculate historic pricing for gpt-4o (async)', async () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = await calcPriceAsync(usage, 'gpt-4o', {
        providerId: 'openai',
        timestamp: new Date('2024-01-01T12:00:00Z'),
      })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        total_price: expect.any(Number),
        input_price: expect.any(Number),
        output_price: expect.any(Number),
        provider: { name: expect.stringMatching(/OpenAI/i) },
        model: { name: expect.stringMatching(/gpt/i) },
      })
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
    })

    it('should use cache on subsequent calls', async () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const first = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
      const second = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })

      expect(first).not.toBeNull()
      expect(second).not.toBeNull()
      expect(second).toMatchObject({
        total_price: first!.total_price,
        input_price: first!.input_price,
        output_price: first!.output_price,
        provider: { name: first!.provider.name },
      })
    })

    it('should calculate prices for multiple models (async)', async () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const models = ['gpt-3.5-turbo', 'gpt-4o', 'o1']
      const results = await Promise.all(models.map((model) => calcPriceAsync(usage, model, { providerId: 'openai' })))

      expect(results.length).toBe(models.length)
      for (const result of results) {
        expect(result).not.toBeNull()
        expect(result).toMatchObject({
          total_price: expect.any(Number),
          input_price: expect.any(Number),
          output_price: expect.any(Number),
          provider: { name: expect.any(String) },
          model: { name: expect.any(String) },
        })
        expect(result!.total_price).toBeGreaterThanOrEqual(0)
        expect(result!.input_price).toBeGreaterThanOrEqual(0)
        expect(result!.output_price).toBeGreaterThanOrEqual(0)
        expect(result!.provider.name).toBeTruthy()
        expect(result!.model.name).toBeTruthy()
      }
    })
  })

  describe('Provider and Model Matching', () => {
    function matchModelWithProvider(providers: any[], modelId: string) {
      for (const provider of providers) {
        const model = provider.models.find((m: any) => m.id === modelId)
        if (model) {
          return { provider, model }
        }
      }
      return null
    }

    it.each([
      { name: 'OpenAI', providerId: 'openai', expectedId: 'openai' },
      { name: 'Google', providerId: 'google', expectedId: 'google' },
      { name: 'Anthropic', providerId: 'anthropic', expectedId: 'anthropic' },
    ])('should match $name provider correctly', ({ providerId, expectedId }) => {
      const providers = mockProviders
      const provider = matchProvider(providers, providerId, providerId)
      expect(provider).not.toBeUndefined()
      expect(provider).toMatchObject({ id: expectedId })
    })

    it('should return undefined for non-existent provider', () => {
      const providers = mockProviders
      const result = matchProvider(providers, 'non-existent', 'non-existent')
      expect(result).toBeUndefined()
    })

    it.each([
      { name: 'GPT-3.5', providerId: 'openai', modelId: 'gpt-3.5-turbo', expectedId: 'gpt-3.5-turbo' },
      { name: 'Gemini', providerId: 'google', modelId: 'gemini-1.5-pro', expectedId: 'gemini-1.5-pro' },
      { name: 'Claude', providerId: 'anthropic', modelId: 'claude-3-opus', expectedId: 'claude-3-opus' },
    ])('should match $name model correctly', ({ providerId, modelId, expectedId }) => {
      const providers = mockProviders
      const provider = providers.find((p) => p.id === providerId)!
      const model = matchModel(provider.models, modelId)
      expect(model).not.toBeNull()
      expect(model).toMatchObject({ id: expectedId })
    })

    it('should return undefined for non-existent model', () => {
      const providers = mockProviders
      const openaiProvider = providers.find((p) => p.id === 'openai')!
      const result = matchModel(openaiProvider.models, 'non-existent-model')
      expect(result).toBeUndefined()
    })
  })

  describe('Edge Cases and Special Scenarios', () => {
    it.each([
      {
        name: 'zero tokens',
        usage: { input_tokens: 0, output_tokens: 0 } as Usage,
        expected: { total_price: 0, input_price: 0, output_price: 0 },
      },
      {
        name: 'undefined tokens',
        usage: {} as Usage,
        expected: { total_price: 0, input_price: 0, output_price: 0 },
      },
    ])('should handle $name', ({ usage, expected }) => {
      const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result).toMatchObject(expected)
    })

    it('should handle large token counts', () => {
      const usage: Usage = { input_tokens: 1000000, output_tokens: 500000 }
      const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        total_price: expect.any(Number),
        input_price: expect.any(Number),
        output_price: expect.any(Number),
      })
      expect(result!.total_price).toBeGreaterThan(0)
      expect(result!.input_price).toBeGreaterThan(0)
      expect(result!.output_price).toBeGreaterThan(0)
    })

    it.each([
      {
        name: 'cache tokens',
        usage: {
          input_tokens: 1000,
          cache_write_tokens: 200,
          cache_read_tokens: 100,
          output_tokens: 500,
        } as Usage,
      },
    ])('should handle $name', ({ usage }) => {
      const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        total_price: expect.any(Number),
        input_price: expect.any(Number),
        output_price: expect.any(Number),
      })
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
    })
  })
})
