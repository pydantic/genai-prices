import type {
  ArrayMatch,
  ConditionalPrice,
  DecodedProviderData,
  ExtractPath,
  MatchLogic,
  ModelInfo,
  ModelPrice,
  Provider,
  RawUnitData,
  RawUnitsDict,
  Tier,
  UsageExtractor,
  UsageExtractorMapping,
} from './types'

import { TieredPrices } from './types'

export function decodeV2Payload(raw: unknown): DecodedProviderData {
  const wrapper = exactObject(raw, ['providers', 'units'], ['providers', 'units'], 'v2 payload')
  const rawProviders = arrayValue(wrapper.providers, 'v2 payload.providers')
  const rawUnits = objectValue(wrapper.units, 'v2 payload.units')

  const units: RawUnitsDict = {}
  for (const [usageKey, rawUnit] of Object.entries(rawUnits)) {
    units[usageKey] = decodeUnit(rawUnit, `v2 payload.units.${usageKey}`)
  }

  return {
    providers: rawProviders.map((provider, index) => decodeProvider(provider, `v2 payload.providers[${index.toString()}]`)),
    units,
  }
}

function decodeUnit(raw: unknown, path: string): RawUnitData {
  const unit = exactObject(raw, ['dimensions', 'per', 'price_key'], ['dimensions', 'per'], path)
  const rawDimensions = objectValue(unit.dimensions, `${path}.dimensions`)
  const dimensions: Record<string, string> = {}
  for (const [key, value] of Object.entries(rawDimensions)) {
    dimensions[key] = stringValue(value, `${path}.dimensions.${key}`)
  }

  return {
    dimensions,
    per: positiveIntegerValue(unit.per, `${path}.per`),
    ...(unit.price_key === undefined ? {} : { price_key: stringValue(unit.price_key, `${path}.price_key`) }),
  }
}

function decodeProvider(raw: unknown, path: string): Provider {
  const provider = exactObject(
    raw,
    [
      'api_pattern',
      'description',
      'extractors',
      'fallback_model_providers',
      'id',
      'model_match',
      'models',
      'name',
      'price_comments',
      'pricing_urls',
      'provider_match',
    ],
    ['api_pattern', 'id', 'models', 'name'],
    path
  )

  return {
    api_pattern: stringValue(provider.api_pattern, `${path}.api_pattern`),
    id: idValue(provider.id, `${path}.id`),
    models: arrayValue(provider.models, `${path}.models`).map((model, index) => decodeModel(model, `${path}.models[${index.toString()}]`)),
    name: boundedStringValue(provider.name, `${path}.name`, 100),
    ...(provider.description === undefined ? {} : { description: boundedStringValue(provider.description, `${path}.description`, 1_000) }),
    ...(provider.extractors === undefined
      ? {}
      : {
          extractors: arrayValue(provider.extractors, `${path}.extractors`).map((extractor, index) =>
            decodeExtractor(extractor, `${path}.extractors[${index.toString()}]`)
          ),
        }),
    ...(provider.fallback_model_providers === undefined
      ? {}
      : {
          fallback_model_providers: arrayValue(provider.fallback_model_providers, `${path}.fallback_model_providers`).map((value, index) =>
            stringValue(value, `${path}.fallback_model_providers[${index.toString()}]`)
          ),
        }),
    ...(provider.model_match === undefined ? {} : { model_match: decodeMatchLogic(provider.model_match, `${path}.model_match`) }),
    ...(provider.price_comments === undefined
      ? {}
      : { price_comments: boundedStringValue(provider.price_comments, `${path}.price_comments`, 1_000) }),
    ...(provider.pricing_urls === undefined
      ? {}
      : {
          pricing_urls: arrayValue(provider.pricing_urls, `${path}.pricing_urls`).map((value, index) =>
            urlValue(value, `${path}.pricing_urls[${index.toString()}]`)
          ),
        }),
    ...(provider.provider_match === undefined
      ? {}
      : { provider_match: decodeMatchLogic(provider.provider_match, `${path}.provider_match`) }),
  }
}

