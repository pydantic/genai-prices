/* eslint-disable @typescript-eslint/no-non-null-assertion */
import { describe, expect, it } from 'vitest'

import type { Provider } from '../types'

import { data } from '../data'
import { matchLogic, matchModel, matchModelWithFallback, matchProvider, normalizeCompactDatedRef } from '../engine'
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

    it('preserves Mistral aliases without claiming qualified OpenRouter model IDs', () => {
      expect(matchProvider(actualProviders, { modelId: 'open-mistral-7b' })?.id).toBe('mistral')
      expect(matchProvider(actualProviders, { modelId: 'open-mistral-nemo' })?.id).toBe('mistral')
      expect(matchProvider(actualProviders, { modelId: 'open-mixtral-8x7b' })?.id).toBe('mistral')
      expect(matchProvider(actualProviders, { modelId: 'mistralai/voxtral-small-24b-2507' })).toBeUndefined()
    })

    it('infers Cursor only for its Composer namespace', () => {
      expect(matchProvider(actualProviders, { modelId: 'composer-2.5' })?.id).toBe('cursor')
      expect(matchProvider(actualProviders, { modelId: 'grok-4.6' })?.id).not.toBe('cursor')
    })

    it('does not claim third-party model namespaces for Arcee', () => {
      expect(matchProvider(actualProviders, { modelId: 'deepseek/deepseek-v4-pro' })?.id).not.toBe('arcee')
    })

    it('does not claim third-party model namespaces for Baseten', () => {
      expect(matchProvider(actualProviders, { modelId: 'zai-org/GLM-5.3' })?.id).not.toBe('baseten')
    })

    it('does not claim the vendor namespaces GitHub Copilot resells', () => {
      expect(matchProvider(actualProviders, { modelId: 'claude-haiku-4.5' })?.id).toBe('anthropic')
      expect(matchProvider(actualProviders, { modelId: 'gemini-3.6-flash' })?.id).toBe('google')
    })
  })

  describe('matchProvider with providerId', () => {
    it('should find providers by exact ID match', () => {
      expect(matchProvider(actualProviders, { providerId: 'google' })?.id).toBe('google')
      expect(matchProvider(actualProviders, { providerId: 'anthropic' })?.id).toBe('anthropic')
      expect(matchProvider(actualProviders, { providerId: 'openai' })?.id).toBe('openai')
      expect(matchProvider(actualProviders, { providerId: 'arcee' })?.id).toBe('arcee')
      expect(matchProvider(actualProviders, { providerId: 'baseten' })?.id).toBe('baseten')
      expect(matchProvider(actualProviders, { providerId: 'cursor' })?.id).toBe('cursor')
      expect(matchProvider(actualProviders, { providerId: 'github-copilot' })?.id).toBe('github-copilot')
    })

    it('should find providers by provider_match logic', () => {
      expect(matchProvider(actualProviders, { providerId: 'google-gla' })?.id).toBe('google')
      expect(matchProvider(actualProviders, { providerId: 'google-vertex' })?.id).toBe('google')
      expect(matchProvider(actualProviders, { providerId: 'gemini' })?.id).toBe('google')
      expect(matchProvider(actualProviders, { providerId: 'mistral' })?.id).toBe('mistral')
      expect(matchProvider(actualProviders, { providerId: 'mistralai' })?.id).toBe('mistral')
      expect(matchProvider(actualProviders, { providerId: 'copilot' })?.id).toBe('github-copilot')
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
      expect(matchProvider(actualProviders, { providerApiUrl: 'https://api.arcee.ai/api/v1/chat/completions' })?.id).toBe('arcee')
      expect(matchProvider(actualProviders, { providerApiUrl: 'https://inference.baseten.co/v1/chat/completions' })?.id).toBe('baseten')
      expect(matchProvider(actualProviders, { providerApiUrl: 'https://api.cursor.com/v1/agents' })?.id).toBe('cursor')
      expect(matchProvider(actualProviders, { providerApiUrl: 'https://api.githubcopilot.com/chat/completions' })?.id).toBe(
        'github-copilot'
      )
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

    it('should resolve compact dated refs to the dashed alias', () => {
      const openai = matchProvider(actualProviders, { providerId: 'openai' })
      expect(openai).toBeDefined()

      // LiteLLM/OpenRouter emit `gpt-5.2-20251211`, only the dashed form is aliased
      const compact = matchModelWithFallback(openai!, 'gpt-5.2-20251211', actualProviders)
      expect(compact?.id).toBe('gpt-5.2')
      const dashed = matchModelWithFallback(openai!, 'gpt-5.2-2025-12-11', actualProviders)
      expect(dashed?.id).toBe('gpt-5.2')
    })

    it('should not normalize refs that match on the compact date form', () => {
      // Bedrock models match the compact date via `contains`, so they must be returned as-is
      const aws = matchProvider(actualProviders, { providerId: 'aws' })
      expect(aws).toBeDefined()
      const model = matchModelWithFallback(aws!, 'claude-3-5-haiku-20241022', actualProviders)
      expect(model?.id).toBe('regional.anthropic.claude-3-5-haiku-20241022-v1:0')
    })

    it('should only normalize valid compact dates', () => {
      expect(normalizeCompactDatedRef('gpt-5.2-20251211')).toBe('gpt-5.2-2025-12-11')
      expect(normalizeCompactDatedRef('claude-3-5-haiku-20241022')).toBe('claude-3-5-haiku-2024-10-22')
      expect(normalizeCompactDatedRef('model-20240229')).toBe('model-2024-02-29')
      // suffixes that aren't valid calendar dates are left untouched
      expect(normalizeCompactDatedRef('gpt-4o-12345678')).toBe('gpt-4o-12345678')
      expect(normalizeCompactDatedRef('gpt-4o-20251301')).toBe('gpt-4o-20251301')
      expect(normalizeCompactDatedRef('gpt-4o-20250230')).toBe('gpt-4o-20250230')
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

    it('should prioritize an exact fallback match over a normalized fallback match', () => {
      const normalizedProvider: Provider = {
        api_pattern: 'normalized.example.com',
        id: 'normalized-provider',
        models: [{ id: 'normalized-model', match: { equals: 'model-2025-02-28' }, prices: {} }],
        name: 'Normalized Provider',
      }
      const exactProvider: Provider = {
        api_pattern: 'exact.example.com',
        id: 'exact-provider',
        models: [{ id: 'exact-model', match: { equals: 'model-20250228' }, prices: {} }],
        name: 'Exact Provider',
      }
      const mainProvider: Provider = {
        api_pattern: 'main.example.com',
        fallback_model_providers: ['normalized-provider', 'exact-provider'],
        id: 'main-provider',
        models: [],
        name: 'Main Provider',
      }

      const model = matchModelWithFallback(mainProvider, 'model-20250228', [mainProvider, normalizedProvider, exactProvider])
      expect(model?.id).toBe('exact-model')
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

    it('should work with real data - Azure AI Foundry marketplace models fall back to the origin provider', () => {
      const azure = matchProvider(actualProviders, { providerId: 'azure' })
      expect(azure).toBeDefined()
      if (!azure) return
      expect(azure.fallback_model_providers).toEqual(['openai', 'anthropic', 'deepseek', 'x-ai', 'moonshotai'])

      for (const [modelRef, expectedId] of [
        ['Kimi-K2.6-1', 'kimi-k2.6'],
        ['grok-4.3', 'grok-4.3'],
        ['DeepSeek-V4-Pro', 'deepseek-v4-pro'],
      ] as const) {
        expect(matchModel(azure.models, modelRef)).not.toBeDefined()
        expect(matchModelWithFallback(azure, modelRef, actualProviders)?.id).toBe(expectedId)
      }
    })
  })
})

describe('Claude Fable 5 vs 5.1', () => {
  // Fable 5.1 caches reads at 0.025x base input; Fable 5 at the usual 0.1x. The Fable 5
  // records match by prefix, so a loose clause silently prices Fable 5.1 cache reads 4x
  // too high instead of failing.
  const usage = { cache_read_tokens: 1_000_000, input_tokens: 1_000_000 }

  it.each([
    ['anthropic', 'claude-fable-5', 'claude-fable-5-1'],
    ['anthropic', 'claude-fable-5-20260901', 'claude-fable-5-1-20260901'],
    ['google', 'claude-fable-5', 'claude-fable-5-1'],
    ['google', 'claude-fable-5@20260901', 'claude-fable-5-1@20260901'],
    ['aws', 'global.anthropic.claude-fable-5-v1:0', 'global.anthropic.claude-fable-5-1-v1:0'],
    ['aws', 'us.anthropic.claude-fable-5-v1:0', 'us.anthropic.claude-fable-5-1-v1:0'],
    ['openrouter', 'anthropic/claude-fable-5', 'anthropic/claude-fable-5.1'],
  ])('keeps %s Fable 5.1 off Fable 5 prices', (providerId, fable5Ref, fable51Ref) => {
    const fable5 = calcPrice(usage, fable5Ref, { providerId })
    const fable51 = calcPrice(usage, fable51Ref, { providerId })

    expect(fable51!.model.id).not.toBe(fable5!.model.id)
    expect(fable51!.total_price).toBeCloseTo(fable5!.total_price / 4, 10)
  })

  it.each([
    ['anthropic', 'claude-fable-5-1', 0.25],
    ['anthropic', 'claude-fable-5-1-20260901', 0.25],
    ['google', 'claude-fable-5-1', 0.25],
    ['google', 'claude-fable-5-1@20260901', 0.25],
    ['aws', 'global.anthropic.claude-fable-5-1-v1:0', 0.25],
    ['aws', 'us.anthropic.claude-fable-5-1-v1:0', 0.275],
    ['openrouter', 'anthropic/claude-fable-5.1', 0.25],
  ])('prices %s %s cache reads at the 0.025x rate', (providerId, modelRef, expected) => {
    expect(calcPrice(usage, modelRef, { providerId })!.total_price).toBeCloseTo(expected, 10)
  })

  it('leaves the OpenRouter family-level alias on Fable 5', () => {
    const price = calcPrice(usage, '~anthropic/claude-fable-latest', { providerId: 'openrouter' })

    expect(price!.total_price).toBeCloseTo(1, 10)
  })
})
