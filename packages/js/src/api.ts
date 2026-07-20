import type {
  PriceCalculationResult,
  PriceOptions,
  Provider,
  ProviderDataPayload,
  ProviderDataValue,
  ProviderFindOptions,
  StorageFactoryParams,
  Usage,
  WrappedProviderData,
} from './types'

import { data as embeddedData } from './data'
import { calcPrice as calcPriceInternal, getActiveModelPrice, matchModelWithFallback, matchProvider } from './engine'
import { getActiveRegistry, setActiveRegistry, UnitRegistry } from './units'
import { validateExtractorDestinations } from './validation'

export const REMOTE_DATA_JSON_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/data_v2.json'

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
        if (data === null) {
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
    providerDataPromise = updatePromise
  } else {
    providerDataPromise = Promise.resolve(activateProviderData(data))
  }
}

function activateProviderData(data: Exclude<ProviderDataValue, null>): Provider[] {
  if (Array.isArray(data)) {
    validateExtractorDestinations(data)
    providerData = data
    return data
  }

  if (typeof data === 'object' && isWrappedProviderData(data)) {
    // Published unit data is trusted to evolve compatibly. We only roll back if
    // this payload's providers fail activation; no registry-history diff is enforced.
    const candidateRegistry = new UnitRegistry(data.units)
    const previousRegistry = getActiveRegistry()
    setActiveRegistry(candidateRegistry)
    try {
      validateExtractorDestinations(data.providers)
      providerData = data.providers
      return data.providers
    } catch (error) {
      setActiveRegistry(previousRegistry)
      throw error
    }
  }

  throw new Error('Expected null, Provider[], or { units, providers }')
}

function isWrappedProviderData(data: object): data is WrappedProviderData {
  return 'providers' in data && 'units' in data
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
