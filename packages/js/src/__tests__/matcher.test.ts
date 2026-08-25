/* eslint-disable @typescript-eslint/no-non-null-assertion */
import { describe, expect, it } from 'vitest'

import type { Provider } from '../types'

import { data } from '../data'
import { matchLogic, matchModel, matchModelWithFallback, matchProvider } from '../engine'
import { calcPrice } from '../index'

const actualProviders = data

describe('Match Logic', () => {
  it('should match string clauses case-insensitively', () => {
    expect(matchLogic({ equals: 'Qwen/Qwen3.5-9B' }, 'qwen/qwen3.5-9b')).toBe(true)
    expect(matchLogic({ starts_with: 'Qwen/' }, 'qwen/qwen3.5-9b')).toBe(true)
    expect(matchLogic({ ends_with: '-9B' }, 'qwen/qwen3.5-9b')).toBe(true)
    expect(matchLogic({ contains: 'Qwen3.5' }, 'qwen/qwen3.5-9b')).toBe(true)
  })

  it('should keep regex clauses case-sensitive', () => {
    expect(matchLogic({ regex: 'Qwen/Qwen3\\.5-9B' }, 'qwen/qwen3.5-9b')).toBe(false)
    expect(matchLogic({ regex: 'Qwen/Qwen3\\.5-9B' }, 'Qwen/Qwen3.5-9B')).toBe(true)
  })
})

describe('Provider Matching', () => {
  describe('matchProvider with modelId', () => {
    it('prefers Fireworks for its fully-qualified DeepSeek model IDs', () => {
      const provider = matchProvider(actualProviders, { modelId: 'accounts/fireworks/models/deepseek-v4-flash-0731' })

      expect(provider?.id).toBe('fireworks')
    })
  })

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

    it('should not price OpenAI Codex subscriptions as OpenAI API usage', () => {
      const provider = matchProvider(actualProviders, { providerId: 'openai-codex' })

      expect(provider?.id).toBe('openai-codex')
      expect(provider?.models).toEqual([])
      expect(calcPrice({ input_tokens: 1_000 }, 'gpt-5.4', { providerId: 'openai-codex' })).toBeNull()
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

    it('prices only known Command A model IDs', () => {
      const usage = { input_tokens: 1 }

      expect(calcPrice(usage, 'command-a', { providerId: 'cohere' })?.model.id).toBe('command-a')
      expect(calcPrice(usage, 'command-a-03-2025', { providerId: 'cohere' })?.model.id).toBe('command-a')
      expect(calcPrice(usage, 'command-a-plus-05-2026', { providerId: 'cohere' })).toBeNull()
    })
  })

  describe('matchProvider with providerApiUrl', () => {
    // Every `api_pattern` is unanchored, so matching must be anchored at the start of the URL — as
    // Python's `re.match` is. Otherwise a proxy URL carrying a provider host resolves to that provider
    // in JS while raising `LookupError` in Python.
    const proxiedOpenaiApiUrl = 'http://localhost:8080/proxy?u=https://api.openai.com/v1'

    it('should match a provider at the start of the URL', () => {
      expect(matchProvider(actualProviders, { providerApiUrl: 'https://api.openai.com/v1/chat/completions' })?.id).toBe('openai')
    })

    it('should not match a provider embedded later in the URL', () => {
      expect(matchProvider(actualProviders, { providerApiUrl: proxiedOpenaiApiUrl })).toBeUndefined()
      expect(calcPrice({ input_tokens: 1_000 }, 'gpt-4o', { providerApiUrl: proxiedOpenaiApiUrl })).toBeNull()
    })
  })
})

describe('LiteLLM Provider Handling', () => {
  it('should allow litellm to fall through to model matching', () => {
    // When provider_id is 'litellm' and not found, should fall through to model matching
    const provider = matchProvider(actualProviders, { modelId: 'gpt-4o-mini', providerId: 'litellm' })
    expect(provider).toBeDefined()
    expect(provider?.id).toBe('openai')
  })

  it('should return undefined for litellm with unknown model', () => {
    const provider = matchProvider(actualProviders, { modelId: 'unknown-model-xyz', providerId: 'litellm' })
    expect(provider).toBeUndefined()
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
