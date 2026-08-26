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
    { expectedModelId: 'pixtral-12b', expectedTotalPrice: 0.000165, model: 'pixtral-12b-latest' },
    { expectedModelId: 'pixtral-large', expectedTotalPrice: 0.0026, model: 'pixtral-large-2411' },
    { expectedModelId: 'mixtral-8x7b', expectedTotalPrice: 0.00077, model: 'mixtral-8x7b-instruct-v0.1' },
  ])('prices $model without a provider ID', ({ expectedModelId, expectedTotalPrice, model }) => {
    const result = calcPrice({ input_tokens: 1000, output_tokens: 100 }, model)

    expect(result?.provider.id).toBe('mistral')
    expect(result?.model.id).toBe(expectedModelId)
    expect(result?.total_price).toBeCloseTo(expectedTotalPrice, 12)
  })

  it.each([
    {
      cacheReadRate: 0.0165,
      contextWindow: 1_000_000,
      inputRate: 0.0805,
      model: 'deepseek/deepseek-v4-flash',
      outputRate: 0.161,
    },
    { cacheReadRate: 0.10875, contextWindow: 1_000_000, inputRate: 1.305, model: 'deepseek/deepseek-v4-pro', outputRate: 2.61 },
    {
      cacheReadRate: 0.0198,
      contextWindow: 1_000_000,
      inputRate: 0.594,
      model: 'deepseek/deepseek-v4-pro-0813',
      outputRate: 1.782,
    },
    { cacheReadRate: 0.012, contextWindow: 163_000, inputRate: 0.23, model: 'deepseek/deepseek-v3.2', outputRate: 0.33 },
    { cacheReadRate: 0.15, contextWindow: 196_000, inputRate: 0.27, model: 'minimax/minimax-m2.5', outputRate: 1.08 },
    { cacheReadRate: 0.097, contextWindow: 202_000, inputRate: 0.388, model: 'z-ai/glm-4.7', outputRate: 1.806 },
    { cacheReadRate: 0.129, contextWindow: 205_000, inputRate: 0.516, model: 'z-ai/glm-5', outputRate: 2.322 },
    { cacheReadRate: 0.186, contextWindow: 202_000, inputRate: 0.743, model: 'z-ai/glm-5.1', outputRate: 2.971 },
    { cacheReadRate: 0.124, contextWindow: 1_000_000, inputRate: 0.495, model: 'z-ai/glm-5.2', outputRate: 1.733 },
    { cacheReadRate: 0.225, contextWindow: 262_000, inputRate: 0.45, model: 'moonshotai/kimi-k2.5', outputRate: 2.2 },
    { cacheReadRate: 0.16, contextWindow: 262_000, inputRate: 0.95, model: 'moonshotai/kimi-k2.6', outputRate: 4 },
    { cacheReadRate: 0.05, contextWindow: 1_000_000, inputRate: 0.2, model: 'xiaomi/mimo-v2.5', outputRate: 0.4 },
    { cacheReadRate: 0.0036, contextWindow: 1_000_000, inputRate: 0.435, model: 'xiaomi/mimo-v2.5-pro', outputRate: 0.87 },
  ])('prices Avian $model', ({ cacheReadRate, contextWindow, inputRate, model, outputRate }) => {
    const result = calcPrice({ cache_read_tokens: 1_000_000, input_tokens: 2_000_000, output_tokens: 1_000_000 }, model, {
      providerId: 'avian',
    })

    expect(result?.provider.id).toBe('avian')
    expect(result?.model.id).toBe(model)
    expect(result?.model.context_window).toBe(contextWindow)
    expect(result?.input_price).toBeCloseTo(inputRate + cacheReadRate, 12)
    expect(result?.output_price).toBeCloseTo(outputRate, 12)
    expect(result?.total_price).toBeCloseTo(inputRate + cacheReadRate + outputRate, 12)
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

  it('uses the inclusive OpenAI long-context boundary', () => {
    const result = calcPrice({ input_tokens: 272_000 }, 'gpt-5.4', { providerId: 'openai' })

    expect(result?.input_price).toBe(1.36)
  })

  it('uses the OpenAI boundary convention through Azure fallback', () => {
    const result = calcPrice({ input_tokens: 272_000 }, 'gpt-5.4', { providerId: 'azure' })

    expect(result?.provider.id).toBe('azure')
    expect(result?.model.id).toBe('gpt-5.4')
    expect(result?.input_price).toBe(1.36)
  })

  it('uses the inclusive xAI tier boundary', () => {
    const xai = providerDataModule.data.find((provider) => provider.id === 'x-ai')
    if (xai === undefined) {
      throw new Error('xAI provider data is missing')
    }
    const model = {
      ...xai.models[0],
      id: 'grok-tiered',
      match: { equals: 'grok-tiered' },
      prices: { input_mtok: { base: 1, tiers: [{ price: 2, start: 200_000 }] } },
    }
    const result = calcPrice({ input_tokens: 200_000 }, model.id, { provider: { ...xai, models: [model] } })

    expect(result?.input_price).toBe(0.4)
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

  it.each([
    {
      expectedAnnotatedPagePrice: 1,
      expectedModelId: 'mistral-ocr-2503',
      expectedPagePrice: 1,
      model: 'mistral-ocr-2503-completion',
      timestamp: new Date('2025-03-06T00:00:00Z'),
    },
    {
      expectedAnnotatedPagePrice: 3,
      expectedModelId: 'mistral-ocr-2505',
      expectedPagePrice: 1,
      model: 'mistral-ocr-2505',
      timestamp: new Date('2025-05-22T00:00:00Z'),
    },
    {
      expectedAnnotatedPagePrice: 1,
      expectedModelId: 'mistral-ocr-latest',
      expectedPagePrice: 1,
      model: 'mistral-ocr-latest',
      timestamp: new Date('2025-03-06T00:00:00Z'),
    },
    {
      expectedAnnotatedPagePrice: 3,
      expectedModelId: 'mistral-ocr-2512',
      expectedPagePrice: 2,
      model: 'mistral-ocr-2512-completion',
      timestamp: new Date('2025-12-18T00:00:00Z'),
    },
    {
      expectedAnnotatedPagePrice: 5,
      expectedModelId: 'mistral-ocr-4-0',
      expectedPagePrice: 4,
      model: 'mistral-ocr-4-0',
      timestamp: new Date('2026-06-23T00:00:00Z'),
    },
    {
      expectedAnnotatedPagePrice: 5,
      expectedModelId: 'mistral-ocr-4-1',
      expectedPagePrice: 4,
      model: 'mistral-ocr-4',
      timestamp: new Date('2026-07-16T00:00:00Z'),
    },
    {
      expectedAnnotatedPagePrice: 3,
      expectedModelId: 'mistral-ocr-latest',
      expectedPagePrice: 1,
      model: 'mistral-ocr-latest',
      timestamp: new Date('2025-05-22T00:00:00Z'),
    },
    {
      expectedAnnotatedPagePrice: 3,
      expectedModelId: 'mistral-ocr-latest',
      expectedPagePrice: 1,
      model: 'mistral-ocr-latest',
      timestamp: new Date('2025-12-17T00:00:00Z'),
    },
    {
      expectedAnnotatedPagePrice: 3,
      expectedModelId: 'mistral-ocr-latest',
      expectedPagePrice: 2,
      model: 'mistral-ocr-latest',
      timestamp: new Date('2025-12-18T00:00:00Z'),
    },
    {
      expectedAnnotatedPagePrice: 5,
      expectedModelId: 'mistral-ocr-latest',
      expectedPagePrice: 4,
      model: 'mistral-ocr-latest',
      timestamp: new Date('2026-06-23T00:00:00Z'),
    },
  ])(
    'prices OCR pages for $model at $timestamp',
    ({ expectedAnnotatedPagePrice, expectedModelId, expectedPagePrice, model, timestamp }) => {
      const pagePrice = calcPrice({ input_document_pages: 1_000 }, model, { providerId: 'mistral', timestamp })
      const annotatedPagePrice = calcPrice({ input_annotated_document_pages: 1_000, input_document_pages: 1_000 }, model, {
        providerId: 'mistral',
        timestamp,
      })

      expect(pagePrice?.model.id).toBe(expectedModelId)
      expect(pagePrice?.input_price).toBe(expectedPagePrice)
      expect(pagePrice?.total_price).toBe(expectedPagePrice)
      expect(annotatedPagePrice?.input_price).toBe(expectedAnnotatedPagePrice)
      expect(annotatedPagePrice?.total_price).toBe(expectedAnnotatedPagePrice)
    }
  )

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
