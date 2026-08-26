import type { PriceCalculationResult, PriceOptions, Provider, ProviderFindOptions, StorageFactoryParams, Usage } from './types'

import { data as embeddedData } from './data'
import { calcPrice as calcPriceInternal, getActiveModelPrice, matchModelWithFallback, matchProvider } from './engine'
import { utcTimeOfDaySeconds } from './timeOfDay'
import { warnUnsupportedExtractorDestinations } from './validation'

export const REMOTE_DATA_JSON_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/new_data/v2/data.json'

let providerData: Provider[] = embeddedData
let providerDataPromise: Promise<null | Provider[]> = Promise.resolve(embeddedData)
let autoUpdateCb: (() => void) | null = null

function setProviderData(data: unknown) {
  // null means the update failed; keep existing data
  if (data === null) {
    return
  }
  if (isPromiseLike(data)) {
    const updatePromise = Promise.resolve(data)
      .then((data) => {
        if (data === null || providerDataPromise !== updatePromise) {
          return providerData
        }
        return activateProviderData(data)
      })
      .catch((error: unknown) => {
        if (providerDataPromise === updatePromise) {
          providerDataPromise = Promise.resolve(providerData)
        }
        throw error
      })
    // Updates may be fire-and-forget. Observe failures without changing the
    // original promise returned by waitForUpdate() to callers that do await it.
    // A rejected update never replaces the active data, so warn to make the
    // resulting staleness observable to fire-and-forget consumers.
    updatePromise.catch((error: unknown) => {
      console.warn(
        `genai-prices: provider data update rejected; keeping previously active data: ${error instanceof Error ? error.message : String(error)}`
      )
    })
    providerDataPromise = updatePromise
  } else {
    providerDataPromise = Promise.resolve(activateProviderData(data))
  }
}

function activateProviderData(data: unknown): Provider[] {
  if (!Array.isArray(data)) {
    throw new Error('Expected null or Provider[]')
  }

  const providers = data.map(validateProvider)
  warnUnsupportedExtractorDestinations(providers)
  providerData = providers
  return providers
}

function validateProvider(provider: unknown): Provider {
  if (
    !isRecord(provider) ||
    typeof provider.api_pattern !== 'string' ||
    typeof provider.id !== 'string' ||
    !Array.isArray(provider.models) ||
    typeof provider.name !== 'string'
  ) {
    throw new Error('Expected null or Provider[]')
  }

  for (const model of provider.models) {
    if (!isRecord(model) || typeof model.id !== 'string' || !('prices' in model)) {
      throw new Error('Expected null or Provider[]')
    }
    if (Array.isArray(model.prices)) {
      for (const conditionalPrice of model.prices) {
        validateConditionalPrice(conditionalPrice, provider.id, model.id)
      }
    }
  }

  return provider as unknown as Provider
}

function validateConditionalPrice(conditionalPrice: unknown, providerId: string, modelId: string): void {
  if (!isRecord(conditionalPrice) || !isRecord(conditionalPrice.prices)) {
    throw new Error('Expected null or Provider[]')
  }
  const constraint: unknown = conditionalPrice.constraint
  if (constraint === undefined) {
    return
  }
  if (!isRecord(constraint)) {
    throw invalidConstraintError(constraint, providerId, modelId)
  }
  if (hasExactKeys(constraint, ['start_date']) && isValidStartDate(constraint.start_date)) {
    return
  }
  if (
    hasExactKeys(constraint, ['end_time', 'start_time']) &&
    isValidTimeOfDay(constraint.start_time) &&
    isValidTimeOfDay(constraint.end_time)
  ) {
    return
  }
  throw invalidConstraintError(constraint, providerId, modelId)
}

function invalidConstraintError(constraint: unknown, providerId: string, modelId: string): Error {
  return new Error(
    `Expected a start-date or time-of-day price constraint for provider '${providerId}' model '${modelId}', got: ${JSON.stringify(constraint)}`
  )
}

// Strict ISO calendar date: correct shape and a real date (rejects e.g.
// '2025-02-30', which Date would silently roll over to March 2). Years start
// at 1, matching the feed's source `date` type (Python), which cannot
// represent year zero.
function isValidStartDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false
  }
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.getUTCFullYear() >= 1 && parsed.toISOString().startsWith(value)
}

// Reject constraints carrying keys outside the expected shape, so a mixed or
// misspelled constraint fails activation instead of silently losing fields.
function hasExactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  const actual = Object.keys(value)
  return actual.length === keys.length && actual.every((key) => keys.includes(key))
}

// Reuse the engine's parser so activation accepts exactly what price calculation can later evaluate.
function isValidTimeOfDay(value: unknown): value is string {
  if (typeof value !== 'string') {
    return false
  }
  try {
    utcTimeOfDaySeconds(value)
    return true
  } catch {
    return false
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isPromiseLike(value: unknown): value is PromiseLike<unknown> {
  return isRecord(value) && typeof value.then === 'function'
}

function onCalc(cb: () => void) {
  autoUpdateCb = cb
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function updatePrices(factory: (options: StorageFactoryParams) => any): void {
  factory({
    onCalc,
    remoteDataUrl: REMOTE_DATA_JSON_URL,
    setProviderData,
  })
}

export function waitForUpdate() {
  return providerDataPromise
}

export function calcPrice(usage: Usage, modelId: string, options?: PriceOptions): PriceCalculationResult {
  autoUpdateCb?.()
  let lowerModelId = modelId.toLowerCase().trim()
  let providerId = options?.providerId

  // Handle litellm provider_id by extracting actual provider from model name prefix
  if (providerId && providerId.toLowerCase() === 'litellm' && lowerModelId.includes('/')) {
    const slashIndex = lowerModelId.indexOf('/')
    const actualProviderId = lowerModelId.slice(0, slashIndex)
    const actualModelId = lowerModelId.slice(slashIndex + 1)
    // Only use the extracted provider if it exists
    if (actualProviderId && actualModelId && matchProvider(providerData, { providerId: actualProviderId })) {
      providerId = actualProviderId
      lowerModelId = actualModelId
    }
  }

  const provider = options?.provider
    ? validateProvider(options.provider)
    : matchProvider(providerData, { modelId: lowerModelId, providerApiUrl: options?.providerApiUrl, providerId })
  if (!provider) return null
  const model = matchModelWithFallback(provider, lowerModelId, providerData)
  if (!model) return null
  const timestamp = options?.timestamp ?? new Date()
  const modelPrice = getActiveModelPrice(model, timestamp)
  const priceResult = calcPriceInternal(usage, modelPrice)
  return {
    auto_update_timestamp: undefined,
    model,
    model_price: modelPrice,
    provider,
    ...priceResult,
  }
}

export function findProvider(options: ProviderFindOptions): Provider | undefined {
  autoUpdateCb?.()
  return matchProvider(providerData, options)
}
