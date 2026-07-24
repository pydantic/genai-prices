import type { UnitDef } from './types'
import type { UnitRegistry } from './units'
import type { NormalizedUsage } from './usage'

import { getActiveRegistry, isDescendantOrSelf } from './units'
import { getUsageValue } from './usage'

export function computeLeafValues(
  pricedUsageKeys: Set<string>,
  usage: NormalizedUsage,
  unitsByUsageKey: Map<string, UnitDef>,
  registry: UnitRegistry = getActiveRegistry()
): Record<string, number> {
  const pricedUnits = [...pricedUsageKeys]
    .filter((usageKey) => unitsByUsageKey.has(usageKey))
    .sort()
    .map((usageKey) => unitsByUsageKey.get(usageKey))
    .filter((unit): unit is UnitDef => unit !== undefined)
  const leafValues: Record<string, number> = {}

  for (const unit of pricedUnits) {
    let leafValue = 0
    for (const descendant of pricedUnits) {
      if (!isDescendantOrSelf(unit, descendant)) continue

      const sign = (Object.keys(descendant.dimensions).length - Object.keys(unit.dimensions).length) % 2 === 0 ? 1 : -1
      leafValue += sign * getUsageValue(usage, descendant.usageKey, registry)
    }

    if (leafValue < 0) {
      throw new Error(negativeLeafErrorMessage(unit, pricedUnits, usage, leafValue, registry))
    }

    leafValues[unit.usageKey] = leafValue
  }

  return leafValues
}

function negativeLeafErrorMessage(
  unit: UnitDef,
  pricedUnits: UnitDef[],
  usage: NormalizedUsage,
  leafValue: number,
  registry: UnitRegistry
): string {
  const unitValue = getUsageValue(usage, unit.usageKey, registry)
  const descendantValues = pricedUnits
    .filter((descendant) => descendant !== unit && isDescendantOrSelf(unit, descendant))
    .map((descendant) => ({
      unit: descendant,
      value: getUsageValue(usage, descendant.usageKey, registry),
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
