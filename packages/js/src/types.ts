export interface Usage {
  input_tokens?: number
  cache_write_tokens?: number
  cache_read_tokens?: number
  output_tokens?: number
  input_audio_tokens?: number
  cache_audio_read_tokens?: number
  output_audio_tokens?: number
  requests?: number
}

export interface Tier {
  start: number
  price: number
}

export interface TieredPrices {
  base: number
  tiers: Tier[]
}

export interface ModelPrice {
  input_mtok?: number | TieredPrices
  cache_write_mtok?: number | TieredPrices
  cache_read_mtok?: number | TieredPrices
  output_mtok?: number | TieredPrices
  input_audio_mtok?: number | TieredPrices
  cache_audio_read_mtok?: number | TieredPrices
  output_audio_mtok?: number | TieredPrices
  requests_kcount?: number
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
  start_time: string // HH:MM:SS
  end_time: string // HH:MM:SS
  type: 'time_of_date'
}

export type MatchLogic =
  | { starts_with: string }
  | { ends_with: string }
  | { contains: string }
  | { equals: string }
  | { regex: string }
  | { or: MatchLogic[] }
  | { and: MatchLogic[] }

export interface ModelInfo {
  id: string
  match: MatchLogic
  name?: string
  description?: string
  context_window?: number
  price_comments?: string
  prices: ModelPrice | ConditionalPrice[]
}

export interface Provider {
  id: string
  name: string
  api_pattern: string
  pricing_urls?: string[]
  description?: string
  price_comments?: string
  model_match?: MatchLogic
  models: ModelInfo[]
}

export interface PriceCalculation {
  price: number
  provider: Provider
  model: ModelInfo
  model_price: ModelPrice
  auto_update_timestamp?: string
}

export type PriceCalculationResult = PriceCalculation | null

export type PriceDataStorage = {
  get: () => Promise<string | null>
  set: (data: string) => Promise<void>
  get_last_modified?: () => Promise<number | null>
}
