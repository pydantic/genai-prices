import { describe, expect, it } from 'vitest'

import type { RawUnitsDict } from '../types'

import { unitData } from '../dataUnits'
import { calcPrice } from '../engine'
import { getActiveRegistry, isCompatible, setActiveRegistry, UnitRegistry, validateUnitEvolution } from '../units'
import { normalizeUsage } from '../usage'

const tokenUsageKeys = [
  'input_tokens',
  'output_tokens',
  'cache_read_tokens',
  'cache_write_tokens',
  'cache_write_5m_tokens',
  'cache_write_1h_tokens',
  'input_text_tokens',
  'output_text_tokens',
  'cache_text_read_tokens',
  'cache_text_write_tokens',
  'cache_text_write_5m_tokens',
  'cache_text_write_1h_tokens',
  'input_audio_tokens',
  'output_audio_tokens',
  'cache_audio_read_tokens',
  'cache_audio_write_tokens',
  'cache_audio_write_5m_tokens',
  'cache_audio_write_1h_tokens',
  'input_image_tokens',
  'output_image_tokens',
  'cache_image_read_tokens',
  'cache_image_write_tokens',
  'cache_image_write_5m_tokens',
  'cache_image_write_1h_tokens',
  'input_video_tokens',
  'output_video_tokens',
  'cache_video_read_tokens',
  'cache_video_write_tokens',
  'cache_video_write_5m_tokens',
  'cache_video_write_1h_tokens',
  'input_tool_tokens',
  'input_text_tool_tokens',
  'input_audio_tool_tokens',
  'input_image_tool_tokens',
  'input_video_tool_tokens',
  'output_reasoning_tokens',
  'output_text_reasoning_tokens',
  'output_audio_reasoning_tokens',
  'output_image_reasoning_tokens',
  'output_video_reasoning_tokens',
  'output_citation_tokens',
  'output_text_citation_tokens',
  'output_audio_citation_tokens',
  'output_image_citation_tokens',
  'output_video_citation_tokens',
]

const tokenPriceKeys = [
  'input_mtok',
  'output_mtok',
  'cache_read_mtok',
  'cache_write_mtok',
  'cache_write_5m_mtok',
  'cache_write_1h_mtok',
  'input_text_mtok',
  'output_text_mtok',
  'cache_text_read_mtok',
  'cache_text_write_mtok',
  'cache_text_write_5m_mtok',
  'cache_text_write_1h_mtok',
  'input_audio_mtok',
  'output_audio_mtok',
  'cache_audio_read_mtok',
  'cache_audio_write_mtok',
  'cache_audio_write_5m_mtok',
  'cache_audio_write_1h_mtok',
  'input_image_mtok',
  'output_image_mtok',
  'cache_image_read_mtok',
  'cache_image_write_mtok',
  'cache_image_write_5m_mtok',
  'cache_image_write_1h_mtok',
  'input_video_mtok',
  'output_video_mtok',
  'cache_video_read_mtok',
  'cache_video_write_mtok',
  'cache_video_write_5m_mtok',
  'cache_video_write_1h_mtok',
  'input_tool_mtok',
  'input_text_tool_mtok',
  'input_audio_tool_mtok',
  'input_image_tool_mtok',
  'input_video_tool_mtok',
  'output_reasoning_mtok',
  'output_text_reasoning_mtok',
  'output_audio_reasoning_mtok',
  'output_image_reasoning_mtok',
  'output_video_reasoning_mtok',
  'output_citation_mtok',
  'output_text_citation_mtok',
  'output_audio_citation_mtok',
  'output_image_citation_mtok',
  'output_video_citation_mtok',
]

const nonTokenReportableUnits = {
  audio_seconds: 'audio_hours',
  code_executions: 'code_executions_kcount',
  input_annotated_document_pages: 'input_annotated_document_kpages',
  input_audio_seconds: 'input_audio_hours',
  input_characters: 'input_mchars',
  input_document_pages: 'input_document_kpages',
  input_pixels: 'input_gpixels',
  input_text_messages: 'input_text_messages_kcount',
  output_audio_seconds: 'output_audio_hours',
  rerank_searches: 'rerank_searches_kcount',
  social_searches: 'social_searches_kcount',
  storage_searches: 'storage_searches_kcount',
  web_searches: 'web_searches_kcount',
} as const

