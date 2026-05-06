import type { ParsedFamilies, RawFamiliesDict, UnitDef, UnitFamily } from './types'

import { unitFamiliesData } from './dataUnits'

const generatedFamilies = parseFamilies(unitFamiliesData)
let activeFamilies = generatedFamilies

export function parseFamilies(raw: RawFamiliesDict): ParsedFamilies {
  const parsed: ParsedFamilies = {}
  const priceKeys = new Set<string>()
  const usageKeys = new Set<string>()

  for (const [familyId, rawFamily] of Object.entries(raw)) {
    const family: UnitFamily = {
      description: rawFamily.description,
      id: familyId,
      per: rawFamily.per,
      units: {},
      unitsByDimension: new Map(),
    }
    parsed[familyId] = family

    for (const [usageKey, rawUnit] of Object.entries(rawFamily.units)) {
      if (usageKeys.has(usageKey)) {
        throw new Error(`Duplicate unit usage key: ${usageKey}`)
      }
      usageKeys.add(usageKey)

      const priceKey = rawUnit.price_key ?? usageKey
      if (priceKeys.has(priceKey)) {
        throw new Error(`Duplicate unit price key: ${priceKey}`)
      }
      priceKeys.add(priceKey)

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
    }
  }

  validateIntervalClosure(parsed)
  return parsed
}

export function getActiveFamilies(): ParsedFamilies {
  return activeFamilies
}

export function getFamily(familyId: string): UnitFamily {
  const family = activeFamilies[familyId]
  if (!family) {
    throw new Error(`Unknown unit family: ${familyId}`)
  }
  return family
}

export function getUnit(usageKey: string): UnitDef {
  for (const family of Object.values(activeFamilies)) {
    const unit = family.units[usageKey]
    if (unit) return unit
  }
  throw new Error(`Unknown unit usage key: ${usageKey}`)
}

export function getUnitForPriceKey(priceKey: string): UnitDef {
  for (const family of Object.values(activeFamilies)) {
    for (const unit of Object.values(family.units)) {
      if (unit.priceKey === priceKey) return unit
    }
  }
  throw new Error(`Unknown unit price key: ${priceKey}`)
}

export function getUsageKeyForPriceKey(priceKey: string): string {
  return getUnitForPriceKey(priceKey).usageKey
}

export function setUnitFamilies(families: null | ParsedFamilies): void {
  activeFamilies = families ?? generatedFamilies
}

function dimensionKey(dimensions: Record<string, string>): string {
  return Object.entries(dimensions)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${value}`)
    .join('\0')
}

function isDimensionSubset(maybeAncestor: UnitDef, unit: UnitDef): boolean {
  return Object.entries(maybeAncestor.dimensions).every(([key, value]) => unit.dimensions[key] === value)
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
