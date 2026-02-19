export interface Usage {
  cache_audio_read_tokens?: number
  cache_read_tokens?: number
  cache_write_tokens?: number
  input_audio_tokens?: number
  input_tokens?: number
  output_audio_tokens?: number
  output_tokens?: number
  tool_use?: Record<string, number>
}

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

export interface ModelPrice {
  cache_audio_read_mtok?: number | TieredPrices
  cache_read_mtok?: number | TieredPrices
  cache_write_mtok?: number | TieredPrices
  input_audio_mtok?: number | TieredPrices
  input_mtok?: number | TieredPrices
  output_audio_mtok?: number | TieredPrices
  output_mtok?: number | TieredPrices
  requests_kcount?: number
  tool_use_kcount?: Record<string, number>
}

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

export interface CountArrayItems {
  field: string
  match: MatchLogic
  path: ExtractPath
}

export interface UsageExtractorMapping {
  count?: CountArrayItems
  dest: string
  path?: ExtractPath
  required: boolean
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

type OptionalProviders = null | Provider[]
export type ProviderDataPayload = OptionalProviders | Promise<OptionalProviders>

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
