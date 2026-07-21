import type { Provider, UnitDef } from './types'

import { getActiveRegistry, isCompatible, UnitRegistry } from './units'

export function validatePriceKeys(priceKeys: Iterable<string>, registry: UnitRegistry = getActiveRegistry()): void {
  for (const priceKey of priceKeys) {
    if (!registry.unitsByPriceKey.has(priceKey)) {
      throw new Error(`Unknown price key: ${priceKey}`)
    }
  }
}

export function validateAncestorCoverage(priceKeys: Iterable<string>, registry: UnitRegistry = getActiveRegistry()): void {
  const pricedUnits = getUnitsForPriceKeys(priceKeys, registry)
  validateResolvedAncestorCoverage(pricedUnits, registry)
}

function validateResolvedAncestorCoverage(pricedUnits: readonly UnitDef[], registry: UnitRegistry): void {
  const pricedKeys = new Set(pricedUnits.map((unit) => unit.priceKey))

  for (const unit of pricedUnits) {
    const ancestorUsageKeys = registry.ancestorUsageKeysByUsageKey.get(unit.usageKey)
    if (!ancestorUsageKeys) throw new Error(`Unknown unit usage key: ${unit.usageKey}`)

    for (const ancestorUsageKey of ancestorUsageKeys) {
      const ancestor = registry.units.get(ancestorUsageKey)
      if (ancestor && !pricedKeys.has(ancestor.priceKey)) {
        throw new Error(`Missing ancestor price key ${ancestor.priceKey} for ${unit.priceKey}`)
      }
    }
  }
}

export function validateJoinCoverage(priceKeys: Iterable<string>, registry: UnitRegistry = getActiveRegistry()): void {
  const pricedUnits = getUnitsForPriceKeys(priceKeys, registry)
  validateResolvedJoinCoverage(pricedUnits, registry)
}

function validateResolvedJoinCoverage(pricedUnits: readonly UnitDef[], registry: UnitRegistry): void {
  const pricedKeys = new Set(pricedUnits.map((unit) => unit.priceKey))

  for (let leftIndex = 0; leftIndex < pricedUnits.length; leftIndex++) {
    for (let rightIndex = leftIndex + 1; rightIndex < pricedUnits.length; rightIndex++) {
      const left = pricedUnits[leftIndex]
      const right = pricedUnits[rightIndex]
      if (!left || !right || !isCompatible(left, right)) continue

      const joinUnit = registry.findJoin(left, right)
      if (!joinUnit) {
        throw new Error(`Missing registered join unit for ${left.priceKey} and ${right.priceKey}`)
      }
      if (!pricedKeys.has(joinUnit.priceKey)) {
        throw new Error(`Missing join price key ${joinUnit.priceKey} for ${left.priceKey} and ${right.priceKey}`)
      }
    }
  }
}

export function validateModelPrice(priceKeys: Iterable<string>, registry: UnitRegistry = getActiveRegistry()): void {
  validatePricedUnits(getUnitsForPriceKeys(priceKeys, registry), registry)
}

export function validatePricedUnits(pricedUnits: readonly UnitDef[], registry: UnitRegistry): void {
  validateResolvedAncestorCoverage(pricedUnits, registry)
  validateResolvedJoinCoverage(pricedUnits, registry)
}

export function validateExtractorDestinations(providerData: Provider[], registry: UnitRegistry = getActiveRegistry()): void {
  for (const provider of providerData) {
    for (const extractor of provider.extractors ?? []) {
      for (const [mappingIndex, mapping] of extractor.mappings.entries()) {
        if (!registry.reportedUsageKeys.has(mapping.dest)) {
          throw new Error(
            `Invalid extractor destination for ${provider.id}/${extractor.api_flavor} mapping ${mappingIndex.toString()}: ${mapping.dest}`
          )
        }
      }
    }
  }
}

function getUnitsForPriceKeys(priceKeys: Iterable<string>, registry: UnitRegistry): UnitDef[] {
  return [...new Set(priceKeys)].map((priceKey) => {
    const unit = registry.unitsByPriceKey.get(priceKey)
    if (!unit) throw new Error(`Unknown price key: ${priceKey}`)
    return unit
  })
}
