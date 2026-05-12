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

const reservedPublicKeys = new Set(['__proto__', 'constructor', 'prototype'])
const reservedKeywords = new Set([
  'await',
  'break',
  'case',
  'catch',
  'class',
  'const',
  'continue',
  'debugger',
  'default',
  'delete',
  'do',
  'else',
  'enum',
  'export',
  'extends',
  'false',
  'finally',
  'for',
  'function',
  'if',
  'import',
  'in',
  'instanceof',
  'new',
  'null',
  'return',
  'super',
  'switch',
  'this',
  'throw',
  'true',
  'try',
  'typeof',
  'var',
  'void',
  'while',
  'with',
  'yield',
])

export function validateUnitFamilies(raw: RawFamiliesDict): UnitRegistry {
  const usageKeys = new Set<string>()
  const priceKeys = new Set<string>()

  for (const [familyId, rawFamily] of Object.entries(raw)) {
    const dimensionSets = new Map<string, string>()

    for (const [usageKey, rawUnit] of Object.entries(rawFamily.units)) {
      validatePublicKey('usage', usageKey)
      if (usageKeys.has(usageKey)) {
        throw new Error(`Duplicate unit usage key: ${usageKey}`)
      }
      usageKeys.add(usageKey)

      const priceKey = rawUnit.price_key ?? usageKey
      validatePublicKey('price', priceKey)
      if (priceKeys.has(priceKey)) {
        throw new Error(`Duplicate unit price key: ${priceKey}`)
      }
      priceKeys.add(priceKey)

      const dimensions = dimensionKey(rawUnit.dimensions)
      const existingUnit = dimensionSets.get(dimensions)
      if (existingUnit) {
        throw new Error(`Duplicate dimensions in unit family ${familyId}: ${existingUnit} and ${usageKey}`)
      }
      dimensionSets.set(dimensions, usageKey)
    }
  }

  const registry = new UnitRegistry(raw)
  validateIntervalClosure(registry.families)
  return registry
}

function validatePublicKey(kind: 'price' | 'usage', key: string): void {
  if (!/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(key)) {
    throw new Error(`Invalid unit ${kind} key: ${key} is not a public identifier`)
  }
  if (key.startsWith('_')) {
    throw new Error(`Invalid unit ${kind} key: ${key} must not start with "_"`)
  }
  if (reservedKeywords.has(key)) {
    throw new Error(`Invalid unit ${kind} key: ${key} is a reserved keyword`)
  }
  if (reservedPublicKeys.has(key)) {
    throw new Error(`Invalid unit ${kind} key: ${key} is reserved`)
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

export function setUnitFamilies(registry: null | UnitRegistry): void {
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

function combinations<T>(items: T[], size: number): T[][] {
  if (size === 0) return [[]]
  if (items.length < size) return []

  const [first, ...rest] = items
  if (first === undefined) return []

  return [...combinations(rest, size - 1).map((combo) => [first, ...combo]), ...combinations(rest, size)]
}

function validateIntervalClosure(families: Record<string, UnitFamily>): void {
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