const reportableUsageKeys = [...tokenUsageKeys, ...Object.keys(nonTokenReportableUnits)]

describe('UnitRegistry', () => {
  it('constructs generated flat units into indexed runtime objects', () => {
    const registry = new UnitRegistry(unitData)

    expect(new Set(tokenUsageKeys.map((usageKey) => registry.getUnit(usageKey)?.usageKey))).toEqual(new Set(tokenUsageKeys))
    expect(
      Object.fromEntries(Object.keys(nonTokenReportableUnits).map((usageKey) => [usageKey, registry.getUnit(usageKey)?.priceKey]))
    ).toEqual(nonTokenReportableUnits)
    expect(registry.getUnit('requests')?.priceKey).toBe('requests_kcount')
    expect(registry.getAllUsageKeys().size).toBe(reportableUsageKeys.length + 1)
    expect(registry.getUnitForPriceKey('input_mtok')).toBe(registry.getUnit('input_tokens'))
    expect(registry.getUnitForPriceKey('cache_image_write_mtok')?.usageKey).toBe('cache_image_write_tokens')
    expect(registry.getAllUsageKeys()).toContain('input_tokens')
    expect(registry.getAllPriceKeys()).toContain('input_mtok')
    expect(new Set(registry.reportedUsageKeys())).toContain('input_tokens')
    expect(new Set(registry.reportedUsageKeys())).not.toContain('requests')
  })

  it('models directional audio durations as children of total audio duration', () => {
    const registry = new UnitRegistry(unitData)
    const inputAudio = registry.getUnit('input_audio_seconds')
    const outputAudio = registry.getUnit('output_audio_seconds')
    expect(inputAudio).toBeDefined()
    expect(outputAudio).toBeDefined()
    if (!inputAudio || !outputAudio) throw new Error('Expected directional audio duration units')

    expect(registry.ancestorUsageKeys('input_audio_seconds')).toEqual(new Set(['audio_seconds']))
    expect(registry.ancestorUsageKeys('output_audio_seconds')).toEqual(new Set(['audio_seconds']))
    expect(isCompatible(inputAudio, outputAudio)).toBe(false)
  })

  it('defaults missing price keys to the usage key', () => {
    const registry = new UnitRegistry({
      widgets: {
        dimensions: { family: 'widgets' },
        per: 1,
      },
    })

    expect(registry.getUnit('widgets')?.priceKey).toBe('widgets')
    expect(registry.getUnitForPriceKey('widgets')).toBe(registry.getUnit('widgets'))
  })

  it('indexes units by full dimension set', () => {
    const registry = new UnitRegistry(unitData)
    const inputAudio = registry.getUnit('input_audio_tokens')
    expect(inputAudio).toBeDefined()
    if (!inputAudio) throw new Error('Expected input_audio_tokens')

    expect(inputAudio.dimensions.family).toBe('tokens')
    expect(inputAudio.per).toBe(1_000_000)
    expect(registry.findJoin(inputAudio, inputAudio)).toBe(inputAudio)
  })

  it('indexes ancestor usage keys', () => {
    const registry = new UnitRegistry(unitData)

    expect(registry.ancestorUsageKeys('cache_audio_read_tokens')).toEqual(
      new Set(['cache_read_tokens', 'input_audio_tokens', 'input_tokens'])
    )
    expect(registry.ancestorUsageKeys('requests')).toEqual(new Set())
  })

  it('indexes reasoning-modality joins', () => {
    const registry = new UnitRegistry(unitData)
    const text = registry.getUnit('output_text_tokens')
    const reasoning = registry.getUnit('output_reasoning_tokens')
    expect(text).toBeDefined()
    expect(reasoning).toBeDefined()
    if (!text || !reasoning) throw new Error('Expected generated reasoning units')

    expect(registry.findJoin(text, reasoning)).toBe(registry.getUnit('output_text_reasoning_tokens'))
    expect(registry.ancestorUsageKeys('output_text_reasoning_tokens')).toEqual(
      new Set(['output_reasoning_tokens', 'output_text_tokens', 'output_tokens'])
    )
  })

  it('rejects joins between distinct token types', () => {
    const registry = new UnitRegistry(unitData)
    const cacheRead = registry.getUnit('cache_read_tokens')
    const tool = registry.getUnit('input_tool_tokens')
    const reasoning = registry.getUnit('output_reasoning_tokens')
    const citation = registry.getUnit('output_citation_tokens')
    expect(cacheRead).toBeDefined()
    expect(tool).toBeDefined()
    expect(reasoning).toBeDefined()
    expect(citation).toBeDefined()
    if (!cacheRead || !tool || !reasoning || !citation) throw new Error('Expected generated token-type units')

    expect(registry.findJoin(cacheRead, tool)).toBeUndefined()
    expect(registry.findJoin(reasoning, citation)).toBeUndefined()
  })

  it('indexes non-token relationships', () => {
    const registry = new UnitRegistry(unitData)
    const documentPages = registry.getUnit('input_document_pages')
    const annotatedDocumentPages = registry.getUnit('input_annotated_document_pages')
    const webSearches = registry.getUnit('web_searches')
    const socialSearches = registry.getUnit('social_searches')
    expect(documentPages).toBeDefined()
    expect(annotatedDocumentPages).toBeDefined()
    expect(webSearches).toBeDefined()
    expect(socialSearches).toBeDefined()
    if (!documentPages || !annotatedDocumentPages || !webSearches || !socialSearches) {
      throw new Error('Expected generated non-token units')
    }

    expect(registry.ancestorUsageKeys('input_annotated_document_pages')).toEqual(new Set(['input_document_pages']))
    expect(registry.ancestorUsageKeys('web_searches')).toEqual(new Set())
    expect(registry.findJoin(webSearches, socialSearches)).toBeUndefined()
  })

  it('keeps construction independent of generated data fixtures', () => {
    const raw: RawUnitsDict = {
      billable_calls: {
        dimensions: {
          class: 'billable',
          family: 'calls',
        },
        per: 100,
        price_key: 'billable_call_count',
      },
    }

    const unit = new UnitRegistry(raw).getUnit('billable_calls')
    expect(unit).toMatchObject({
      dimensions: { class: 'billable', family: 'calls' },
      per: 100,
      priceKey: 'billable_call_count',
      usageKey: 'billable_calls',
    })
  })

  it('does not expose mutable registry state', () => {
    const registry = new UnitRegistry(unitData)
    const usageKeys = registry.getAllUsageKeys()
    const inputUnit = registry.getUnit('input_tokens')
    expect(inputUnit).toBeDefined()
    if (!inputUnit) throw new Error('Expected input_tokens')

    usageKeys.clear()

    expect(registry.getAllUsageKeys()).toContain('input_tokens')
    expect(registry.isReportedUsageKey('input_tokens')).toBe(true)
    expect(Object.isFrozen(inputUnit)).toBe(true)
    expect(Object.isFrozen(inputUnit.dimensions)).toBe(true)
    expect(() => Object.assign(inputUnit.dimensions, { family: 'changed' })).toThrow(TypeError)
    expect(registry.getUnit('input_tokens')?.dimensions.family).toBe('tokens')
  })

  it('constructs an ordered frozen projection from untrusted unit data', () => {
    const raw = {
      first_events: {
        dimension_requirements: { ignored: true },
        dimensions: { family: 'first_events' },
        future_member: 'ignored',
        per: 1,
      },
      last_events: {
        dimensions: { family: 'last_events' },
        per: Number.MAX_SAFE_INTEGER,
        price_key: 'last_event_price',
      },
    }

    const registry = UnitRegistry.fromUntrusted(raw)
    raw.first_events.dimensions.family = 'changed'
    raw.first_events.per = 2

    expect([...registry.reportedUsageKeys()]).toEqual(['first_events', 'last_events'])
    expect(registry.getUnit('first_events')).toEqual({
      dimensions: { family: 'first_events' },
      per: 1,
      priceKey: 'first_events',
      usageKey: 'first_events',
    })
    expect(registry.getUnit('last_events')?.per).toBe(Number.MAX_SAFE_INTEGER)
    expect(registry.getUnit('last_events')).not.toHaveProperty('dimension_requirements')
    expect(Object.isFrozen(registry.getUnit('first_events'))).toBe(true)
    expect(Object.isFrozen(registry.getUnit('first_events')?.dimensions)).toBe(true)
  })

  it.each([null, [], 'units', 1, true])('rejects a non-object untrusted root: %j', (raw) => {
    expect(() => UnitRegistry.fromUntrusted(raw)).toThrow('genai-prices: invalid data: units must be an object')
  })

  it.each([
    [{ events: null }, 'unit "events" must be an object'],
    [{ events: [] }, 'unit "events" must be an object'],
    [{ events: { dimensions: { family: 'events' } } }, 'unit "events" is missing per'],
    [{ events: { dimensions: { family: 'events' }, per: 0 } }, 'safe positive integer'],
    [{ events: { dimensions: { family: 'events' }, per: -1 } }, 'safe positive integer'],
    [{ events: { dimensions: { family: 'events' }, per: 1.5 } }, 'safe positive integer'],
    [{ events: { dimensions: { family: 'events' }, per: true } }, 'safe positive integer'],
    [{ events: { dimensions: { family: 'events' }, per: Number.MAX_SAFE_INTEGER + 1 } }, 'safe positive integer'],
    [{ events: { dimensions: { family: 'events' }, per: Number.NaN } }, 'safe positive integer'],
    [{ events: { dimensions: { family: 'events' }, per: 1, price_key: null } }, 'price_key must be a string'],
    [{ events: { per: 1 } }, 'dimensions must be an object'],
    [{ events: { dimensions: [], per: 1 } }, 'dimensions must be an object'],
    [{ events: { dimensions: {}, per: 1 } }, 'missing the family dimension'],
    [{ events: { dimensions: { family: '' }, per: 1 } }, 'non-empty string keys and values'],
    [{ events: { dimensions: { family: 'events', type: 1 }, per: 1 } }, 'non-empty string keys and values'],
  ])('rejects malformed recognized unit fields: %j', (raw, message) => {
    expect(() => UnitRegistry.fromUntrusted(raw)).toThrow('genai-prices: invalid data:')
    expect(() => UnitRegistry.fromUntrusted(raw)).toThrow(message)
  })

  it.each(['_private', 'two words', 'class', 'constructor', 'prototype'])('rejects unsafe usage key %j', (usageKey) => {
    expect(() => UnitRegistry.fromUntrusted({ [usageKey]: { dimensions: { family: 'events' }, per: 1 } })).toThrow(
      'genai-prices: invalid data: unit usage key'
    )
  })

  it.each(['_private', 'two words', 'await', 'constructor', 'prototype'])('rejects unsafe price key %j', (priceKey) => {
    expect(() => UnitRegistry.fromUntrusted({ events: { dimensions: { family: 'events' }, per: 1, price_key: priceKey } })).toThrow(
      'genai-prices: invalid data: unit price key'
    )
  })

  it('rejects duplicate price and dimension identities', () => {
    expect(() =>
      UnitRegistry.fromUntrusted({
        first_events: { dimensions: { family: 'first' }, per: 1, price_key: 'event_price' },
        second_events: { dimensions: { family: 'second' }, per: 1, price_key: 'event_price' },
      })
    ).toThrow('units "first_events" and "second_events" use price key event_price')

    expect(() =>
      UnitRegistry.fromUntrusted({
        first_events: { dimensions: { family: 'events' }, per: 1 },
        second_events: { dimensions: { family: 'events' }, per: 1 },
      })
    ).toThrow('units "first_events" and "second_events" use identical dimensions')
  })

  it('normalizes each family to one exact factor', () => {
    expect(() =>
      UnitRegistry.fromUntrusted({
        input_events: { dimensions: { direction: 'input', family: 'events' }, per: 1 },
        output_events: { dimensions: { direction: 'output', family: 'events' }, per: 2 },
      })
    ).toThrow('per 2 differs from 1 for family "events"')
  })

  it('requires every compatible dimension join and accepts a complete join', () => {
    const incomplete = {
      input_events: { dimensions: { direction: 'input', family: 'events' }, per: 1 },
      special_events: { dimensions: { event_type: 'special', family: 'events' }, per: 1 },
    }
    expect(() => UnitRegistry.fromUntrusted(incomplete)).toThrow('missing join unit dimensions between input_events and special_events')

    const registry = UnitRegistry.fromUntrusted({
      ...incomplete,
      input_special_events: {
        dimensions: { direction: 'input', event_type: 'special', family: 'events' },
        per: 1,
      },
    })
    const inputEvents = registry.getUnit('input_events')
    const specialEvents = registry.getUnit('special_events')
    expect(inputEvents).toBeDefined()
    expect(specialEvents).toBeDefined()
    if (!inputEvents || !specialEvents) throw new Error('Expected complete event units')
    expect(registry.findJoin(inputEvents, specialEvents)).toBe(registry.getUnit('input_special_events'))
  })

  it('treats inherited object properties as absent dimensions', () => {
    const incomplete = {
      constructor_events: { dimensions: { constructor: 'custom', family: 'events' }, per: 1 },
      special_events: { dimensions: { family: 'events', kind: 'special' }, per: 1 },
    }
    expect(() => UnitRegistry.fromUntrusted(incomplete)).toThrow(
      'missing join unit dimensions between constructor_events and special_events'
    )

    const registry = UnitRegistry.fromUntrusted({
      ...incomplete,
      constructor_special_events: {
        dimensions: { constructor: 'custom', family: 'events', kind: 'special' },
        per: 1,
      },
    })
    const constructorEvents = registry.getUnit('constructor_events')
    const specialEvents = registry.getUnit('special_events')
    expect(constructorEvents).toBeDefined()
    expect(specialEvents).toBeDefined()
    if (!constructorEvents || !specialEvents) throw new Error('Expected complete event units')
    expect(isCompatible(constructorEvents, specialEvents)).toBe(true)
    expect(registry.findJoin(constructorEvents, specialEvents)).toBe(registry.getUnit('constructor_special_events'))
  })

  it('scales validation across large disjoint families', () => {
    const units: RawUnitsDict = {}
    for (let index = 0; index < 20_000; index++) {
      units[`unit_${String(index)}`] = { dimensions: { family: `family_${String(index)}` }, per: 1 }
    }

    const registry = UnitRegistry.fromUntrusted(units)

    expect(registry.getAllUsageKeys()).toHaveLength(20_000)
  })

  it('accepts the last member retained by standard JSON duplicate decoding', () => {
    const decoded: unknown = JSON.parse(
      '{"events":{"per":0,"dimensions":{"family":"bad"}},"events":{"per":2,"per":1,"dimensions":{"family":"events"}}}'
    )

    const registry = UnitRegistry.fromUntrusted(decoded)

    expect(registry.getUnit('events')?.per).toBe(1)
    expect(registry.getUnit('events')?.dimensions.family).toBe('events')
  })
})

