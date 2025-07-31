import { Usage, ModelPrice, TieredPrices, ModelInfo, ConditionalPrice, CalcPrice } from './types.js'

function calcTieredPrice(tiered: TieredPrices, tokens: number): number {
  if (tokens <= 0) return 0
  let price = 0
  // Sort tiers by start ascending
  const tiers = [...tiered.tiers].sort((a, b) => a.start - b.start)

  // Base price for tokens up to the first tier start
  const firstTierStart = tiers[0]?.start ?? tokens
  const baseTokens = Math.min(tokens, firstTierStart)
  price += (baseTokens * tiered.base) / 1_000_000

  // Price for each tier
  for (let i = 0; i < tiers.length; i++) {
    const tier = tiers[i]
    const nextTierStart = tiers[i + 1]?.start ?? Infinity
    // Tokens in this tier: from tier.start up to nextTierStart or tokens
    const tierTokenCount = Math.max(0, Math.min(tokens, nextTierStart) - tier.start)
    if (tierTokenCount > 0) {
      price += (tierTokenCount * tier.price) / 1_000_000
    }
  }

  return price
}

function calcMtokPrice(price: number | TieredPrices | undefined, tokens: number | undefined, _field: string): number {
  if (price === undefined || tokens === undefined) return 0
  if (typeof price === 'number') {
    return (price * tokens) / 1_000_000
  }
  return calcTieredPrice(price, tokens)
}

export function calcPrice(usage: Usage, modelPrice: ModelPrice): CalcPrice {
  let input_price = 0
  let output_price = 0

  // Input-related prices
  input_price += calcMtokPrice(modelPrice.input_mtok, usage.input_tokens, 'input_mtok')
  input_price += calcMtokPrice(modelPrice.cache_write_mtok, usage.cache_write_tokens, 'cache_write_mtok')
  input_price += calcMtokPrice(modelPrice.cache_read_mtok, usage.cache_read_tokens, 'cache_read_mtok')
  input_price += calcMtokPrice(modelPrice.input_audio_mtok, usage.input_audio_tokens, 'input_audio_mtok')
  input_price += calcMtokPrice(
    modelPrice.cache_audio_read_mtok,
    usage.cache_audio_read_tokens,
    'cache_audio_read_mtok',
  )

  // Output-related prices
  output_price += calcMtokPrice(modelPrice.output_mtok, usage.output_tokens, 'output_mtok')
  output_price += calcMtokPrice(modelPrice.output_audio_mtok, usage.output_audio_tokens, 'output_audio_mtok')

  // Requests price (counted as input cost)
  if (modelPrice.requests_kcount !== undefined) {
    input_price += modelPrice.requests_kcount * ((usage.requests ?? 1) / 1000)
  }

  const total_price = input_price + output_price

  return {
    input_price,
    output_price,
    total_price,
  }
}

export function getActiveModelPrice(model: ModelInfo, timestamp: Date): ModelPrice {
  if (!Array.isArray(model.prices)) {
    return model.prices
  }
  // Conditional prices: last active wins
  for (let i = model.prices.length - 1; i >= 0; i--) {
    const cond = model.prices[i] as ConditionalPrice
    if (!cond.constraint) return cond.prices
    if (cond.constraint.type === 'start_date') {
      if (timestamp >= new Date(cond.constraint.start_date)) {
        return cond.prices
      }
    } else if (cond.constraint.type === 'time_of_date') {
      const t = timestamp.toTimeString().slice(0, 8)
      if (t >= cond.constraint.start_time && t < cond.constraint.end_time) {
        return cond.prices
      }
    }
  }
  // Fallback to first
  return (model.prices[0] as ConditionalPrice).prices
}
