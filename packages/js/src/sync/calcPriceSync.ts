import { getProvidersSync } from '../dataLoader.js'
import { matchProvider, matchModel } from '../matcher.js'
import { calcPrice as calcModelPrice, getActiveModelPrice } from '../priceCalc.js'
import type { Usage, PriceCalculation, PriceCalculationResult } from '../types.js'

export type { Usage, PriceCalculation, PriceCalculationResult } from '../types.js'

export interface CalcPriceOptions {
  providerId?: string
  providerApiUrl?: string
  timestamp?: Date
}

export function calcPriceSync(usage: Usage, modelRef: string, options: CalcPriceOptions = {}): PriceCalculationResult {
  const providers = getProvidersSync()
  const provider = matchProvider(providers, modelRef, options.providerId, options.providerApiUrl)
  if (!provider) return null
  const model = matchModel(provider.models, modelRef)
  if (!model) return null
  const timestamp = options.timestamp || new Date()
  const model_price = getActiveModelPrice(model, timestamp)
  const price = calcModelPrice(usage, model_price)
  return {
    price,
    provider,
    model,
    model_price,
    auto_update_timestamp: undefined,
  }
}
