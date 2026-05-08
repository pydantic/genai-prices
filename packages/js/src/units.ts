import type { ParsedFamilies, RawFamiliesDict, UnitDef, UnitFamily } from './types'

import { unitFamiliesData } from './dataUnits'

export class UnitRegistry {
  allPriceKeys: Set<string>
  allUsageKeys: Set<string>
  ancestorUsageKeysByUsageKey: Map<string, Set<string>>
  families: ParsedFamilies
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
        if (this.units.has(usageKey)) {
          throw new Error(`Duplicate unit usage key: ${usageKey}`)
        }

        const priceKey = rawUnit.price_key ?? usageKey
        if (this.unitsByPriceKey.has(priceKey)) {
          throw new Error(`Duplicate unit price key: ${priceKey}`)
        }

        const unit: UnitDef = {
          dimensions: { ...rawUnit.dimensions },
          family,
          familyId,
          priceKey,
          usageKey,
        }
        const dimensionSet = dimensionKey(unit.dimensions)
        const existingUnit = family.unitsByDimension.get(dimensionSet)
        if (existingUnit) {
          throw new Error(`Duplicate dimensions in unit family ${familyId}: ${existingUnit.usageKey} and ${usageKey}`)
        }

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

    validateIntervalClosure(this.families)
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

// Transitional compatibility wrapper for modules not yet migrated to UnitRegistry.
export function parseFamilies(raw: RawFamiliesDict): ParsedFamilies {
  return new UnitRegistry(raw).families
}

// Transitional compatibility wrapper for modules not yet migrated to UnitRegistry.
export function getActiveFamilies(): ParsedFamilies {
  return activeRegistry.families
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

export function getReportedUsageKeys(): Set<string> {
  return new Set(activeRegistry.reportedUsageKeys)
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

export function setUnitFamilies(registry: null | ParsedFamilies | UnitRegistry): void {
  if (registry === null) {
    activeRegistry = generatedRegistry
  } else if (registry instanceof UnitRegistry) {
    activeRegistry = registry
  } else {
    activeRegistry = registryForParsedFamilies(registry)
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

function combinations<T>(items: T[], size: number): T[][] {
  if (size === 0) return [[]]
  if (items.length < size) return []

  const [first, ...rest] = items
  if (first === undefined) return []

  return [...combinations(rest, size - 1).map((combo) => [first, ...combo]), ...combinations(rest, size)]
}

function validateIntervalClosure(families: ParsedFamilies): void {
  for (const family of Object.values(families)) {
    for (const ancestor of Object.values(family.units)) {
      for (const descendant of Object.values(family.units)) {
        if (ancestor === descendant || !isDimensionSubset(ancestor, descendant)) continue

        const addedDimensions = Object.entries(descendant.dimensions)
          .filter(([key, value]) => ancestor.dimensions[key] !== value)
          .sort(([left], [right]) => left.localeCompare(right))

        for (let size = 1; size < addedDimensions.length; size++) {
          for (const addedSubset of combinations(addedDimensions, size)) {
            const requiredDimensions = Object.fromEntries([...Object.entries(ancestor.dimensions), ...addedSubset])
            if (family.unitsByDimension.has(dimensionKey(requiredDimensions))) continue

            const missingDimensions = Object.entries(requiredDimensions)
              .sort(([left], [right]) => left.localeCompare(right))
              .map(([key, value]) => `${key}=${value}`)
              .join(', ')
            throw new Error(
              `Missing intermediate unit dimensions in family ${family.id} between ${ancestor.usageKey} and ${descendant.usageKey}: ${missingDimensions}`
            )
          }
        }
      }
    }
  }
}

function registryForParsedFamilies(families: ParsedFamilies): UnitRegistry {
  return Object.assign(Object.create(UnitRegistry.prototype) as UnitRegistry, {
    allPriceKeys: new Set(Object.values(families).flatMap((family) => Object.values(family.units).map((unit) => unit.priceKey))),
    allUsageKeys: new Set(Object.values(families).flatMap((family) => Object.keys(family.units))),
    ancestorUsageKeysByUsageKey: new Map(
      Object.values(families)
        .flatMap((family) => Object.values(family.units))
        .map((unit) => [
          unit.usageKey,
          new Set(
            Object.values(unit.family.units)
              .filter((maybeAncestor) => maybeAncestor !== unit && isDimensionSubset(maybeAncestor, unit))
              .map((maybeAncestor) => maybeAncestor.usageKey)
          ),
        ])
    ),
    families,
    reportedUsageKeys: new Set(
      Object.values(families).flatMap((family) => Object.keys(family.units).filter((usageKey) => usageKey !== 'requests'))
    ),
    units: new Map(Object.values(families).flatMap((family) => Object.values(family.units).map((unit) => [unit.usageKey, unit]))),
    unitsByPriceKey: new Map(Object.values(families).flatMap((family) => Object.values(family.units).map((unit) => [unit.priceKey, unit]))),
  })
}
