import { describe, it, expect, beforeAll } from 'vitest';
import { calcPrice, enableAutoUpdate, Usage } from '../index.js';

describe('calcPrice', () => {
  beforeAll(() => {
    enableAutoUpdate();
  });

  it('calculates price for gpt-3.5-turbo', async () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 };
    const result = await calcPrice(usage, 'gpt-3.5-turbo', { providerId: 'openai' });
    expect(result.price).toBeGreaterThanOrEqual(0);
    expect(result.provider.name).toMatch(/OpenAI/i);
    expect(result.model.name?.toLowerCase()).toContain('gpt');
  });

  it('calculates tiered pricing for Gemini 1.5 Pro (Google)', async () => {
    // Gemini 1.5 Pro has tiered pricing for large input tokens
    const usage: Usage = { inputTokens: 2_000_000, outputTokens: 1000 };
    const result = await calcPrice(usage, 'gemini-1.5-pro', { providerId: 'google' });
    expect(result.price).toBeGreaterThan(0);
    expect(result.provider.name).toMatch(/Google/i);
    expect(result.model.name?.toLowerCase()).toContain('gemini');
  });

  it('throws error for invalid provider', async () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 };
    await expect(calcPrice(usage, 'gpt-3.5-turbo', { providerId: 'notaprovider' })).rejects.toThrow(
      /Provider not found/
    );
  });

  it('throws error for invalid model', async () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 };
    await expect(calcPrice(usage, 'not-a-real-model', { providerId: 'openai' })).rejects.toThrow(
      /Model not found/
    );
  });

  it('calculates historic pricing for gpt-4o (OpenAI)', async () => {
    const usage: Usage = { inputTokens: 1000, outputTokens: 100 };
    // Use a date in the past to test historic pricing logic
    const result = await calcPrice(usage, 'gpt-4o', {
      providerId: 'openai',
      timestamp: new Date('2024-01-01T12:00:00Z'),
    });
    expect(result.price).toBeGreaterThanOrEqual(0);
    expect(result.provider.name).toMatch(/OpenAI/i);
    expect(result.model.name?.toLowerCase()).toContain('gpt');
  });
});
