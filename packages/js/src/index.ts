import {
  getProvidersSync,
  getProvidersAsync,
  enableAutoUpdate,
  isLocalDataOutdated,
} from './dataLoader.js';
import { matchProvider, matchModel } from './matcher.js';
import { calcPrice as calcModelPrice, getActiveModelPrice } from './priceCalc.js';
import type { Usage, PriceCalculation, Provider, ModelInfo } from './types.js';

export type { Usage, PriceCalculation, Provider, ModelInfo } from './types.js';
export { enableAutoUpdate };

export interface CalcPriceOptions {
  providerId?: string;
  providerApiUrl?: string;
  timestamp?: Date;
}

// Outdated data warning (1 day threshold)
if (isLocalDataOutdated()) {
  // eslint-disable-next-line no-console
  console.warn(
    '[genai-prices] Your local price data is more than 1 day old. Run `make build` or use --auto-update to get the latest prices.'
  );
}

export function calcPriceSync(
  usage: Usage,
  modelRef: string,
  options: CalcPriceOptions = {}
): PriceCalculation {
  const providers = getProvidersSync();
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
    autoUpdateTimestamp: undefined,
  };
}

let asyncCache: { providers: Provider[]; timestamp: number } | null = null;
let asyncInitPromise: Promise<Provider[]> | null = null;

export async function calcPriceAsync(
  usage: Usage,
  modelRef: string,
  options: CalcPriceOptions = {}
): Promise<PriceCalculation> {
  if (asyncCache) {
    // Always async, even if cached
    return Promise.resolve(calcPriceSync(usage, modelRef, options));
  }
  if (!asyncInitPromise) {
    asyncInitPromise = getProvidersAsync();
  }
  const providers = await asyncInitPromise;
  asyncCache = { providers, timestamp: Date.now() };
  // Now use the cached providers for calculation
  return calcPriceSync(usage, modelRef, options);
}
