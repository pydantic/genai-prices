import { expect, it } from 'vitest'

import type { PriceContext } from '../types'

import { calcPrice } from '../api'

const ttsCases: { context: PriceContext; model: string; totals: [number, number] }[] = [
  { context: {}, model: 'gemini-3.8-flash-tts', totals: [9.5, 19] },
  { context: { processing: 'batch' }, model: 'gemini-3.8-flash-tts', totals: [4.75, 9.5] },
  { context: { service_tier: 'flex' }, model: 'gemini-3.8-flash-tts', totals: [4.75, 9.5] },
  { context: { service_tier: 'priority' }, model: 'gemini-3.8-flash-tts', totals: [17.1, 34.2] },
  { context: {}, model: 'gemini-3.8-flash-lite-tts', totals: [6.5, 13] },
  { context: { processing: 'batch' }, model: 'gemini-3.8-flash-lite-tts', totals: [3.25, 6.5] },
  { context: { service_tier: 'flex' }, model: 'gemini-3.8-flash-lite-tts', totals: [3.25, 6.5] },
  { context: { service_tier: 'priority' }, model: 'gemini-3.8-flash-lite-tts', totals: [11.7, 23.4] },
]

it.each(ttsCases)('prices $model in $context across the January 2027 boundary', ({ context, model, totals }) => {
  for (const { timestamp, total } of [
    { timestamp: '2026-12-31T23:59:00Z', total: totals[0] },
    { timestamp: '2027-01-01T00:00:00Z', total: totals[1] },
  ]) {
    const price = calcPrice({ input_tokens: 1_000_000, output_audio_tokens: 1_000_000, output_tokens: 1_000_000 }, model, {
      priceContext: context,
      providerId: 'google',
      timestamp: new Date(timestamp),
    })
    expect(price?.model.id).toBe(model)
    expect(price?.total_price).toBeCloseTo(total, 12)
  }
})

it('prices Nano Banana search grounding', () => {
  expect(calcPrice({ web_searches: 1_000 }, 'gemini-nano-banana-2.1', { providerId: 'google' })?.total_price).toBe(14)
})

it.each([
  { model: 'kimi-k2.6', total: 4.7525 },
  { model: 'kimi-k2.7-code', total: 4.76 },
  { model: 'kimi-k2.7-code-highspeed', total: 9.52 },
])('prices the verified Moonshot $model rates', ({ model, total }) => {
  expect(
    calcPrice({ cache_read_tokens: 250_000, input_tokens: 1_000_000, output_tokens: 1_000_000 }, model, {
      providerId: 'moonshotai',
      timestamp: new Date('2026-10-17T00:00:00Z'),
    })?.total_price
  ).toBeCloseTo(total, 12)
})

it.each(['jev-1.14.0', 'jev-preview'])('preserves the default context limit for %s', (model) => {
  const price = calcPrice({ input_tokens: 1_000_000 }, model, { providerId: 'typesafe' })
  expect(price?.model.id).toBe('jev-1.14.0')
  expect(price?.model.context_window).toBe(32_000)
  expect(price?.total_price).toBe(0.042)
})

it('keeps the unverified Grok multi-agent alias unpriced', () => {
  expect(calcPrice({ input_tokens: 1 }, 'grok-4.20-multi-agent-0309', { providerId: 'x-ai' })).toBeNull()
  expect(
    calcPrice({ input_tokens: 200_000, output_tokens: 1_000_000 }, 'grok-4.20-multi-agent', { providerId: 'x-ai' })?.total_price
  ).toBeCloseTo(6.4, 12)
})
