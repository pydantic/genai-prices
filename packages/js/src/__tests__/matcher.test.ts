import { describe, it, expect } from 'vitest'
import { matchProvider } from '../matcher.js'
import type { Provider } from '../types.js'

// Mock providers for testing
const mockProviders: Provider[] = [
  {
    id: 'google',
    name: 'Google',
    api_pattern: '',
    models: [],
    provider_match: {
      or: [
        { equals: 'google' },
        { equals: 'gemini' },
        { equals: 'google-gla' },
        { equals: 'google-vertex' },
        { equals: 'google-ai' },
      ],
    },
  },
  {
    id: 'meta',
    name: 'Meta',
    api_pattern: '',
    models: [],
    provider_match: {
      or: [{ equals: 'meta' }, { equals: 'meta-llama' }, { equals: 'llama' }],
    },
  },
  {
    id: 'mistral',
    name: 'Mistral',
    api_pattern: '',
    models: [],
    provider_match: {
      or: [{ equals: 'mistral' }, { equals: 'mistralai' }],
    },
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    api_pattern: '',
    models: [],
    provider_match: {
      or: [{ equals: 'anthropic' }, { equals: 'claude' }],
    },
  },
  {
    id: 'openai',
    name: 'OpenAI',
    api_pattern: '',
    models: [],
    provider_match: {
      or: [{ equals: 'openai' }, { equals: 'gpt' }],
    },
  },
]

describe('Provider Matching', () => {
  describe('matchProvider with providerId', () => {
    it('should find providers by exact ID match', () => {
      expect(matchProvider(mockProviders, 'any-model', 'google')?.id).toBe('google')
      expect(matchProvider(mockProviders, 'any-model', 'meta')?.id).toBe('meta')
      expect(matchProvider(mockProviders, 'any-model', 'mistral')?.id).toBe('mistral')
    })

    it('should find providers by provider_match logic', () => {
      expect(matchProvider(mockProviders, 'any-model', 'gemini')?.id).toBe('google')
      expect(matchProvider(mockProviders, 'any-model', 'google-gla')?.id).toBe('google')
      expect(matchProvider(mockProviders, 'any-model', 'google-vertex')?.id).toBe('google')
      expect(matchProvider(mockProviders, 'any-model', 'meta-llama')?.id).toBe('meta')
      expect(matchProvider(mockProviders, 'any-model', 'llama')?.id).toBe('meta')
      expect(matchProvider(mockProviders, 'any-model', 'mistralai')?.id).toBe('mistral')
      expect(matchProvider(mockProviders, 'any-model', 'claude')?.id).toBe('anthropic')
      expect(matchProvider(mockProviders, 'any-model', 'gpt')?.id).toBe('openai')
    })

    it('should handle case insensitive matching', () => {
      expect(matchProvider(mockProviders, 'any-model', 'GEMINI')?.id).toBe('google')
      expect(matchProvider(mockProviders, 'any-model', 'GOOGLE-GLA')?.id).toBe('google')
    })

    it('should handle whitespace', () => {
      expect(matchProvider(mockProviders, 'any-model', '  gemini  ')?.id).toBe('google')
      expect(matchProvider(mockProviders, 'any-model', 'google-gla ')?.id).toBe('google')
    })

    it('should return undefined for unknown providers', () => {
      expect(matchProvider(mockProviders, 'any-model', 'unknown-provider')).toBeUndefined()
      expect(matchProvider(mockProviders, 'any-model', 'custom-ai')).toBeUndefined()
    })
  })
})
