export interface Usage {
  inputTokens?: number
  cacheWriteTokens?: number
  cacheReadTokens?: number
  outputTokens?: number
  inputAudioTokens?: number
  cacheAudioReadTokens?: number
  outputAudioTokens?: number
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
  inputMtok?: number | TieredPrices
  cacheWriteMtok?: number | TieredPrices
  cacheReadMtok?: number | TieredPrices
  outputMtok?: number | TieredPrices
  inputAudioMtok?: number | TieredPrices
  cacheAudioReadMtok?: number | TieredPrices
  outputAudioMtok?: number | TieredPrices
  requestsKcount?: number
}

export interface ConditionalPrice {
  constraint?: StartDateConstraint | TimeOfDateConstraint
  prices: ModelPrice
}

export interface StartDateConstraint {
  startDate: string // ISO date string
  type: 'start_date'
}

export interface TimeOfDateConstraint {
  startTime: string // HH:MM:SS
  endTime: string // HH:MM:SS
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
  contextWindow?: number
  priceComments?: string
  prices: ModelPrice | ConditionalPrice[]
}

export interface Provider {
  id: string
  name: string
  apiPattern: string
  pricingUrls?: string[]
  description?: string
  priceComments?: string
  modelMatch?: MatchLogic
  models: ModelInfo[]
}

export interface PriceCalculation {
  price: number
  provider: Provider
  model: ModelInfo
  modelPrice: ModelPrice
  autoUpdateTimestamp?: string
}

export type PriceDataStorage = {
  get: () => Promise<string | null>
  set: (data: string) => Promise<void>
  getLastModified?: () => Promise<number | null>
}
