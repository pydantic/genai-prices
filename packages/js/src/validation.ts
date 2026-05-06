import type { ParsedFamilies, Provider, UnitDef } from './types'

import { getActiveFamilies } from './units'

export function validatePriceKeys(priceKeys: Iterable<string>, families: ParsedFamilies = getActiveFamilies()): void {
  const registeredPriceKeys = new Set(Object.values(families).flatMap((family) => Object.values(family.units).map((unit) => unit.priceKey)))

  for (const priceKey of priceKeys) {
    if (!registeredPriceKeys.has(priceKey)) {
      throw new Error(`Unknown price key: ${priceKey}`)
    }
  }
}

export function validateAncestorCoverage(priceKeys: Iterable<string>, families: ParsedFamilies = getActiveFamilies()): void {
  validatePriceKeys(priceKeys, families)
  const pricedKeys = new Set(priceKeys)
  const pricedUnits = getUnitsForPriceKeys(pricedKeys, families)

  for (const unit of pricedUnits) {
    for (const maybeAncestor of Object.values(unit.family.units)) {
      if (maybeAncestor === unit || !isDimensionSubset(maybeAncestor, unit)) continue
      if (!pricedKeys.has(maybeAncestor.priceKey)) {
        throw new Error(`Missing ancestor price key ${maybeAncestor.priceKey} for ${unit.priceKey}`)
      }
    }
  }
}

export function validateJoinCoverage(priceKeys: Iterable<string>, families: ParsedFamilies = getActiveFamilies()): void {
  validatePriceKeys(priceKeys, families)
  const pricedKeys = new Set(priceKeys)
  const pricedUnits = getUnitsForPriceKeys(pricedKeys, families)

  for (let leftIndex = 0; leftIndex < pricedUnits.length; leftIndex++) {
    for (let rightIndex = leftIndex + 1; rightIndex < pricedUnits.length; rightIndex++) {
      const left = pricedUnits[leftIndex]
      const right = pricedUnits[rightIndex]
      if (!left || !right || !isCompatible(left, right)) continue

      const joinDimensions = { ...left.dimensions, ...right.dimensions }
      const joinUnit = left.family.unitsByDimension.get(dimensionKey(joinDimensions))
      if (!joinUnit) {
        throw new Error(`Missing registered join unit for ${left.priceKey} and ${right.priceKey}`)
      }
      if (!pricedKeys.has(joinUnit.priceKey)) {
        throw new Error(`Missing join price key ${joinUnit.priceKey} for ${left.priceKey} and ${right.priceKey}`)
      }
    }
  }
}

export function validateModelPrice(priceKeys: Iterable<string>, families: ParsedFamilies = getActiveFamilies()): void {
  const effectivePriceKeys = [...priceKeys]
  validatePriceKeys(effectivePriceKeys, families)
  validateAncestorCoverage(effectivePriceKeys, families)
  validateJoinCoverage(effectivePriceKeys, families)
}

export function validateExtractorDestinations(providerData: Provider[], families: ParsedFamilies = getActiveFamilies()): void {
  const reportedUsageKeys = reportedUsageKeysForFamilies(families)

  for (const provider of providerData) {
    for (const extractor of provider.extractors ?? []) {
      for (const [mappingIndex, mapping] of extractor.mappings.entries()) {
        if (!reportedUsageKeys.has(mapping.dest)) {
          throw new Error(
            `Invalid extractor destination for ${provider.id}/${extractor.api_flavor} mapping ${mappingIndex.toString()}: ${mapping.dest}`
          )
        }
      }
    }
  }
}

function dimensionKey(dimensions: Record<string, string>): string {
  return Object.entries(dimensions)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${value}`)
    .join('\0')
}

function getUnitsForPriceKeys(priceKeys: Set<string>, families: ParsedFamilies): UnitDef[] {
  const unitsByPriceKey = new Map<string, UnitDef>()
  for (const family of Object.values(families)) {
    for (const unit of Object.values(family.units)) {
      unitsByPriceKey.set(unit.priceKey, unit)
    }
  }

  return [...priceKeys].map((priceKey) => {
    const unit = unitsByPriceKey.get(priceKey)
    if (!unit) throw new Error(`Unknown price key: ${priceKey}`)
    return unit
  })
}

function isDimensionSubset(maybeAncestor: UnitDef, unit: UnitDef): boolean {
  return Object.entries(maybeAncestor.dimensions).every(([key, value]) => unit.dimensions[key] === value)
}

function isCompatible(left: UnitDef, right: UnitDef): boolean {
  if (left.family !== right.family) return false
  return Object.entries(left.dimensions).every(([key, value]) => right.dimensions[key] === undefined || right.dimensions[key] === value)
}

function reportedUsageKeysForFamilies(families: ParsedFamilies): Set<string> {
  return new Set(Object.values(families).flatMap((family) => Object.keys(family.units).filter((usageKey) => usageKey !== 'requests')))
}