describe('generated unit registry', () => {
  it('initializes from generated unit data', () => {
    const active = getActiveRegistry()
    expect(active.getUnit('input_tokens')?.priceKey).toBe('input_mtok')
    expect(active.getUnit('requests')?.priceKey).toBe('requests_kcount')
  })

  it('keeps a stable generated registry while allowing direct construction', () => {
    const generated = getActiveRegistry()
    const custom = new UnitRegistry({
      widgets: {
        dimensions: { family: 'widgets' },
        per: 1,
      },
    })

    expect(getActiveRegistry()).toBe(generated)
    expect(getActiveRegistry().getUnit('input_tokens')?.priceKey).toBe('input_mtok')
    expect(getActiveRegistry().getUnit('widgets')).toBeUndefined()
    expect(custom.getUnit('widgets')?.priceKey).toBe('widgets')
  })

  it('looks up generated units', () => {
    expect(getActiveRegistry().getUnit('input_tokens')?.per).toBe(1_000_000)
    expect(getActiveRegistry().getUnit('requests')?.per).toBe(1_000)
  })

  it('returns undefined for unknown usage keys', () => {
    expect(getActiveRegistry().getUnit('imaginary_tokens')).toBeUndefined()
  })

  it('looks up generated price keys', () => {
    const registry = getActiveRegistry()
    expect(registry.getUnitForPriceKey('input_mtok')).toBe(registry.getUnit('input_tokens'))
    expect(registry.getUnitForPriceKey('output_mtok')).toBe(registry.getUnit('output_tokens'))
    expect(registry.getUnitForPriceKey('web_searches_kcount')).toBe(registry.getUnit('web_searches'))
    expect(registry.getUnitForPriceKey('requests_kcount')).toBe(registry.getUnit('requests'))
  })

  it('returns undefined for unknown price keys', () => {
    expect(getActiveRegistry().getUnitForPriceKey('imaginary_mtok')).toBeUndefined()
  })

  it('returns the generated full usage-key set', () => {
    expect(getActiveRegistry().getAllUsageKeys()).toEqual(new Set(['requests', ...reportableUsageKeys]))
  })

  it('returns the generated full price-key set', () => {
    expect(getActiveRegistry().getAllPriceKeys()).toEqual(
      new Set(['requests_kcount', ...Object.values(nonTokenReportableUnits), ...tokenPriceKeys])
    )
  })

  it('returns externally reported usage keys without pricing-only requests', () => {
    expect(getActiveRegistry().getAllUsageKeys()).toContain('requests')
    expect(new Set(getActiveRegistry().reportedUsageKeys())).toEqual(new Set(reportableUsageKeys))
    expect(getActiveRegistry().isReportedUsageKey('web_searches')).toBe(true)
    expect(getActiveRegistry().isReportedUsageKey('requests')).toBe(false)
  })

  it('selects and restores an active replacement through existing helpers', () => {
    const bundled = getActiveRegistry()
    const replacement = UnitRegistry.fromUntrusted({
      remote_events: {
        dimensions: { family: 'remote_events' },
        per: 1,
        price_key: 'remote_event_price',
      },
    })

    try {
      setActiveRegistry(replacement)

      expect(getActiveRegistry()).toBe(replacement)
      expect(normalizeUsage({ input_tokens: 5, remote_events: 3 })).toEqual({ remote_events: 3 })
      expect(calcPrice({ remote_events: 4 }, { remote_event_price: 2 })).toEqual({
        input_price: 0,
        output_price: 0,
        total_price: 8,
      })
    } finally {
      setActiveRegistry()
    }

    expect(getActiveRegistry()).toBe(bundled)
    expect(getActiveRegistry().getUnit('input_tokens')).toBeDefined()
    expect(getActiveRegistry().getUnit('remote_events')).toBeUndefined()
  })
})