function decodeModel(raw: unknown, path: string): ModelInfo {
  const model = exactObject(
    raw,
    ['context_window', 'deprecated', 'description', 'id', 'match', 'name', 'price_comments', 'prices'],
    ['id', 'match', 'prices'],
    path
  )
  const prices = Array.isArray(model.prices)
    ? model.prices.map((conditional, index) => decodeConditionalPrice(conditional, `${path}.prices[${index.toString()}]`))
    : decodeModelPrice(model.prices, `${path}.prices`)

  return {
    id: idValue(model.id, `${path}.id`),
    match: decodeMatchLogic(model.match, `${path}.match`),
    prices,
    ...(model.context_window === undefined ? {} : { context_window: integerValue(model.context_window, `${path}.context_window`) }),
    ...(model.deprecated === undefined ? {} : { deprecated: booleanValue(model.deprecated, `${path}.deprecated`) }),
    ...(model.description === undefined ? {} : { description: boundedStringValue(model.description, `${path}.description`, 1_000) }),
    ...(model.name === undefined ? {} : { name: boundedStringValue(model.name, `${path}.name`, 100) }),
    ...(model.price_comments === undefined
      ? {}
      : { price_comments: boundedStringValue(model.price_comments, `${path}.price_comments`, 1_000) }),
  }
}

function decodeConditionalPrice(raw: unknown, path: string): ConditionalPrice {
  const conditional = exactObject(raw, ['constraint', 'prices'], ['prices'], path)
  return {
    prices: decodeModelPrice(conditional.prices, `${path}.prices`),
    ...(conditional.constraint === undefined ? {} : { constraint: decodeConstraint(conditional.constraint, `${path}.constraint`) }),
  }
}

function decodeConstraint(raw: unknown, path: string): NonNullable<ConditionalPrice['constraint']> {
  const constraint = objectValue(raw, path)
  if ('start_date' in constraint) {
    const startDate = exactObject(constraint, ['start_date'], ['start_date'], path)
    const value = stringValue(startDate.start_date, `${path}.start_date`)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      throw new Error(`Expected ${path}.start_date to use YYYY-MM-DD`)
    }
    return { start_date: value, type: 'start_date' }
  }

  const timeOfDate = exactObject(constraint, ['end_time', 'start_time'], ['end_time', 'start_time'], path)
  return {
    end_time: stringValue(timeOfDate.end_time, `${path}.end_time`),
    start_time: stringValue(timeOfDate.start_time, `${path}.start_time`),
    type: 'time_of_date',
  }
}

function decodeModelPrice(raw: unknown, path: string): ModelPrice {
  const rawPrices = objectValue(raw, path)
  const prices: ModelPrice = {}
  for (const [priceKey, price] of Object.entries(rawPrices)) {
    prices[priceKey] = decodePriceValue(price, `${path}.${priceKey}`)
  }
  return prices
}

function decodePriceValue(raw: unknown, path: string): number | TieredPrices {
  if (typeof raw === 'number') return finiteNumberValue(raw, path)

  const tiered = exactObject(raw, ['base', 'tiers'], ['base', 'tiers'], path)
  return new TieredPrices({
    base: finiteNumberValue(tiered.base, `${path}.base`),
    tiers: arrayValue(tiered.tiers, `${path}.tiers`).map((tier, index) => decodeTier(tier, `${path}.tiers[${index.toString()}]`)),
  })
}

function decodeTier(raw: unknown, path: string): Tier {
  const tier = exactObject(raw, ['price', 'start'], ['price', 'start'], path)
  return {
    price: finiteNumberValue(tier.price, `${path}.price`),
    start: integerValue(tier.start, `${path}.start`),
  }
}

function decodeExtractor(raw: unknown, path: string): UsageExtractor {
  const extractor = exactObject(raw, ['api_flavor', 'mappings', 'model_path', 'root'], ['mappings', 'root'], path)
  return {
    api_flavor: extractor.api_flavor === undefined ? 'default' : stringValue(extractor.api_flavor, `${path}.api_flavor`),
    mappings: arrayValue(extractor.mappings, `${path}.mappings`).map((mapping, index) =>
      decodeExtractorMapping(mapping, `${path}.mappings[${index.toString()}]`)
    ),
    model_path: extractor.model_path === undefined ? 'model' : decodeExtractPath(extractor.model_path, `${path}.model_path`),
    root: decodeExtractPath(extractor.root, `${path}.root`),
  }
}

function decodeExtractorMapping(raw: unknown, path: string): UsageExtractorMapping {
  const mapping = exactObject(raw, ['dest', 'path', 'required'], ['dest', 'path'], path)
  return {
    dest: stringValue(mapping.dest, `${path}.dest`),
    path: decodeExtractPath(mapping.path, `${path}.path`),
    required: mapping.required === undefined ? true : booleanValue(mapping.required, `${path}.required`),
  }
}

