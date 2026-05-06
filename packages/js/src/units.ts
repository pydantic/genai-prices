import type { ParsedFamilies, RawFamiliesDict, UnitDef, UnitFamily } from './types'

export function parseFamilies(raw: RawFamiliesDict): ParsedFamilies {
  const parsed: ParsedFamilies = {}
  const usageKeys = new Set<string>()

  for (const [familyId, rawFamily] of Object.entries(raw)) {
    const family: UnitFamily = {
      description: rawFamily.description,
      id: familyId,
      per: rawFamily.per,
      units: {},
      unitsByDimension: new Map(),
    }
    parsed[familyId] = family

    for (const [usageKey, rawUnit] of Object.entries(rawFamily.units)) {
      if (usageKeys.has(usageKey)) {
        throw new Error(`Duplicate unit usage key: ${usageKey}`)
      }
      usageKeys.add(usageKey)

      const unit: UnitDef = {
        dimensions: { ...rawUnit.dimensions },
        family,
        familyId,
        priceKey: rawUnit.price_key ?? usageKey,
        usageKey,
      }
      family.units[usageKey] = unit
      family.unitsByDimension.set(dimensionKey(unit.dimensions), unit)
    }
  }

  return parsed
}

function dimensionKey(dimensions: Record<string, string>): string {
  return Object.entries(dimensions)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${value}`)
    .join('\0')
}
