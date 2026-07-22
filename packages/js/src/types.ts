export type Usage = Record<string, number | undefined>

export interface Tier {
  price: number
  start: number
}

export class TieredPrices {
  base: number
  tiers: Tier[]

  constructor(data: { base: number; tiers: Tier[] }) {
    this.base = data.base
    // Ensure tiers are sorted in ascending order by start threshold
    this.tiers = [...data.tiers].sort((a, b) => a.start - b.start)
  }
}

export type ModelPrice = Record<string, number | TieredPrices | undefined>

export interface ConditionalPrice {
  constraint?: StartDateConstraint | TimeOfDateConstraint
  prices: ModelPrice
}

export interface StartDateConstraint {
  start_date: string // ISO date string
  type: 'start_date'
}

export interface TimeOfDateConstraint {
  end_time: string // HH:MM:SS
  start_time: string // HH:MM:SS
  type: 'time_of_date'
}

export type MatchLogic =
  | { and: MatchLogic[] }
  | { contains: string }
  | { ends_with: string }
  | { equals: string }
  | { or: MatchLogic[] }
  | { regex: string }
  | { starts_with: string }

export interface ArrayMatch {
  field: string
  match: MatchLogic
  type: 'array-match'
}

export type ExtractPath = (ArrayMatch | string)[] | string

export interface UsageExtractorMapping {
  dest: string
  path: ExtractPath
  required: boolean
}

export interface RawUnitData {
  dimension_requirements?: Record<string, Record<string, string>>
  dimensions: Record<string, string>
  per: number
  price_key?: string
}

export type RawUnitsDict = Record<string, RawUnitData>

export interface UnitDef {
  readonly dimensionRequirements: Readonly<Record<string, Readonly<Record<string, string>>>>
  readonly dimensions: Readonly<Record<string, string>>
  readonly per: number
  readonly priceKey: string
  readonly usageKey: string
}

export interface UsageExtractor {
  api_flavor: string
  mappings: UsageExtractorMapping[]
  model_path: ExtractPath
  root: ExtractPath
}

export interface ModelInfo {
  context_window?: number
  deprecated?: boolean
  description?: string
  id: string
  match: MatchLogic
  name?: string
  price_comments?: string
  prices: ConditionalPrice[] | ModelPrice
}

export interface Provider {
  api_pattern: string
  description?: string
  extractors?: UsageExtractor[]
  fallback_model_providers?: string[]
  id: string
  model_match?: MatchLogic
  models: ModelInfo[]
  name: string
  price_comments?: string
  pricing_urls?: string[]
  provider_match?: MatchLogic
}

export interface ModelPriceCalculationResult {
  input_price: number
  output_price: number
  total_price: number
}

export interface PriceCalculation {
  auto_update_timestamp?: string
  input_price: number
  model: ModelInfo
  model_price: ModelPrice
  output_price: number
  provider: Provider
  total_price: number
}

export type PriceCalculationResult = null | PriceCalculation

export interface PriceDataStorage {
  get: () => Promise<null | string>
  get_last_modified?: () => Promise<null | number>
  set: (data: string) => Promise<void>
}

export type ProviderDataValue = null | Provider[]
export type ProviderDataPayload = Promise<ProviderDataValue> | ProviderDataValue

export interface StorageFactoryParams {
  onCalc: (cb: () => void) => void
  remoteDataUrl: string
  setProviderData: (data: ProviderDataPayload) => void
}

export interface ProviderFindOptions {
  modelId?: string
  providerApiUrl?: string
  providerId?: string
}

export interface PriceOptions {
  provider?: Provider
  providerApiUrl?: string
  providerId?: string
  timestamp?: Date
}
