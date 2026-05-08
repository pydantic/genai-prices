import type { UnitDef, Usage } from './types'

import { dimensionKey, getActiveRegistry, isCompatible, UnitRegistry } from './units'

export type NormalizedUsage = Usage

export function normalizeUsage(obj: unknown): NormalizedUsage {
  if (!isPlainObject(obj)) return {}

  const registry = getActiveRegistry()
  const usage: NormalizedUsage = {}
  for (const usageKey of registry.reportedUsageKeys) {
    const value = obj[usageKey]
    if (typeof value === 'number') {
      usage[usageKey] = value
    }
  }
  return usage
}

export function getUsageValue(usage: NormalizedUsage, usageKey: string): number {
  const registry = getActiveRegistry()
  const requestedUnit = unitForUsageKey(registry, usageKey)
  if (requestedUnit.familyId === 'requests') return 1

  const storedValue = usage[usageKey]
  if (storedValue !== undefined) return storedValue

  for (const [reportedUsageKey, reportedValue] of Object.entries(usage)) {
    if ((reportedValue ?? 0) <= 0) continue
    const reportedUnit = unitForOptionalUsageKey(registry, reportedUsageKey)
    if (!reportedUnit) continue

    if (reportedUsageKey !== usageKey && registry.ancestorUsageKeys(reportedUnit.usageKey).has(usageKey)) {
      throw new Error(`Missing usage value for ${usageKey} with positive reported descendant ${reportedUsageKey}`)
    }
  }

  const positiveReportedUnits = Object.entries(usage)
    .filter(([, value]) => (value ?? 0) > 0)
    .map(([reportedUsageKey]) => unitForOptionalUsageKey(registry, reportedUsageKey))
    .filter((unit): unit is UnitDef => unit !== undefined)

  for (let leftIndex = 0; leftIndex < positiveReportedUnits.length; leftIndex++) {
    for (let rightIndex = leftIndex + 1; rightIndex < positiveReportedUnits.length; rightIndex++) {
      const left = positiveReportedUnits[leftIndex]
      const right = positiveReportedUnits[rightIndex]
      if (!left || !right || !isCompatible(left, right) || isComparable(registry, left, right)) continue

      const joinDimensions = { ...left.dimensions, ...right.dimensions }
      if (left.family.unitsByDimension.get(dimensionKey(joinDimensions)) === requestedUnit) {
        throw new Error(`Missing usage value for ${usageKey} with positive reported overlap ${left.usageKey} and ${right.usageKey}`)
      }
    }
  }

  return 0
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
