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
    it('should calculate price for gpt-3.5-turbo with provider ID', () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
      expect(result!.provider.name).toMatch(/OpenAI/i)
      expect(result!.model.name?.toLowerCase()).toContain('gpt')
    })

    it('should calculate price for gpt-4o with provider ID', () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = calcPriceSync(usage, 'gpt-4o', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
      expect(result!.provider.name).toMatch(/OpenAI/i)
      expect(result!.model.name?.toLowerCase()).toContain('gpt')
    })

    it('should calculate price for o1 with provider ID', () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = calcPriceSync(usage, 'o1', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
      expect(result!.provider.name).toMatch(/OpenAI/i)
      expect(result!.model.name?.toLowerCase()).toContain('o1')
    })

    it('should calculate tiered pricing for Gemini 1.5 Pro', () => {
      const usage: Usage = { input_tokens: 2_000_000, output_tokens: 1000 }
      const result = calcPriceSync(usage, 'gemini-1.5-pro', { providerId: 'google' })

      expect(result).not.toBeNull()
      expect(result!.total_price).toBeGreaterThan(0)
      expect(result!.input_price).toBeGreaterThan(0)
      expect(result!.output_price).toBeGreaterThan(0)
      expect(result!.provider.name).toMatch(/Google/i)
      expect(result!.model.name?.toLowerCase()).toContain('gemini')
    })

    it('should calculate price for Claude 3 Opus', () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = calcPriceSync(usage, 'claude-3-opus', { providerId: 'anthropic' })

      expect(result).not.toBeNull()
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
      expect(result!.provider.name).toMatch(/Anthropic/i)
      expect(result!.model.name?.toLowerCase()).toContain('claude')
    })
  })

  describe('calcPriceSync - Error Handling', () => {
    it('should return null for invalid provider', () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'notaprovider' })
      expect(result).toBeNull()
    })

    it('should return null for invalid model', () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = calcPriceSync(usage, 'not-a-real-model', { providerId: 'openai' })
      expect(result).toBeNull()
    })

    it('should return null for invalid model with valid provider', () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = calcPriceSync(usage, 'invalid-model', { providerId: 'openai' })
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
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
      expect(result!.provider.name).toMatch(/OpenAI/i)
      expect(result!.model.name?.toLowerCase()).toContain('gpt')
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
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
      expect(result!.provider.name).toMatch(/OpenAI/i)
      expect(result!.model.name?.toLowerCase()).toContain('gpt')
    })

    it('should calculate tiered pricing for Gemini 1.5 Pro (async)', async () => {
      const usage: Usage = { input_tokens: 2_000_000, output_tokens: 1000 }
      const result = await calcPriceAsync(usage, 'gemini-1.5-pro', { providerId: 'google' })

      expect(result).not.toBeNull()
      expect(result!.total_price).toBeGreaterThan(0)
      expect(result!.input_price).toBeGreaterThan(0)
      expect(result!.output_price).toBeGreaterThan(0)
      expect(result!.provider.name).toMatch(/Google/i)
      expect(result!.model.name?.toLowerCase()).toContain('gemini')
    })

    it('should return null for invalid provider (async)', async () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'notaprovider' })
      expect(result).toBeNull()
    })

    it('should return null for invalid model (async)', async () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = await calcPriceAsync(usage, 'not-a-real-model', { providerId: 'openai' })
      expect(result).toBeNull()
    })

    it('should calculate historic pricing for gpt-4o (async)', async () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = await calcPriceAsync(usage, 'gpt-4o', {
        providerId: 'openai',
        timestamp: new Date('2024-01-01T12:00:00Z'),
      })

      expect(result).not.toBeNull()
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
      expect(result!.provider.name).toMatch(/OpenAI/i)
      expect(result!.model.name?.toLowerCase()).toContain('gpt')
    })

    it('should use cache on subsequent calls', async () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const first = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
      const second = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })

      expect(first).not.toBeNull()
      expect(second).not.toBeNull()
      expect(second!.total_price).toBe(first!.total_price)
      expect(second!.input_price).toBe(first!.input_price)
      expect(second!.output_price).toBe(first!.output_price)
      expect(second!.provider.name).toBe(first!.provider.name)
    })

    it('should calculate prices for multiple models (async)', async () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const models = ['gpt-3.5-turbo', 'gpt-4o', 'o1']
      const results = await Promise.all(models.map((model) => calcPriceAsync(usage, model, { providerId: 'openai' })))

      expect(results.length).toBe(models.length)
      for (const result of results) {
        expect(result).not.toBeNull()
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

    it('should match providers correctly', () => {
      const providers = mockProviders

      const openaiProvider = matchProvider(providers, 'openai', 'openai')
      expect(openaiProvider).not.toBeUndefined()
      expect(openaiProvider!.id).toBe('openai')

      const googleProvider = matchProvider(providers, 'google', 'google')
      expect(googleProvider).not.toBeUndefined()
      expect(googleProvider!.id).toBe('google')

      const anthropicProvider = matchProvider(providers, 'anthropic', 'anthropic')
      expect(anthropicProvider).not.toBeUndefined()
      expect(anthropicProvider!.id).toBe('anthropic')
    })

    it('should return undefined for non-existent provider', () => {
      const providers = mockProviders
      const result = matchProvider(providers, 'non-existent', 'non-existent')
      expect(result).toBeUndefined()
    })

    it('should match models correctly', () => {
      const providers = mockProviders

      // Find OpenAI provider and test GPT-3.5
      const openaiProvider = providers.find((p) => p.id === 'openai')!
      const gpt35Model = matchModel(openaiProvider.models, 'gpt-3.5-turbo')
      expect(gpt35Model).not.toBeNull()
      expect(gpt35Model!.id).toBe('gpt-3.5-turbo')

      // Find Google provider and test Gemini
      const googleProvider = providers.find((p) => p.id === 'google')!
      const geminiModel = matchModel(googleProvider.models, 'gemini-1.5-pro')
      expect(geminiModel).not.toBeNull()
      expect(geminiModel!.id).toBe('gemini-1.5-pro')

      // Find Anthropic provider and test Claude
      const anthropicProvider = providers.find((p) => p.id === 'anthropic')!
      const claudeModel = matchModel(anthropicProvider.models, 'claude-3-opus')
      expect(claudeModel).not.toBeNull()
      expect(claudeModel!.id).toBe('claude-3-opus')
    })

    it('should return undefined for non-existent model', () => {
      const providers = mockProviders
      const openaiProvider = providers.find((p) => p.id === 'openai')!
      const result = matchModel(openaiProvider.models, 'non-existent-model')
      expect(result).toBeUndefined()
    })
  })

  describe('Edge Cases and Special Scenarios', () => {
    it('should handle zero tokens', () => {
      const usage: Usage = { input_tokens: 0, output_tokens: 0 }
      const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result!.total_price).toBe(0)
      expect(result!.input_price).toBe(0)
      expect(result!.output_price).toBe(0)
    })

    it('should handle undefined tokens', () => {
      const usage: Usage = {}
      const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result!.total_price).toBe(0)
      expect(result!.input_price).toBe(0)
      expect(result!.output_price).toBe(0)
    })

    it('should handle large token counts', () => {
      const usage: Usage = { input_tokens: 1000000, output_tokens: 500000 }
      const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result!.total_price).toBeGreaterThan(0)
      expect(result!.input_price).toBeGreaterThan(0)
      expect(result!.output_price).toBeGreaterThan(0)
    })

    it('should handle cache tokens', () => {
      const usage: Usage = {
        input_tokens: 1000,
        cache_write_tokens: 200,
        cache_read_tokens: 100,
        output_tokens: 500,
      }
      const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
    })

    it('should handle requests', () => {
      const usage: Usage = {
        input_tokens: 1000,
        output_tokens: 500,
        requests: 2,
      }
      const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
    })
  })
})
