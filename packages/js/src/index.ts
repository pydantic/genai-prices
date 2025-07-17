import { getProviders, enableAutoUpdate } from './dataLoader.js';
import { matchProvider, matchModel } from './matcher.js';
import { calcPrice as calcModelPrice, getActiveModelPrice } from './priceCalc.js';
import type { Usage, PriceCalculation } from './types.js';

export type { Usage, PriceCalculation, Provider, ModelInfo } from './types.js';
export { enableAutoUpdate };

export interface CalcPriceOptions {
  providerId?: string;
  providerApiUrl?: string;
  timestamp?: Date;
}

export async function calcPrice(
  usage: Usage,
  modelRef: string,
  options: CalcPriceOptions = {}
): Promise<PriceCalculation> {
  const providers = await getProviders();
  const provider = matchProvider(providers, modelRef, options.providerId, options.providerApiUrl);
  if (!provider) throw new Error('Provider not found');
  const model = matchModel(provider.models, modelRef);
  if (!model) throw new Error('Model not found');
  const timestamp = options.timestamp || new Date();
  const modelPrice = getActiveModelPrice(model, timestamp);
  const price = calcModelPrice(usage, modelPrice);
  return {
    price,
    provider,
    model,
    modelPrice,
    autoUpdateTimestamp: undefined, // Could be set if tracking dataLoader cache time
  };
}
