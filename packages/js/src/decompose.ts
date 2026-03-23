import type { UnitDef, UnitFamily } from './units'

/**
 * True if candidate's dimensions are a (non-strict) superset of ancestor's.
 */
export function isDescendantOrSelf(ancestor: UnitDef, candidate: UnitDef): boolean {
  if (ancestor.familyId !== candidate.familyId) return false
  return Object.entries(ancestor.dimensions).every(([k, v]) => candidate.dimensions[k] === v)
}

/**
 * Get a usage value by key from a plain object. Returns 0 for missing/undefined/null.
 */
function getUsageValue(usage: Record<string, unknown>, key: string): number {
  const val = usage[key]
  return typeof val === 'number' ? val : 0
}

/**
 * Validate that every priced unit has all its ancestors also priced.
 * Throws if any ancestor is missing.
 */
export function validateAncestorCoverage(pricedUnitIds: Set<string>, family: UnitFamily): void {
  for (const unitId of pricedUnitIds) {
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    const unit = family.units[unitId]!
    for (const [otherId, other] of Object.entries(family.units)) {
      if (otherId !== unitId && isDescendantOrSelf(other, unit) && !pricedUnitIds.has(otherId)) {
        throw new Error(
          `Unit '${unitId}' is priced but its ancestor '${otherId}' is not. ` + `All ancestors of a priced unit must also be priced.`
        )
      }
    }
  }
}

/**
 * Compute leaf values for each priced unit via Mobius inversion on the containment poset.
 *
 * Only priced units participate. Unpriced units' tokens stay in the nearest
 * priced ancestor's catch-all. Throws on negative leaf values.
 *
 * Precondition: if a unit is priced, all its ancestors must also be priced
 * (ancestor coverage rule). Violating this produces silently incorrect results.
 */
export function computeLeafValues(pricedUnitIds: Set<string>, usage: Record<string, unknown>, family: UnitFamily): Record<string, number> {
  const result: Record<string, number> = {}

  for (const unitId of pricedUnitIds) {
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    const unit = family.units[unitId]!
    const targetDepth = Object.keys(unit.dimensions).length

    let leafValue = 0
    for (const otherId of pricedUnitIds) {
      // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
      const other = family.units[otherId]!
      if (!isDescendantOrSelf(unit, other)) continue
      const depthDiff = Object.keys(other.dimensions).length - targetDepth
      const coefficient = (-1) ** depthDiff
      leafValue += coefficient * getUsageValue(usage, other.usageKey)
    }

    if (leafValue < 0) {
      const involved = [...pricedUnitIds]
        .filter((oid) => {
          // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
          const o = family.units[oid]!
          return isDescendantOrSelf(unit, o) && getUsageValue(usage, o.usageKey) !== 0
        })
        .map((oid) => {
          // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
          const o = family.units[oid]!
          return `${o.usageKey}=${String(getUsageValue(usage, o.usageKey))}`
        })
      throw new Error(`Negative leaf value (${String(leafValue)}) for ${unitId}: inconsistent usage values: ${involved.join(', ')}`)
    }

    result[unitId] = leafValue
  }

  return result
}
