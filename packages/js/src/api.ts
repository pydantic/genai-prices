import type { PriceCalculationResult, PriceOptions, Provider, ProviderFindOptions, StorageFactoryParams, Usage } from './types'

import { data as embeddedData } from './data'
import { calcPrice as calcPriceInternal, getActiveModelPrice, matchModel, matchProvider } from './engine'

export const REMOTE_DATA_JSON_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/data.json'

let providerData: Provider[] = embeddedData
let providerDataPromise: Promise<Provider[]> = Promise.resolve(embeddedData)
let autoUpdateCb: (() => void) | null = null

function setProviderData(data: Promise<Provider[]> | Provider[]) {
  if ('then' in data) {
    providerDataPromise = data
    // eslint-disable-next-line @typescript-eslint/no-floating-promises
    data.then((data) => {
      providerData = data
    })
  } else {
    providerDataPromise = Promise.resolve(data)
    providerData = data
  }
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
  const provider =
    options?.provider ?? matchProvider(providerData, { modelId, providerApiUrl: options?.providerApiUrl, providerId: options?.providerId })
  if (!provider) return null
  const model = matchModel(provider.models, modelId)
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
