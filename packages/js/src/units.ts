import type { RawFamiliesDict, UnitDef, UnitFamily } from './types'

import { unitFamiliesData } from './dataUnits'

export class UnitRegistry {
  allPriceKeys: Set<string>
  allUsageKeys: Set<string>
  ancestorUsageKeysByUsageKey: Map<string, Set<string>>
  families: Record<string, UnitFamily>
  reportedUsageKeys: Set<string>
  units: Map<string, UnitDef>
  unitsByPriceKey: Map<string, UnitDef>

  constructor(raw: RawFamiliesDict) {
    this.ancestorUsageKeysByUsageKey = new Map()
    this.allPriceKeys = new Set()
    this.allUsageKeys = new Set()
    this.families = {}
    this.reportedUsageKeys = new Set()
    this.units = new Map()
    this.unitsByPriceKey = new Map()

    for (const [familyId, rawFamily] of Object.entries(raw)) {
      const family: UnitFamily = {
        description: rawFamily.description,
        id: familyId,
        per: rawFamily.per,
        units: {},
        unitsByDimension: new Map(),
      }
      this.families[familyId] = family

      for (const [usageKey, rawUnit] of Object.entries(rawFamily.units)) {
        const priceKey = rawUnit.price_key ?? usageKey
        const unit: UnitDef = {
          dimensions: { ...rawUnit.dimensions },
          family,
          familyId,
          priceKey,
          usageKey,
        }
        const dimensionSet = dimensionKey(unit.dimensions)

        family.units[usageKey] = unit
        family.unitsByDimension.set(dimensionSet, unit)
        this.allPriceKeys.add(priceKey)
        this.allUsageKeys.add(usageKey)
        this.units.set(usageKey, unit)
        this.unitsByPriceKey.set(priceKey, unit)
      }
    }

    for (const [usageKey, unit] of this.units) {
      this.ancestorUsageKeysByUsageKey.set(
        usageKey,
        new Set(
          Object.values(unit.family.units)
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
}

const generatedRegistry = new UnitRegistry(unitFamiliesData)
let activeRegistry = generatedRegistry

export function getActiveRegistry(): UnitRegistry {
  return activeRegistry
}

export function getFamily(familyId: string): UnitFamily {
  const family = activeRegistry.families[familyId]
  if (!family) {
    throw new Error(`Unknown unit family: ${familyId}`)
  }
  return family
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
  return ancestor.family === descendant.family && isDimensionSubset(ancestor, descendant)
}

export function isCompatible(left: UnitDef, right: UnitDef): boolean {
  if (left.family !== right.family) return false
  return Object.entries(left.dimensions).every(([key, value]) => right.dimensions[key] === undefined || right.dimensions[key] === value)
}
