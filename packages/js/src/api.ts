import type {
  PriceCalculationResult,
  PriceOptions,
  Provider,
  ProviderDataPayload,
  ProviderFindOptions,
  StorageFactoryParams,
  Usage,
} from './types'

import { calcPrice as calcPriceInternal, getActiveModelPrice, matchModelWithFallback, matchProvider } from './engine'
import { activateRuntimeData, getRuntimeData } from './runtimeState'
import { warnUnsupportedExtractorDestinations } from './validation'

export const REMOTE_DATA_JSON_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/data_v2.json'

let providerDataPromise: Promise<null | Provider[]> = Promise.resolve(getRuntimeData().providers)
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
          return getRuntimeData().providers
        }
        return activateProviderData(data)
      })
      .catch((error: unknown) => {
        if (providerDataPromise === updatePromise) {
          providerDataPromise = Promise.resolve(getRuntimeData().providers)
        }
        throw error
      })
    providerDataPromise = updatePromise
  } else {
    providerDataPromise = Promise.resolve(activateProviderData(data))
  }
}

function activateProviderData(data: Provider[]): Provider[] {
  if (!Array.isArray(data)) {
    throw new Error('Expected null or Provider[]')
  }

  const active = getRuntimeData()
  warnUnsupportedExtractorDestinations(data, active.registry)
  activateRuntimeData({ providers: data, registry: active.registry })
  return data
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
  const state = getRuntimeData()
  let lowerModelId = modelId.toLowerCase().trim()
  let providerId = options?.providerId

  // Handle litellm provider_id by extracting actual provider from model name prefix
  if (providerId && providerId.toLowerCase() === 'litellm' && lowerModelId.includes('/')) {
    const slashIndex = lowerModelId.indexOf('/')
    const actualProviderId = lowerModelId.slice(0, slashIndex)
    const actualModelId = lowerModelId.slice(slashIndex + 1)
    // Only use the extracted provider if it exists
    if (actualProviderId && actualModelId && matchProvider(state.providers, { providerId: actualProviderId })) {
      providerId = actualProviderId
      lowerModelId = actualModelId
    }
  }

  const provider =
    options?.provider ?? matchProvider(state.providers, { modelId: lowerModelId, providerApiUrl: options?.providerApiUrl, providerId })
  if (!provider) return null
  const model = matchModelWithFallback(provider, lowerModelId, state.providers)
  if (!model) return null
  const timestamp = options?.timestamp ?? new Date()
  const modelPrice = getActiveModelPrice(model, timestamp)
  const priceResult = calcPriceInternal(usage, modelPrice, state.registry)
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
  return matchProvider(getRuntimeData().providers, options)
}
