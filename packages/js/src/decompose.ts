import type { UnitDef } from './types'

export function isDescendantOrSelf(ancestor: UnitDef, descendant: UnitDef): boolean {
  if (ancestor.family !== descendant.family) return false
  return Object.entries(ancestor.dimensions).every(([key, value]) => descendant.dimensions[key] === value)
}
