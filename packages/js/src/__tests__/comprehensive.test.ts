/* eslint-disable @typescript-eslint/no-non-null-assertion */
/* eslint-disable @typescript-eslint/no-unsafe-assignment */
import { describe, expect, it } from 'vitest'

import type { Usage } from '../types.js'

import { calcPrice, waitForUpdate } from '../'
import { matchModel, matchProvider } from '../engine'

// Mock data for tests
const mockProviders = [
  {
    api_pattern: '',
    description: '',
    id: 'openai',
    models: [
      {
        context_window: 16385,
        description: '',
        id: 'gpt-5',
        match: { equals: 'gpt-5' },
        name: 'gpt 3.5 turbo',
        price_comments: '',
        prices: { input_mtok: 0.0005, output_mtok: 0.0015 },
      },
      {
        context_window: 128000,
        description: '',
        id: 'gpt-4o',
        match: { equals: 'gpt-4o' },
        name: 'gpt-4o',
        price_comments: '',
        prices: { input_mtok: 0.0005, output_mtok: 0.0015 },
      },
      {
        context_window: 32768,
        description: '',
        id: 'o1',
        match: { equals: 'o1' },
        name: 'O1',
        price_comments: '',
        prices: { input_mtok: 0.001, output_mtok: 0.002 },
      },
    ],
    name: 'OpenAI',
    price_comments: '',
    pricing_urls: [],
  },
  {
    api_pattern: '',
    description: '',
    id: 'google',
    models: [
      {
        context_window: 1000000,
        description: '',
        id: 'gemini-1.5-pro',
        match: { equals: 'gemini-1.5-pro' },
        name: 'Gemini 1.5 Pro',
        price_comments: '',
        prices: { input_mtok: 0.00025, output_mtok: 0.0005 },
      },
    ],
    name: 'Google',
    price_comments: '',
    pricing_urls: [],
  },
  {
    api_pattern: '',
    description: '',
    id: 'anthropic',
    models: [
      {
        context_window: 200000,
        description: '',
        id: 'claude-3-opus',
        match: { equals: 'claude-3-opus' },
        name: 'Claude 3 Opus',
        price_comments: '',
        prices: { input_mtok: 0.0015, output_mtok: 0.0075 },
      },
    ],
    name: 'Anthropic',
    price_comments: '',
    pricing_urls: [],
  },
]

