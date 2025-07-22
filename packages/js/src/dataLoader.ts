import type { Provider, PriceDataStorage } from './types.js'
import { data as embeddedData } from './data.js'

const DEFAULT_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/data.json'
const DEFAULT_TTL_MS = 60 * 60 * 1000 // 1 hour
const OUTDATED_THRESHOLD_MS = 24 * 60 * 60 * 1000 // 1 day
const BACKGROUND_REFRESH_MS = 30 * 60 * 1000 // 30 minutes

// Universal environment detection
function detectEnvironment(): 'node' | 'browser' | 'cloudflare' | 'deno' | 'unknown' {
  if (typeof globalThis !== 'undefined' && 'caches' in globalThis && 'default' in globalThis.caches) {
    return 'cloudflare'
  }
  if (typeof (globalThis as any).Deno !== 'undefined') {
    return 'deno'
  }
  if (typeof process !== 'undefined' && process.versions && process.versions.node) {
    return 'node'
  }
  if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    return 'browser'
  }
  return 'unknown'
}

async function universalFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const env = detectEnvironment()
  if (env === 'node') {
    const { default: nodeFetch } = await import('node-fetch')
    return nodeFetch(url, options as any) as any
  }
  if (typeof fetch !== 'undefined') {
    return fetch(url, options)
  }
  throw new Error(`Fetch not available in environment: ${env}`)
}

// Universal file system access (Node.js only)
async function readLocalFile(path: string): Promise<string | null> {
  const env = detectEnvironment()
  if (env === 'node') {
    try {
      const fs = await import('fs')
      const pathModule = await import('path')
      try {
        const dataPath = pathModule.join(__dirname, 'data.json')
        return fs.readFileSync(dataPath, 'utf-8')
      } catch (error) {
        try {
          const monorepoPath = pathModule.join(__dirname, '../../prices/data.json')
          return fs.readFileSync(monorepoPath, 'utf-8')
        } catch (error2) {
          return null
        }
      }
    } catch (error) {
      return null
    }
  }
  return null
}

// Universal storage implementation
let inMemoryData: string | null = null
let inMemoryLastModified: number | null = null

const universalStorage: PriceDataStorage = {
  get: async (): Promise<string | null> => inMemoryData,
  set: async (data: string) => {
    inMemoryData = data
    inMemoryLastModified = Date.now()
  },
  get_last_modified: async (): Promise<number | null> => inMemoryLastModified,
}

let storageBackend: PriceDataStorage = universalStorage
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
  return Array.isArray(data) ? data : []
}

async function saveDataAsync(data: string) {
  await storageBackend.set(data)
}

export async function fetchRemoteData(): Promise<Provider[]> {
  const res = await universalFetch(remoteUrl, { cache: 'no-store' })
  if (!res.ok) throw new Error(`Failed to fetch data: ${res.statusText}`)
  const data = await res.text()
  await saveDataAsync(data)
  const parsed = JSON.parse(data)
  return Array.isArray(parsed) ? parsed : []
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
  if (!storageBackend.get_last_modified) return false
  const ts = await storageBackend.get_last_modified()
  if (!ts) return true
  return Date.now() - ts > OUTDATED_THRESHOLD_MS
}

export function prefetchAsync(): void {
  if (!asyncFetchPromise) {
    asyncFetchPromise = getProvidersAsync()
  }
}

// Universal sync function that works everywhere
export function getProvidersSync(): Provider[] {
  return embeddedData
}

export function getEnvironmentInfo() {
  return {
    environment: detectEnvironment(),
    hasFetch: typeof fetch !== 'undefined',
    hasProcess: typeof process !== 'undefined',
    hasWindow: typeof window !== 'undefined',
  }
}
