import type {
  PriceCalculationResult,
  PriceOptions,
  Provider,
  ProviderDataPayload,
  ProviderFindOptions,
  StorageFactoryParams,
  Usage,
} from './types'

import { data as embeddedData } from './data'
import { calcPrice as calcPriceInternal, getActiveModelPrice, matchModelWithFallback, matchProvider } from './engine'
import { type DecodedProviderData, decodeProviderData } from './providerData'
import { getActiveRegistry, setActiveRegistry, validateUnitEvolution } from './units'
import { validateUsageValue } from './usage'
import { warnUnsupportedExtractorDestinations } from './validation'

export const REMOTE_DATA_JSON_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/new_data/v3/data.json'

let providerData: Provider[] = embeddedData
let providerDataPromise: Promise<Provider[]> = Promise.resolve(embeddedData)
let autoUpdateCb: (() => void) | null = null

function setProviderData(data: ProviderDataPayload): void {
  // null means the update failed; keep existing data
  if (data === null) {
    return
  }
  if (typeof data === 'object' && 'then' in data) {
    const updatePromise = data
      .then((data) => {
        if (data === null || providerDataPromise !== updatePromise) {
          return providerData
        }
        const decoded = decodeProviderData(data, getActiveRegistry())
        const providers = activateProviderData(decoded)
        warnCompatibility(decoded.compatibilityWarnings)
        return providers
      })
      .catch((error: unknown) => {
        if (providerDataPromise === updatePromise) {
          providerDataPromise = Promise.resolve(providerData)
        }
        throw error
      })
    // Updates may be fire-and-forget. Observe failures without changing the
    // original promise returned by waitForUpdate() to callers that do await it.
    // A rejected update never replaces the active data, so warn to make the
    // resulting staleness observable to fire-and-forget consumers.
    updatePromise.catch((error: unknown) => {
      console.warn(
        `genai-prices: provider data update rejected; keeping previously active data: ${error instanceof Error ? error.message : String(error)}`
      )
    })
    providerDataPromise = updatePromise
  } else {
    const decoded = decodeProviderData(data, getActiveRegistry())
    const providers = activateProviderData(decoded)
    warnCompatibility(decoded.compatibilityWarnings)
    providerDataPromise = Promise.resolve(providers)
  }
}

function activateProviderData(decoded: DecodedProviderData): Provider[] {
  const { providers, registry } = decoded
  if (registry === undefined) {
    warnUnsupportedExtractorDestinations(providers, getActiveRegistry())
    providerData = providers
    return providers
  }

  validateUnitEvolution(getActiveRegistry(), registry)
  warnUnsupportedExtractorDestinations(providers, registry)
  setActiveRegistry(registry)
  providerData = providers
  return providers
}

function warnCompatibility(warnings: readonly string[]): void {
  for (const warning of warnings) console.warn(warning)
}

function onCalc(cb: () => void) {
  autoUpdateCb = cb
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function updatePrices(factory: (options: StorageFactoryParams) => any): void {
  factory({
    onCalc,
    remoteDataUrl: REMOTE_DATA_JSON_URL,
    setProviderData,
  })
}

export function waitForUpdate() {
  return providerDataPromise
}

export function calcPrice(usage: Usage, modelId: string, options?: PriceOptions): PriceCalculationResult {
  autoUpdateCb?.()
  let lowerModelId = modelId.toLowerCase().trim()
  let providerId = options?.providerId

  // Handle litellm provider_id by extracting actual provider from model name prefix
  if (providerId && providerId.toLowerCase() === 'litellm' && lowerModelId.includes('/')) {
    const slashIndex = lowerModelId.indexOf('/')
    const actualProviderId = lowerModelId.slice(0, slashIndex)
    const actualModelId = lowerModelId.slice(slashIndex + 1)
    // Only use the extracted provider if it exists
    if (actualProviderId && actualModelId && matchProvider(providerData, { providerId: actualProviderId })) {
      providerId = actualProviderId
      lowerModelId = actualModelId
    }
  }

  // Caller-supplied providers bypass activation, so normalize them here to
  // give them the same constraint handling as downloaded/bundled data.
  const provider = options?.provider
    ? decodeProviderData([options.provider], getActiveRegistry()).providers[0]
    : matchProvider(providerData, { modelId: lowerModelId, providerApiUrl: options?.providerApiUrl, providerId })
  if (!provider) return null
  const model = matchModelWithFallback(provider, lowerModelId, providerData)
  if (!model) return null
  const timestamp = options?.timestamp ?? new Date()
  const modelPrice = getActiveModelPrice(model, timestamp)
  let billedUsage = usage
  if (provider.id === 'groq' && (model.id === 'whisper-large-v3' || model.id === 'whisper-large-v3-turbo')) {
    billedUsage = { ...usage }
    const audioSeconds = billedUsage.audio_seconds
    const inputAudioSeconds = billedUsage.input_audio_seconds
    if (audioSeconds !== undefined) validateUsageValue('audio_seconds', audioSeconds)
    if (inputAudioSeconds !== undefined) validateUsageValue('input_audio_seconds', inputAudioSeconds)
    const reportedSeconds = audioSeconds === 0 ? inputAudioSeconds : (audioSeconds ?? inputAudioSeconds)
    if (reportedSeconds !== undefined) {
      const billedSeconds = reportedSeconds > 0 ? Math.max(reportedSeconds, 10) : 0
      billedUsage.audio_seconds = billedSeconds
      billedUsage.input_audio_seconds = billedSeconds
    }
  }
  const priceResult = calcPriceInternal(billedUsage, modelPrice)
  return {
    auto_update_timestamp: undefined,
    model,
    model_price: modelPrice,
    provider,
    ...priceResult,
  }
}

export function findProvider(options: ProviderFindOptions): Provider | undefined {
  autoUpdateCb?.()
  return matchProvider(providerData, options)
}
