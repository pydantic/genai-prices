import { MatchLogic, ModelInfo, ModelPrice, ModelPriceCalculationResult, Provider, ProviderFindOptions, TieredPrices, Usage } from './types'

/**
 * Calculate price using threshold-based (cliff) pricing model.
 *
 * When token count crosses a tier threshold, ALL tokens are charged at that tier's rate.
 * This is the industry standard used by Anthropic, Google, OpenAI, and most other providers.
 *
 * Example with base=$3/MTok and tier at 200K=$6/MTok:
 * - 199,999 tokens: all at $3/MTok = $0.599997
 * - 200,001 tokens: all at $6/MTok = $1.200006 (cliff jump)
 *
 * @param tiered - Tiered pricing structure
 * @param tokens - Number of tokens of this specific type to price
 * @param totalInputTokens - Total input tokens for tier determination
 */
function calcTieredPrice(tiered: TieredPrices, tokens: number, totalInputTokens: number): number {
  if (tokens <= 0) return 0

  // Threshold-based pricing: tier is determined by totalInputTokens
  // When totalInputTokens is 0, no tier condition is met, so base rate is used
  let applicablePrice = tiered.base
  for (const tier of tiered.tiers) {
    if (totalInputTokens > tier.start) {
      applicablePrice = tier.price
    }
  }

  // All tokens pay the applicable rate
  return (applicablePrice * tokens) / 1_000_000
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function calcMtokPrice(
  price: number | TieredPrices | undefined,
  tokens: number | undefined,
  _field: string,
  totalInputTokens: number
): number {
  if (price === undefined || tokens === undefined) return 0
  if (typeof price === 'number') {
    return (price * tokens) / 1_000_000
  }
  return calcTieredPrice(price, tokens, totalInputTokens)
}

export function calcPrice(usage: Usage, modelPrice: ModelPrice): ModelPriceCalculationResult {
  let inputPrice = 0
  let outputPrice = 0

  // Calculate total input tokens for tier determination
  const totalInputTokens = usage.input_tokens ?? 0

  const cacheReadTokens = usage.cache_read_tokens ?? 0
  const cacheWriteTokens = usage.cache_write_tokens ?? 0
  const cacheAudioReadTokens = usage.cache_audio_read_tokens ?? 0
  const outputAudioTokens = usage.output_audio_tokens ?? 0

  let uncachedAudioInputTokens = usage.input_audio_tokens ?? 0
  uncachedAudioInputTokens -= cacheAudioReadTokens
  if (uncachedAudioInputTokens < 0) {
    throw new Error('cache_audio_read_tokens cannot be greater than input_audio_tokens')
  }

  let uncachedTextInputTokens = usage.input_tokens ?? 0
  uncachedTextInputTokens -= cacheReadTokens
  uncachedTextInputTokens -= cacheWriteTokens
  uncachedTextInputTokens -= uncachedAudioInputTokens
  if (uncachedTextInputTokens < 0) {
    throw new Error('Uncached text input tokens cannot be negative')
  }

  let cachedTextInputTokens = cacheReadTokens
  cachedTextInputTokens -= cacheAudioReadTokens
  if (cachedTextInputTokens < 0) {
    throw new Error('cache_audio_read_tokens cannot be greater than cache_read_tokens')
  }

  inputPrice += calcMtokPrice(modelPrice.input_mtok, uncachedTextInputTokens, 'input_mtok', totalInputTokens)
  inputPrice += calcMtokPrice(modelPrice.cache_read_mtok, cachedTextInputTokens, 'cache_read_mtok', totalInputTokens)
  inputPrice += calcMtokPrice(modelPrice.cache_write_mtok, cacheWriteTokens, 'cache_write_mtok', totalInputTokens)
  inputPrice += calcMtokPrice(modelPrice.input_audio_mtok, uncachedAudioInputTokens, 'input_audio_mtok', totalInputTokens)
  inputPrice += calcMtokPrice(modelPrice.cache_audio_read_mtok, cacheAudioReadTokens, 'cache_audio_read_mtok', totalInputTokens)

  let textOutputTokens = usage.output_tokens ?? 0
  textOutputTokens -= outputAudioTokens
  if (textOutputTokens < 0) {
    throw new Error('output_audio_tokens cannot be greater than output_tokens')
  }
  outputPrice += calcMtokPrice(modelPrice.output_mtok, textOutputTokens, 'output_mtok', totalInputTokens)
  outputPrice += calcMtokPrice(modelPrice.output_audio_mtok, usage.output_audio_tokens, 'output_audio_mtok', totalInputTokens)

  let totalPrice = inputPrice + outputPrice
  if (modelPrice.requests_kcount !== undefined) {
    totalPrice += modelPrice.requests_kcount / 1000
  }
  if (modelPrice.tool_use_kcount && usage.tool_use) {
    for (const [unit, price] of Object.entries(modelPrice.tool_use_kcount)) {
      const count = usage.tool_use[unit] ?? 0
      if (count) {
        totalPrice += (price * count) / 1000
      }
    }
  }

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

export function matchLogic(logic: MatchLogic, text: string): boolean {
  if ('or' in logic) {
    return logic.or.some((clause) => matchLogic(clause, text))
  } else if ('and' in logic) {
    return logic.and.every((clause) => matchLogic(clause, text))
  } else if ('equals' in logic) {
    return text === logic.equals
  } else if ('starts_with' in logic) {
    return text.startsWith(logic.starts_with)
  } else if ('ends_with' in logic) {
    return text.endsWith(logic.ends_with)
  } else if ('contains' in logic) {
    return text.includes(logic.contains)
  } else if ('regex' in logic) {
    return new RegExp(logic.regex).test(text)
  } else {
    return false
  }
}

function findProviderById(providers: Provider[], providerId: string): Provider | undefined {
  const normalizedProviderId = providerId.toLowerCase().trim()

  const exactMatch = providers.find((p) => p.id === normalizedProviderId)
  if (exactMatch) return exactMatch

  return providers.find((p) => p.provider_match && matchLogic(p.provider_match, normalizedProviderId))
}

export function matchProvider(providers: Provider[], { modelId, providerApiUrl, providerId }: ProviderFindOptions): Provider | undefined {
  if (providerId) {
    const provider = findProviderById(providers, providerId)
    // Special case for litellm: fall back to model matching if provider not found
    if (provider || providerId.toLowerCase() !== 'litellm') {
      return provider
    }
    // Fall through to model matching for litellm
  }

  if (providerApiUrl) {
    return providers.find((p) => new RegExp(p.api_pattern).test(providerApiUrl))
  }

  if (modelId) {
    return providers.find((p) => p.model_match && matchLogic(p.model_match, modelId))
  }
}

export function matchModel(models: ModelInfo[], modelId: string): ModelInfo | undefined {
  return models.find((m) => matchLogic(m.match, modelId))
}

export function matchModelWithFallback(provider: Provider, modelId: string, allProviders?: Provider[]): ModelInfo | undefined {
  const model = matchModel(provider.models, modelId)
  if (model) return model

  if (provider.fallback_model_providers && allProviders) {
    for (const fallbackProviderId of provider.fallback_model_providers) {
      const fallbackProvider = allProviders.find((p) => p.id === fallbackProviderId)
      if (fallbackProvider) {
        // don't pass allProviders when falling back, so we can only have one step of fallback
        const fallbackModel = matchModelWithFallback(fallbackProvider, modelId)
        if (fallbackModel) return fallbackModel
      }
    }
  }
  return undefined
}
