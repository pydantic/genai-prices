import type { UnitRegistry } from './unitRegistry'

import { getRuntimeData } from './runtimeState'

export { isCompatible, isDescendantOrSelf, UnitRegistry } from './unitRegistry'

export function getActiveRegistry(): UnitRegistry {
  return getRuntimeData().registry
}
