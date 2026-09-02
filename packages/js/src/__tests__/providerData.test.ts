import { describe, expect, it, vi } from 'vitest'

import type { ModelPrice, RawUnitsDict } from '../types'

import { unitData } from '../dataUnits'
import { calcPrice, matchModel } from '../engine'
import { decodeProviderData } from '../providerData'
import { getActiveRegistry } from '../units'
import { warnUnsupportedExtractorDestinations } from '../validation'

function providerFixture(): Record<string, unknown> {
  return {
    api_pattern: 'remote',
    extractors: [
      {
        mappings: [
          { dest: 'input_tokens', path: 'input' },
          { dest: 'output_tokens', path: 'output', required: false },
        ],
        root: 'usage',
      },
    ],
    id: 'remote',
    models: [
      {
        id: 'model-a',
        match: { equals: 'model-a' },
        prices: { input_mtok: 1, output_mtok: 2 },
      },
      {
        id: 'model-b',
        match: { equals: 'model-b' },
        prices: { input_mtok: 3, output_mtok: 4 },
      },
    ],
    name: 'Remote',
    provider_match: { equals: 'remote' },
  }
}

function wrappedFixture(provider: unknown = providerFixture()): Record<string, unknown> {
  const units = structuredClone(unitData) as RawUnitsDict & Record<string, Record<string, unknown>>
  units.remote_events = {
    dimensions: { family: 'remote_events' },
    per: 1,
    price_key: 'remote_event_price',
  }
  return { providers: [provider], units }
}

function defined<T>(value: T | undefined): T {
  if (value === undefined) throw new Error('Expected fixture value to be defined')
  return value
}

