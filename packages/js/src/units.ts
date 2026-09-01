import type { RawUnitsDict, UnitDef } from './types'

import { unitData } from './dataUnits'

const invalidDataPrefix = 'genai-prices: invalid data:'
const publicKeyPattern = /^[A-Za-z][A-Za-z0-9_]*$/
const reservedPublicKeys = new Set([
  '__proto__',
  'arguments',
  'await',
  'break',
  'case',
  'catch',
  'class',
  'const',
  'constructor',
  'continue',
  'debugger',
  'def',
  'default',
  'del',
  'delete',
  'do',
  'elif',
  'else',
  'enum',
  'eval',
  'except',
  'export',
  'extends',
  'false',
  'finally',
  'for',
  'from',
  'function',
  'global',
  'if',
  'implements',
  'import',
  'in',
  'instanceof',
  'interface',
  'is',
  'lambda',
  'let',
  'new',
  'nonlocal',
  'not',
  'null',
  'or',
  'package',
  'pass',
  'private',
  'protected',
  'prototype',
  'public',
  'raise',
  'return',
  'static',
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

  static fromUntrusted(rawUnits: unknown): UnitRegistry {
    if (!isObject(rawUnits)) throw invalidData('units must be an object')

    const canonicalUnits: RawUnitsDict = {}
    const usageKeyByDimensions = new Map<string, string>()
    const usageKeyByPriceKey = new Map<string, string>()
    const perByFamily = new Map<string, number>()

    for (const [usageKey, rawUnitValue] of Object.entries(rawUnits)) {
      validatePublicKey('usage', usageKey)
      if (!isObject(rawUnitValue)) throw invalidData(`unit ${JSON.stringify(usageKey)} must be an object`)
      if (!hasOwn(rawUnitValue, 'per')) throw invalidData(`unit ${JSON.stringify(usageKey)} is missing per`)

      const per = rawUnitValue.per
      if (typeof per !== 'number' || !Number.isSafeInteger(per) || per < 1) {
        throw invalidData(`unit ${JSON.stringify(usageKey)} per must be a safe positive integer, got ${JSON.stringify(per)}`)
      }

      let priceKey = usageKey
      if (hasOwn(rawUnitValue, 'price_key')) {
        if (typeof rawUnitValue.price_key !== 'string') {
          throw invalidData(`unit ${JSON.stringify(usageKey)} price_key must be a string`)
        }
        priceKey = rawUnitValue.price_key
      }
      validatePublicKey('price', priceKey)

      if (!hasOwn(rawUnitValue, 'dimensions') || !isObject(rawUnitValue.dimensions)) {
        throw invalidData(`unit ${JSON.stringify(usageKey)} dimensions must be an object`)
      }
      const dimensions: Record<string, string> = {}
      for (const [key, value] of Object.entries(rawUnitValue.dimensions)) {
        if (key.length === 0 || typeof value !== 'string' || value.length === 0) {
          throw invalidData(`unit ${JSON.stringify(usageKey)} dimensions must use non-empty string keys and values`)
        }
        dimensions[key] = value
      }
      const family = dimensions.family
      if (family === undefined) throw invalidData(`unit ${JSON.stringify(usageKey)} is missing the family dimension`)

      const previousUsageKey = usageKeyByPriceKey.get(priceKey)
      if (previousUsageKey !== undefined) {
        throw invalidData(`units ${JSON.stringify(previousUsageKey)} and ${JSON.stringify(usageKey)} use price key ${priceKey}`)
      }
      usageKeyByPriceKey.set(priceKey, usageKey)

      const dimensionsKey = dimensionKey(dimensions)
      const previousDimensionsUsageKey = usageKeyByDimensions.get(dimensionsKey)
      if (previousDimensionsUsageKey !== undefined) {
        throw invalidData(`units ${JSON.stringify(previousDimensionsUsageKey)} and ${JSON.stringify(usageKey)} use identical dimensions`)
      }
      usageKeyByDimensions.set(dimensionsKey, usageKey)

      const previousPer = perByFamily.get(family)
      if (previousPer !== undefined && previousPer !== per) {
        throw invalidData(
          `unit ${JSON.stringify(usageKey)} per ${String(per)} differs from ${String(previousPer)} for family ${JSON.stringify(family)}`
        )
      }
      perByFamily.set(family, per)
      canonicalUnits[usageKey] = { dimensions, per, ...(priceKey === usageKey ? {} : { price_key: priceKey }) }
    }

    validateJoinAvailability(canonicalUnits, usageKeyByDimensions)
    return new UnitRegistry(canonicalUnits)
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
let activeRegistry: undefined | UnitRegistry

export function getActiveRegistry(): UnitRegistry {
  return activeRegistry ?? generatedRegistry
}

export function setActiveRegistry(registry?: UnitRegistry): void {
  activeRegistry = registry
}

export function validateUnitEvolution(previous: UnitRegistry, candidate: UnitRegistry): void {
  const previousOrder = [...previous.getAllUsageKeys()]
  const candidateOrder = [...candidate.getAllUsageKeys()]

  for (const usageKey of previousOrder) {
    if (candidate.getUnit(usageKey) === undefined) throw invalidData(`removed published unit: ${usageKey}`)
  }

  const candidateOldOrder = candidateOrder.filter((usageKey) => previous.getUnit(usageKey) !== undefined)
  if (!arraysEqual(candidateOldOrder, previousOrder)) {
    throw invalidData(`reordered published units: expected ${JSON.stringify(previousOrder)}, got ${JSON.stringify(candidateOldOrder)}`)
  }
  if (!arraysEqual(candidateOrder.slice(0, previousOrder.length), previousOrder)) {
    const firstInserted = candidateOrder.find((usageKey) => previous.getUnit(usageKey) === undefined)
    throw invalidData(`new unit ${String(firstInserted)} must be appended after all published units`)
  }

  for (const usageKey of previousOrder) {
    const previousUnit = previous.getUnit(usageKey)
    const candidateUnit = candidate.getUnit(usageKey)
    if (!previousUnit || !candidateUnit) continue
    if (!unitDefinitionsEqual(previousUnit, candidateUnit)) throw invalidData(`redefined published unit: ${usageKey}`)
  }

  for (const usageKey of candidateOrder.slice(previousOrder.length)) {
    const newUnit = candidate.getUnit(usageKey)
    if (!newUnit) continue
    for (const oldUsageKey of previousOrder) {
      const oldUnit = previous.getUnit(oldUsageKey)
      if (oldUnit && isDimensionSubset(newUnit, oldUnit)) {
        throw invalidData(`new unit ${usageKey} is an ancestor or intermediate of published unit ${oldUsageKey}`)
      }
    }
  }
}

function dimensionKey(dimensions: Readonly<Record<string, string>>): string {
  return JSON.stringify(Object.entries(dimensions).sort(([left], [right]) => left.localeCompare(right)))
}

function arraysEqual(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index])
}

function invalidData(message: string): Error {
  return new Error(`${invalidDataPrefix} ${message}`)
}

function hasOwn(value: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key)
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function validateJoinAvailability(rawUnits: RawUnitsDict, usageKeyByDimensions: ReadonlyMap<string, string>): void {
  const entries = Object.entries(rawUnits)
  for (let leftIndex = 0; leftIndex < entries.length; leftIndex++) {
    const leftEntry = entries[leftIndex]
    if (!leftEntry) continue
    const [leftUsageKey, left] = leftEntry
    for (let rightIndex = leftIndex + 1; rightIndex < entries.length; rightIndex++) {
      const rightEntry = entries[rightIndex]
      if (!rightEntry) continue
      const [rightUsageKey, right] = rightEntry
      if (!dimensionsCompatible(left.dimensions, right.dimensions)) continue
      const joinedDimensions = { ...left.dimensions, ...right.dimensions }
      if (!usageKeyByDimensions.has(dimensionKey(joinedDimensions))) {
        throw invalidData(`missing join unit dimensions between ${leftUsageKey} and ${rightUsageKey}`)
      }
    }
  }
}

function validatePublicKey(kind: 'price' | 'usage', key: string): void {
  if (!publicKeyPattern.test(key)) throw invalidData(`unit ${kind} key ${JSON.stringify(key)} is not a public identifier`)
  if (reservedPublicKeys.has(key)) throw invalidData(`unit ${kind} key ${JSON.stringify(key)} is reserved`)
}

function dimensionsCompatible(left: Readonly<Record<string, string>>, right: Readonly<Record<string, string>>): boolean {
  return Object.entries(left).every(([key, value]) => right[key] === undefined || right[key] === value)
}

function isDimensionSubset(maybeAncestor: UnitDef, unit: UnitDef): boolean {
  return Object.entries(maybeAncestor.dimensions).every(([key, value]) => unit.dimensions[key] === value)
}

function unitDefinitionsEqual(left: UnitDef, right: UnitDef): boolean {
  return (
    left.usageKey === right.usageKey &&
    left.priceKey === right.priceKey &&
    left.per === right.per &&
    dimensionKey(left.dimensions) === dimensionKey(right.dimensions)
  )
}

export function isDescendantOrSelf(ancestor: UnitDef, descendant: UnitDef): boolean {
  return isDimensionSubset(ancestor, descendant)
}

export function isCompatible(left: UnitDef, right: UnitDef): boolean {
  return Object.entries(left.dimensions).every(([key, value]) => right.dimensions[key] === undefined || right.dimensions[key] === value)
}
