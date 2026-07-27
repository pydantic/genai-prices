import type { Provider } from './types'

import { data as embeddedData } from './data'
import { unitData } from './dataUnits'
import { UnitRegistry } from './unitRegistry'

export type RuntimeData = Readonly<{
  providers: Provider[]
  registry: UnitRegistry
}>

export const bundledRuntimeData: RuntimeData = Object.freeze({
  providers: embeddedData,
  registry: new UnitRegistry(unitData),
})

let runtimeData = bundledRuntimeData

export function getRuntimeData(): RuntimeData {
  return runtimeData
}

export function activateRuntimeData(candidate: RuntimeData): void {
  runtimeData = Object.freeze(candidate)
}
