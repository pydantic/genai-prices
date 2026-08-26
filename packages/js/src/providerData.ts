import { utcTimeOfDaySeconds } from './timeOfDay'
import {
  ArrayMatch,
  ConditionalPrice,
  ExtractPath,
  MatchLogic,
  ModelInfo,
  ModelPrice,
  Provider,
  Tier,
  TieredPrices,
  UsageExtractor,
  UsageExtractorMapping,
} from './types'

export function parseProviderData(value: unknown): Provider[] {
  if (!Array.isArray(value)) {
    throw invalidProviderData('Expected provider data to be an array')
  }
  return requireDenseArray(value, 'providers').map((provider, index) => parseProvider(provider, `providers[${String(index)}]`))
}

function parseProvider(value: unknown, path: string): Provider {
  const record = requireRecord(value, path)
  const id = requireString(record, 'id', path)
  const modelValues = requireArray(record, 'models', path)
  const models = modelValues.map((model, index) => parseModel(model, `${path}.models[${String(index)}]`, id))
  const description = optionalString(record, 'description', path)
  const extractors = optionalExtractors(record, path)
  const fallbackModelProviders = optionalStringArray(record, 'fallback_model_providers', path)
  const modelMatch = optionalMatchLogic(record, 'model_match', path)
  const priceComments = optionalString(record, 'price_comments', path)
  const pricingUrls = optionalStringArray(record, 'pricing_urls', path)
  const providerMatch = optionalMatchLogic(record, 'provider_match', path)

  return {
    api_pattern: requireString(record, 'api_pattern', path),
    ...(description === undefined ? {} : { description }),
    ...(extractors === undefined ? {} : { extractors }),
    ...(fallbackModelProviders === undefined ? {} : { fallback_model_providers: fallbackModelProviders }),
    id,
    ...(modelMatch === undefined ? {} : { model_match: modelMatch }),
    models,
    name: requireString(record, 'name', path),
    ...(priceComments === undefined ? {} : { price_comments: priceComments }),
    ...(pricingUrls === undefined ? {} : { pricing_urls: pricingUrls }),
    ...(providerMatch === undefined ? {} : { provider_match: providerMatch }),
  }
}

function parseModel(value: unknown, path: string, providerId: string): ModelInfo {
  const record = requireRecord(value, path)
  const id = requireString(record, 'id', path)
  const pricesValue = requireProperty(record, 'prices', path)
  const contextWindow = optionalNumber(record, 'context_window', path)
  const deprecated = optionalBoolean(record, 'deprecated', path)
  const description = optionalString(record, 'description', path)
  const name = optionalString(record, 'name', path)
  const priceComments = optionalString(record, 'price_comments', path)

  return {
    ...(contextWindow === undefined ? {} : { context_window: contextWindow }),
    ...(deprecated === undefined ? {} : { deprecated }),
    ...(description === undefined ? {} : { description }),
    id,
    match: parseMatchLogic(requireProperty(record, 'match', path), `${path}.match`),
    ...(name === undefined ? {} : { name }),
    ...(priceComments === undefined ? {} : { price_comments: priceComments }),
    prices: Array.isArray(pricesValue)
      ? requireDenseArray(pricesValue, `${path}.prices`).map((price, index) =>
          parseConditionalPrice(price, `${path}.prices[${String(index)}]`, providerId, id)
        )
      : parseModelPrice(pricesValue, `${path}.prices`),
  }
}

function parseConditionalPrice(value: unknown, path: string, providerId: string, modelId: string): ConditionalPrice {
  const record = requireRecord(value, path)
  const prices = parseModelPrice(requireProperty(record, 'prices', path), `${path}.prices`)
  const constraint = optionalProperty(record, 'constraint', path)
  if (constraint === undefined) return { prices }

  const normalizedConstraint = parseConstraint(constraint, providerId, modelId)
  return { constraint: normalizedConstraint, prices }
}

function parseConstraint(value: unknown, providerId: string, modelId: string): NonNullable<ConditionalPrice['constraint']> {
  if (!isRecord(value)) {
    throw invalidConstraintError(value, providerId, modelId)
  }
  if (isExactKeys(value, ['start_date', 'type']) && value['type'] === 'start_date' && isValidStartDate(value['start_date'])) {
    return { start_date: value['start_date'], type: 'start_date' }
  }
  if (
    isExactKeys(value, ['end_time', 'start_time', 'type']) &&
    value['type'] === 'time_of_date' &&
    isValidTimeOfDay(value['start_time']) &&
    isValidTimeOfDay(value['end_time'])
  ) {
    return { end_time: value['end_time'], start_time: value['start_time'], type: 'time_of_date' }
  }
  if (isExactKeys(value, ['start_date']) && isValidStartDate(value['start_date'])) {
    return { start_date: value['start_date'], type: 'start_date' }
  }
  if (isExactKeys(value, ['end_time', 'start_time']) && isValidTimeOfDay(value['start_time']) && isValidTimeOfDay(value['end_time'])) {
    return { end_time: value['end_time'], start_time: value['start_time'], type: 'time_of_date' }
  }
  throw invalidConstraintError(value, providerId, modelId)
}

