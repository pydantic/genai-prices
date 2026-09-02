import type { ConditionalPrice, Provider } from './types'

import { utcTimeOfDaySeconds } from './timeOfDay'
import { UnitRegistry, validateUnitEvolution } from './units'

export type DecodedProviderData = Readonly<{
  compatibilityWarnings: string[]
  providers: Provider[]
  registry?: UnitRegistry
}>

type Projection = Readonly<{ supported: boolean; value: unknown }>
type WireExtractor = Record<string, unknown> & {
  api_flavor?: unknown
  mappings: unknown[]
  model_path?: unknown
}
type WireExtractorMapping = Record<string, unknown> & { required?: unknown }

export function decodeProviderData(raw: unknown, compatibilityRegistry: UnitRegistry): DecodedProviderData {
  if (Array.isArray(raw)) return decodeLegacyProviderArray(raw)
  if (isRecord(raw)) return decodeWrappedProviderData(raw, compatibilityRegistry)
  throw invalidData('root must be a wrapped object or provider array')
}

function decodeLegacyProviderArray(raw: unknown[]): DecodedProviderData {
  return { compatibilityWarnings: [], providers: normalizeProviderArray(raw) }
}

function decodeWrappedProviderData(raw: Record<string, unknown>, compatibilityRegistry: UnitRegistry): DecodedProviderData {
  if (!Object.prototype.hasOwnProperty.call(raw, 'units')) throw invalidData('missing units')
  if (!Object.prototype.hasOwnProperty.call(raw, 'providers')) throw invalidData('missing providers')
  if (!Array.isArray(raw.providers)) throw invalidData('providers must be an array')

  const registry = UnitRegistry.fromUntrusted(raw.units)
  validateUnitEvolution(compatibilityRegistry, registry)
  const projector = new ProviderProjector()
  const projectedProviders = raw.providers.map((provider, index) => projector.projectProvider(provider, index))
  return {
    compatibilityWarnings: projector.warnings,
    providers: normalizeProviderArray(projectedProviders),
    registry,
  }
}

class ProviderProjector {
  readonly warnings: string[] = []

  projectProvider(raw: unknown, providerIndex: number): unknown {
    if (!isRecord(raw)) return raw
    const provider = { ...raw }
    const context = providerContext(provider, providerIndex)

    for (const field of ['model_match', 'provider_match'] as const) {
      if (field in provider) {
        const path = `providers[${String(providerIndex)}].${field}`
        const projected = this.projectMatch(provider[field], path)
        if (projected.supported) provider[field] = projected.value
        else {
          this.warn('match', path, context)
          Reflect.deleteProperty(provider, field)
        }
      }
    }

    if (Array.isArray(provider.extractors)) {
      const extractors: unknown[] = []
      for (const [index, extractor] of provider.extractors.entries()) {
        const projected = this.projectExtractor(extractor, `providers[${String(providerIndex)}].extractors[${String(index)}]`, context)
        if (projected !== undefined) extractors.push(projected)
      }
      provider.extractors = extractors
    }

    if (Array.isArray(provider.models)) {
      const models: unknown[] = []
      for (const [index, model] of provider.models.entries()) {
        const projected = this.projectModel(model, providerIndex, index, context)
        if (projected !== undefined) models.push(projected)
      }
      provider.models = models
    }
    return provider
  }

  private projectExtractor(raw: unknown, path: string, context: string): unknown {
    if (!isRecord(raw)) return raw
    const extractor = { ...raw }
    if ('type' in extractor || (!('root' in extractor) && !('mappings' in extractor))) {
      this.warn('extractor', path, context)
      return undefined
    }
    if (!('root' in extractor)) throw invalidData(`${path}.root is required`)
    if (!('mappings' in extractor)) throw invalidData(`${path}.mappings is required`)

    for (const field of ['root', 'model_path'] as const) {
      if (field in extractor) {
        const fieldPath = `${path}.${field}`
        const projected = this.projectExtractPath(extractor[field], fieldPath)
        if (!projected.supported) {
          this.warn('extractor', fieldPath, context)
          return undefined
        }
        extractor[field] = projected.value
      }
    }

    if (Array.isArray(extractor.mappings)) {
      const originalMappingCount = extractor.mappings.length
      const mappings: unknown[] = []
      for (const [index, rawMapping] of extractor.mappings.entries()) {
        if (!isRecord(rawMapping)) {
          mappings.push(rawMapping)
          continue
        }
        const mappingPath = `${path}.mappings[${String(index)}]`
        const mapping = { ...rawMapping }
        if (!('path' in mapping) && !('dest' in mapping)) {
          this.warn('extractor mapping', mappingPath, context)
          continue
        }
        if ('path' in mapping) {
          const pathPath = `${mappingPath}.path`
          const projected = this.projectExtractPath(mapping.path, pathPath)
          if (!projected.supported) {
            this.warn('extractor mapping', pathPath, context)
            continue
          }
          mapping.path = projected.value
        }
        mappings.push(mapping)
      }
      if (originalMappingCount > 0 && mappings.length === 0) return undefined
      extractor.mappings = mappings
    }
    return extractor
  }

