import { describe, expect, it } from 'vitest'

import { data } from '../data'
import { matchProvider } from '../engine'

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
