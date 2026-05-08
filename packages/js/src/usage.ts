import type { UnitDef, Usage } from './types'

import { dimensionKey, getReportedUsageKeys, getUnit, isCompatible, isDescendantOrSelf } from './units'

export type NormalizedUsage = Usage

export function normalizeUsage(obj: unknown): NormalizedUsage {
  if (!isPlainObject(obj)) return {}

  const usage: NormalizedUsage = {}
  for (const usageKey of getReportedUsageKeys()) {
    const value = obj[usageKey]
    if (typeof value === 'number') {
      usage[usageKey] = value
    }
  }
  return usage
}

export function getUsageValue(usage: NormalizedUsage, usageKey: string): number {
  const requestedUnit = getUnit(usageKey)
  const storedValue = usage[usageKey]
  if (storedValue !== undefined) return storedValue

  for (const [reportedUsageKey, reportedValue] of Object.entries(usage)) {
    if ((reportedValue ?? 0) <= 0) continue
    const reportedUnit = getUnit(reportedUsageKey)
    if (reportedUnit !== requestedUnit && isDescendantOrSelf(requestedUnit, reportedUnit)) {
      throw new Error(`Missing usage value for ${usageKey} with positive reported descendant ${reportedUsageKey}`)
    }
  }

  const positiveReportedUnits = Object.entries(usage)
    .filter(([, value]) => (value ?? 0) > 0)
    .map(([reportedUsageKey]) => getUnit(reportedUsageKey))

  for (let leftIndex = 0; leftIndex < positiveReportedUnits.length; leftIndex++) {
    for (let rightIndex = leftIndex + 1; rightIndex < positiveReportedUnits.length; rightIndex++) {
      const left = positiveReportedUnits[leftIndex]
      const right = positiveReportedUnits[rightIndex]
      if (!left || !right || !isCompatible(left, right) || isComparable(left, right)) continue

      const joinDimensions = { ...left.dimensions, ...right.dimensions }
      if (dimensionKey(joinDimensions) === dimensionKey(requestedUnit.dimensions)) {
        throw new Error(`Missing usage value for ${usageKey} with positive reported overlap ${left.usageKey} and ${right.usageKey}`)
      }
    }
  }

  return 0
}

function isPlainObject(obj: unknown): obj is Record<string, unknown> {
  return typeof obj === 'object' && obj !== null && !Array.isArray(obj)
}

function isComparable(left: UnitDef, right: UnitDef): boolean {
  return isDescendantOrSelf(left, right) || isDescendantOrSelf(right, left)
}