describe('decodeProviderData', () => {
  it('decodes legacy arrays with extractor defaults and both wire constraint forms', () => {
    const provider = providerFixture()
    const models = provider.models as Record<string, unknown>[]
    defined(models[0]).prices = [
      { prices: { input_mtok: 1 } },
      { constraint: { start_date: '2025-01-01' }, prices: { input_mtok: 2 } },
      { constraint: { end_time: '16:00:00Z', start_time: '08:00:00Z' }, prices: { input_mtok: 3 } },
    ]

    const decoded = decodeProviderData([provider], getActiveRegistry())

    expect(decoded.registry).toBeUndefined()
    expect(decoded.compatibilityWarnings).toEqual([])
    expect(decoded.providers[0]?.extractors?.[0]).toMatchObject({
      api_flavor: 'default',
      mappings: [
        { dest: 'input_tokens', path: 'input', required: true },
        { dest: 'output_tokens', path: 'output', required: false },
      ],
      model_path: 'model',
    })
    expect(decoded.providers[0]?.models[0]?.prices).toEqual([
      { prices: { input_mtok: 1 } },
      { constraint: { start_date: '2025-01-01', type: 'start_date' }, prices: { input_mtok: 2 } },
      {
        constraint: { end_time: '16:00:00Z', start_time: '08:00:00Z', type: 'time_of_date' },
        prices: { input_mtok: 3 },
      },
    ])
  })

  it('decodes wrapped data without changing active state and ignores object extensions', () => {
    const active = getActiveRegistry()
    const provider = providerFixture()
    provider.future_provider_member = true
    provider.provider_match = { equals: 'remote', future_match_member: true }
    const models = provider.models as Record<string, unknown>[]
    defined(models[0]).prices = [
      {
        constraint: { future_constraint_member: true, start_date: '2025-01-01' },
        future_conditional_member: true,
        prices: { input_mtok: 2 },
      },
    ]
    const wrapped = wrappedFixture(provider)
    wrapped.future_wrapper_member = true
    const units = wrapped.units as Record<string, Record<string, unknown>>
    defined(units.remote_events).future_unit_member = true

    const decoded = decodeProviderData(wrapped, active)

    expect(decoded.registry?.getUnit('remote_events')?.priceKey).toBe('remote_event_price')
    expect(decoded.providers[0]?.provider_match).toEqual({ equals: 'remote', future_match_member: true })
    expect(decoded.providers[0]?.models[0]?.prices).toEqual([
      { constraint: { start_date: '2025-01-01', type: 'start_date' }, prices: { input_mtok: 2 } },
    ])
    expect(decoded.compatibilityWarnings).toEqual([])
    expect(getActiveRegistry()).toBe(active)
  })

  it.each([null, 'providers', 1, true])('rejects invalid roots: %j', (raw) => {
    expect(() => decodeProviderData(raw, getActiveRegistry())).toThrow(
      'genai-prices: invalid data: root must be a wrapped object or provider array'
    )
  })

  it.each([
    [{ providers: [] }, 'missing units'],
    [{ units: {} }, 'missing providers'],
    [{ providers: {}, units: {} }, 'providers must be an array'],
    [{ providers: [], units: [] }, 'units must be an object'],
  ])('rejects malformed wrapped cores: %j', (raw, message) => {
    expect(() => decodeProviderData(raw, getActiveRegistry())).toThrow(`genai-prices: invalid data: ${message}`)
  })

  it('projects unsupported capabilities in deterministic contextual order', () => {
    const provider = providerFixture()
    provider.provider_match = { future_match: 'remote' }
    const extractors = provider.extractors as unknown[]
    extractors.unshift({ config: {}, type: 'future-extractor' })
    const models = provider.models as Record<string, unknown>[]
    models.unshift({ id: 'future-model', match: { future_match: 'x' }, prices: { input_mtok: 10 } })
    defined(models[1]).prices = [
      { constraint: { type: 'future-constraint' }, prices: { input_mtok: 99 } },
      { prices: { input_mtok: { type: 'future-price' }, output_mtok: 2 } },
    ]

    const decoded = decodeProviderData(wrappedFixture(provider), getActiveRegistry())

    expect(decoded.providers[0]?.provider_match).toBeUndefined()
    expect(decoded.providers[0]?.extractors).toHaveLength(1)
    expect(decoded.providers[0]?.models.map(({ id }) => id)).toEqual(['model-a', 'model-b'])
    expect(decoded.providers[0]?.models[0]?.prices).toEqual([{ prices: { output_mtok: 2 } }])
    expect(decoded.compatibilityWarnings).toEqual([
      "Unsupported match variant at providers[0].provider_match for provider 'remote'; upgrade genai-prices for full support",
      "Unsupported extractor variant at providers[0].extractors[0] for provider 'remote'; upgrade genai-prices for full support",
      "Unsupported match variant at providers[0].models[0].match for provider 'remote', model 'future-model'; upgrade genai-prices for full support",
      "Unsupported constraint variant at providers[0].models[1].prices[0].constraint for provider 'remote', model 'model-a'; upgrade genai-prices for full support",
      "Unsupported price variant at providers[0].models[1].prices[1].prices.input_mtok for provider 'remote', model 'model-a'; upgrade genai-prices for full support",
    ])
  })

  it('drops a model whose direct price map only contains future variants', () => {
    const provider = providerFixture()
    const models = provider.models as Record<string, unknown>[]
    models.unshift({ id: 'future-price-model', match: { equals: 'future-price-model' }, prices: { input_mtok: { type: 'future' } } })

    const decoded = decodeProviderData(wrappedFixture(provider), getActiveRegistry())

    expect(decoded.providers[0]?.models.map(({ id }) => id)).toEqual(['model-a', 'model-b'])
    expect(decoded.compatibilityWarnings).toEqual([
      "Unsupported price variant at providers[0].models[0].prices.input_mtok for provider 'remote', model 'future-price-model'; upgrade genai-prices for full support",
    ])
  })

  it('drops a model whose conditional prices only contain future variants', () => {
    const provider = providerFixture()
    const models = provider.models as Record<string, unknown>[]
    defined(models[0]).prices = [{ constraint: { type: 'weekday' }, prices: { input_mtok: 99 } }]

    const decoded = decodeProviderData(wrappedFixture(provider), getActiveRegistry())

    expect(decoded.providers[0]?.models.map(({ id }) => id)).toEqual(['model-b'])
    expect(decoded.compatibilityWarnings).toEqual([
      "Unsupported constraint variant at providers[0].models[0].prices[0].constraint for provider 'remote', model 'model-a'; upgrade genai-prices for full support",
    ])
  })

  it('drops a model whose conditional price maps only contain future variants', () => {
    const provider = providerFixture()
    const models = provider.models as Record<string, unknown>[]
    defined(models[0]).prices = [{ prices: { input_mtok: { type: 'future-price' } } }]

    const decoded = decodeProviderData(wrappedFixture(provider), getActiveRegistry())

    expect(decoded.providers[0]?.models.map(({ id }) => id)).toEqual(['model-b'])
    expect(decoded.compatibilityWarnings).toEqual([
      "Unsupported price variant at providers[0].models[0].prices[0].prices.input_mtok for provider 'remote', model 'model-a'; upgrade genai-prices for full support",
    ])
  })

  it('projects unsupported extractor paths, mappings, and conditional price entries', () => {
    const provider = providerFixture()
    provider.extractors = [
      { mappings: [], root: { type: 'future-path' } },
      {
        mappings: [
          { dest: 'input_tokens', path: [{ type: 'future-path' }] },
          { dest: 'input_tokens', path: ['items', { field: 'kind', match: { equals: 'usage' }, type: 'array-match' }, 'count'] },
          { future_mapping: true },
          { dest: 'output_tokens', path: 'output' },
        ],
        root: 'usage',
      },
    ]
    const models = provider.models as Record<string, unknown>[]
    defined(models[0]).prices = [{ type: 'future-conditional' }, { prices: { output_mtok: 2 } }]

    const decoded = decodeProviderData(wrappedFixture(provider), getActiveRegistry())

    expect(decoded.providers[0]?.extractors).toHaveLength(1)
    expect(decoded.providers[0]?.extractors?.[0]?.mappings.map(({ dest }) => dest)).toEqual(['input_tokens', 'output_tokens'])
    expect(decoded.providers[0]?.models[0]?.prices).toEqual([{ prices: { output_mtok: 2 } }])
    expect(decoded.compatibilityWarnings.map((warning) => warning.split(' for ')[0])).toEqual([
      'Unsupported extractor variant at providers[0].extractors[0].root',
      'Unsupported extractor mapping variant at providers[0].extractors[1].mappings[0].path',
      'Unsupported extractor mapping variant at providers[0].extractors[1].mappings[2]',
      'Unsupported price variant at providers[0].models[0].prices[0]',
    ])
  })

  it('drops an extractor when every mapping is a future variant', () => {
    const provider = providerFixture()
    const extractors = provider.extractors as unknown[]
    extractors.unshift({ mappings: [{ type: 'future-mapping' }], root: 'usage' })

    const decoded = decodeProviderData(wrappedFixture(provider), getActiveRegistry())

    expect(decoded.providers[0]?.extractors).toHaveLength(1)
    expect(decoded.providers[0]?.extractors?.[0]?.mappings[0]?.dest).toBe('input_tokens')
    expect(decoded.compatibilityWarnings).toEqual([
      "Unsupported extractor mapping variant at providers[0].extractors[0].mappings[0] for provider 'remote'; upgrade genai-prices for full support",
    ])
  })

  it.each([
    [null, 'providers[0].extractors[0].root must be a string or array'],
    [['items', null, 'count'], 'providers[0].extractors[0].root[1] must be a string or object'],
    [['items', { field: 'kind', type: 'array-match' }, 'count'], 'providers[0].extractors[0].root[1].match is required'],
  ])('rejects malformed recognized extractor path %j', (root, message) => {
    const provider = providerFixture()
    provider.extractors = [{ mappings: [], root }]

    expect(() => decodeProviderData(wrappedFixture(provider), getActiveRegistry())).toThrow(`genai-prices: invalid data: ${message}`)
  })

  it.each([
    [[3], 'providers[0] must be an object'],
    [[{ ...providerFixture(), models: {} }], 'providers[0].models must be an array'],
    [[{ ...providerFixture(), extractors: {} }], 'providers[0].extractors must be an array'],
    [[{ ...providerFixture(), extractors: [3] }], 'providers[0].extractors[0] must be an object'],
    [[{ ...providerFixture(), extractors: [{ mappings: {}, root: 'usage' }] }], 'providers[0].extractors[0].mappings must be an array'],
    [
      [{ ...providerFixture(), extractors: [{ mappings: [3], root: 'usage' }] }],
      'providers[0].extractors[0].mappings[0] must be an object',
    ],
  ])('rejects malformed recognized provider structures: %j', (raw, message) => {
    expect(() => decodeProviderData(raw, getActiveRegistry())).toThrow(`genai-prices: invalid data: ${message}`)
  })

  it.each([undefined, 1])('rejects wrapped models with malformed prices: %j', (prices) => {
    const provider = providerFixture()
    const models = provider.models as Record<string, unknown>[]
    if (prices === undefined) Reflect.deleteProperty(defined(models[0]), 'prices')
    else defined(models[0]).prices = prices

    expect(() => decodeProviderData(wrappedFixture(provider), getActiveRegistry())).toThrow(
      'genai-prices: invalid data: providers[0].models[0].prices must be an object or array'
    )
  })

  it('rejects a conditional price whose prices member is not an object', () => {
    const provider = providerFixture()
    const models = provider.models as Record<string, unknown>[]
    defined(models[0]).prices = [{ constraint: { start_date: '2026-01-01' }, prices: 1 }]

    expect(() => decodeProviderData(wrappedFixture(provider), getActiveRegistry())).toThrow(
      "genai-prices: invalid data: providers[0].models[0].prices[0].prices must be an object for provider 'remote' model 'model-a'"
    )
  })

  it('rejects a recognized extractor mapping missing a required core field', () => {
    const provider = providerFixture()
    provider.extractors = [{ mappings: [{ dest: 'input_tokens' }], root: 'usage' }]

    expect(() => decodeProviderData(wrappedFixture(provider), getActiveRegistry())).toThrow(
      'genai-prices: invalid data: providers[0].extractors[0].mappings[0] must include path and dest'
    )
  })

  it.each([
    ['non-object', 'not-an-object'],
    ['bad start date', { start_date: 'not-a-date' }],
    ['incomplete time', { start_time: '08:00:00Z' }],
    ['mixed forms', { end_time: '16:00:00Z', start_date: '2025-01-01', start_time: '08:00:00Z' }],
  ])('rejects malformed recognized %s constraints with model context', (_name, constraint) => {
    const provider = providerFixture()
    const models = provider.models as Record<string, unknown>[]
    defined(models[0]).prices = [{ constraint, prices: { input_mtok: 1 } }]

    expect(() => decodeProviderData([provider], getActiveRegistry())).toThrow(
      "genai-prices: invalid data: providers[0].models[0].prices[0] expected a start-date or time-of-day price constraint for provider 'remote' model 'model-a'"
    )
  })

  it('defers price, extractor destination, and match value validation without warnings or state changes', () => {
    const active = getActiveRegistry()
    const provider = providerFixture()
    const extractors = provider.extractors as Record<string, unknown>[]
    const mappings = defined(extractors[0]).mappings as unknown[]
    mappings.push({ dest: 'unknown_events', path: 'unknown', required: false })
    const models = provider.models as Record<string, unknown>[]
    defined(models[0]).match = { equals: 3 }
    defined(models[0]).prices = { input_mtok: 'invalid-later', unknown_event_price: 5 }
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    try {
      const decoded = decodeProviderData([provider], active)
      expect(warnSpy).not.toHaveBeenCalled()
      expect(getActiveRegistry()).toBe(active)

      const decodedProvider = defined(decoded.providers[0])
      const decodedModel = defined(decodedProvider.models[0])
      expect(() => calcPrice({ input_tokens: 1 }, decodedModel.prices as ModelPrice, active)).toThrow('Invalid price value for input_mtok')
      warnUnsupportedExtractorDestinations(decoded.providers, active)
      expect(warnSpy).toHaveBeenCalledWith('Unsupported extractor destination for standard extraction: unknown_events')
      expect(() => matchModel(decodedProvider.models, 'model-a')).toThrow(TypeError)
    } finally {
      warnSpy.mockRestore()
    }
  })

  it('preserves active state when wrapped registry evolution fails', () => {
    const active = getActiveRegistry()
    const wrapped = wrappedFixture()
    const units = wrapped.units as Record<string, unknown>
    delete units.input_tokens

    expect(() => decodeProviderData(wrapped, active)).toThrow('genai-prices: invalid data: removed published unit: input_tokens')
    expect(getActiveRegistry()).toBe(active)
  })
})
