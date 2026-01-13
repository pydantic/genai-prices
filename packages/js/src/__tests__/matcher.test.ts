/* eslint-disable @typescript-eslint/no-non-null-assertion */
import { describe, expect, it } from 'vitest'

import type { Provider } from '../types'

import { data } from '../data'
import { matchModel, matchModelWithFallback, matchProvider } from '../engine'

const actualProviders = data

describe('Provider Matching', () => {
  describe('matchProvider with providerId', () => {
    it('should find providers by exact ID match', () => {
      expect(matchProvider(actualProviders, { providerId: 'google' })?.id).toBe('google')
      expect(matchProvider(actualProviders, { providerId: 'anthropic' })?.id).toBe('anthropic')
      expect(matchProvider(actualProviders, { providerId: 'openai' })?.id).toBe('openai')
    })

    it('should find providers by provider_match logic', () => {
      expect(matchProvider(actualProviders, { providerId: 'google-gla' })?.id).toBe('google')
      expect(matchProvider(actualProviders, { providerId: 'google-vertex' })?.id).toBe('google')
      expect(matchProvider(actualProviders, { providerId: 'gemini' })?.id).toBe('google')
      expect(matchProvider(actualProviders, { providerId: 'mistral' })?.id).toBe('mistral')
      expect(matchProvider(actualProviders, { providerId: 'mistralai' })?.id).toBe('mistral')
      expect(matchProvider(actualProviders, { providerId: 'anthropic' })?.id).toBe('anthropic')
      expect(matchProvider(actualProviders, { providerId: 'openai' })?.id).toBe('openai')
    })

    it('should handle case insensitive matching', () => {
      expect(matchProvider(actualProviders, { providerId: 'GOOGLE-GLA' })?.id).toBe('google')
      expect(matchProvider(actualProviders, { providerId: 'ANTHROPIC' })?.id).toBe('anthropic')
    })

    it('should handle whitespace', () => {
      expect(matchProvider(actualProviders, { providerId: '  google-gla  ' })?.id).toBe('google')
      expect(matchProvider(actualProviders, { providerId: 'openai ' })?.id).toBe('openai')
    })

    it('should return undefined for unknown providers', () => {
      expect(matchProvider(actualProviders, { providerId: 'unknown-provider' })).toBeUndefined()
      expect(matchProvider(actualProviders, { providerId: 'custom-ai' })).toBeUndefined()
    })

    it('should not match model names as providers', () => {
      expect(matchProvider(actualProviders, { providerId: 'claude' })).toBeUndefined()
      expect(matchProvider(actualProviders, { providerId: 'gpt' })).toBeUndefined()
    })
  })
})

describe('Model Matching with Fallback', () => {
  describe('matchModelWithFallback', () => {
    it('should find models directly in provider', () => {
      const azure = matchProvider(actualProviders, { providerId: 'azure' })
      expect(azure).toBeDefined()

      // Azure has its own gpt-4.1 model accessible via a fallback
      const model = matchModelWithFallback(azure!, 'gpt-4.1', actualProviders)
      expect(model).toBeDefined()
      expect(model?.id).toBe('gpt-4.1')
    })

    it('should fallback to other providers when model not found directly', () => {
      // Create mock providers to test fallback
      const fallbackProvider: Provider = {
        api_pattern: 'fallback.example.com',
        id: 'fallback-provider',
        models: [
          {
            id: 'fallback-model',
            match: { equals: 'fallback-model' },
            prices: { input_mtok: 1, output_mtok: 2 },
          },
        ],
        name: 'Fallback Provider',
      }

      const mainProvider: Provider = {
        api_pattern: 'main.example.com',
        fallback_model_providers: ['fallback-provider'],
        id: 'main-provider',
        models: [
          {
            id: 'main-model',
            match: { equals: 'main-model' },
            prices: { input_mtok: 1, output_mtok: 2 },
          },
        ],
        name: 'Main Provider',
      }

      const allProviders = [mainProvider, fallbackProvider]

      // Should find model in main provider directly
      const mainModel = matchModelWithFallback(mainProvider, 'main-model', allProviders)
      expect(mainModel).toBeDefined()
      expect(mainModel?.id).toBe('main-model')

      // Should fallback to find model in fallback provider
      const fallbackModel = matchModelWithFallback(mainProvider, 'fallback-model', allProviders)
      expect(fallbackModel).toBeDefined()
      expect(fallbackModel?.id).toBe('fallback-model')

      // Should return undefined for non-existent model
      const nonExistent = matchModelWithFallback(mainProvider, 'non-existent', allProviders)
      expect(nonExistent).toBeUndefined()
    })

    it('should prioritize direct match over fallback', () => {
      // Both providers have a model with the same match pattern
      const fallbackProvider: Provider = {
        api_pattern: 'fallback.example.com',
        id: 'fallback-provider',
        models: [
          {
            id: 'shared-model-fallback',
            match: { equals: 'shared-model' },
            prices: { input_mtok: 10, output_mtok: 20 },
          },
        ],
        name: 'Fallback Provider',
      }

      const mainProvider: Provider = {
        api_pattern: 'main.example.com',
        fallback_model_providers: ['fallback-provider'],
        id: 'main-provider',
        models: [
          {
            id: 'shared-model-main',
            match: { equals: 'shared-model' },
            prices: { input_mtok: 1, output_mtok: 2 },
          },
        ],
        name: 'Main Provider',
      }

      const allProviders = [mainProvider, fallbackProvider]

      // Should find the main provider's version, not the fallback
      const model = matchModelWithFallback(mainProvider, 'shared-model', allProviders)
      expect(model).toBeDefined()
      expect(model?.id).toBe('shared-model-main')
    })

    it('should support chained fallbacks', () => {
      const secondProvider: Provider = {
        api_pattern: 'second.example.com',
        id: 'second-provider',
        models: [
          {
            id: 'third-model',
            match: { equals: 'third-model' },
            prices: { input_mtok: 1, output_mtok: 2 },
          },
        ],
        name: 'Third Provider',
      }

      const firstProvider: Provider = {
        api_pattern: 'first.example.com',
        fallback_model_providers: ['second-provider'],
        id: 'first-provider',
        models: [],
        name: 'First Provider',
      }

      const allProviders = [firstProvider, secondProvider]

      // Should chain through second to find model in third
      const model = matchModelWithFallback(firstProvider, 'third-model', allProviders)
      expect(model).toBeDefined()
      expect(model?.id).toBe('third-model')
    })

    it('should work with real data - Azure falls back to OpenAI', () => {
      const azure = matchProvider(actualProviders, { providerId: 'azure' })
      const openai = matchProvider(actualProviders, { providerId: 'openai' })
      expect(azure).toBeDefined()
      expect(openai).toBeDefined()
      if (!azure || !openai) return
      expect(azure.fallback_model_providers).toContain('openai')

      // Find a model that exists in OpenAI
      const openaiModel = matchModel(openai.models, 'gpt-4o-mini')
      expect(openaiModel).toBeDefined()

      // If Azure doesn't have it directly, it should fallback to OpenAI
      const directMatch = matchModel(azure.models, 'gpt-4o-mini')
      expect(directMatch).not.toBeDefined()

      const fallbackMatch = matchModelWithFallback(azure, 'gpt-4o-mini', actualProviders)
      expect(fallbackMatch).toBeDefined()
      expect(fallbackMatch?.id).toBe(openaiModel?.id)
    })
  })
})
