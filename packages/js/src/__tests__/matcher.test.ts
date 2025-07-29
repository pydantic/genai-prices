import { describe, it, expect } from 'vitest'
import { findProviderByMatch, normalizeModel } from '../matcher.js'
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

describe('Provider and Model Matching', () => {
  describe('findProviderByMatch', () => {
    it('should find providers by exact ID match', () => {
      expect(findProviderByMatch(mockProviders, 'google')?.id).toBe('google')
      expect(findProviderByMatch(mockProviders, 'meta')?.id).toBe('meta')
      expect(findProviderByMatch(mockProviders, 'mistral')?.id).toBe('mistral')
    })

    it('should find providers by provider_match logic', () => {
      expect(findProviderByMatch(mockProviders, 'gemini')?.id).toBe('google')
      expect(findProviderByMatch(mockProviders, 'google-gla')?.id).toBe('google')
      expect(findProviderByMatch(mockProviders, 'google-vertex')?.id).toBe('google')
      expect(findProviderByMatch(mockProviders, 'meta-llama')?.id).toBe('meta')
      expect(findProviderByMatch(mockProviders, 'llama')?.id).toBe('meta')
      expect(findProviderByMatch(mockProviders, 'mistralai')?.id).toBe('mistral')
      expect(findProviderByMatch(mockProviders, 'claude')?.id).toBe('anthropic')
      expect(findProviderByMatch(mockProviders, 'gpt')?.id).toBe('openai')
    })

    it('should handle case insensitive matching', () => {
      expect(findProviderByMatch(mockProviders, 'GEMINI')?.id).toBe('google')
      expect(findProviderByMatch(mockProviders, 'GOOGLE-GLA')?.id).toBe('google')
    })

    it('should handle whitespace', () => {
      expect(findProviderByMatch(mockProviders, '  gemini  ')?.id).toBe('google')
      expect(findProviderByMatch(mockProviders, 'google-gla ')?.id).toBe('google')
    })

    it('should return undefined for unknown providers', () => {
      expect(findProviderByMatch(mockProviders, 'unknown-provider')).toBeUndefined()
      expect(findProviderByMatch(mockProviders, 'custom-ai')).toBeUndefined()
    })
  })

  describe('normalizeModel', () => {
    it('should normalize Anthropic Claude Opus 4 models', () => {
      expect(normalizeModel('anthropic', 'claude-opus-4-20250514')).toBe('claude-opus-4-20250514')
      expect(normalizeModel('anthropic', 'claude-opus-4-something')).toBe('claude-opus-4-20250514')
      expect(normalizeModel('anthropic', 'claude-opus-4')).toBe('claude-opus-4-20250514')
    })

    it('should normalize OpenAI GPT-3.5 models', () => {
      expect(normalizeModel('openai', 'gpt-3.5-turbo')).toBe('gpt-3.5-turbo')
      expect(normalizeModel('openai', 'gpt-3.5-turbo-16k')).toBe('gpt-3.5-turbo')
      expect(normalizeModel('openai', 'gpt-3.5-turbo-instruct')).toBe('gpt-3.5-turbo')
    })

    it('should not normalize other provider models', () => {
      expect(normalizeModel('google', 'gemini-2.5-pro')).toBe('gemini-2.5-pro')
      expect(normalizeModel('mistral', 'mistral-large')).toBe('mistral-large')
      expect(normalizeModel('anthropic', 'claude-3-sonnet')).toBe('claude-3-sonnet')
    })

    it('should handle whitespace', () => {
      expect(normalizeModel('anthropic', '  claude-opus-4  ')).toBe('claude-opus-4-20250514')
      expect(normalizeModel('openai', ' gpt-3.5-turbo ')).toBe('gpt-3.5-turbo')
    })
  })
})