function parseModelPrice(value: unknown, path: string): ModelPrice {
  const record = requireRecord(value, path)
  const prices: ModelPrice = {}
  for (const [key, price] of Object.entries(record)) {
    prices[key] =
      price === undefined
        ? undefined
        : typeof price === 'number'
          ? parsePriceNumber(price, `${path}.${key}`)
          : parseTieredPrices(price, `${path}.${key}`)
  }
  return prices
}

function parseTieredPrices(value: unknown, path: string): TieredPrices {
  const record = requireRecord(value, path)
  const base = parsePriceNumber(requireNumber(record, 'base', path), `${path}.base`)
  const tierValues = requireArray(record, 'tiers', path)
  const tiers: Tier[] = tierValues.map((tier, index) => {
    const tierRecord = requireRecord(tier, `${path}.tiers[${String(index)}]`)
    return {
      price: parsePriceNumber(
        requireNumber(tierRecord, 'price', `${path}.tiers[${String(index)}]`),
        `${path}.tiers[${String(index)}].price`
      ),
      start: parseTierStart(requireNumber(tierRecord, 'start', `${path}.tiers[${String(index)}]`), `${path}.tiers[${String(index)}].start`),
    }
  })
  return new TieredPrices({ base, tiers })
}

function parseMatchLogic(value: unknown, path: string): MatchLogic {
  const record = requireRecord(value, path)
  const keys = Object.keys(record)
  if (keys.length !== 1) throw invalidProviderData(`${path} must contain exactly one match operation`)
  const key = keys[0]
  if (key === undefined) throw invalidProviderData(`${path} must contain a match operation`)
  const operand = record[key]
  if (key === 'and' || key === 'or') {
    if (!Array.isArray(operand)) throw invalidProviderData(`${path}.${key} must be an array`)
    const clauses = requireDenseArray(operand, `${path}.${key}`).map((clause, index) =>
      parseMatchLogic(clause, `${path}.${key}[${String(index)}]`)
    )
    return key === 'and' ? { and: clauses } : { or: clauses }
  }
  if (key === 'contains') {
    if (typeof operand !== 'string') throw invalidProviderData(`${path}.${key} must be a string`)
    return { contains: operand }
  }
  if (key === 'ends_with') {
    if (typeof operand !== 'string') throw invalidProviderData(`${path}.${key} must be a string`)
    return { ends_with: operand }
  }
  if (key === 'equals') {
    if (typeof operand !== 'string') throw invalidProviderData(`${path}.${key} must be a string`)
    return { equals: operand }
  }
  if (key === 'regex') {
    if (typeof operand !== 'string') throw invalidProviderData(`${path}.${key} must be a string`)
    try {
      RegExp(operand)
    } catch {
      throw invalidProviderData(`${path}.${key} must be a valid regular expression`)
    }
    return { regex: operand }
  }
  if (key === 'starts_with') {
    if (typeof operand !== 'string') throw invalidProviderData(`${path}.${key} must be a string`)
    return { starts_with: operand }
  }
  throw invalidProviderData(`${path} has an unknown match operation '${key}'`)
}

function parseExtractors(value: unknown, path: string): UsageExtractor[] {
  if (!Array.isArray(value)) throw invalidProviderData(`${path}.extractors must be an array`)
  return requireDenseArray(value, `${path}.extractors`).map((extractor, index) =>
    parseExtractor(extractor, `${path}.extractors[${String(index)}]`)
  )
}

function parseExtractor(value: unknown, path: string): UsageExtractor {
  const record = requireRecord(value, path)
  const mappings = requireArray(record, 'mappings', path).map((mapping, index) =>
    parseMapping(mapping, `${path}.mappings[${String(index)}]`)
  )
  return {
    api_flavor: requireString(record, 'api_flavor', path),
    mappings,
    model_path: parseExtractPath(requireProperty(record, 'model_path', path), `${path}.model_path`),
    root: parseExtractPath(requireProperty(record, 'root', path), `${path}.root`),
  }
}

function parseMapping(value: unknown, path: string): UsageExtractorMapping {
  const record = requireRecord(value, path)
  return {
    dest: requireString(record, 'dest', path),
    path: parseExtractPath(requireProperty(record, 'path', path), `${path}.path`),
    required: requireBoolean(record, 'required', path),
  }
}

function parseExtractPath(value: unknown, path: string): ExtractPath {
  if (typeof value === 'string') return value
  if (!Array.isArray(value)) throw invalidProviderData(`${path} must be a string or array`)
  return requireDenseArray(value, path).map((step, index) =>
    typeof step === 'string' ? step : parseArrayMatch(step, `${path}[${String(index)}]`)
  )
}

