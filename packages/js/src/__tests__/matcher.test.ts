import { describe, it, expect } from 'vitest'
import { normalizeProvider, normalizeModel } from '../matcher.js'

describe('Provider and Model Normalization', () => {
  describe('normalizeProvider', () => {
    it('should normalize Google provider aliases', () => {
      expect(normalizeProvider('gemini')).toBe('google')
      expect(normalizeProvider('google-gla')).toBe('google')
      expect(normalizeProvider('google-vertex')).toBe('google')
      expect(normalizeProvider('google-ai')).toBe('google')
      expect(normalizeProvider('GOOGLE-GLA')).toBe('google')
    })

    it('should normalize Meta provider aliases', () => {
      expect(normalizeProvider('meta-llama')).toBe('meta')
      expect(normalizeProvider('llama')).toBe('meta')
    })

    it('should normalize Mistral provider aliases', () => {
      expect(normalizeProvider('mistralai')).toBe('mistral')
    })

    it('should normalize Anthropic provider aliases', () => {
      expect(normalizeProvider('anthropic')).toBe('anthropic')
      expect(normalizeProvider('claude')).toBe('anthropic')
    })

    it('should normalize OpenAI provider aliases', () => {
      expect(normalizeProvider('openai')).toBe('openai')
      expect(normalizeProvider('gpt')).toBe('openai')
    })

    it('should handle unknown providers', () => {
      expect(normalizeProvider('unknown-provider')).toBe('unknown-provider')
      expect(normalizeProvider('custom-ai')).toBe('custom-ai')
    })

    it('should handle whitespace', () => {
      expect(normalizeProvider('  gemini  ')).toBe('google')
      expect(normalizeProvider('google-gla ')).toBe('google')
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

    it('should not normalize models for other providers', () => {
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
