import type {
  ConditionalPrice,
  PriceCalculationResult,
  PriceOptions,
  Provider,
  ProviderDataPayload,
  ProviderFindOptions,
  StorageFactoryParams,
  Usage,
} from './types'

import { data as embeddedData } from './data'
import { calcPrice as calcPriceInternal, getActiveModelPrice, matchModelWithFallback, matchProvider } from './engine'
import { warnUnsupportedExtractorDestinations } from './validation'

export const REMOTE_DATA_JSON_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/new_data/v2/data.json'

let providerData: Provider[] = embeddedData
let providerDataPromise: Promise<null | Provider[]> = Promise.resolve(embeddedData)
let autoUpdateCb: (() => void) | null = null

function setProviderData(data: ProviderDataPayload) {
  // null means the update failed; keep existing data
  if (data === null) {
    return
  }
  if (typeof data === 'object' && 'then' in data) {
    const updatePromise = data
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
    updatePromise.catch(() => undefined)
    providerDataPromise = updatePromise
  } else {
    providerDataPromise = Promise.resolve(activateProviderData(data))
  }
}

function activateProviderData(data: Provider[]): Provider[] {
  if (!Array.isArray(data)) {
    throw new Error('Expected null or Provider[]')
  }

  const normalizedData = normalizeProviderData(data)
  warnUnsupportedExtractorDestinations(normalizedData)
  providerData = normalizedData
  return normalizedData
}

function normalizeProviderData(data: Provider[]): Provider[] {
  return data.map((provider) => ({
    ...provider,
    models: provider.models.map((model) => ({
      ...model,
      prices: Array.isArray(model.prices) ? model.prices.map(normalizeConditionalPrice) : model.prices,
    })),
  }))
}

function normalizeConditionalPrice(conditionalPrice: ConditionalPrice): ConditionalPrice {
  const constraint: unknown = conditionalPrice.constraint
  if (constraint === undefined) {
    return conditionalPrice
  }
  if (isRecord(constraint) && typeof constraint.start_date === 'string') {
    return {
      ...conditionalPrice,
      constraint: { start_date: constraint.start_date, type: 'start_date' },
    }
  }
  if (isRecord(constraint) && typeof constraint.start_time === 'string' && typeof constraint.end_time === 'string') {
    return {
      ...conditionalPrice,
      constraint: {
        end_time: constraint.end_time,
        start_time: constraint.start_time,
        type: 'time_of_date',
      },
    }
  }
  throw new Error('Expected a start-date or time-of-day price constraint')
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
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

  const provider =
    options?.provider ?? matchProvider(providerData, { modelId: lowerModelId, providerApiUrl: options?.providerApiUrl, providerId })
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
