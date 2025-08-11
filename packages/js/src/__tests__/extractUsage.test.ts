import { describe, it, expect } from 'vitest'
import { extractUsage } from '../index.js'
import type { Provider } from '../types.js'
import { data } from '../data.js'

const anthropicProvider: Provider = data[0]

describe('extractUsage', () => {
  describe('successful extraction', () => {
    it('should extract usage with cache tokens', () => {
      const responseData = {
        id: 'msg_0152tnC3YpjyASTB9qxqDJXu',
        type: 'message',
        role: 'assistant',
        model: 'claude-sonnet-4-20250514',
        stop_reason: 'tool_use',
        stop_sequence: null,
        usage: {
          input_tokens: 504,
          cache_creation_input_tokens: 123,
          cache_read_input_tokens: 0,
          output_tokens: 97,
          service_tier: 'standard',
        },
      }

      const [model, usage] = extractUsage(anthropicProvider, responseData)

      expect(model).toBe('claude-sonnet-4-20250514')
      expect(usage).toEqual({
        input_tokens: 504,
        cache_write_tokens: 123,
        cache_read_tokens: 0,
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

      const [model, usage] = extractUsage(anthropicProvider, responseData)

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
        usage: { prompt_tokens: 100, completion_tokens: 200 },
      }

      const [model, usage] = extractUsage(openaiProvider, responseData, 'chat')

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
          prompt_tokens: 100,
          completion_tokens: 200,
          completion_tokens_details: {
            audio_tokens: 150,
          },
        },
      }

      const [model, usage] = extractUsage(openaiProvider, responseData, 'chat')

      expect(model).toBe('gpt-4.1')
      expect(usage).toEqual({
        input_tokens: 100,
        output_tokens: 200,
        output_audio_tokens: 150,
      })
    })

    it('should extract usage with responses apiFlavor', () => {
      const responseData = {
        model: 'gpt-5',
        usage: { input_tokens: 100, output_tokens: 200 },
      }

      const [model, usage] = extractUsage(openaiProvider, responseData, 'responses')

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

      expect(() => extractUsage(openaiProvider, responseData)).toThrow(
        'No apiFlavor specified and multiple extractors available',
      )
    })
  })

  describe('error handling', () => {
    it.each([
      [{}, 'Missing value at `model`'],
      [{ model: null }, 'Expected `model` value to be a string, got null'],
      [{ model: 'x' }, 'Missing value at `usage`'],
      [{ model: 'x', usage: {} }, 'Missing value at `usage.input_tokens`'],
      [{ model: 'x', usage: 123 }, 'Expected `usage` value to be a mapping, got number'],
      [
        { model: 'x', usage: { input_tokens: 'not-a-number' } },
        'Expected `usage.input_tokens` value to be a number, got string',
      ],
      [{ model: 'x', usage: { input_tokens: [] } }, 'Expected `usage.input_tokens` value to be a number, got array'],
    ])('should throw error for invalid data: %j', (responseData, expectedError) => {
      expect(() => extractUsage(anthropicProvider, responseData)).toThrow(expectedError)
    })
  })

  describe('apiFlavor handling', () => {
    it('should throw error for unknown apiFlavor', () => {
      const responseData = {
        model: 'test-model',
        usage: { input_tokens: 100, output_tokens: 50 },
      }

      expect(() => extractUsage(anthropicProvider, responseData, 'wrong')).toThrow(
        "Unknown apiFlavor 'wrong', allowed values: default",
      )
    })

    it('should work with correct apiFlavor', () => {
      const responseData = {
        model: 'test-model',
        usage: { input_tokens: 100, output_tokens: 50 },
      }

      const [model, usage] = extractUsage(anthropicProvider, responseData, 'default')

      expect(model).toBe('test-model')
      expect(usage).toEqual({
        input_tokens: 100,
        output_tokens: 50,
      })
    })
  })

  describe('provider without extractors', () => {
    it('should throw error when no extraction logic is defined', () => {
      const providerWithoutExtractors: Provider = {
        id: 'test',
        name: 'Test',
        api_pattern: 'x',
        models: [],
      }

      const responseData = {
        model: 'test-model',
        usage: { input_tokens: 100, output_tokens: 50 },
      }

      expect(() => extractUsage(providerWithoutExtractors, responseData)).toThrow(
        'No extraction logic defined for this provider',
      )
    })
  })
})