  private projectExtractPath(raw: unknown, path: string): Projection {
    if (typeof raw === 'string') return { supported: true, value: raw }
    if (!Array.isArray(raw)) {
      if (isRecord(raw)) return { supported: false, value: raw }
      throw invalidData(`${path} must be a string or array`)
    }

    const steps: unknown[] = []
    for (const [index, step] of raw.entries()) {
      if (typeof step === 'string') {
        steps.push(step)
        continue
      }
      if (!isRecord(step)) throw invalidData(`${path}[${String(index)}] must be a string or object`)
      if (step.type !== 'array-match') return { supported: false, value: raw }
      const arrayMatch = { ...step }
      if (typeof arrayMatch.field !== 'string') throw invalidData(`${path}[${String(index)}].field must be a string`)
      if (!('match' in arrayMatch)) throw invalidData(`${path}[${String(index)}].match is required`)
      const projected = this.projectMatch(arrayMatch.match, `${path}[${String(index)}].match`)
      if (!projected.supported) return { supported: false, value: raw }
      arrayMatch.match = projected.value
      steps.push(arrayMatch)
    }
    return { supported: true, value: steps }
  }

  private projectMatch(raw: unknown, path: string): Projection {
    if (!isRecord(raw)) throw invalidData(`${path} match must be an object`)
    const discriminator = matchDiscriminators.find((key) => key in raw)
    if (discriminator === undefined) return { supported: false, value: raw }
    if ((discriminator === 'or' || discriminator === 'and') && Array.isArray(raw[discriminator])) {
      const children: unknown[] = []
      for (const [index, child] of raw[discriminator].entries()) {
        const projected = this.projectMatch(child, `${path}.${discriminator}[${String(index)}]`)
        if (!projected.supported) return { supported: false, value: raw }
        children.push(projected.value)
      }
      return { supported: true, value: { ...raw, [discriminator]: children } }
    }
    return { supported: true, value: raw }
  }

  private projectModel(raw: unknown, providerIndex: number, modelIndex: number, providerContextValue: string): unknown {
    if (!isRecord(raw)) return raw
    const model = { ...raw }
    const path = `providers[${String(providerIndex)}].models[${String(modelIndex)}]`
    const context = `${providerContextValue}, ${modelContext(model, modelIndex)}`
    if ('match' in model) {
      const projected = this.projectMatch(model.match, `${path}.match`)
      if (!projected.supported) {
        this.warn('match', `${path}.match`, context)
        return undefined
      }
      model.match = projected.value
    }
    if ('prices' in model) {
      const rawPrices = model.prices
      const projectedPrices = this.projectPrices(rawPrices, `${path}.prices`, context)
      if (
        isRecord(rawPrices) &&
        Object.keys(rawPrices).length > 0 &&
        isRecord(projectedPrices) &&
        Object.keys(projectedPrices).length === 0
      ) {
        return undefined
      }
      if (Array.isArray(rawPrices) && rawPrices.length > 0 && Array.isArray(projectedPrices) && projectedPrices.length === 0) {
        return undefined
      }
      model.prices = projectedPrices
    }
    return model
  }

  private projectPriceMap(raw: Record<string, unknown>, path: string, context: string): Record<string, unknown> {
    const prices: Record<string, unknown> = {}
    for (const [priceKey, value] of Object.entries(raw)) {
      if (isRecord(value) && !('base' in value) && !('tiers' in value)) {
        this.warn('price', `${path}.${priceKey}`, context)
      } else prices[priceKey] = value
    }
    return prices
  }

