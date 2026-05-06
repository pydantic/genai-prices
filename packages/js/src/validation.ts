import type { ParsedFamilies } from './types'

import { getActiveFamilies } from './units'

export function validatePriceKeys(priceKeys: Iterable<string>, families: ParsedFamilies = getActiveFamilies()): void {
  const registeredPriceKeys = new Set(Object.values(families).flatMap((family) => Object.values(family.units).map((unit) => unit.priceKey)))

  for (const priceKey of priceKeys) {
    if (!registeredPriceKeys.has(priceKey)) {
      throw new Error(`Unknown price key: ${priceKey}`)
    }
  }
}
