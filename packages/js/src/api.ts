import type { RuntimeData } from './runtimeState'
import type {
  PriceCalculationResult,
  PriceOptions,
  Provider,
  ProviderDataPayload,
  ProviderDataValue,
  ProviderFindOptions,
  StorageFactoryParams,
  Usage,
} from './types'

import { decodeV2Payload } from './decodeProviderData'
import { calcPrice as calcPriceInternal, getActiveModelPrice, matchModelWithFallback, matchProvider } from './engine'
import { projectProviderData, validateProviderPriceCoverage } from './providerData'
import { activateRuntimeData, getRuntimeData } from './runtimeState'
import { UnitRegistry } from './unitRegistry'

export const REMOTE_DATA_JSON_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/data_v2.json'

let providerDataPromise: Promise<Provider[]> = Promise.resolve(getRuntimeData().providers)
let updateGeneration = 0
let autoUpdateCb: (() => void) | null = null

function setProviderData(data: ProviderDataPayload) {
  const generation = ++updateGeneration
  if (data === null) {
    providerDataPromise = Promise.resolve(getRuntimeData().providers)
    return
  }
  if (typeof data === 'object' && 'then' in data) {
    const updatePromise = data
      .then((data) => {
        if (data === null || generation !== updateGeneration) return getRuntimeData().providers
        return prepareAndActivateProviderData(data, generation)
      })
      .catch((error: unknown) => {
        if (generation === updateGeneration && providerDataPromise === updatePromise)
          providerDataPromise = Promise.resolve(getRuntimeData().providers)
        throw error
      })
    providerDataPromise = updatePromise
  } else {
    try {
      providerDataPromise = Promise.resolve(prepareAndActivateProviderData(data, generation))
    } catch (error) {
      providerDataPromise = Promise.resolve(getRuntimeData().providers)
      throw error
    }
  }
}

function prepareAndActivateProviderData(data: Exclude<ProviderDataValue, null>, generation: number): Provider[] {
  let candidate: RuntimeData
  if (Array.isArray(data)) {
    const active = getRuntimeData()
    candidate = {
      providers: projectProviderData(data, active.registry),
      registry: active.registry,
    }
  } else {
    const decoded = decodeV2Payload(data)
    const registry = UnitRegistry.fromUntrusted(decoded.units)
    candidate = {
      providers: projectProviderData(decoded.providers, registry),
      registry,
    }
  }

  validateProviderPriceCoverage(candidate.providers, candidate.registry)
  if (generation !== updateGeneration) return getRuntimeData().providers
  activateRuntimeData(candidate)
  return candidate.providers
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
