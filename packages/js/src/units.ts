import { unitData } from './dataUnits'
import { UnitRegistry } from './unitRegistry'

export { isCompatible, isDescendantOrSelf, UnitRegistry } from './unitRegistry'

const generatedRegistry = new UnitRegistry(unitData)

export function getActiveRegistry(): UnitRegistry {
  return generatedRegistry
}