/* eslint-disable perfectionist/sort-objects -- Unit evolution tests intentionally exercise object-member order. */
function publishedRegistry(): UnitRegistry {
  return UnitRegistry.fromUntrusted({
    events: { dimensions: { family: 'events' }, per: 1 },
    special_events: { dimensions: { family: 'events', kind: 'special' }, per: 1 },
  })
}

describe('validateUnitEvolution', () => {
  it('accepts appended descendants, intersections, and new families', () => {
    const previous = publishedRegistry()
    const candidate = UnitRegistry.fromUntrusted({
      events: { dimensions: { family: 'events' }, per: 1 },
      special_events: { dimensions: { family: 'events', kind: 'special' }, per: 1 },
      vip_events: { dimensions: { audience: 'vip', family: 'events' }, per: 1 },
      vip_special_events: { dimensions: { audience: 'vip', family: 'events', kind: 'special' }, per: 1 },
      seconds: { dimensions: { family: 'durations' }, per: 1 },
    })

    expect(() => {
      validateUnitEvolution(previous, candidate)
    }).not.toThrow()
    expect([...previous.reportedUsageKeys()]).toEqual(['events', 'special_events'])
    expect([...candidate.reportedUsageKeys()].slice(-3)).toEqual(['vip_events', 'vip_special_events', 'seconds'])
  })

  it.each([
    [UnitRegistry.fromUntrusted({ events: { dimensions: { family: 'events' }, per: 1 } }), 'removed published unit'],
    [
      UnitRegistry.fromUntrusted({
        special_events: { dimensions: { family: 'events', kind: 'special' }, per: 1 },
        events: { dimensions: { family: 'events' }, per: 1 },
      }),
      'reordered published units',
    ],
    [
      UnitRegistry.fromUntrusted({
        events: { dimensions: { family: 'events' }, per: 1 },
        seconds: { dimensions: { family: 'durations' }, per: 1 },
        special_events: { dimensions: { family: 'events', kind: 'special' }, per: 1 },
      }),
      'new unit seconds must be appended',
    ],
  ])('rejects removal, reorder, or insertion without mutation', (candidate, message) => {
    const previous = publishedRegistry()
    const previousOrder = [...previous.reportedUsageKeys()]
    const candidateOrder = [...candidate.reportedUsageKeys()]

    expect(() => {
      validateUnitEvolution(previous, candidate)
    }).toThrow(`genai-prices: invalid data: ${message}`)
    expect([...previous.reportedUsageKeys()]).toEqual(previousOrder)
    expect([...candidate.reportedUsageKeys()]).toEqual(candidateOrder)
  })

  it.each([
    { dimensions: { family: 'events', kind: 'original' }, per: 2, price_key: 'published_price' },
    { dimensions: { family: 'events', kind: 'original' }, per: 1, price_key: 'replacement_price' },
    { dimensions: { family: 'events', kind: 'corrected' }, per: 1, price_key: 'published_price' },
  ])('rejects an old definition change', (candidateDefinition) => {
    const previous = UnitRegistry.fromUntrusted({
      published_events: {
        dimensions: { family: 'events', kind: 'original' },
        per: 1,
        price_key: 'published_price',
      },
    })
    const candidate = UnitRegistry.fromUntrusted({ published_events: candidateDefinition })

    expect(() => {
      validateUnitEvolution(previous, candidate)
    }).toThrow('genai-prices: invalid data: redefined published unit: published_events')
    expect(previous.getUnit('published_events')?.per).toBe(1)
    expect(candidate.getUnit('published_events')).toBeDefined()
  })

  it('allows additive correction descendants but rejects new ancestors', () => {
    const previous = UnitRegistry.fromUntrusted({
      mistaken_events: { dimensions: { family: 'events', kind: 'mistaken' }, per: 1 },
    })
    const corrected = UnitRegistry.fromUntrusted({
      mistaken_events: { dimensions: { family: 'events', kind: 'mistaken' }, per: 1 },
      corrected_events: { dimensions: { correction: 'v2', family: 'events', kind: 'mistaken' }, per: 1 },
    })
    expect(() => {
      validateUnitEvolution(previous, corrected)
    }).not.toThrow()

    const ancestor = UnitRegistry.fromUntrusted({
      mistaken_events: { dimensions: { family: 'events', kind: 'mistaken' }, per: 1 },
      events: { dimensions: { family: 'events' }, per: 1 },
    })
    expect(() => {
      validateUnitEvolution(previous, ancestor)
    }).toThrow('genai-prices: invalid data: new unit events is an ancestor or intermediate of published unit mistaken_events')
    expect([...previous.reportedUsageKeys()]).toEqual(['mistaken_events'])
    expect([...ancestor.reportedUsageKeys()]).toEqual(['mistaken_events', 'events'])
  })
})
/* eslint-enable perfectionist/sort-objects */