  private projectPrices(raw: unknown, path: string, context: string): unknown {
    if (isRecord(raw)) return this.projectPriceMap(raw, path, context)
    if (!Array.isArray(raw)) return raw

    const prices: unknown[] = []
    for (const [index, rawPrice] of raw.entries()) {
      if (!isRecord(rawPrice)) {
        prices.push(rawPrice)
        continue
      }
      const pricePath = `${path}[${String(index)}]`
      if (!('prices' in rawPrice)) {
        this.warn('price', pricePath, context)
        continue
      }
      const conditionalPrice = { ...rawPrice }
      if ('constraint' in conditionalPrice) {
        const projected = projectConstraint(conditionalPrice.constraint)
        if (!projected.supported) {
          this.warn('constraint', `${pricePath}.constraint`, context)
          continue
        }
        conditionalPrice.constraint = projected.value
      }
      if (isRecord(conditionalPrice.prices)) {
        const rawPriceCount = Object.keys(conditionalPrice.prices).length
        const projectedPrices = this.projectPriceMap(conditionalPrice.prices, `${pricePath}.prices`, context)
        if (rawPriceCount > 0 && Object.keys(projectedPrices).length === 0) continue
        conditionalPrice.prices = projectedPrices
      }
      prices.push(conditionalPrice)
    }
    return prices
  }

  private warn(capability: string, path: string, context: string): void {
    this.warnings.push(`Unsupported ${capability} variant at ${path} for ${context}; upgrade genai-prices for full support`)
  }
}

const matchDiscriminators = ['or', 'and', 'equals', 'starts_with', 'ends_with', 'contains', 'regex'] as const

function hasAny(record: Record<string, unknown>, keys: readonly string[]): boolean {
  return keys.some((key) => key in record)
}

