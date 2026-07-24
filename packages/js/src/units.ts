import type { RawUnitsDict, UnitDef } from './types'

import { unitData } from './dataUnits'

export class UnitRegistry {
  readonly #allPriceKeys: Set<string>
  readonly #allUsageKeys: Set<string>
  readonly #ancestorUsageKeysByUsageKey: Map<string, Set<string>>
  readonly #reportedUsageKeys: Set<string>
  readonly #units: Map<string, UnitDef>
  readonly #unitsByDimension: Map<string, UnitDef>
  readonly #unitsByPriceKey: Map<string, UnitDef>

  constructor(raw: RawUnitsDict) {
    this.#ancestorUsageKeysByUsageKey = new Map()
    this.#allPriceKeys = new Set()
    this.#allUsageKeys = new Set()
    this.#reportedUsageKeys = new Set()
    this.#units = new Map()
    this.#unitsByDimension = new Map()
    this.#unitsByPriceKey = new Map()

    for (const [usageKey, rawUnit] of Object.entries(raw)) {
      const priceKey = rawUnit.price_key ?? usageKey
      const unit: UnitDef = Object.freeze({
        dimensions: Object.freeze({ ...rawUnit.dimensions }),
        per: rawUnit.per,
        priceKey,
        usageKey,
      })

      this.#allPriceKeys.add(priceKey)
      this.#allUsageKeys.add(usageKey)
      this.#units.set(usageKey, unit)
      this.#unitsByPriceKey.set(priceKey, unit)
      this.#unitsByDimension.set(dimensionKey(unit.dimensions), unit)
    }

    for (const [usageKey, unit] of this.#units) {
      this.#ancestorUsageKeysByUsageKey.set(
        usageKey,
        new Set(
          [...this.#units.values()]
            .filter((maybeAncestor) => maybeAncestor !== unit && isDimensionSubset(maybeAncestor, unit))
            .map((maybeAncestor) => maybeAncestor.usageKey)
        )
      )
      if (usageKey !== 'requests') {
        this.#reportedUsageKeys.add(usageKey)
      }
    }
  }

  ancestorUsageKeys(usageKey: string): Set<string> {
    const ancestorUsageKeys = this.#ancestorUsageKeysByUsageKey.get(usageKey)
    if (!ancestorUsageKeys) {
      throw new Error(`Unknown unit usage key: ${usageKey}`)
    }
    return new Set(ancestorUsageKeys)
  }

  findJoin(left: UnitDef, right: UnitDef): undefined | UnitDef {
    if (!isCompatible(left, right)) return undefined
    return this.#unitsByDimension.get(dimensionKey({ ...left.dimensions, ...right.dimensions }))
  }

  getAllPriceKeys(): Set<string> {
    return new Set(this.#allPriceKeys)
  }

  getAllUsageKeys(): Set<string> {
    return new Set(this.#allUsageKeys)
  }

  getUnit(usageKey: string): undefined | UnitDef {
    return this.#units.get(usageKey)
  }

  getUnitForPriceKey(priceKey: string): undefined | UnitDef {
    return this.#unitsByPriceKey.get(priceKey)
  }

  isReportedUsageKey(usageKey: string): boolean {
    return this.#reportedUsageKeys.has(usageKey)
  }

  reportedUsageKeys(): IterableIterator<string> {
    return this.#reportedUsageKeys.values()
  }
}

const generatedRegistry = new UnitRegistry(unitData)

export function getActiveRegistry(): UnitRegistry {
  return generatedRegistry
}

function dimensionKey(dimensions: Readonly<Record<string, string>>): string {
  return JSON.stringify(Object.entries(dimensions).sort(([left], [right]) => left.localeCompare(right)))
}

function isDimensionSubset(maybeAncestor: UnitDef, unit: UnitDef): boolean {
  return Object.entries(maybeAncestor.dimensions).every(([key, value]) => unit.dimensions[key] === value)
}

export function isDescendantOrSelf(ancestor: UnitDef, descendant: UnitDef): boolean {
  return isDimensionSubset(ancestor, descendant)
}

export function isCompatible(left: UnitDef, right: UnitDef): boolean {
  return Object.entries(left.dimensions).every(([key, value]) => right.dimensions[key] === undefined || right.dimensions[key] === value)
}
