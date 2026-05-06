import type { UnitDef, Usage } from './types'

import { getReportedUsageKeys, getUnit } from './units'

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

  return 0
}

function isPlainObject(obj: unknown): obj is Record<string, unknown> {
  return typeof obj === 'object' && obj !== null && !Array.isArray(obj)
}

function isDescendantOrSelf(ancestor: UnitDef, descendant: UnitDef): boolean {
  if (ancestor.family !== descendant.family) return false
  return Object.entries(ancestor.dimensions).every(([key, value]) => descendant.dimensions[key] === value)
}
