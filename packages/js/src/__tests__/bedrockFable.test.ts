import { expect, it } from 'vitest'

import { calcPrice } from '../api'

it.each([
  ['eu.anthropic.claude-fable-5', 80.85],
  ['us.anthropic.claude-fable-5', 80.85],
  ['anthropic.claude-fable-5', 80.85],
  ['global.anthropic.claude-fable-5', 73.5],
] as const)('prices the exact AWS Fable ID %s', (model, expected) => {
  const price = calcPrice(
    { cache_read_tokens: 1_000_000, cache_write_tokens: 1_000_000, input_tokens: 3_000_000, output_tokens: 1_000_000 },
    model,
    { providerId: 'aws' }
  )
  expect(price?.provider.id).toBe('aws')
  expect(price?.total_price).toBeCloseTo(expected)
})
