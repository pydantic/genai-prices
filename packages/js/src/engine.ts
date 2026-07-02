import { computeLeafValues } from './decompose'
import {
  Condition,
  ConditionalPrice,
  MatchLogic,
  ModelInfo,
  ModelPrice,
  ModelPriceCalculationResult,
  PriceContext,
  PriceContextValue,
  Provider,
  ProviderConditionalPrice,
  ProviderFindOptions,
  TieredPrices,
  Usage,
} from './types'
import { getActiveRegistry, getUnitForPriceKey } from './units'
import { getUsageValue } from './usage'
import { validateModelPrice } from './validation'

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

function calcUnitPrice(price: number | TieredPrices | undefined, count: number | undefined, totalInputTokens: number, per: number): number {
  if (price === undefined || count === undefined) return 0
  if (typeof price === 'number') {
    return (price * count) / per
  }
  return (calcTieredPrice(price, count, totalInputTokens) * 1_000_000) / per
}

export function calcPrice(usage: Usage, modelPrice: ModelPrice): ModelPriceCalculationResult {
  const effectivePriceKeys = Object.entries(modelPrice)
    .filter(([, price]) => price !== undefined)
    .map(([priceKey]) => priceKey)
  validateModelPrice(effectivePriceKeys)

  let inputPrice = 0
  let outputPrice = 0
  let totalOnlyPrice = 0

  const hasTieredPrice = effectivePriceKeys.some((priceKey) => isTieredPrice(modelPrice[priceKey]))
  const totalInputTokens = hasTieredPrice ? getUsageValue(usage, 'input_tokens') : 0
  const registry = getActiveRegistry()
  const pricedUnits = effectivePriceKeys.map((priceKey) => getUnitForPriceKey(priceKey))
  const pricedUsageKeys = new Set(pricedUnits.filter((unit) => unit.usageKey !== 'requests').map((unit) => unit.usageKey))
  const leafValues = computeLeafValues(pricedUsageKeys, usage, registry.units)
  if (pricedUnits.some((unit) => unit.usageKey === 'requests')) {
    leafValues.requests = 1
  }

  for (const unit of pricedUnits) {
    const price = modelPrice[unit.priceKey]
    const unitPrice = calcUnitPrice(price, leafValues[unit.usageKey] ?? 0, totalInputTokens, unit.per)
    if (unit.dimensions.direction === 'input') {
      inputPrice += unitPrice
    } else if (unit.dimensions.direction === 'output') {
      outputPrice += unitPrice
    } else {
      totalOnlyPrice += unitPrice
    }
  }

  const totalPrice = inputPrice + outputPrice + totalOnlyPrice

  return {
    input_price: inputPrice,
    output_price: outputPrice,
    total_price: totalPrice,
  }
}

function isTieredPrice(price: number | TieredPrices | undefined): price is TieredPrices {
  return typeof price === 'object'
}

export function getActiveModelPrice(model: ModelInfo, timestamp: Date, priceContext: PriceContext = {}, provider?: Provider): ModelPrice {
  const modelPrice = resolveConditionalPrices(model.prices, timestamp, priceContext, model.id)
  if (provider?.prices === undefined) return modelPrice
  const providerPrice = resolveConditionalPrices(provider.prices, timestamp, priceContext, model.id)
  return mergeProviderPrices(modelPrice, providerPrice)
}

function resolveConditionalPrices(
  prices: ConditionalPrice[] | ModelPrice | ProviderConditionalPrice[] | undefined,
  timestamp: Date,
  priceContext: PriceContext,
  modelId: string
): ModelPrice {
  if (prices === undefined) return {}
  if (!Array.isArray(prices)) return prices

  // Per-unit first-match: for each unit, the first eligible entry that defines it wins.
  const resolved: ModelPrice = {}
  for (const entry of prices) {
    if (!entryEligible(entry, timestamp, priceContext, modelId)) continue
    for (const [priceKey, value] of Object.entries(entry.values)) {
      if (value !== undefined && !(priceKey in resolved)) {
        resolved[priceKey] = value
      }
    }
  }
  return resolved
}

function mergeProviderPrices(modelPrice: ModelPrice, providerPrice: ModelPrice): ModelPrice {
  // Model-level prices override provider-level prices for the same unit.
  return { ...providerPrice, ...modelPrice }
}

function entryEligible(
  entry: ConditionalPrice | ProviderConditionalPrice,
  timestamp: Date,
  priceContext: PriceContext,
  modelId: string
): boolean {
  return constraintActive(entry.constraint, timestamp) && whenMatches(entry.when, priceContext, modelId)
}

function constraintActive(constraint: ConditionalPrice['constraint'], timestamp: Date): boolean {
  if (constraint === undefined) return true
  if (constraint.type === 'start_date') {
    return timestamp >= new Date(constraint.start_date)
  }
  // Extract UTC time to match constraint times which are in UTC (with 'Z' suffix)
  const t = timestamp.toISOString().slice(11, 19) // Get "HH:MM:SS" from ISO string
  const { end_time: endTime, start_time: startTime } = constraint
  // Time ranges that span midnight (end < start) are in range if t >= start OR t < end
  if (endTime < startTime) {
    return t >= startTime || t < endTime
  }
  return t >= startTime && t < endTime
}

function whenMatches(when: Record<string, Condition | MatchLogic> | undefined, priceContext: PriceContext, modelId: string): boolean {
  if (when === undefined) return true
  return Object.entries(when).every(([key, condition]) => {
    if (key === 'model') return modelConditionMatches(condition, modelId)
    return conditionMatches(condition as Condition, priceContext[key])
  })
}

function modelConditionMatches(condition: Condition | MatchLogic, modelId: string): boolean {
  if (typeof condition === 'string') return condition.toLowerCase() === modelId.toLowerCase()
  if (typeof condition === 'object' && isMatchLogic(condition)) return matchLogic(condition, modelId.toLowerCase())
  return false
}

function isMatchLogic(value: object): value is MatchLogic {
  return (
    'starts_with' in value ||
    'ends_with' in value ||
    'contains' in value ||
    'equals' in value ||
    'regex' in value ||
    'or' in value ||
    'and' in value
  )
}

function conditionMatches(condition: Condition, actual: PriceContextValue | undefined): boolean {
  if (typeof condition !== 'object') {
    return contextValuesEqual(actual, condition)
  }
  if (condition.eq !== undefined && !contextValuesEqual(actual, condition.eq)) return false
  if (condition.in !== undefined && !condition.in.some((item) => contextValuesEqual(actual, item))) return false
  if (condition.gte !== undefined && !compareNumeric(actual, condition.gte, (a, b) => a >= b)) return false
  if (condition.lte !== undefined && !compareNumeric(actual, condition.lte, (a, b) => a <= b)) return false
  if (condition.gt !== undefined && !compareNumeric(actual, condition.gt, (a, b) => a > b)) return false
  if (condition.lt !== undefined && !compareNumeric(actual, condition.lt, (a, b) => a < b)) return false
  return true
}

function contextValuesEqual(actual: PriceContextValue | undefined, expected: PriceContextValue): boolean {
  return typeof actual === typeof expected && actual === expected
}

function compareNumeric(
  actual: PriceContextValue | undefined,
  expected: PriceContextValue,
  compare: (a: number, b: number) => boolean
): boolean {
  if (typeof actual !== 'number' || typeof expected !== 'number') return false
  return compare(actual, expected)
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
