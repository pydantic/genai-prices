/* eslint-disable @typescript-eslint/no-non-null-assertion */
import { describe, expect, it } from 'vitest'

import type { Provider } from '../types'

import { data } from '../data'
import { extractUsage } from '../index'

const anthropicProvider: Provider = data.find((provider) => provider.id === 'anthropic')!

describe('extractUsage', () => {
  describe('successful extraction', () => {
    it('should extract usage with cache tokens', () => {
      const responseData = {
        id: 'msg_0152tnC3YpjyASTB9qxqDJXu',
        model: 'claude-sonnet-4-20250514',
        role: 'assistant',
        stop_reason: 'tool_use',
        stop_sequence: null,
        type: 'message',
        usage: {
          cache_creation_input_tokens: 123,
          cache_read_input_tokens: 0,
          input_tokens: 504,
          output_tokens: 97,
          service_tier: 'standard',
        },
      }

      const { model, usage } = extractUsage(anthropicProvider, responseData)

      expect(model).toBe('claude-sonnet-4-20250514')
      expect(usage).toEqual({
        cache_read_tokens: 0,
        cache_write_tokens: 123,
        input_tokens: 627,
        output_tokens: 97,
      })
    })

    it('should extract basic usage without cache tokens', () => {
      const responseData = {
        model: 'x',
        usage: {
          input_tokens: 504,
          output_tokens: 97,
          service_tier: 'standard',
        },
      }

      const { model, usage } = extractUsage(anthropicProvider, responseData)

      expect(model).toBe('x')
      expect(usage).toEqual({
        input_tokens: 504,
        output_tokens: 97,
      })
    })
  })

  describe('OpenAI provider', () => {
    const openaiProvider: Provider = data.find((provider) => provider.id === 'openai')!

    it('should have correct provider properties', () => {
      expect(openaiProvider.name).toBe('OpenAI')
      expect(openaiProvider.extractors).toBeDefined()
    })

    it('should extract usage with chat apiFlavor', () => {
      const responseData = {
        model: 'gpt-4.1',
        usage: { completion_tokens: 200, prompt_tokens: 100 },
      }

      const { model, usage } = extractUsage(openaiProvider, responseData, 'chat')

      expect(model).toBe('gpt-4.1')
      expect(usage).toEqual({
        input_tokens: 100,
        output_tokens: 200,
      })
    })

    it('should extract usage with audio apiFlavor', () => {
      const responseData = {
        model: 'gpt-4.1',
        usage: {
          completion_tokens: 200,
          completion_tokens_details: {
            audio_tokens: 150,
          },
          prompt_tokens: 100,
        },
      }

      const { model, usage } = extractUsage(openaiProvider, responseData, 'chat')

      expect(model).toBe('gpt-4.1')
      expect(usage).toEqual({
        input_tokens: 100,
        output_audio_tokens: 150,
        output_tokens: 200,
      })
    })

    it('should extract usage with responses apiFlavor', () => {
      const responseData = {
        model: 'gpt-5',
        usage: { input_tokens: 100, output_tokens: 200 },
      }

      const { model, usage } = extractUsage(openaiProvider, responseData, 'responses')

      expect(model).toBe('gpt-5')
      expect(usage).toEqual({
        input_tokens: 100,
        output_tokens: 200,
      })
    })

    it('should error if not apiFlavor is provided', () => {
      const responseData = {
        model: 'gpt-5',
        usage: { input_tokens: 100, output_tokens: 200 },
      }

      expect(() => extractUsage(openaiProvider, responseData)).toThrow("Unknown apiFlavor 'default', allowed values: chat, responses")
    })
  })

  describe('OpenRouter provider', () => {
    const openrouterProvider: Provider = data.find((provider) => provider.id === 'openrouter')!

    it('should extract chat usage with cache write tokens', () => {
      const responseData = {
        model: 'anthropic/claude-4.6-sonnet-20260217',
        usage: {
          completion_tokens: 1906,
          completion_tokens_details: {
            audio_tokens: 23,
          },
          prompt_tokens: 4819,
          prompt_tokens_details: {
            audio_tokens: 17,
            cache_write_tokens: 4800,
            cached_tokens: 0,
          },
          total_tokens: 6725,
        },
      }

      const { model, usage } = extractUsage(openrouterProvider, responseData, 'chat')

      expect(model).toBe('anthropic/claude-4.6-sonnet-20260217')
      expect(usage).toEqual({
        cache_read_tokens: 0,
        cache_write_tokens: 4800,
        input_audio_tokens: 17,
        input_tokens: 4819,
        output_audio_tokens: 23,
        output_tokens: 1906,
      })
    })
  })

  describe('error handling', () => {
    it.each([
      [{}, 'Missing value at `usage`'],
      [{ model: 'x' }, 'Missing value at `usage`'],
      [{ model: 'x', usage: {} }, 'Missing value at `usage.input_tokens`'],
      [{ model: 'x', usage: 123 }, 'Expected `usage` value to be a mapping, got number'],
      [{ model: 'x', usage: { input_tokens: 'not-a-number' } }, 'Expected `usage.input_tokens` value to be a number, got string'],
      [{ model: 'x', usage: { input_tokens: [] } }, 'Expected `usage.input_tokens` value to be a number, got array'],
    ])('should throw error for invalid data: %j', (responseData, expectedError) => {
      expect(() => extractUsage(anthropicProvider, responseData)).toThrow(expectedError)
    })

    it('should throw when a required nested path has the wrong intermediate shape', () => {
      const provider: Provider = {
        api_pattern: 'test',
        extractors: [
          {
            api_flavor: 'default',
            mappings: [{ dest: 'input_tokens', path: ['totals', 'input_tokens'], required: true }],
            model_path: 'model',
            root: 'usage',
          },
        ],
        id: 'test',
        models: [],
        name: 'Test',
      }

      expect(() => extractUsage(provider, { model: 'test-model', usage: { totals: 1 } })).toThrow(
        'Expected `usage.totals` value to be a mapping, got number'
      )
    })

    it('should skip optional nested paths with the wrong intermediate shape', () => {
      const provider: Provider = {
        api_pattern: 'test',
        extractors: [
          {
            api_flavor: 'default',
            mappings: [
              { dest: 'input_tokens', path: ['totals', 'input_tokens'], required: false },
              { dest: 'output_tokens', path: 'output_tokens', required: true },
            ],
            model_path: 'model',
            root: 'usage',
          },
        ],
        id: 'test',
        models: [],
        name: 'Test',
      }

      expect(extractUsage(provider, { model: 'test-model', usage: { output_tokens: 2, totals: 1 } })).toEqual({
        model: 'test-model',
        usage: { output_tokens: 2 },
      })
    })
  })

  describe('apiFlavor handling', () => {
    it('should throw error for unknown apiFlavor', () => {
      const responseData = {
        model: 'test-model',
        usage: { input_tokens: 100, output_tokens: 50 },
      }

      expect(() => extractUsage(anthropicProvider, responseData, 'wrong')).toThrow("Unknown apiFlavor 'wrong', allowed values: default")
    })

    it('should work with correct apiFlavor', () => {
      const responseData = {
        model: 'test-model',
        usage: { input_tokens: 100, output_tokens: 50 },
      }

      const { model, usage } = extractUsage(anthropicProvider, responseData, 'default')

      expect(model).toBe('test-model')
      expect(usage).toEqual({
        input_tokens: 100,
        output_tokens: 50,
      })
    })
  })

  describe('OVHcloud provider', () => {
    const ovhProvider = data.find((p) => p.id === 'ovhcloud')!

    it('should extract embeddings usage', () => {
      const { model, usage } = extractUsage(ovhProvider, { model: 'bge-m3', usage: { prompt_tokens: 512 } }, 'embeddings')

      expect(model).toBe('bge-m3')
      expect(usage).toEqual({ input_tokens: 512 })
    })
  })

  describe('provider without extractors', () => {
    it('should throw error when no extraction logic is defined', () => {
      const providerWithoutExtractors: Provider = {
        api_pattern: 'x',
        id: 'test',
        models: [],
        name: 'Test',
      }

      const responseData = {
        model: 'test-model',
        usage: { input_tokens: 100, output_tokens: 50 },
      }

      expect(() => extractUsage(providerWithoutExtractors, responseData)).toThrow('No extraction logic defined for this provider')
    })
  })

  describe('Google provider', () => {
    const googleProvider: Provider = data.find((provider) => provider.id === 'google')!

    it('should find the model correctly and have correct usage without caching', () => {
      const responseData = {
        createTime: '2025-08-25T14:26:17.534704Z',
        modelVersion: 'gemini-2.5-flash',
        responseId: 'iXKsaLDRIPqsgLUPotqEyA0',
        usageMetadata: {
          candidatesTokenCount: 18,
          candidatesTokensDetails: [{ modality: 'TEXT', tokenCount: 18 }],
          promptTokenCount: 75,
          promptTokensDetails: [{ modality: 'TEXT', tokenCount: 75 }],
          thoughtsTokenCount: 144,
          toolUsePromptTokenCount: 25,
          totalTokenCount: 262,
          trafficType: 'ON_DEMAND',
        },
      }
      const { model, usage } = extractUsage(googleProvider, responseData)

      expect(model).toBe('gemini-2.5-flash')
      expect(usage).toEqual({
        input_tokens: 100,
        output_tokens: 162,
      })
    })

    it('should have correct usage with caching', () => {
      const responseData = {
        modelVersion: 'gemini-2.5-flash',
        usageMetadata: {
          cachedContentTokenCount: 12239,
          cacheTokensDetails: [
            { modality: 'AUDIO', tokenCount: 129 },
            { modality: 'TEXT', tokenCount: 12110 },
          ],
          candidatesTokenCount: 50,
          candidatesTokensDetails: [{ modality: 'TEXT', tokenCount: 50 }],
          promptTokenCount: 14152,
          promptTokensDetails: [
            { modality: 'TEXT', tokenCount: 14002 },
            { modality: 'AUDIO', tokenCount: 150 },
          ],
          thoughtsTokenCount: 69,
          totalTokenCount: 14271,
          trafficType: 'ON_DEMAND',
        },
      }
      const { model, usage } = extractUsage(googleProvider, responseData)

      expect(model).toBe('gemini-2.5-flash')
      expect(usage).toEqual({
        cache_audio_read_tokens: 129,
        cache_read_tokens: 12239,
        input_audio_tokens: 150,
        input_tokens: 14152,
        output_tokens: 119,
      })
    })
  })

  describe('MiniMax provider', () => {
    const minimaxProvider = data.find((p) => p.id === 'minimax')!

    it('should extract default usage without cache', () => {
      const responseData = { model: 'MiniMax-M2', usage: { input_tokens: 100, output_tokens: 50 } }

      const { model, usage } = extractUsage(minimaxProvider, responseData)

      expect(model).toBe('MiniMax-M2')
      expect(usage).toEqual({ input_tokens: 100, output_tokens: 50 })
    })

    it('should extract default usage with cache write (Anthropic accounting: add-back)', () => {
      const responseData = {
        usage: { cache_creation_input_tokens: 1900, cache_read_input_tokens: 0, input_tokens: 0, output_tokens: 8 },
      }

      const { usage } = extractUsage(minimaxProvider, responseData)

      // cache_read_input_tokens: 0 is present so cache_read_tokens: 0 also appears
      expect(usage).toEqual({ cache_read_tokens: 0, cache_write_tokens: 1900, input_tokens: 1900, output_tokens: 8 })
    })

    it('should extract default usage with cache read (Anthropic accounting: add-back)', () => {
      const responseData = {
        usage: { cache_creation_input_tokens: 0, cache_read_input_tokens: 1900, input_tokens: 0, output_tokens: 8 },
      }

      const { usage } = extractUsage(minimaxProvider, responseData)

      // cache_creation_input_tokens: 0 is present so cache_write_tokens: 0 also appears
      expect(usage).toEqual({ cache_read_tokens: 1900, cache_write_tokens: 0, input_tokens: 1900, output_tokens: 8 })
    })

    it('should extract responses usage without cache (OpenAI accounting: no add-back)', () => {
      const responseData = {
        usage: { input_tokens: 1925, input_tokens_details: { cached_tokens: 0 }, output_tokens: 16 },
      }

      const { usage } = extractUsage(minimaxProvider, responseData, 'responses')

      expect(usage).toEqual({ cache_read_tokens: 0, input_tokens: 1925, output_tokens: 16 })
    })

    it('should extract responses usage with cache (OpenAI accounting: subset, no add-back)', () => {
      const responseData = {
        usage: { input_tokens: 2000, input_tokens_details: { cached_tokens: 500 }, output_tokens: 16 },
      }

      const { usage } = extractUsage(minimaxProvider, responseData, 'responses')

      expect(usage).toEqual({ cache_read_tokens: 500, input_tokens: 2000, output_tokens: 16 })
    })
  })

  describe('AWS Bedrock provider', () => {
    const bedrockProvider: Provider = data.find((provider) => provider.id === 'aws')!

    it('should extract usage with model name', () => {
      const responseData = {
        usage: { inputTokens: 406, outputTokens: 53, serverToolUsage: {}, totalTokens: 459 },
      }

      const { model, usage } = extractUsage(bedrockProvider, responseData)

      expect(model).toBeNull()
      expect(usage).toEqual({ input_tokens: 406, output_tokens: 53 })
    })
  })
})
