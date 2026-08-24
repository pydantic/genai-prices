import { describe, expect, it } from 'vitest'

import type { Provider } from '../types'

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
    { expectedPrice: 0.0000375, model: 'gpt-transcribe', providerId: 'openai', seconds: 0.5 },
    { expectedPrice: 0.003, model: 'whisper-1', providerId: 'openai', seconds: 30 },
    { expectedPrice: 0.00185, model: 'whisper-large-v3', providerId: 'groq', seconds: 60 },
    { expectedPrice: 0.001, model: 'whisper-large-v3-turbo', providerId: 'groq', seconds: 90 },
    { expectedPrice: 0.003, model: 'voxtral-mini-2602', providerId: 'mistral', seconds: 60 },
  ])('prices $model transcription duration', ({ expectedPrice, model, providerId, seconds }) => {
    const result = calcPrice({ audio_seconds: seconds, input_audio_seconds: seconds }, model, { providerId })

    expect(result?.input_price).toBeCloseTo(expectedPrice, 15)
    expect(result?.output_price).toBe(0)
    expect(result?.total_price).toBeCloseTo(expectedPrice, 15)
  })

  it.each([
    { billedSeconds: 10, hourlyRate: 0.111, model: 'whisper-large-v3', reportedSeconds: 1 },
    { billedSeconds: 10, hourlyRate: 0.111, model: 'whisper-large-v3', reportedSeconds: 10 },
    { billedSeconds: 11, hourlyRate: 0.111, model: 'whisper-large-v3', reportedSeconds: 11 },
    { billedSeconds: 10, hourlyRate: 0.04, model: 'whisper-large-v3-turbo', reportedSeconds: 1 },
    { billedSeconds: 10, hourlyRate: 0.04, model: 'whisper-large-v3-turbo', reportedSeconds: 10 },
    { billedSeconds: 11, hourlyRate: 0.04, model: 'whisper-large-v3-turbo', reportedSeconds: 11 },
  ])(
    'applies the minimum billed duration for $model at $reportedSeconds seconds',
    ({ billedSeconds, hourlyRate, model, reportedSeconds }) => {
      const result = calcPrice({ audio_seconds: reportedSeconds, input_audio_seconds: reportedSeconds }, model, { providerId: 'groq' })
      const expectedPrice = (hourlyRate * billedSeconds) / 3_600

      expect(result?.input_price).toBeCloseTo(expectedPrice, 15)
      expect(result?.total_price).toBeCloseTo(expectedPrice, 15)
    }
  )

  it('preserves zero duration subtypes and the caller usage when applying a minimum', () => {
    const usage = { audio_seconds: 5, input_audio_seconds: 0 }

    const result = calcPrice(usage, 'whisper-large-v3', { providerId: 'groq' })

    expect(result?.input_price).toBe(0)
    expect(result?.total_price).toBeCloseTo((0.111 * 10) / 3_600, 15)
    expect(usage).toEqual({ audio_seconds: 5, input_audio_seconds: 0 })
  })

  it.each([-1, Number.NEGATIVE_INFINITY, Number.POSITIVE_INFINITY, Number.NaN])(
    'rejects invalid reported audio duration %s before applying a minimum',
    (seconds) => {
      expect(() => calcPrice({ audio_seconds: seconds }, 'whisper-large-v3', { providerId: 'groq' })).toThrow(
        'Invalid usage value for audio_seconds: expected a finite non-negative number'
      )
    }
  )

  it('rejects invalid original duration relationships before applying a minimum', () => {
    expect(() => calcPrice({ audio_seconds: 5, input_audio_seconds: 6 }, 'whisper-large-v3', { providerId: 'groq' })).toThrow(
      'Invalid usage data: input_audio_seconds (6) cannot exceed audio_seconds (5)'
    )
  })

  it('rejects invalid directional duration totals before applying a minimum', () => {
    expect(() =>
      calcPrice({ audio_seconds: 5, input_audio_seconds: 3, output_audio_seconds: 3 }, 'whisper-large-v3', {
        providerId: 'groq',
      })
    ).toThrow(
      'Invalid usage data: more-specific usage for input_audio_seconds, output_audio_seconds totals 6, which exceeds audio_seconds (5)'
    )
  })

  it('accepts directional duration totals within floating-point rounding tolerance', () => {
    const result = calcPrice({ audio_seconds: 0.3, input_audio_seconds: 0.1, output_audio_seconds: 0.2 }, 'whisper-large-v3', {
      providerId: 'groq',
    })

    expect(result?.total_price).toBeCloseTo((0.111 * 10) / 3_600, 15)
  })

  it('preserves the billed aggregate when directional durations fully attribute it', () => {
    const provider: Provider = {
      api_pattern: '',
      id: 'groq',
      models: [
        {
          id: 'whisper-large-v3',
          match: { equals: 'whisper-large-v3' },
          prices: { audio_hours: 0.1, input_audio_hours: 0.1, output_audio_hours: 0.1 },
        },
      ],
      name: 'Groq',
    }
    const result = calcPrice({ audio_seconds: 0.3, input_audio_seconds: 0.1, output_audio_seconds: 0.2 }, 'whisper-large-v3', { provider })

    expect(result?.input_price).toBeCloseTo((0.1 * (10 / 3)) / 3_600, 15)
    expect((result?.input_price ?? 0) + (result?.output_price ?? 0)).toBe(result?.total_price)
  })

  it('rejects a positive directional duration when the aggregate duration is zero', () => {
    expect(() =>
      calcPrice({ audio_seconds: 0, input_audio_seconds: Number.MIN_VALUE }, 'whisper-large-v3', { providerId: 'groq' })
    ).toThrow(`Invalid usage data: input_audio_seconds (${Number.MIN_VALUE.toString()}) cannot exceed audio_seconds (0)`)
  })

  it('rejects a directional duration total that overflows', () => {
    expect(() =>
      calcPrice(
        { audio_seconds: Number.MAX_VALUE, input_audio_seconds: Number.MAX_VALUE, output_audio_seconds: Number.MAX_VALUE },
        'whisper-large-v3',
        { providerId: 'groq' }
      )
    ).toThrow(
      `Invalid usage data: more-specific usage for input_audio_seconds, output_audio_seconds totals Infinity, which exceeds audio_seconds (${Number.MAX_VALUE.toString()})`
    )
  })

  it('scales directional audio usage when applying a minimum duration', () => {
    const usage = { audio_seconds: 5, input_audio_seconds: 2, output_audio_seconds: 3 }
    const provider: Provider = {
      api_pattern: '',
      id: 'groq',
      models: [
        {
          id: 'whisper-large-v3',
          match: { equals: 'whisper-large-v3' },
          prices: { audio_hours: 0.1, input_audio_hours: 0.1, output_audio_hours: 0.1 },
        },
      ],
      name: 'Groq',
    }

    const result = calcPrice(usage, 'whisper-large-v3', { provider })

    expect(result?.input_price).toBeCloseTo((0.1 * 4) / 3_600, 15)
    expect(result?.output_price).toBeCloseTo((0.1 * 6) / 3_600, 15)
    expect(result?.total_price).toBeCloseTo((0.1 * 10) / 3_600, 15)
    expect(usage).toEqual({ audio_seconds: 5, input_audio_seconds: 2, output_audio_seconds: 3 })
  })

  it('scales extremely small directional audio usage without overflowing', () => {
    const provider: Provider = {
      api_pattern: '',
      id: 'groq',
      models: [
        {
          id: 'whisper-large-v3',
          match: { equals: 'whisper-large-v3' },
          prices: { audio_hours: 0.1, input_audio_hours: 0.1 },
        },
      ],
      name: 'Groq',
    }

    const result = calcPrice({ audio_seconds: Number.MIN_VALUE, input_audio_seconds: Number.MIN_VALUE }, 'whisper-large-v3', { provider })

    expect(result?.input_price).toBeCloseTo((0.1 * 10) / 3_600, 15)
  })

  it('matches only verified OpenAI diarization model IDs', () => {
    expect(calcPrice({ input_audio_tokens: 1, input_tokens: 1 }, 'gpt-4o-transcribe-diarize', { providerId: 'openai' })?.model.id).toBe(
      'gpt-4o-transcribe'
    )
    expect(calcPrice({}, 'gpt-transcribe-diarize', { providerId: 'openai' })).toBeNull()
  })
})
