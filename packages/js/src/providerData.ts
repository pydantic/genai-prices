import type { ModelPrice, Provider } from './types'
import type { UnitRegistry } from './unitRegistry'

import { validatePricedUnits } from './validation'

export function projectProviderData(providers: Provider[], registry: UnitRegistry): Provider[] {
  const unsupportedPriceKeys = new Set<string>()
  const unsupportedDestinations = new Set<string>()

  const projected = providers.map((provider) => ({
    ...provider,
    ...(provider.extractors === undefined
      ? {}
      : {
          extractors: provider.extractors.map((extractor) => ({
            ...extractor,
            mappings: extractor.mappings.filter((mapping) => {
              if (registry.isReportedUsageKey(mapping.dest)) return true
              unsupportedDestinations.add(mapping.dest)
              return false
            }),
          })),
        }),
    models: provider.models.map((model) => ({
      ...model,
      prices: Array.isArray(model.prices)
        ? model.prices.map((conditional) => ({
            ...conditional,
            prices: projectModelPrice(conditional.prices, registry, unsupportedPriceKeys),
          }))
        : projectModelPrice(model.prices, registry, unsupportedPriceKeys),
    })),
  }))

  if (unsupportedPriceKeys.size) {
    console.warn(`Unsupported price key for standard pricing: ${[...unsupportedPriceKeys].sort().join(', ')}`)
  }
  if (unsupportedDestinations.size) {
    console.warn(`Unsupported extractor destination for standard extraction: ${[...unsupportedDestinations].sort().join(', ')}`)
  }
  return projected
}

export function validateProviderPriceCoverage(providers: Provider[], registry: UnitRegistry): void {
  for (const provider of providers) {
    for (const model of provider.models) {
      const modelPrices = Array.isArray(model.prices) ? model.prices.map(({ prices }) => prices) : [model.prices]
      for (const modelPrice of modelPrices) {
        const units = Object.keys(modelPrice)
          .map((priceKey) => registry.getUnitForPriceKey(priceKey))
          .filter((unit) => unit !== undefined)
        try {
          validatePricedUnits(units, registry)
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error)
          throw new Error(`Invalid price coverage for ${provider.id}/${model.id}: ${message}`)
        }
      }
    }
  }
}

function projectModelPrice(modelPrice: ModelPrice, registry: UnitRegistry, unsupportedPriceKeys: Set<string>): ModelPrice {
  const projected: ModelPrice = {}
  for (const [priceKey, price] of Object.entries(modelPrice)) {
    if (registry.getUnitForPriceKey(priceKey)) {
      projected[priceKey] = price
    } else {
      unsupportedPriceKeys.add(priceKey)
    }
  }
  return projected
}