function invalidData(message: string): Error {
  return new Error(`genai-prices: invalid data: ${message}`)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function modelContext(model: Record<string, unknown>, index: number): string {
  return typeof model.id === 'string' ? `model '${model.id}'` : `model index ${String(index)}`
}

function normalizeConditionalPrice(raw: unknown, providerId: string, modelId: string, path: string): ConditionalPrice {
  if (!isRecord(raw)) throw invalidData(`${path} must be an object for provider '${providerId}' model '${modelId}'`)
  if (!isRecord(raw.prices)) {
    throw invalidData(`${path}.prices must be an object for provider '${providerId}' model '${modelId}'`)
  }
  const constraint = raw.constraint
  const prices = raw.prices as ConditionalPrice['prices']
  if (constraint === undefined) return { prices }
  if (!isRecord(constraint)) throw invalidConstraintError(constraint, providerId, modelId, path)
  if (constraint.type !== undefined) {
    if (
      (constraint.type === 'start_date' && hasExactKeys(constraint, ['start_date', 'type']) && isValidStartDate(constraint.start_date)) ||
      (constraint.type === 'time_of_date' &&
        hasExactKeys(constraint, ['end_time', 'start_time', 'type']) &&
        isValidTimeOfDay(constraint.start_time) &&
        isValidTimeOfDay(constraint.end_time))
    ) {
      return raw as unknown as ConditionalPrice
    }
    throw invalidConstraintError(constraint, providerId, modelId, path)
  }
  if (hasExactKeys(constraint, ['start_date']) && isValidStartDate(constraint.start_date)) {
    return { constraint: { start_date: constraint.start_date, type: 'start_date' }, prices }
  }
  if (
    hasExactKeys(constraint, ['end_time', 'start_time']) &&
    isValidTimeOfDay(constraint.start_time) &&
    isValidTimeOfDay(constraint.end_time)
  ) {
    return {
      constraint: { end_time: constraint.end_time, start_time: constraint.start_time, type: 'time_of_date' },
      prices,
    }
  }
  throw invalidConstraintError(constraint, providerId, modelId, path)
}

function normalizeExtractor(raw: unknown, path: string): unknown {
  if (!isRecord(raw)) throw invalidData(`${path} must be an object`)
  if (!Array.isArray(raw.mappings)) throw invalidData(`${path}.mappings must be an array`)
  const extractor: WireExtractor = { ...raw, mappings: raw.mappings }
  return {
    ...extractor,
    api_flavor: extractor.api_flavor ?? 'default',
    mappings: extractor.mappings.map((mapping, index) => {
      if (!isRecord(mapping)) throw invalidData(`${path}.mappings[${String(index)}] must be an object`)
      if (!('path' in mapping) || !('dest' in mapping)) {
        throw invalidData(`${path}.mappings[${String(index)}] must include path and dest`)
      }
      const wireMapping: WireExtractorMapping = mapping
      return { ...wireMapping, required: wireMapping.required ?? true }
    }),
    model_path: extractor.model_path ?? 'model',
  }
}

function normalizeModel(raw: unknown, providerId: string, providerIndex: number, modelIndex: number): unknown {
  const path = `providers[${String(providerIndex)}].models[${String(modelIndex)}]`
  if (!isRecord(raw)) throw invalidData(`${path} must be an object`)
  if (!('match' in raw)) throw invalidData(`${path}.match is required`)
  if (!isRecord(raw.prices) && !Array.isArray(raw.prices)) {
    throw invalidData(`${path}.prices must be an object or array`)
  }
  const modelId = typeof raw.id === 'string' ? raw.id : String(modelIndex)
  return {
    ...raw,
    prices: Array.isArray(raw.prices)
      ? raw.prices.map((price, priceIndex) =>
          normalizeConditionalPrice(price, providerId, modelId, `${path}.prices[${String(priceIndex)}]`)
        )
      : raw.prices,
  }
}

function normalizeProviderArray(raw: unknown[]): Provider[] {
  return raw.map((rawProvider, providerIndex) => {
    const path = `providers[${String(providerIndex)}]`
    if (!isRecord(rawProvider)) throw invalidData(`${path} must be an object`)
    if (!Array.isArray(rawProvider.models)) throw invalidData(`${path}.models must be an array`)
    const providerId = typeof rawProvider.id === 'string' ? rawProvider.id : String(providerIndex)
    if (rawProvider.extractors !== undefined && !Array.isArray(rawProvider.extractors)) {
      throw invalidData(`${path}.extractors must be an array`)
    }
    return {
      ...rawProvider,
      ...(rawProvider.extractors === undefined
        ? {}
        : {
            extractors: rawProvider.extractors.map((extractor, index) =>
              normalizeExtractor(extractor, `${path}.extractors[${String(index)}]`)
            ),
          }),
      models: rawProvider.models.map((model, index) => normalizeModel(model, providerId, providerIndex, index)),
    } as unknown as Provider
  })
}

function projectConstraint(raw: unknown): Projection {
  if (!isRecord(raw)) return { supported: true, value: raw }
  if ('type' in raw) {
    if (raw.type === 'start_date') {
      if (!('start_date' in raw)) return { supported: true, value: raw }
      if (hasAny(raw, ['end_time', 'start_time'])) return { supported: true, value: raw }
      return { supported: true, value: { start_date: raw.start_date, type: raw.type } }
    }
    if (raw.type === 'time_of_date') {
      if (!('start_time' in raw) || !('end_time' in raw)) return { supported: true, value: raw }
      if ('start_date' in raw) return { supported: true, value: raw }
      return { supported: true, value: { end_time: raw.end_time, start_time: raw.start_time, type: raw.type } }
    }
    return { supported: false, value: raw }
  }

  const hasStartDate = 'start_date' in raw
  const hasTime = hasAny(raw, ['start_time', 'end_time'])
  if (hasStartDate && hasTime) return { supported: true, value: raw }
  if (hasStartDate) return { supported: true, value: { start_date: raw.start_date } }
  if (hasTime) {
    if (!('start_time' in raw) || !('end_time' in raw)) return { supported: true, value: raw }
    return { supported: true, value: { end_time: raw.end_time, start_time: raw.start_time } }
  }
  return { supported: false, value: raw }
}

function providerContext(provider: Record<string, unknown>, index: number): string {
  return typeof provider.id === 'string' ? `provider '${provider.id}'` : `provider index ${String(index)}`
}

function invalidConstraintError(constraint: unknown, providerId: string, modelId: string, path: string): Error {
  return invalidData(
    `${path} expected a start-date or time-of-day price constraint for provider '${providerId}' model '${modelId}', got: ${JSON.stringify(constraint)}`
  )
}

function isValidStartDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.getUTCFullYear() >= 1 && parsed.toISOString().startsWith(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  const actual = Object.keys(value)
  return actual.length === keys.length && actual.every((key) => keys.includes(key))
}

function isValidTimeOfDay(value: unknown): value is string {
  if (typeof value !== 'string') return false
  try {
    utcTimeOfDaySeconds(value)
    return true
  } catch {
    return false
  }
}
