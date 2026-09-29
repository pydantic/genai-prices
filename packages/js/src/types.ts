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
  end_time: string // HH:MM:SS[.fraction](Z|±HH:MM)
  start_time: string // HH:MM:SS[.fraction](Z|±HH:MM)
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
  dimensions: Record<string, string>
  per: number
  price_key?: string
}

export type RawUnitsDict = Record<string, RawUnitData>

export interface UnitDef {
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

/** How a model exposes reasoning (also called thinking), in the provider's own terms. */
export interface ReasoningCapabilities {
  /** Whether the provider can decide per request whether and how much to reason. */
  adaptive?: boolean
  /** Whether reasoning cannot be turned off. */
  always_on?: boolean
  /** Whether reasoning from earlier turns can be carried into later requests. */
  cross_turn_context?: boolean
  /** Accepted effort values, in the provider's vocabulary, e.g. `[none, low, medium, high, xhigh]`. */
  effort_levels?: string[]
  /** Accepted reasoning modes, e.g. `[standard, pro]`. */
  modes?: string[]
  /** Accepted values for a reasoning summary in the response, e.g. `[auto, concise, detailed]`. */
  summary_levels?: string[]
  /** Whether the model can reason at all. `false` means the other fields do not apply. */
  supported?: boolean
  /** Whether the request may set an explicit reasoning token budget. */
  token_budget?: boolean
}

/** Which sampling parameters the provider accepts for this model. */
export interface SamplingCapabilities {
  seed?: boolean
  temperature?: boolean
  top_k?: boolean
  top_p?: boolean
}

/** Request parameters a model accepts. Facts about the provider's API, not any client's settings. */
export interface ModelCapabilities {
  /** Largest number of output tokens a single request may produce. */
  max_output_tokens?: number
  /** Reasoning support and the knobs that control it. */
  reasoning?: ReasoningCapabilities
  /** Which sampling parameters are accepted. */
  sampling?: SamplingCapabilities
  /** Accepted service tier values, e.g. `[auto, default, flex, priority]`. */
  service_tiers?: string[]
  /** Accepted output verbosity values, e.g. `[low, medium, high]`. */
  verbosity_levels?: string[]
}

export interface ModelInfo {
  /** Request parameters the model accepts: reasoning knobs, sampling, service tiers, output limits. */
  capabilities?: ModelCapabilities
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
