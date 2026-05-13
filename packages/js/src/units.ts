import type { RawUnitsDict, UnitDef } from './types'

import { unitData } from './dataUnits'

export class UnitRegistry {
  allPriceKeys: Set<string>
  allUsageKeys: Set<string>
  ancestorUsageKeysByUsageKey: Map<string, Set<string>>
  reportedUsageKeys: Set<string>
  units: Map<string, UnitDef>
  unitsByDimensionByFamily: Map<string, Map<string, UnitDef>>
  unitsByFamily: Map<string, Map<string, UnitDef>>
  unitsByPriceKey: Map<string, UnitDef>

  constructor(raw: RawUnitsDict) {
    this.ancestorUsageKeysByUsageKey = new Map()
    this.allPriceKeys = new Set()
    this.allUsageKeys = new Set()
    this.reportedUsageKeys = new Set()
    this.units = new Map()
    this.unitsByDimensionByFamily = new Map()
    this.unitsByFamily = new Map()
    this.unitsByPriceKey = new Map()

    for (const [usageKey, rawUnit] of Object.entries(raw)) {
      const priceKey = rawUnit.price_key ?? usageKey
      const unit: UnitDef = {
        dimensions: { ...rawUnit.dimensions },
        per: rawUnit.per,
        priceKey,
        usageKey,
      }
      const familyValue = unitFamilyValue(unit)

      this.allPriceKeys.add(priceKey)
      this.allUsageKeys.add(usageKey)
      this.units.set(usageKey, unit)
      this.unitsByPriceKey.set(priceKey, unit)
      getOrCreateMap(this.unitsByFamily, familyValue).set(usageKey, unit)
      getOrCreateMap(this.unitsByDimensionByFamily, familyValue).set(dimensionKey(unit.dimensions), unit)
    }

    for (const [usageKey, unit] of this.units) {
      this.ancestorUsageKeysByUsageKey.set(
        usageKey,
        new Set(
          [...this.unitsForFamily(unitFamilyValue(unit)).values()]
            .filter((maybeAncestor) => maybeAncestor !== unit && isDimensionSubset(maybeAncestor, unit))
            .map((maybeAncestor) => maybeAncestor.usageKey)
        )
      )
      if (usageKey !== 'requests') {
        this.reportedUsageKeys.add(usageKey)
      }
    }
  }

  ancestorUsageKeys(usageKey: string): Set<string> {
    const ancestorUsageKeys = this.ancestorUsageKeysByUsageKey.get(usageKey)
    if (!ancestorUsageKeys) {
      throw new Error(`Unknown unit usage key: ${usageKey}`)
    }
    return new Set(ancestorUsageKeys)
  }

  familyValues(): Set<string> {
    return new Set(this.unitsByFamily.keys())
  }

  findJoin(left: UnitDef, right: UnitDef): undefined | UnitDef {
    if (!isCompatible(left, right)) return undefined
    const familyValue = unitFamilyValue(left)
    if (familyValue !== unitFamilyValue(right)) return undefined
    return this.unitsByDimensionByFamily.get(familyValue)?.get(dimensionKey({ ...left.dimensions, ...right.dimensions }))
  }

  unitsForFamily(familyValue: string): Map<string, UnitDef> {
    const units = this.unitsByFamily.get(familyValue)
    if (!units) {
      throw new Error(`Unknown unit family dimension: ${familyValue}`)
    }
    return new Map(units)
  }
}

const generatedRegistry = new UnitRegistry(unitData)
let activeRegistry = generatedRegistry

export function getActiveRegistry(): UnitRegistry {
  return activeRegistry
}

export function getAllPriceKeys(): Set<string> {
  return new Set(activeRegistry.allPriceKeys)
}

export function getAllUsageKeys(): Set<string> {
  return new Set(activeRegistry.allUsageKeys)
}

export function getUnit(usageKey: string): UnitDef {
  const unit = activeRegistry.units.get(usageKey)
  if (unit) return unit
  throw new Error(`Unknown unit usage key: ${usageKey}`)
}

export function getUnitForPriceKey(priceKey: string): UnitDef {
  const unit = activeRegistry.unitsByPriceKey.get(priceKey)
  if (unit) return unit
  throw new Error(`Unknown unit price key: ${priceKey}`)
}

export function getUsageKeyForPriceKey(priceKey: string): string {
  return getUnitForPriceKey(priceKey).usageKey
}

export function setActiveRegistry(registry: null | UnitRegistry): void {
  if (registry === null) {
    activeRegistry = generatedRegistry
  } else {
    activeRegistry = registry
  }
}

export function dimensionKey(dimensions: Record<string, string>): string {
  return Object.entries(dimensions)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${value}`)
    .join('\0')
}

export function isDimensionSubset(maybeAncestor: UnitDef, unit: UnitDef): boolean {
  return Object.entries(maybeAncestor.dimensions).every(([key, value]) => unit.dimensions[key] === value)
}

export function isDescendantOrSelf(ancestor: UnitDef, descendant: UnitDef): boolean {
  return isDimensionSubset(ancestor, descendant)
}

export function isCompatible(left: UnitDef, right: UnitDef): boolean {
  return Object.entries(left.dimensions).every(([key, value]) => right.dimensions[key] === undefined || right.dimensions[key] === value)
}

export function unitFamilyValue(unit: UnitDef): string {
  const familyValue = unit.dimensions.family
  if (familyValue === undefined) {
    throw new Error(`Unit ${unit.usageKey} is missing required family dimension`)
  }
  return familyValue
}

function getOrCreateMap<K, V>(outer: Map<string, Map<K, V>>, key: string): Map<K, V> {
  const existing = outer.get(key)
  if (existing) return existing
  const created = new Map<K, V>()
  outer.set(key, created)
  return created
}