describe('Comprehensive API Tests', () => {
  describe('calcPrice - Basic Functionality', () => {
    it.each([
      {
        expectedModel: /gpt/i,
        expectedProvider: /OpenAI/i,
        model: 'gpt-5',
        name: 'gpt-5',
        providerId: 'openai',
      },
      {
        expectedModel: /gpt/i,
        expectedProvider: /OpenAI/i,
        model: 'gpt-4o',
        name: 'gpt-4o',
        providerId: 'openai',
      },
      {
        expectedModel: /o1/i,
        expectedProvider: /OpenAI/i,
        model: 'o1',
        name: 'o1',
        providerId: 'openai',
      },
    ])('should calculate price for $name with provider ID', ({ expectedModel, expectedProvider, model, providerId }) => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = calcPrice(usage, model, { providerId })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        input_price: expect.any(Number),
        model: { name: expect.stringMatching(expectedModel) },
        output_price: expect.any(Number),
        provider: { name: expect.stringMatching(expectedProvider) },
        total_price: expect.any(Number),
      })
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
    })

    it('should calculate tiered pricing for Gemini 1.5 Pro', () => {
      const usage: Usage = { input_tokens: 2_000_000, output_tokens: 1000 }
      const result = calcPrice(usage, 'gemini-1.5-pro', { providerId: 'google' })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        input_price: expect.any(Number),
        model: { name: expect.stringMatching(/gemini/i) },
        output_price: expect.any(Number),
        provider: { name: expect.stringMatching(/Google/i) },
        total_price: expect.any(Number),
      })
      expect(result!.total_price).toBeGreaterThan(0)
      expect(result!.input_price).toBeGreaterThan(0)
      expect(result!.output_price).toBeGreaterThan(0)
    })

    it('should calculate price for Claude 3 Opus', () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = calcPrice(usage, 'claude-3-opus', { providerId: 'anthropic' })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        input_price: expect.any(Number),
        model: { name: expect.stringMatching(/claude/i) },
        output_price: expect.any(Number),
        provider: { name: expect.stringMatching(/Anthropic/i) },
        total_price: expect.any(Number),
      })
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
    })
  })

  describe('calcPrice - Error Handling', () => {
    it.each([
      { model: 'gpt-5', name: 'invalid provider', providerId: 'notaprovider' },
      { model: 'not-a-real-model', name: 'invalid model', providerId: 'openai' },
      { model: 'invalid-model', name: 'invalid model with valid provider', providerId: 'openai' },
    ])('should return null for $name', ({ model, providerId }) => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = calcPrice(usage, model, { providerId })
      expect(result).toBeNull()
    })
  })

  describe('calcPrice - Historic Pricing', () => {
    it('should calculate historic pricing for gpt-4o', () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const result = calcPrice(usage, 'gpt-4o', {
        providerId: 'openai',
        timestamp: new Date('2024-01-01T12:00Z'),
      })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        input_price: expect.any(Number),
        model: { name: expect.stringMatching(/gpt/i) },
        output_price: expect.any(Number),
        provider: { name: expect.stringMatching(/OpenAI/i) },
        total_price: expect.any(Number),
      })
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
    })
  })

  describe('calcPrice - Multiple Models', () => {
    it('should calculate prices for multiple models', () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const models = ['gpt-5', 'gpt-4o', 'o1']
      const results = models.map((model) => calcPrice(usage, model, { providerId: 'openai' }))

      expect(results.length).toBe(models.length)
      for (const result of results) {
        expect(result).not.toBeNull()
        expect(result).toMatchObject({
          input_price: expect.any(Number),
          model: { name: expect.any(String) },
          output_price: expect.any(Number),
          provider: { name: expect.any(String) },
          total_price: expect.any(Number),
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
        { model: 'gpt-5', providerId: 'openai' },
        { model: 'gemini-1.5-pro', providerId: 'google' },
        { model: 'claude-3-opus', providerId: 'anthropic' },
      ]

      const results = testCases.map(({ model, providerId }) => calcPrice(usage, model, { providerId }))

      expect(results.length).toBe(testCases.length)
      for (const result of results) {
        expect(result).not.toBeNull()
        expect(result).toMatchObject({
          input_price: expect.any(Number),
          model: { name: expect.any(String) },
          output_price: expect.any(Number),
          provider: { name: expect.any(String) },
          total_price: expect.any(Number),
        })
        expect(result!.total_price).toBeGreaterThanOrEqual(0)
        expect(result!.input_price).toBeGreaterThanOrEqual(0)
        expect(result!.output_price).toBeGreaterThanOrEqual(0)
        expect(result!.provider.name).toBeTruthy()
        expect(result!.model.name).toBeTruthy()
      }
    })
  })

  describe('calcPrice - Basic Functionality', () => {
    it('should calculate price for gpt-5 (async)', async () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      await waitForUpdate()
      const result = calcPrice(usage, 'gpt-5', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        input_price: expect.any(Number),
        model: { name: expect.stringMatching(/gpt/i) },
        output_price: expect.any(Number),
        provider: { name: expect.stringMatching(/OpenAI/i) },
        total_price: expect.any(Number),
      })
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
    })

    it('should calculate tiered pricing for Gemini 1.5 Pro (async)', async () => {
      const usage: Usage = { input_tokens: 2_000_000, output_tokens: 1000 }
      await waitForUpdate()
      const result = calcPrice(usage, 'gemini-1.5-pro', { providerId: 'google' })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        input_price: expect.any(Number),
        model: { name: expect.stringMatching(/gemini/i) },
        output_price: expect.any(Number),
        provider: { name: expect.stringMatching(/Google/i) },
        total_price: expect.any(Number),
      })
      expect(result!.total_price).toBeGreaterThan(0)
      expect(result!.input_price).toBeGreaterThan(0)
      expect(result!.output_price).toBeGreaterThan(0)
    })

    it.each([
      { model: 'gpt-5', name: 'invalid provider', providerId: 'notaprovider' },
      { model: 'not-a-real-model', name: 'invalid model', providerId: 'openai' },
    ])('should return null for $name (async)', async ({ model, providerId }) => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      await waitForUpdate()
      const result = calcPrice(usage, model, { providerId })
      expect(result).toBeNull()
    })

    it('should calculate historic pricing for gpt-4o (async)', async () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      await waitForUpdate()
      const result = calcPrice(usage, 'gpt-4o', {
        providerId: 'openai',
        timestamp: new Date('2024-01-01T12:00:00Z'),
      })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        input_price: expect.any(Number),
        model: { name: expect.stringMatching(/gpt/i) },
        output_price: expect.any(Number),
        provider: { name: expect.stringMatching(/OpenAI/i) },
        total_price: expect.any(Number),
      })
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
    })

    it('should use cache on subsequent calls', async () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      await waitForUpdate()
      const first = calcPrice(usage, 'gpt-5', {
        providerId: 'openai',
      })
      const second = calcPrice(usage, 'gpt-5', {
        providerId: 'openai',
      })

      expect(first).not.toBeNull()
      expect(second).not.toBeNull()
      expect(second).toMatchObject({
        input_price: first!.input_price,
        output_price: first!.output_price,
        provider: { name: first!.provider.name },
        total_price: first!.total_price,
      })
    })

    it('should calculate prices for multiple models (async)', async () => {
      const usage: Usage = { input_tokens: 1000, output_tokens: 100 }
      const models = ['gpt-5', 'gpt-4o', 'o1']
      const results = await Promise.all(models.map((model) => calcPrice(usage, model, { providerId: 'openai' })))

      expect(results.length).toBe(models.length)
      for (const result of results) {
        expect(result).not.toBeNull()
        expect(result).toMatchObject({
          input_price: expect.any(Number),
          model: { name: expect.any(String) },
          output_price: expect.any(Number),
          provider: { name: expect.any(String) },
          total_price: expect.any(Number),
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
    it.each([
      { expectedId: 'openai', name: 'OpenAI', providerId: 'openai' },
      { expectedId: 'google', name: 'Google', providerId: 'google' },
      { expectedId: 'anthropic', name: 'Anthropic', providerId: 'anthropic' },
    ])('should match $name provider correctly', ({ expectedId, providerId }) => {
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
      { expectedId: 'gpt-5', modelId: 'gpt-5', name: 'GPT-3.5', providerId: 'openai' },
      { expectedId: 'gemini-1.5-pro', modelId: 'gemini-1.5-pro', name: 'Gemini', providerId: 'google' },
      { expectedId: 'claude-3-opus', modelId: 'claude-3-opus', name: 'Claude', providerId: 'anthropic' },
    ])('should match $name model correctly', ({ expectedId, modelId, providerId }) => {
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
        expected: { input_price: 0, output_price: 0, total_price: 0 },
        name: 'zero tokens',
        usage: { input_tokens: 0, output_tokens: 0 } as Usage,
      },
      {
        expected: { input_price: 0, output_price: 0, total_price: 0 },
        name: 'undefined tokens',
        usage: {} as Usage,
      },
    ])('should handle $name', ({ expected, usage }) => {
      const result = calcPrice(usage, 'gpt-5', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result).toMatchObject(expected)
    })

    it('should handle large token counts', () => {
      const usage: Usage = { input_tokens: 1000000, output_tokens: 500000 }
      const result = calcPrice(usage, 'gpt-5', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        input_price: expect.any(Number),
        output_price: expect.any(Number),
        total_price: expect.any(Number),
      })
      expect(result!.total_price).toBeGreaterThan(0)
      expect(result!.input_price).toBeGreaterThan(0)
      expect(result!.output_price).toBeGreaterThan(0)
    })

    it.each([
      {
        name: 'cache tokens',
        usage: {
          cache_read_tokens: 100,
          cache_write_tokens: 200,
          input_tokens: 1000,
          output_tokens: 500,
        } as Usage,
      },
    ])('should handle $name', ({ usage }) => {
      const result = calcPrice(usage, 'gpt-5', { providerId: 'openai' })

      expect(result).not.toBeNull()
      expect(result).toMatchObject({
        input_price: expect.any(Number),
        output_price: expect.any(Number),
        total_price: expect.any(Number),
      })
      expect(result!.total_price).toBeGreaterThanOrEqual(0)
      expect(result!.input_price).toBeGreaterThanOrEqual(0)
      expect(result!.output_price).toBeGreaterThanOrEqual(0)
    })
  })
})
