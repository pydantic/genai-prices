import type { UnitDef } from './types'
import type { UnitRegistry } from './units'
import type { NormalizedUsage } from './usage'

import { getActiveRegistry, isDescendantOrSelf } from './units'
import { getUsageValue } from './usage'

export function computeLeafValues(
  pricedUsageKeys: Set<string>,
  usage: NormalizedUsage,
  registry: UnitRegistry = getActiveRegistry()
): Record<string, number> {
  const pricedUnits = [...pricedUsageKeys]
    .map((usageKey) => registry.getUnit(usageKey))
    .filter((unit): unit is UnitDef => unit !== undefined)
    .sort(
      (left, right) =>
        Object.keys(right.dimensions).length - Object.keys(left.dimensions).length || left.usageKey.localeCompare(right.usageKey)
    )
  const leafValues: Record<string, number> = {}

  for (const unit of pricedUnits) {
    const unitValue = getUsageValue(usage, unit.usageKey, registry)
    let descendantLeafTotal = 0
    for (const descendant of pricedUnits) {
      if (descendant === unit || !isDescendantOrSelf(unit, descendant)) continue

      const descendantLeafValue = leafValues[descendant.usageKey]
      if (descendantLeafValue === undefined) {
        throw new Error(`Missing computed leaf value for ${descendant.usageKey}`)
      }
      descendantLeafTotal += descendantLeafValue
    }

    let leafValue = unitValue - descendantLeafTotal
    const roundingTolerance = Number.EPSILON * Math.max(1, Math.abs(unitValue), Math.abs(descendantLeafTotal)) * (pricedUnits.length + 1)
    if (leafValue < 0 && Math.abs(leafValue) <= roundingTolerance) {
      leafValue = 0
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
