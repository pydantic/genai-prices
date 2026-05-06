import type { Usage } from './types'

import { getReportedUsageKeys } from './units'

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

function isPlainObject(obj: unknown): obj is Record<string, unknown> {
  return typeof obj === 'object' && obj !== null && !Array.isArray(obj)
}
