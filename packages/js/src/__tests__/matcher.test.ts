import { describe, it, expect } from 'vitest'
import { matchProvider } from '../matcher.js'
import { data } from '../data.js'

const actualProviders = data

describe('Provider Matching', () => {
  describe('matchProvider with providerId', () => {
    it('should find providers by exact ID match', () => {
      expect(matchProvider(actualProviders, 'any-model', 'google')?.id).toBe('google')
      expect(matchProvider(actualProviders, 'any-model', 'anthropic')?.id).toBe('anthropic')
      expect(matchProvider(actualProviders, 'any-model', 'openai')?.id).toBe('openai')
    })

    it('should find providers by provider_match logic', () => {
      expect(matchProvider(actualProviders, 'any-model', 'google-gla')?.id).toBe('google')
      expect(matchProvider(actualProviders, 'any-model', 'google-vertex')?.id).toBe('google')
      expect(matchProvider(actualProviders, 'any-model', 'gemini')?.id).toBe('google')
      expect(matchProvider(actualProviders, 'any-model', 'mistral')?.id).toBe('mistral')
      expect(matchProvider(actualProviders, 'any-model', 'mistralai')?.id).toBe('mistral')
      expect(matchProvider(actualProviders, 'any-model', 'anthropic')?.id).toBe('anthropic')
      expect(matchProvider(actualProviders, 'any-model', 'openai')?.id).toBe('openai')
    })

    it('should handle case insensitive matching', () => {
      expect(matchProvider(actualProviders, 'any-model', 'GOOGLE-GLA')?.id).toBe('google')
      expect(matchProvider(actualProviders, 'any-model', 'ANTHROPIC')?.id).toBe('anthropic')
    })

    it('should handle whitespace', () => {
      expect(matchProvider(actualProviders, 'any-model', '  google-gla  ')?.id).toBe('google')
      expect(matchProvider(actualProviders, 'any-model', 'openai ')?.id).toBe('openai')
    })

    it('should return undefined for unknown providers', () => {
      expect(matchProvider(actualProviders, 'any-model', 'unknown-provider')).toBeUndefined()
      expect(matchProvider(actualProviders, 'any-model', 'custom-ai')).toBeUndefined()
    })

    it('should not match model names as providers', () => {
      expect(matchProvider(actualProviders, 'any-model', 'claude')).toBeUndefined()
      expect(matchProvider(actualProviders, 'any-model', 'gpt')).toBeUndefined()
    })
  })
})
