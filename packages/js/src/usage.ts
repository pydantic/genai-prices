import type { UnitDef, Usage } from './types'

import { getActiveRegistry, isCompatible, UnitRegistry } from './units'

export type NormalizedUsage = Usage

export function normalizeUsage(obj: unknown, registry: UnitRegistry = getActiveRegistry()): NormalizedUsage {
  if (!isPlainObject(obj)) return {}

  const usage: NormalizedUsage = {}
  for (const usageKey of registry.reportedUsageKeys) {
    const value = obj[usageKey]
    if (typeof value === 'number') {
      usage[usageKey] = validateUsageValue(usageKey, value)
    }
  }
  return usage
}

export function getUsageValue(usage: NormalizedUsage, usageKey: string, registry: UnitRegistry = getActiveRegistry()): number {
  if (usageKey === 'requests') return 1
  const requestedUnit = unitForUsageKey(registry, usageKey)

  const storedValue = validateOptionalUsageValue(usageKey, usage[usageKey])
  if (storedValue !== undefined) return storedValue

  for (const [reportedUsageKey, rawReportedValue] of Object.entries(usage)) {
    const reportedUnit = unitForOptionalUsageKey(registry, reportedUsageKey)
    if (!reportedUnit) continue
    const reportedValue = validateOptionalUsageValue(reportedUsageKey, rawReportedValue)
    if ((reportedValue ?? 0) <= 0) continue

    if (reportedUsageKey !== usageKey && registry.ancestorUsageKeys(reportedUnit.usageKey).has(usageKey)) {
      throw new Error(`Missing usage value for ${usageKey} with positive reported descendant ${reportedUsageKey}`)
    }
  }

  const positiveReportedUnits = Object.entries(usage)
    .map(([reportedUsageKey, rawValue]) => {
      const unit = unitForOptionalUsageKey(registry, reportedUsageKey)
      if (!unit) return undefined
      const value = validateOptionalUsageValue(reportedUsageKey, rawValue)
      return (value ?? 0) > 0 ? unit : undefined
    })
    .filter((unit): unit is UnitDef => unit !== undefined)

  for (let leftIndex = 0; leftIndex < positiveReportedUnits.length; leftIndex++) {
    for (let rightIndex = leftIndex + 1; rightIndex < positiveReportedUnits.length; rightIndex++) {
      const left = positiveReportedUnits[leftIndex]
      const right = positiveReportedUnits[rightIndex]
      if (!left || !right || !isCompatible(left, right) || isComparable(registry, left, right)) continue

      if (registry.findJoin(left, right) === requestedUnit) {
        throw new Error(`Missing usage value for ${usageKey} with positive reported overlap ${left.usageKey} and ${right.usageKey}`)
      }
    }
  }

  return 0
}

function validateOptionalUsageValue(usageKey: string, value: unknown): number | undefined {
  if (value === undefined) return undefined
  if (typeof value !== 'number') {
    throw new Error(`Invalid usage value for ${usageKey}: expected a finite non-negative number`)
  }
  return validateUsageValue(usageKey, value)
}

function validateUsageValue(usageKey: string, value: number): number {
  if (!Number.isFinite(value) || value < 0) {
    throw new Error(`Invalid usage value for ${usageKey}: expected a finite non-negative number`)
  }
  return value
}

function isPlainObject(obj: unknown): obj is Record<string, unknown> {
  return typeof obj === 'object' && obj !== null && !Array.isArray(obj)
}

function isComparable(registry: UnitRegistry, left: UnitDef, right: UnitDef): boolean {
  return (
    left === right ||
    registry.ancestorUsageKeys(right.usageKey).has(left.usageKey) ||
    registry.ancestorUsageKeys(left.usageKey).has(right.usageKey)
  )
}

function unitForUsageKey(registry: UnitRegistry, usageKey: string): UnitDef {
  const unit = registry.units.get(usageKey)
  if (!unit) {
    throw new Error(`Unknown unit usage key: ${usageKey}`)
  }
  return unit
}

function unitForOptionalUsageKey(registry: UnitRegistry, usageKey: string): undefined | UnitDef {
  return registry.units.get(usageKey)
}
