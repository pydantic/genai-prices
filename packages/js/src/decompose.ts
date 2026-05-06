import type { UnitDef, UnitFamily } from './types'
import type { NormalizedUsage } from './usage'

import { getUsageValue } from './usage'

export function isDescendantOrSelf(ancestor: UnitDef, descendant: UnitDef): boolean {
  if (ancestor.family !== descendant.family) return false
  return Object.entries(ancestor.dimensions).every(([key, value]) => descendant.dimensions[key] === value)
}

export function computeLeafValues(pricedUsageKeys: Set<string>, usage: NormalizedUsage, family: UnitFamily): Record<string, number> {
  const pricedUnits = [...pricedUsageKeys]
    .filter((usageKey) => family.units[usageKey] !== undefined)
    .sort()
    .map((usageKey) => family.units[usageKey])
    .filter((unit): unit is UnitDef => unit !== undefined)
  const leafValues: Record<string, number> = {}

  for (const unit of pricedUnits) {
    let leafValue = 0
    for (const descendant of pricedUnits) {
      if (!isDescendantOrSelf(unit, descendant)) continue

      const sign = (Object.keys(descendant.dimensions).length - Object.keys(unit.dimensions).length) % 2 === 0 ? 1 : -1
      leafValue += sign * getUsageValue(usage, descendant.usageKey)
    }

    if (leafValue < 0) {
      throw new Error(negativeLeafErrorMessage(unit, pricedUnits, usage, leafValue))
    }

    leafValues[unit.usageKey] = leafValue
  }

  return leafValues
}

function negativeLeafErrorMessage(unit: UnitDef, pricedUnits: UnitDef[], usage: NormalizedUsage, leafValue: number): string {
  const unitValue = getUsageValue(usage, unit.usageKey)
  const descendantValues = pricedUnits
    .filter((descendant) => descendant !== unit && isDescendantOrSelf(unit, descendant))
    .map((descendant) => ({
      unit: descendant,
      value: getUsageValue(usage, descendant.usageKey),
    }))
    .filter(({ value }) => value > 0)

  for (const descendant of descendantValues) {
    if (descendant.value > unitValue) {
      return `Invalid usage data: ${descendant.unit.usageKey} (${descendant.value.toString()}) cannot exceed ${unit.usageKey} (${unitValue.toString()})`
    }
  }

  const descendantKeys = descendantValues.map(({ unit }) => unit.usageKey).join(', ')
  const descendantTotal = unitValue - leafValue
  return `Invalid usage data: more-specific usage for ${descendantKeys} totals ${descendantTotal.toString()}, which exceeds ${unit.usageKey} (${unitValue.toString()})`
}
