import type { ParsedFamilies, UnitDef } from './types'

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
