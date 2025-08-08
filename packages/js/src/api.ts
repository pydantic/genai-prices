import type { AsyncProviderStorage, PriceCalculationResult, PriceOptions, StorageFactoryParams, SyncProviderStorage, Usage } from './types'

import { data as embeddedData, dataTimestamp as embeddedDataTimestamp } from './data'
import { calcPrice } from './engine'

export const REMOTE_DATA_JSON_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/data.json'

// module level "singletons"
let theSyncDataProviderStorage: SyncProviderStorage = () => embeddedData
let theAsyncDataProviderStorage: AsyncProviderStorage = async () => Promise.resolve(embeddedData)

function createProviderStorage<T extends AsyncProviderStorage | SyncProviderStorage>(factory: (options: StorageFactoryParams) => T): T {
  return factory({
    embeddedData,
    embeddedDataTimestamp,
    remoteDataUrl: REMOTE_DATA_JSON_URL,
  })
}

export function enableAutoUpdateForSyncCalc(factory: (options: StorageFactoryParams) => SyncProviderStorage): void {
  theSyncDataProviderStorage = createProviderStorage<SyncProviderStorage>(factory)
}

export function enableAutoUpdateForAsyncCalc(factory: (options: StorageFactoryParams) => AsyncProviderStorage): void {
  theAsyncDataProviderStorage = createProviderStorage<AsyncProviderStorage>(factory)
}

export function calcPriceSync(usage: Usage, modelId: string, options?: PriceOptions): PriceCalculationResult {
  return calcPrice(usage, modelId, theSyncDataProviderStorage(), options)
}

export async function calcPriceAsync(usage: Usage, modelId: string, options?: PriceOptions): Promise<PriceCalculationResult> {
  return calcPrice(usage, modelId, await theAsyncDataProviderStorage(), options)
}
