import unitsData from './units-data.json'

export interface UnitDef {
  dimensions: Record<string, string>
  familyId: string
  id: string
  usageKey: string
}

export interface UnitFamily {
  description: string
  dimensions: Record<string, string[]>
  id: string
  per: number
  units: Record<string, UnitDef>
}

interface RawUnitData {
  dimensions: Record<string, string>
  usage_key: string
}

interface RawFamilyData {
  description: string
  dimensions: Record<string, string[]>
  per: number
  units: Record<string, RawUnitData>
}

interface RawUnitsData {
  families: Record<string, RawFamilyData>
}

function loadFamilies(): Record<string, UnitFamily> {
  const families: Record<string, UnitFamily> = {}
  const raw = unitsData as RawUnitsData

  for (const [familyId, famData] of Object.entries(raw.families)) {
    const units: Record<string, UnitDef> = {}
    for (const [unitId, unitData] of Object.entries(famData.units)) {
      units[unitId] = {
        dimensions: unitData.dimensions,
        familyId,
        id: unitId,
        usageKey: unitData.usage_key,
      }
    }
    families[familyId] = {
      description: famData.description,
      dimensions: famData.dimensions,
      id: familyId,
      per: famData.per,
      units,
    }
  }
  return families
}

const FAMILIES = loadFamilies()
// eslint-disable-next-line @typescript-eslint/no-non-null-assertion
export const TOKENS_FAMILY = FAMILIES.tokens!

const ALL_UNITS: Record<string, UnitDef> = {}
for (const family of Object.values(FAMILIES)) {
  for (const [unitId, unit] of Object.entries(family.units)) {
    ALL_UNITS[unitId] = unit
  }
}

/** Mapping from current ModelPrice field names to registry unit IDs. */
export const FIELD_TO_UNIT: Record<string, string> = {
  cache_audio_read_mtok: 'cache_audio_read_mtok',
  cache_read_mtok: 'cache_read_mtok',
  cache_write_mtok: 'cache_write_mtok',
  input_audio_mtok: 'input_audio_mtok',
  input_mtok: 'input_mtok',
  output_audio_mtok: 'output_audio_mtok',
  output_mtok: 'output_mtok',
}

export function getFamily(familyId: string): UnitFamily {
  const family = FAMILIES[familyId]
  if (!family) throw new Error(`Unknown family: ${familyId}`)
  return family
}

export function getUnit(unitId: string): UnitDef {
  const unit = ALL_UNITS[unitId]
  if (!unit) throw new Error(`Unknown unit: ${unitId}`)
  return unit
}
