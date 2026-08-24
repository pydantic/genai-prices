import { describe, expect, it } from 'vitest'

import { calcPrice } from '../api'
import * as providerDataModule from '../data'
import { unitData } from '../dataUnits'
import { UnitRegistry } from '../units'

const tokenUsageKeys = [
  'input_tokens',
  'output_tokens',
  'cache_read_tokens',
  'cache_write_tokens',
  'cache_write_5m_tokens',
  'cache_write_1h_tokens',
  'input_text_tokens',
  'output_text_tokens',
  'cache_text_read_tokens',
  'cache_text_write_tokens',
  'cache_text_write_5m_tokens',
  'cache_text_write_1h_tokens',
  'input_audio_tokens',
  'output_audio_tokens',
  'cache_audio_read_tokens',
  'cache_audio_write_tokens',
  'cache_audio_write_5m_tokens',
  'cache_audio_write_1h_tokens',
  'input_image_tokens',
  'output_image_tokens',
  'cache_image_read_tokens',
  'cache_image_write_tokens',
  'cache_image_write_5m_tokens',
  'cache_image_write_1h_tokens',
  'input_video_tokens',
  'output_video_tokens',
  'cache_video_read_tokens',
  'cache_video_write_tokens',
  'cache_video_write_5m_tokens',
  'cache_video_write_1h_tokens',
  'input_tool_tokens',
  'input_text_tool_tokens',
  'input_audio_tool_tokens',
  'input_image_tool_tokens',
  'input_video_tool_tokens',
  'output_reasoning_tokens',
  'output_text_reasoning_tokens',
  'output_audio_reasoning_tokens',
  'output_image_reasoning_tokens',
  'output_video_reasoning_tokens',
  'output_citation_tokens',
  'output_text_citation_tokens',
  'output_audio_citation_tokens',
  'output_image_citation_tokens',
  'output_video_citation_tokens',
]

const nonTokenUsageKeys = [
  'audio_seconds',
  'input_characters',
  'input_text_messages',
  'input_audio_seconds',
  'input_pixels',
  'input_document_pages',
  'input_annotated_document_pages',
  'output_audio_seconds',
  'rerank_searches',
  'web_searches',
  'social_searches',
  'storage_searches',
  'code_executions',
]

const reportableUsageKeys = [...tokenUsageKeys, ...nonTokenUsageKeys]

