import fs from 'fs';
import path from 'path';
import fetch, { type RequestInfo, type RequestInit } from 'node-fetch';
import os from 'os';
import { Provider, ModelInfo, ModelPrice, TieredPrices, ConditionalPrice } from './types.js';

const DEFAULT_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/data.json';
const DEFAULT_TTL_MS = 60 * 60 * 1000; // 1 hour
const OUTDATED_THRESHOLD_MS = 24 * 60 * 60 * 1000; // 1 day

function mapTieredPrices(json: any): TieredPrices {
  return {
    base: json.base,
    tiers: Array.isArray(json.tiers)
      ? json.tiers.map((t: any) => ({ start: t.start, price: t.price }))
      : [],
  };
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
  };
}

function mapConditionalPrice(json: any): ConditionalPrice {
  return {
    constraint: json.constraint,
    prices: mapModelPrice(json.prices),
  };
}

function mapModelInfo(json: any): ModelInfo {
  return {
    id: json.id,
    match: json.match,
    name: json.name,
    description: json.description,
    contextWindow: json.context_window,
    priceComments: json.price_comments,
    prices: Array.isArray(json.prices)
      ? json.prices.map(mapConditionalPrice)
      : mapModelPrice(json.prices),
  };
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
  };
}

function findProjectRoot(): string {
  let dir = process.cwd();
  while (dir !== path.parse(dir).root) {
    if (fs.existsSync(path.join(dir, 'prices', 'data.json'))) {
      return dir;
    }
    dir = path.dirname(dir);
  }
  throw new Error('Could not find project root containing prices/data.json');
}

function getLocalDataPath() {
  const root = findProjectRoot();
  return path.join(root, 'prices', 'data.json');
}

let asyncProviders: Provider[] | null = null;
let asyncLastLoaded = 0;
let asyncFetchPromise: Promise<Provider[]> | null = null;
let autoUpdate = false;
let remoteUrl = DEFAULT_URL;
let ttlMs = DEFAULT_TTL_MS;

function getCachePath() {
  return path.join(os.tmpdir(), 'genai-prices-data.json');
}

async function fetchRemoteData(): Promise<Provider[]> {
  const res = await fetch(remoteUrl as RequestInfo, { cache: 'no-store' } as RequestInit);
  if (!res.ok) throw new Error(`Failed to fetch data: ${res.statusText}`);
  const data = await res.json();
  return Array.isArray(data) ? data.map(mapProvider) : [];
}

function loadLocalData(): Provider[] {
  const localPath = getLocalDataPath();
  if (fs.existsSync(localPath)) {
    const raw = fs.readFileSync(localPath, 'utf-8');
    const data = JSON.parse(raw);
    return Array.isArray(data) ? data.map(mapProvider) : [];
  }
  const cachePath = getCachePath();
  if (fs.existsSync(cachePath)) {
    const raw = fs.readFileSync(cachePath, 'utf-8');
    const data = JSON.parse(raw);
    return Array.isArray(data) ? data.map(mapProvider) : [];
  }
  throw new Error('No local data.json found');
}

export function getProvidersSync(): Provider[] {
  return loadLocalData();
}

export async function getProvidersAsync(): Promise<Provider[]> {
  const now = Date.now();
  if (asyncProviders && now - asyncLastLoaded < ttlMs) {
    return asyncProviders;
  }
  if (asyncFetchPromise) {
    return asyncFetchPromise;
  }
  asyncFetchPromise = (async () => {
    try {
      asyncProviders = await fetchRemoteData();
      asyncLastLoaded = Date.now();
      return asyncProviders;
    } catch (e) {
      asyncProviders = loadLocalData();
      asyncLastLoaded = Date.now();
      return asyncProviders;
    } finally {
      asyncFetchPromise = null;
    }
  })();
  return asyncFetchPromise;
}

export function enableAutoUpdate(options?: { url?: string; ttlMs?: number }) {
  autoUpdate = true;
  if (options?.url) remoteUrl = options.url;
  if (options?.ttlMs) ttlMs = options.ttlMs;
}

export function isLocalDataOutdated(): boolean {
  const localPath = getLocalDataPath();
  if (!fs.existsSync(localPath)) return true;
  const stats = fs.statSync(localPath);
  const age = Date.now() - stats.mtimeMs;
  return age > OUTDATED_THRESHOLD_MS;
}
