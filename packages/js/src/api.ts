import type { PriceCalculationResult, PriceOptions, Provider, StorageFactoryParams, Usage } from './types'

import { data as embeddedData, dataTimestamp as embeddedDataTimestamp } from './data'
import { calcPriceInternal } from './engine'

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
export function enableAutoUpdate(factory: (options: StorageFactoryParams) => any): void {
  factory({
    embeddedDataTimestamp,
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
  return calcPriceInternal(usage, modelId, providerData, options)
}
