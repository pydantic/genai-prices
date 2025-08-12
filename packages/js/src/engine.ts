import { MatchLogic, ModelInfo, ModelPrice, ModelPriceCalculationResult, Provider, ProviderFindOptions, TieredPrices, Usage } from './types'

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
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    const tier = tiers[i]!
    const nextTierStart = tiers[i + 1]?.start ?? Infinity
    // Tokens in this tier: from tier.start up to nextTierStart or tokens
    const tierTokenCount = Math.max(0, Math.min(tokens, nextTierStart) - tier.start)
    if (tierTokenCount > 0) {
      price += (tierTokenCount * tier.price) / 1_000_000
    }
  }

  return price
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function calcMtokPrice(price: number | TieredPrices | undefined, tokens: number | undefined, _field: string): number {
  if (price === undefined || tokens === undefined) return 0
  if (typeof price === 'number') {
    return (price * tokens) / 1_000_000
  }
  return calcTieredPrice(price, tokens)
}

export function calcPrice(usage: Usage, modelPrice: ModelPrice): ModelPriceCalculationResult {
  let inputPrice = 0
  let outputPrice = 0

  // Input-related prices
  inputPrice += calcMtokPrice(modelPrice.input_mtok, usage.input_tokens, 'input_mtok')
  inputPrice += calcMtokPrice(modelPrice.cache_write_mtok, usage.cache_write_tokens, 'cache_write_mtok')
  inputPrice += calcMtokPrice(modelPrice.cache_read_mtok, usage.cache_read_tokens, 'cache_read_mtok')
  inputPrice += calcMtokPrice(modelPrice.input_audio_mtok, usage.input_audio_tokens, 'input_audio_mtok')
  inputPrice += calcMtokPrice(modelPrice.cache_audio_read_mtok, usage.cache_audio_read_tokens, 'cache_audio_read_mtok')

  // Output-related prices
  outputPrice += calcMtokPrice(modelPrice.output_mtok, usage.output_tokens, 'output_mtok')
  outputPrice += calcMtokPrice(modelPrice.output_audio_mtok, usage.output_audio_tokens, 'output_audio_mtok')

  // Requests price (counted as input cost)
  if (modelPrice.requests_kcount !== undefined) {
    inputPrice += modelPrice.requests_kcount / 1000
  }

  const totalPrice = inputPrice + outputPrice

  return {
    input_price: inputPrice,
    output_price: outputPrice,
    total_price: totalPrice,
  }
}

export function getActiveModelPrice(model: ModelInfo, timestamp: Date): ModelPrice {
  if (!Array.isArray(model.prices)) {
    return model.prices
  }
  // Conditional prices: last active wins
  for (let i = model.prices.length - 1; i >= 0; i--) {
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    const cond = model.prices[i]!
    const constraint = cond.constraint

    if (constraint === undefined) {
      return cond.prices
    }

    if (constraint.type === 'start_date') {
      if (timestamp >= new Date(constraint.start_date)) {
        return cond.prices
      }
    } else {
      // Extract UTC time to match constraint times which are in UTC (with 'Z' suffix)
      const t = timestamp.toISOString().slice(11, 19) // Get "HH:MM:SS" from ISO string
      const startTime = constraint.start_time
      const endTime = constraint.end_time

      // Handle time ranges that span midnight (end time < start time)
      if (endTime < startTime) {
        // Time is in range if it's >= start OR < end
        if (t >= startTime || t < endTime) {
          return cond.prices
        }
      } else {
        // Normal time range (start <= time < end)
        if (t >= startTime && t < endTime) {
          return cond.prices
        }
      }
    }
  }
  // Fallback to first
  // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
  return model.prices[0]!.prices
}

function matchLogic(logic: MatchLogic, text: string): boolean {
  if ('or' in logic) {
    return logic.or.some((clause) => matchLogic(clause, text))
  }
  if ('and' in logic) {
    return logic.and.every((clause) => matchLogic(clause, text))
  }
  if ('equals' in logic) {
    return text === logic.equals
  }
  if ('starts_with' in logic) {
    return text.startsWith(logic.starts_with)
  }
  if ('ends_with' in logic) {
    return text.endsWith(logic.ends_with)
  }
  if ('contains' in logic) {
    return text.includes(logic.contains)
  }
  if ('regex' in logic) {
    return new RegExp(logic.regex).test(text)
  }
  return false
}

function findProviderById(providers: Provider[], providerId: string): Provider | undefined {
  const normalizedProviderId = providerId.toLowerCase().trim()

  const exactMatch = providers.find((p) => p.id === normalizedProviderId)
  if (exactMatch) return exactMatch

  return providers.find((p) => p.provider_match && matchLogic(p.provider_match, normalizedProviderId))
}

export function matchProvider(providers: Provider[], { modelId, providerApiUrl, providerId }: ProviderFindOptions): Provider | undefined {
  if (providerId) {
    return findProviderById(providers, providerId)
  } else if (providerApiUrl) {
    return providers.find((p) => new RegExp(p.api_pattern).test(providerApiUrl))
  } else if (modelId) {
    return providers.find((p) => p.model_match && matchLogic(p.model_match, modelId))
  }
}

export function matchModel(models: ModelInfo[], modelId: string): ModelInfo | undefined {
  return models.find((m) => matchLogic(m.match, modelId))
}