function parseArrayMatch(value: unknown, path: string): ArrayMatch {
  const record = requireRecord(value, path)
  if (!isExactKeys(record, ['field', 'match', 'type']) || record['type'] !== 'array-match') {
    throw invalidProviderData(`${path} must be an array-match object`)
  }
  return {
    field: requireString(record, 'field', path),
    match: parseMatchLogic(requireProperty(record, 'match', path), `${path}.match`),
    type: 'array-match',
  }
}

function optionalExtractors(record: Record<string, unknown>, path: string): undefined | UsageExtractor[] {
  const value = optionalProperty(record, 'extractors', path)
  return value === undefined ? undefined : parseExtractors(value, path)
}

function optionalMatchLogic(record: Record<string, unknown>, key: string, path: string): MatchLogic | undefined {
  const value = optionalProperty(record, key, path)
  return value === undefined ? undefined : parseMatchLogic(value, `${path}.${key}`)
}

function optionalStringArray(record: Record<string, unknown>, key: string, path: string): string[] | undefined {
  const value = optionalProperty(record, key, path)
  if (value === undefined) return undefined
  if (!Array.isArray(value)) {
    throw invalidProviderData(`${path}.${key} must be an array of strings`)
  }
  const items = requireDenseArray(value, `${path}.${key}`)
  if (!items.every((item): item is string => typeof item === 'string')) {
    throw invalidProviderData(`${path}.${key} must be an array of strings`)
  }
  return items
}

function optionalString(record: Record<string, unknown>, key: string, path: string): string | undefined {
  const value = optionalProperty(record, key, path)
  if (value === undefined) return undefined
  if (typeof value !== 'string') throw invalidProviderData(`${path}.${key} must be a string`)
  return value
}

function optionalNumber(record: Record<string, unknown>, key: string, path: string): number | undefined {
  const value = optionalProperty(record, key, path)
  if (value === undefined) return undefined
  if (typeof value !== 'number') throw invalidProviderData(`${path}.${key} must be a number`)
  return value
}

function optionalBoolean(record: Record<string, unknown>, key: string, path: string): boolean | undefined {
  const value = optionalProperty(record, key, path)
  if (value === undefined) return undefined
  if (typeof value !== 'boolean') throw invalidProviderData(`${path}.${key} must be a boolean`)
  return value
}

function requireString(record: Record<string, unknown>, key: string, path: string): string {
  const value = requireProperty(record, key, path)
  if (typeof value !== 'string') throw invalidProviderData(`${path}.${key} must be a string`)
  return value
}

function requireNumber(record: Record<string, unknown>, key: string, path: string): number {
  const value = requireProperty(record, key, path)
  if (typeof value !== 'number') throw invalidProviderData(`${path}.${key} must be a number`)
  return value
}

function requireBoolean(record: Record<string, unknown>, key: string, path: string): boolean {
  const value = requireProperty(record, key, path)
  if (typeof value !== 'boolean') throw invalidProviderData(`${path}.${key} must be a boolean`)
  return value
}

function requireArray(record: Record<string, unknown>, key: string, path: string): unknown[] {
  const value = requireProperty(record, key, path)
  if (!Array.isArray(value)) throw invalidProviderData(`${path}.${key} must be an array`)
  return requireDenseArray(value, `${path}.${key}`)
}

function requireDenseArray(value: unknown[], path: string): unknown[] {
  const values: unknown[] = []
  for (let index = 0; index < value.length; index += 1) {
    if (!(index in value)) throw invalidProviderData(`${path}[${String(index)}] must not be empty`)
    values.push(value[index])
  }
  return values
}

function parsePriceNumber(value: number, path: string): number {
  if (!Number.isFinite(value) || value < 0) {
    throw invalidProviderData(`${path} must be a finite non-negative number`)
  }
  return value
}

function parseTierStart(value: number, path: string): number {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw invalidProviderData(`${path} must be a non-negative safe integer`)
  }
  return value
}

function requireProperty(record: Record<string, unknown>, key: string, path: string): unknown {
  if (!(key in record)) throw invalidProviderData(`${path}.${key} is required`)
  const value = record[key]
  if (value === undefined) throw invalidProviderData(`${path}.${key} must not be undefined`)
  return value
}

function optionalProperty(record: Record<string, unknown>, key: string, path: string): unknown {
  if (!(key in record)) return undefined
  return requireProperty(record, key, path)
}

function requireRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) throw invalidProviderData(`${path} must be an object`)
  return value
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isExactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  const actual = Object.keys(value)
  return actual.length === keys.length && actual.every((key) => keys.includes(key))
}

function isValidStartDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.getUTCFullYear() >= 1 && parsed.toISOString().startsWith(value)
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

function invalidProviderData(message: string): Error {
  return new Error(`Invalid provider data: ${message}`)
}

function invalidConstraintError(constraint: unknown, providerId: string, modelId: string): Error {
  return new Error(
    `Expected a start-date or time-of-day price constraint for provider '${providerId}' model '${modelId}', got: ${JSON.stringify(constraint)}`
  )
}