function decodeExtractPath(raw: unknown, path: string): ExtractPath {
  if (typeof raw === 'string') return raw
  return arrayValue(raw, path).map((step, index) => {
    if (typeof step === 'string') return step
    return decodeArrayMatch(step, `${path}[${index.toString()}]`)
  })
}

function decodeArrayMatch(raw: unknown, path: string): ArrayMatch {
  const arrayMatch = exactObject(raw, ['field', 'match', 'type'], ['field', 'match', 'type'], path)
  if (arrayMatch.type !== 'array-match') {
    throw new Error(`Expected ${path}.type to equal "array-match"`)
  }
  return {
    field: stringValue(arrayMatch.field, `${path}.field`),
    match: decodeMatchLogic(arrayMatch.match, `${path}.match`),
    type: 'array-match',
  }
}

function decodeMatchLogic(raw: unknown, path: string): MatchLogic {
  const logic = objectValue(raw, path)
  const keys = Object.keys(logic)
  if (keys.length !== 1) {
    throw new Error(`Expected ${path} to contain exactly one match clause`)
  }

  const clause = keys[0]
  if (clause === 'and' || clause === 'or') {
    return {
      [clause]: arrayValue(logic[clause], `${path}.${clause}`).map((nested, index) =>
        decodeMatchLogic(nested, `${path}.${clause}[${index.toString()}]`)
      ),
    } as MatchLogic
  }
  if (clause === 'contains' || clause === 'ends_with' || clause === 'equals' || clause === 'starts_with') {
    return { [clause]: stringValue(logic[clause], `${path}.${clause}`) } as MatchLogic
  }
  if (clause === 'regex') {
    const regex = stringValue(logic.regex, `${path}.regex`)
    try {
      RegExp(regex).test('')
    } catch {
      throw new Error(`Expected ${path}.regex to be a valid regular expression`)
    }
    return { regex }
  }
  throw new Error(`Unknown match clause at ${path}: ${clause ?? 'missing'}`)
}

function exactObject(raw: unknown, allowedFields: string[], requiredFields: string[], path: string): Record<string, unknown> {
  const value = objectValue(raw, path)
  const unknownFields = Object.keys(value).filter((field) => !allowedFields.includes(field))
  if (unknownFields.length) {
    throw new Error(`Unknown fields at ${path}: ${unknownFields.sort().join(', ')}`)
  }
  const missingFields = requiredFields.filter((field) => !(field in value))
  if (missingFields.length) {
    throw new Error(`Missing fields at ${path}: ${missingFields.sort().join(', ')}`)
  }
  return value
}

function objectValue(raw: unknown, path: string): Record<string, unknown> {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    throw new Error(`Expected ${path} to be an object`)
  }
  return raw as Record<string, unknown>
}

function arrayValue(raw: unknown, path: string): unknown[] {
  if (!Array.isArray(raw)) {
    throw new Error(`Expected ${path} to be an array`)
  }
  return raw
}

function stringValue(raw: unknown, path: string): string {
  if (typeof raw !== 'string') {
    throw new Error(`Expected ${path} to be a string`)
  }
  return raw
}

function boundedStringValue(raw: unknown, path: string, maxLength: number): string {
  const value = stringValue(raw, path)
  if (value.length > maxLength) {
    throw new Error(`Expected ${path} to contain at most ${maxLength.toString()} characters`)
  }
  return value
}

function idValue(raw: unknown, path: string): string {
  const value = boundedStringValue(raw, path, 100)
  if (/\s/.test(value)) {
    throw new Error(`Expected ${path} not to contain whitespace`)
  }
  return value
}

function booleanValue(raw: unknown, path: string): boolean {
  if (typeof raw !== 'boolean') {
    throw new Error(`Expected ${path} to be a boolean`)
  }
  return raw
}

function finiteNumberValue(raw: unknown, path: string): number {
  if (typeof raw !== 'number' || !Number.isFinite(raw)) {
    throw new Error(`Expected ${path} to be a finite number`)
  }
  return raw
}

function integerValue(raw: unknown, path: string): number {
  const value = finiteNumberValue(raw, path)
  if (!Number.isInteger(value)) {
    throw new Error(`Expected ${path} to be an integer`)
  }
  return value
}

function positiveIntegerValue(raw: unknown, path: string): number {
  const value = integerValue(raw, path)
  if (value <= 0) {
    throw new Error(`Expected ${path} to be positive`)
  }
  return value
}

function urlValue(raw: unknown, path: string): string {
  const value = stringValue(raw, path)
  if (!URL.canParse(value)) {
    throw new Error(`Expected ${path} to be a valid URL`)
  }
  return value
}
