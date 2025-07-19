import {
  getProvidersAsync,
  getProvidersSync,
  enableAutoUpdate,
  isLocalDataOutdated,
  prefetchAsync,
} from './dataLoader.js'
import { matchProvider, matchModel } from './matcher.js'
import { calcPrice as calcModelPrice, getActiveModelPrice } from './priceCalc.js'
import type { Usage, PriceCalculation } from './types.js'

export type { Usage, PriceCalculation, Provider, ModelInfo } from './types.js'
export { enableAutoUpdate, prefetchAsync }

export interface CalcPriceOptions {
  providerId?: string
  providerApiUrl?: string
  timestamp?: Date
}

// Outdated data warning (1 day threshold)
;(async () => {
  if (await isLocalDataOutdated()) {
    // eslint-disable-next-line no-console
    console.warn(
      '[genai-prices] Your local price data is more than 1 day old. Run `make build` or use --auto-update to get the latest prices.',
    )
  }
})()

// Node.js only: always reads from local prices/data.json
export function calcPriceSync(usage: Usage, modelRef: string, options: CalcPriceOptions = {}): PriceCalculation {
  const providers = getProvidersSync()
  const provider = matchProvider(providers, modelRef, options.providerId, options.providerApiUrl)
  if (!provider) throw new Error('Provider not found')
  const model = matchModel(provider.models, modelRef)
  if (!model) throw new Error('Model not found')
  const timestamp = options.timestamp || new Date()
  const modelPrice = getActiveModelPrice(model, timestamp)
  const price = calcModelPrice(usage, modelPrice)
  return {
    price,
    provider,
    model,
    modelPrice,
    autoUpdateTimestamp: undefined,
  }
}

export async function calcPriceAsync(
  usage: Usage,
  modelRef: string,
  options: CalcPriceOptions = {},
): Promise<PriceCalculation> {
  const providers = await getProvidersAsync()
  const provider = matchProvider(providers, modelRef, options.providerId, options.providerApiUrl)
  if (!provider) throw new Error('Provider not found')
  const model = matchModel(provider.models, modelRef)
  if (!model) throw new Error('Model not found')
  const timestamp = options.timestamp || new Date()
  const modelPrice = getActiveModelPrice(model, timestamp)
  const price = calcModelPrice(usage, modelPrice)
  return {
    price,
    provider,
    model,
    modelPrice,
    autoUpdateTimestamp: undefined,
  }
}