describe('generated data split', () => {
  it('keeps generated provider data separate from generated unit data', () => {
    expect(providerDataModule).toHaveProperty('data')
    expect(providerDataModule.data.length).toBeGreaterThan(0)
    expect(providerDataModule).not.toHaveProperty('unitData')
  })

  it('exposes current JavaScript units without the provider list', () => {
    expect(new Set(Object.keys(unitData))).toEqual(new Set(['requests', ...reportableUsageKeys]))
    expect(new Set(tokenUsageKeys.map((usageKey) => unitData[usageKey]?.dimensions.family))).toEqual(new Set(['tokens']))
    expect(unitData.web_searches?.dimensions.family).toBe('tool_calls')
    expect(unitData.web_searches?.dimensions.tool_type).toBe('web_search')
    expect(unitData.web_searches?.price_key).toBe('web_searches_kcount')
    expect(unitData.audio_seconds?.price_key).toBe('audio_hours')
    expect(unitData.input_audio_seconds?.price_key).toBe('input_audio_hours')
    expect(unitData.input_text_messages?.price_key).toBe('input_text_messages_kcount')
    expect(unitData.output_audio_seconds?.price_key).toBe('output_audio_hours')
    expect(unitData.input_annotated_document_pages?.dimensions.page_type).toBe('annotated')
    expect(unitData.requests?.dimensions.family).toBe('requests')
    expect(unitData.requests?.price_key).toBe('requests_kcount')
  })

  it('constructs a runtime UnitRegistry from generated raw unit data', () => {
    const registry = new UnitRegistry(unitData)

    expect(registry.getUnit('input_tokens')?.priceKey).toBe('input_mtok')
    expect(registry.getAllUsageKeys().size).toBe(reportableUsageKeys.length + 1)
    expect(registry.getUnitForPriceKey('cache_image_write_mtok')?.usageKey).toBe('cache_image_write_tokens')
    expect(registry.getUnitForPriceKey('web_searches_kcount')?.usageKey).toBe('web_searches')
    expect(registry.getUnitForPriceKey('requests_kcount')?.usageKey).toBe('requests')
  })

  it.each([
    {
      expectedPrices: {
        cache_read_mtok: { base: 0.5, tiers: [{ price: 1, start: 272_000 }] },
        cache_write_mtok: { base: 6.25, tiers: [{ price: 12.5, start: 272_000 }] },
        input_mtok: { base: 5, tiers: [{ price: 10, start: 272_000 }] },
        output_mtok: { base: 30, tiers: [{ price: 45, start: 272_000 }] },
      },
      model: 'gpt-5.6-sol',
      timestamp: new Date('2026-08-20T23:59:59Z'),
    },
    {
      expectedPrices: {
        cache_read_mtok: { base: 0.4, tiers: [{ price: 0.8, start: 272_000 }] },
        cache_write_mtok: { base: 5, tiers: [{ price: 10, start: 272_000 }] },
        input_mtok: { base: 4, tiers: [{ price: 8, start: 272_000 }] },
        output_mtok: { base: 20, tiers: [{ price: 30, start: 272_000 }] },
      },
      model: 'gpt-5.6-sol',
      timestamp: new Date('2026-08-21T00:00:00Z'),
    },
    {
      expectedPrices: {
        cache_read_mtok: { base: 0.1, tiers: [{ price: 0.2, start: 272_000 }] },
        cache_write_mtok: { base: 1.25, tiers: [{ price: 2.5, start: 272_000 }] },
        input_mtok: { base: 1, tiers: [{ price: 2, start: 272_000 }] },
        output_mtok: { base: 6, tiers: [{ price: 9, start: 272_000 }] },
      },
      model: 'gpt-5.6-luna',
      timestamp: new Date('2026-07-29T23:59:59Z'),
    },
    {
      expectedPrices: {
        cache_read_mtok: { base: 0.02, tiers: [{ price: 0.04, start: 272_000 }] },
        cache_write_mtok: { base: 0.25, tiers: [{ price: 0.5, start: 272_000 }] },
        input_mtok: { base: 0.2, tiers: [{ price: 0.4, start: 272_000 }] },
        output_mtok: { base: 1.2, tiers: [{ price: 1.8, start: 272_000 }] },
      },
      model: 'gpt-5.6-luna',
      timestamp: new Date('2026-07-30T00:00:00Z'),
    },
    {
      expectedPrices: {
        cache_read_mtok: { base: 0.25, tiers: [{ price: 0.5, start: 272_000 }] },
        cache_write_mtok: { base: 3.125, tiers: [{ price: 6.25, start: 272_000 }] },
        input_mtok: { base: 2.5, tiers: [{ price: 5, start: 272_000 }] },
        output_mtok: { base: 15, tiers: [{ price: 22.5, start: 272_000 }] },
      },
      model: 'gpt-5.6-terra',
      timestamp: new Date('2026-07-29T23:59:59Z'),
    },
    {
      expectedPrices: {
        cache_read_mtok: { base: 0.2, tiers: [{ price: 0.4, start: 272_000 }] },
        cache_write_mtok: { base: 2.5, tiers: [{ price: 5, start: 272_000 }] },
        input_mtok: { base: 2, tiers: [{ price: 4, start: 272_000 }] },
        output_mtok: { base: 12, tiers: [{ price: 18, start: 272_000 }] },
      },
      model: 'gpt-5.6-terra',
      timestamp: new Date('2026-07-30T00:00:00Z'),
    },
  ])('preserves $model prices at $timestamp', ({ expectedPrices, model, timestamp }) => {
    const result = calcPrice({ input_tokens: 0 }, model, { providerId: 'openai', timestamp })

    expect(result?.model_price).toEqual(expectedPrices)
  })

  it.each([
    { expectedInput: 2, model: 'claude-sonnet-5', providerId: 'anthropic' },
    { expectedInput: 2, model: 'global.anthropic.claude-sonnet-5-v1:0', providerId: 'aws' },
    { expectedInput: 2.2, model: 'us.anthropic.claude-sonnet-5-v1:0', providerId: 'aws' },
    { expectedInput: 2, model: 'anthropic/claude-sonnet-5', providerId: 'openrouter' },
  ])('keeps $providerId $model at its launch price', ({ expectedInput, model, providerId }) => {
    const result = calcPrice({ input_tokens: 1_000_000 }, model, {
      providerId,
      timestamp: new Date('2026-09-01T00:00:00Z'),
    })

    expect(result?.input_price).toBe(expectedInput)
    expect(result?.total_price).toBe(expectedInput)
  })

  it.each([
    { expectedOutput: 0.3, model: 'voxtral-small-2507', timestamp: new Date('2026-08-10T00:00:00Z') },
    { expectedOutput: 0.4, model: 'voxtral-small-latest', timestamp: new Date('2026-08-11T00:00:00Z') },
  ])('preserves Voxtral Small output pricing at $timestamp', ({ expectedOutput, model, timestamp }) => {
    const result = calcPrice({ output_tokens: 1_000_000 }, model, { providerId: 'mistral', timestamp })

    expect(result?.model.id).toBe('voxtral-small-24b-2507')
    expect(result?.output_price).toBe(expectedOutput)
    expect(result?.total_price).toBe(expectedOutput)
  })

  it.each([
    {
      expectedInput: 0.1,
      expectedModelId: 'ministral-8b',
      expectedOutput: 0.1,
      model: 'ministral-8b-2410',
      timestamp: new Date('2026-08-24T00:00:00Z'),
    },
    {
      expectedInput: 0.15,
      expectedModelId: 'ministral-8b-2512',
      expectedOutput: 0.15,
      model: 'ministral-8b-2512',
      timestamp: new Date('2026-08-24T00:00:00Z'),
    },
    {
      expectedInput: 0.1,
      expectedModelId: 'ministral-8b-latest',
      expectedOutput: 0.1,
      model: 'ministral-8b-latest',
      timestamp: new Date('2025-12-01T00:00:00Z'),
    },
    {
      expectedInput: 0.15,
      expectedModelId: 'ministral-8b-latest',
      expectedOutput: 0.15,
      model: 'ministral-8b-latest',
      timestamp: new Date('2025-12-02T00:00:00Z'),
    },
    {
      expectedInput: 2.7,
      expectedModelId: 'mistral-medium-2312',
      expectedOutput: 8.1,
      model: 'mistral-medium-2312',
      timestamp: new Date('2025-06-15T00:00:00Z'),
    },
    {
      expectedInput: 0.4,
      expectedModelId: 'mistral-medium-3-1',
      expectedOutput: 2,
      model: 'mistral-medium-2505',
      timestamp: new Date('2026-08-24T00:00:00Z'),
    },
    {
      expectedInput: 0.4,
      expectedModelId: 'mistral-medium-3-1',
      expectedOutput: 2,
      model: 'mistral-medium-2508',
      timestamp: new Date('2026-08-24T00:00:00Z'),
    },
    {
      expectedInput: 1.5,
      expectedModelId: 'mistral-medium-3-5',
      expectedOutput: 7.5,
      model: 'mistral-medium-3.5',
      timestamp: new Date('2026-08-24T00:00:00Z'),
    },
    {
      expectedInput: 1.5,
      expectedModelId: 'mistral-medium-3-5',
      expectedOutput: 7.5,
      model: 'mistral-medium-3-5',
      timestamp: new Date('2026-08-24T00:00:00Z'),
    },
    {
      expectedInput: 1.5,
      expectedModelId: 'mistral-medium-3-5',
      expectedOutput: 7.5,
      model: 'mistral-medium-3',
      timestamp: new Date('2026-08-24T00:00:00Z'),
    },
    {
      expectedInput: 0.4,
      expectedModelId: 'mistral-medium-latest',
      expectedOutput: 2,
      model: 'mistral-medium-latest',
      timestamp: new Date('2026-06-15T00:00:00Z'),
    },
    {
      expectedInput: 1.5,
      expectedModelId: 'mistral-medium-latest',
      expectedOutput: 7.5,
      model: 'mistral-medium-latest',
      timestamp: new Date('2026-06-16T00:00:00Z'),
    },
  ])('prices $model at $timestamp', ({ expectedInput, expectedModelId, expectedOutput, model, timestamp }) => {
    const result = calcPrice({ input_tokens: 1_000_000, output_tokens: 1_000_000 }, model, {
      providerId: 'mistral',
      timestamp,
    })

    expect(result?.model.id).toBe(expectedModelId)
    expect(result?.input_price).toBe(expectedInput)
    expect(result?.output_price).toBe(expectedOutput)
    expect(result?.total_price).toBe(expectedInput + expectedOutput)
  })

  it.each([
    { model: 'mistral-medium-2508', timestamp: new Date('2026-08-24T00:00:00Z') },
    { model: 'mistral-medium-latest', timestamp: new Date('2026-06-15T00:00:00Z') },
  ])('prices cached input for $model at $timestamp', ({ model, timestamp }) => {
    const result = calcPrice({ cache_read_tokens: 1_000_000, input_tokens: 1_000_000 }, model, {
      providerId: 'mistral',
      timestamp,
    })

    expect(result?.input_price).toBe(0.04)
    expect(result?.total_price).toBe(0.04)
  })

  it('infers Mistral for the native Voxtral alias', () => {
    const result = calcPrice({ output_tokens: 1 }, 'voxtral-small-latest')

    expect(result?.provider.id).toBe('mistral')
    expect(result?.model.id).toBe('voxtral-small-24b-2507')
  })

  it('does not infer Mistral for a qualified OpenRouter Voxtral model', () => {
    const model = 'mistralai/voxtral-small-24b-2507'

    expect(calcPrice({ output_tokens: 1 }, model)).toBeNull()

    const result = calcPrice({ output_tokens: 1 }, model, { providerApiUrl: 'https://openrouter.ai/api/v1' })
    expect(result?.provider.id).toBe('openrouter')
    expect(result?.model.id).toBe(model)
  })
})
