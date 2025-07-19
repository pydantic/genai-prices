import type { Provider, ModelInfo, ModelPrice, TieredPrices, ConditionalPrice, PriceDataStorage } from './types.js'

const DEFAULT_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/data.json'
const DEFAULT_TTL_MS = 60 * 60 * 1000 // 1 hour
const OUTDATED_THRESHOLD_MS = 24 * 60 * 60 * 1000 // 1 day
const BACKGROUND_REFRESH_MS = 30 * 60 * 1000 // 30 minutes

function mapTieredPrices(json: any): TieredPrices {
  return {
    base: json.base,
    tiers: Array.isArray(json.tiers) ? json.tiers.map((t: any) => ({ start: t.start, price: t.price })) : [],
  }
}

function mapModelPrice(json: any): ModelPrice {
  return {
    inputMtok:
      typeof json.input_mtok === 'object' && json.input_mtok !== null
        ? mapTieredPrices(json.input_mtok)
        : json.input_mtok,
    cacheWriteMtok:
      typeof json.cache_write_mtok === 'object' && json.cache_write_mtok !== null
        ? mapTieredPrices(json.cache_write_mtok)
        : json.cache_write_mtok,
    cacheReadMtok:
      typeof json.cache_read_mtok === 'object' && json.cache_read_mtok !== null
        ? mapTieredPrices(json.cache_read_mtok)
        : json.cache_read_mtok,
    outputMtok:
      typeof json.output_mtok === 'object' && json.output_mtok !== null
        ? mapTieredPrices(json.output_mtok)
        : json.output_mtok,
    inputAudioMtok:
      typeof json.input_audio_mtok === 'object' && json.input_audio_mtok !== null
        ? mapTieredPrices(json.input_audio_mtok)
        : json.input_audio_mtok,
    cacheAudioReadMtok:
      typeof json.cache_audio_read_mtok === 'object' && json.cache_audio_read_mtok !== null
        ? mapTieredPrices(json.cache_audio_read_mtok)
        : json.cache_audio_read_mtok,
    outputAudioMtok:
      typeof json.output_audio_mtok === 'object' && json.output_audio_mtok !== null
        ? mapTieredPrices(json.output_audio_mtok)
        : json.output_audio_mtok,
    requestsKcount: json.requests_kcount,
  }
}

function mapConditionalPrice(json: any): ConditionalPrice {
  return {
    constraint: json.constraint,
    prices: mapModelPrice(json.prices),
  }
}

function mapModelInfo(json: any): ModelInfo {
  return {
    id: json.id,
    match: json.match,
    name: json.name,
    description: json.description,
    contextWindow: json.context_window,
    priceComments: json.price_comments,
    prices: Array.isArray(json.prices) ? json.prices.map(mapConditionalPrice) : mapModelPrice(json.prices),
  }
}

function mapProvider(json: any): Provider {
  return {
    id: json.id,
    name: json.name,
    apiPattern: json.api_pattern,
    pricingUrls: json.pricing_urls,
    description: json.description,
    priceComments: json.price_comments,
    modelMatch: json.model_match,
    models: Array.isArray(json.models) ? json.models.map(mapModelInfo) : [],
  }
}

// In-memory storage
let inMemoryData: string | null = null
let inMemoryLastModified: number | null = null
const inMemoryStorage: PriceDataStorage = {
  get: async (): Promise<string | null> => inMemoryData,
  set: async (data: string) => {
    inMemoryData = data
    inMemoryLastModified = Date.now()
  },
  getLastModified: async (): Promise<number | null> => inMemoryLastModified,
}

let storageBackend: PriceDataStorage = inMemoryStorage
let asyncProviders: Provider[] | null = null
let asyncLastLoaded: number = 0
let asyncFetchPromise: Promise<Provider[]> | null = null
let autoUpdate: boolean = false
let remoteUrl: string = DEFAULT_URL
let ttlMs: number = DEFAULT_TTL_MS

export function setStorageBackend(storage: PriceDataStorage) {
  storageBackend = storage
}

async function loadDataAsync(): Promise<Provider[]> {
  const raw = await storageBackend.get()
  if (!raw) throw new Error('No data found in storage backend')
  const data = JSON.parse(raw)
  return Array.isArray(data) ? data.map(mapProvider) : []
}

async function saveDataAsync(data: string) {
  await storageBackend.set(data)
}

export async function fetchRemoteData(): Promise<Provider[]> {
  const res = await fetch(remoteUrl, { cache: 'no-store' })
  if (!res.ok) throw new Error(`Failed to fetch data: ${res.statusText}`)
  const data = await res.text()
  await saveDataAsync(data)
  const parsed = JSON.parse(data)
  return Array.isArray(parsed) ? parsed.map(mapProvider) : []
}

export async function getProvidersAsync(): Promise<Provider[]> {
  const now = Date.now()
  if (asyncProviders && now - asyncLastLoaded < ttlMs) {
    if (now - asyncLastLoaded > BACKGROUND_REFRESH_MS && !asyncFetchPromise) {
      asyncFetchPromise = (async () => {
        try {
          asyncProviders = await fetchRemoteData()
          asyncLastLoaded = Date.now()
          return asyncProviders
        } catch (e) {
          return asyncProviders!
        } finally {
          asyncFetchPromise = null
        }
      })()
    }
    return asyncProviders
  }
  if (asyncFetchPromise) {
    return asyncFetchPromise
  }
  asyncFetchPromise = (async () => {
    try {
      asyncProviders = await fetchRemoteData()
      asyncLastLoaded = Date.now()
      return asyncProviders
    } catch (e) {
      asyncProviders = await loadDataAsync()
      asyncLastLoaded = Date.now()
      return asyncProviders
    } finally {
      asyncFetchPromise = null
    }
  })()
  return asyncFetchPromise
}

export function enableAutoUpdate(options?: { url?: string; ttlMs?: number; storage?: PriceDataStorage }) {
  autoUpdate = true
  if (options?.url) remoteUrl = options.url
  if (options?.ttlMs) ttlMs = options.ttlMs
  if (options?.storage) setStorageBackend(options.storage)
}

export async function isLocalDataOutdated(): Promise<boolean> {
  if (!storageBackend.getLastModified) return false
  const ts = await storageBackend.getLastModified()
  if (!ts) return true
  return Date.now() - ts > OUTDATED_THRESHOLD_MS
}

export function prefetchAsync(): void {
  if (!asyncFetchPromise) {
    asyncFetchPromise = getProvidersAsync()
  }
}
