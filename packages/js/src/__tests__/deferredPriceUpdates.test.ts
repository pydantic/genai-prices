import { expect, it } from 'vitest'

import { calcPrice } from '../api'

it.each([
  { cache: 0.0165, input: 0.0805, model: 'deepseek/deepseek-v4-flash', output: 0.161, providerId: 'avian' },
  { cache: 0.0198, input: 0.594, model: 'deepseek/deepseek-v4-pro-0813', output: 1.782, providerId: 'avian' },
  { cache: 0.0036, input: 0.435, model: 'xiaomi/mimo-v2.5-pro', output: 0.87, providerId: 'avian' },
  { cache: 0.05, input: 0.2, model: 'xiaomi/mimo-v2.6-flash', output: 0.4, providerId: 'avian' },
  { cache: 0.0036, input: 0.435, model: 'xiaomi/mimo-v2.6-pro', output: 0.87, providerId: 'avian' },
  { cache: 0.2, input: 2, model: 'claude-sonnet-5.5', output: 10, providerId: 'github-copilot' },
])('preserves $providerId $model rates without an effective date', ({ cache, input, model, output, providerId }) => {
  for (const date of ['2026-09-30', '2026-10-09']) {
    const result = calcPrice({ cache_read_tokens: 1_000_000, input_tokens: 2_000_000, output_tokens: 1_000_000 }, model, {
      providerId,
      timestamp: new Date(`${date}T00:00:00Z`),
    })

    expect(result?.input_price).toBeCloseTo(input + cache, 12)
    expect(result?.output_price).toBe(output)
  }
})
