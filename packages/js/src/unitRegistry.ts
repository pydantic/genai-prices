import type { RawUnitsDict, UnitDef } from './types'

const publicKeyPattern = /^[A-Za-z][A-Za-z0-9_]*$/
const reservedPublicKeys = new Set(['__proto__', 'constructor', 'prototype'])
const reservedKeywords = new Set([
  'and',
  'arguments',
  'as',
  'assert',
  'async',
  'await',
  'break',
  'case',
  'catch',
  'class',
  'const',
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
  'False',
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
  'None',
  'nonlocal',
  'not',
  'null',
  'or',
  'package',
  'pass',
  'private',
  'protected',
  'public',
  'raise',
  'return',
  'static',
  'super',
  'switch',
  'this',
  'throw',
  'True',
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

  static fromUntrusted(raw: unknown): UnitRegistry {
    const registry = new UnitRegistry(validateRawUnits(raw))
    validateIntervalClosure(registry)
    validateJoinClosedness(registry)
    return registry
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

function validateRawUnits(raw: unknown): RawUnitsDict {
  if (!isPlainObject(raw)) {
    throw new Error('Unit definitions must be an object')
  }

  const units: RawUnitsDict = {}
  const priceKeys = new Set<string>()
  const perByFamily = new Map<string, number>()
  const usageKeyByDimensions = new Map<string, string>()

  for (const [usageKey, rawUnit] of Object.entries(raw)) {
    validatePublicKey('usage', usageKey)
    if (!isPlainObject(rawUnit)) {
      throw new Error(`Unit definition for ${usageKey} must be an object`)
    }

    rejectUnknownFields(rawUnit, new Set(['dimensions', 'per', 'price_key']), `unit definition for ${usageKey}`)

    const priceKey = rawUnit.price_key ?? usageKey
    if (typeof priceKey !== 'string') {
      throw new Error(`Unit price key for ${usageKey} must be a string`)
    }
    validatePublicKey('price', priceKey)
    if (priceKeys.has(priceKey)) {
      throw new Error(`Duplicate unit price key: ${priceKey}`)
    }
    priceKeys.add(priceKey)

    const per = rawUnit.per
    if (typeof per !== 'number' || !Number.isInteger(per) || per <= 0) {
      throw new Error(`Unit per for ${usageKey} must be a positive integer`)
    }

    const rawDimensions = rawUnit.dimensions
    if (!isPlainObject(rawDimensions)) {
      throw new Error(`Unit dimensions for ${usageKey} must be an object`)
    }
    const dimensions: Record<string, string> = {}
    for (const [key, value] of Object.entries(rawDimensions)) {
      if (typeof value !== 'string') {
        throw new Error(`Unit dimensions for ${usageKey} must map strings to strings`)
      }
      dimensions[key] = value
    }

    const family = dimensions.family
    if (family === undefined) {
      throw new Error(`Missing required family dimension for unit ${usageKey}`)
    }
    const existingPer = perByFamily.get(family)
    if (existingPer !== undefined && existingPer !== per) {
      throw new Error(
        `Inconsistent per for family dimension ${family}: expected ${existingPer.toString()}, got ${per.toString()} on ${usageKey}`
      )
    }
    perByFamily.set(family, per)

    const dimensionsKey = dimensionKey(dimensions)
    const existingUsageKey = usageKeyByDimensions.get(dimensionsKey)
    if (existingUsageKey !== undefined) {
      throw new Error(`Duplicate unit dimensions: ${existingUsageKey} and ${usageKey}`)
    }
    usageKeyByDimensions.set(dimensionsKey, usageKey)

    units[usageKey] = {
      dimensions,
      per,
      ...(priceKey === usageKey ? {} : { price_key: priceKey }),
    }
  }

  return units
}

function validatePublicKey(kind: 'price' | 'usage', key: string): void {
  if (key.startsWith('_')) {
    throw new Error(`Invalid unit ${kind} key: '${key}' must not start with "_"`)
  }
  if (!publicKeyPattern.test(key)) {
    throw new Error(`Invalid unit ${kind} key: '${key}' is not a public identifier`)
  }
  if (reservedKeywords.has(key)) {
    throw new Error(`Invalid unit ${kind} key: '${key}' is a reserved keyword`)
  }
  if (reservedPublicKeys.has(key)) {
    throw new Error(`Invalid unit ${kind} key: '${key}' is reserved`)
  }
}

function validateIntervalClosure(registry: UnitRegistry): void {
  const units = registryUnits(registry)
  const availableDimensions = new Set(units.map((unit) => dimensionKey(unit.dimensions)))
  const requirements = inferDimensionRequirements(units)

  for (const ancestor of units) {
    for (const descendant of units) {
      if (ancestor === descendant || !isDimensionSubset(ancestor, descendant)) continue

      const ancestorDimensionKeys = new Set(Object.entries(ancestor.dimensions).map(dimensionEntryKey))
      const descendantEntries = Object.entries(descendant.dimensions)
      const descendantEntriesByKey = new Map(descendantEntries.map((entry) => [dimensionEntryKey(entry), entry]))
      const descendantDimensionKeys = new Set(descendantEntriesByKey.keys())
      const addedDimensionKeys = [...descendantDimensionKeys].filter((entryKey) => !ancestorDimensionKeys.has(entryKey))
      for (const addedDimensionKey of addedDimensionKeys) {
        const initialDimensionKeys = new Set(ancestorDimensionKeys)
        initialDimensionKeys.add(addedDimensionKey)
        const requiredDimensionKeys = requirementClosure(initialDimensionKeys, requirements)
        if (setsEqual(requiredDimensionKeys, descendantDimensionKeys)) continue
        const requiredDimensions = Object.fromEntries(
          [...requiredDimensionKeys].map((entryKey) => {
            const entry = descendantEntriesByKey.get(entryKey)
            if (!entry) throw new Error(`Missing inferred dimension entry: ${entryKey}`)
            return entry
          })
        )
        if (availableDimensions.has(dimensionKey(requiredDimensions))) continue

        throw new Error(
          `Missing intermediate unit dimensions between ${ancestor.usageKey} and ${descendant.usageKey}: ${formatDimensions(requiredDimensions)}`
        )
      }
    }
  }
}

function inferDimensionRequirements(units: UnitDef[]): Map<string, Set<string>> {
  const occurrences = new Map<string, Set<string>[]>()
  for (const unit of units) {
    const dimensionKeys = new Set(Object.entries(unit.dimensions).map(dimensionEntryKey))
    for (const entryKey of dimensionKeys) {
      const entryOccurrences = occurrences.get(entryKey) ?? []
      entryOccurrences.push(dimensionKeys)
      occurrences.set(entryKey, entryOccurrences)
    }
  }

  const requirements = new Map<string, Set<string>>()
  for (const [entryKey, dimensionSets] of occurrences) {
    const [first, ...rest] = dimensionSets
    if (!first) continue
    const commonDimensions = new Set(first)
    for (const dimensionSet of rest) {
      for (const commonDimension of commonDimensions) {
        if (!dimensionSet.has(commonDimension)) commonDimensions.delete(commonDimension)
      }
    }
    commonDimensions.delete(entryKey)
    requirements.set(entryKey, commonDimensions)
  }
  return requirements
}

function requirementClosure(initialDimensions: Set<string>, requirements: Map<string, Set<string>>): Set<string> {
  const closedDimensions = new Set(initialDimensions)
  const pendingDimensions = [...initialDimensions]
  while (pendingDimensions.length) {
    const dimension = pendingDimensions.pop()
    if (!dimension) continue
    const dimensionRequirements = requirements.get(dimension)
    if (!dimensionRequirements) throw new Error(`Missing inferred requirements for dimension: ${dimension}`)
    for (const requirement of dimensionRequirements) {
      if (closedDimensions.has(requirement)) continue
      closedDimensions.add(requirement)
      pendingDimensions.push(requirement)
    }
  }
  return closedDimensions
}

function validateJoinClosedness(registry: UnitRegistry): void {
  const units = registryUnits(registry)
  const availableDimensions = new Set(units.map((unit) => dimensionKey(unit.dimensions)))
  for (let firstIndex = 0; firstIndex < units.length; firstIndex++) {
    for (let secondIndex = firstIndex + 1; secondIndex < units.length; secondIndex++) {
      const first = units[firstIndex]
      const second = units[secondIndex]
      if (!first || !second || !isCompatible(first, second)) continue

      const requiredDimensions = { ...first.dimensions, ...second.dimensions }
      if (availableDimensions.has(dimensionKey(requiredDimensions))) continue
      throw new Error(
        `Missing join unit dimensions between ${first.usageKey} and ${second.usageKey}: ${formatDimensions(requiredDimensions)}`
      )
    }
  }
}

function registryUnits(registry: UnitRegistry): UnitDef[] {
  return [...registry.getAllUsageKeys()].map((usageKey) => registry.getUnit(usageKey)).filter((unit): unit is UnitDef => unit !== undefined)
}

function dimensionEntryKey([key, value]: [string, string]): string {
  return JSON.stringify([key, value])
}

function isSubset<T>(subset: Set<T>, superset: Set<T>): boolean {
  return [...subset].every((value) => superset.has(value))
}

function setsEqual<T>(left: Set<T>, right: Set<T>): boolean {
  return left.size === right.size && isSubset(left, right)
}

function formatDimensions(dimensions: Readonly<Record<string, string>>): string {
  return Object.entries(dimensions)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${value}`)
    .join(', ')
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function rejectUnknownFields(value: Record<string, unknown>, allowed: Set<string>, context: string): void {
  const unknownFields = Object.keys(value).filter((field) => !allowed.has(field))
  if (unknownFields.length) {
    throw new Error(`Unknown ${context} fields: ${unknownFields.sort().join(', ')}`)
  }
}
