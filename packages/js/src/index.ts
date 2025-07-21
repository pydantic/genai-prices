// Universal entry point that works in all environments
export { calcPriceSync } from './sync/calcPriceSync.js'
export { calcPriceAsync } from './async/calcPriceAsync.js'
export {
  getProvidersSync,
  getProvidersAsync,
  enableAutoUpdate,
  isLocalDataOutdated,
  prefetchAsync,
  getEnvironmentInfo,
} from './dataLoader.js'
export { matchProvider, matchModel } from './matcher.js'
export type { Usage, PriceCalculation, Provider, ModelInfo } from './types.js'
