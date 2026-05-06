import type { Usage } from './types'

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
  getUnit(usageKey)
  return usage[usageKey] ?? 0
}

function isPlainObject(obj: unknown): obj is Record<string, unknown> {
  return typeof obj === 'object' && obj !== null && !Array.isArray(obj)
}
