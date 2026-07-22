import { describe, expect, it } from 'vitest'

import type { RawUnitsDict } from '../types'

import { unitData } from '../dataUnits'
import { getActiveRegistry, UnitRegistry } from '../units'

const tokenUsageKeys = [
  'input_tokens',
  'output_tokens',
  'cache_read_tokens',
  'cache_write_tokens',
  'input_text_tokens',
  'output_text_tokens',
  'cache_text_read_tokens',
  'cache_text_write_tokens',
  'input_audio_tokens',
  'output_audio_tokens',
  'cache_audio_read_tokens',
  'cache_audio_write_tokens',
  'input_image_tokens',
  'output_image_tokens',
  'cache_image_read_tokens',
  'cache_image_write_tokens',
  'input_video_tokens',
  'output_video_tokens',
  'cache_video_read_tokens',
  'cache_video_write_tokens',
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
  'input_text_mtok',
  'output_text_mtok',
  'cache_text_read_mtok',
  'cache_text_write_mtok',
  'input_audio_mtok',
  'output_audio_mtok',
  'cache_audio_read_mtok',
  'cache_audio_write_mtok',
  'input_image_mtok',
  'output_image_mtok',
  'cache_image_read_mtok',
  'cache_image_write_mtok',
  'input_video_mtok',
  'output_video_mtok',
  'cache_video_read_mtok',
  'cache_video_write_mtok',
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

describe('UnitRegistry', () => {
  it('constructs generated flat units into indexed runtime objects', () => {
    const registry = new UnitRegistry(unitData)

    expect(new Set(tokenUsageKeys.map((usageKey) => registry.getUnit(usageKey)?.usageKey))).toEqual(new Set(tokenUsageKeys))
    expect(registry.getUnit('requests')?.priceKey).toBe('requests_kcount')
    expect(registry.getAllUsageKeys().size).toBe(tokenUsageKeys.length + 1)
    expect(registry.getUnitForPriceKey('input_mtok')).toBe(registry.getUnit('input_tokens'))
    expect(registry.getUnitForPriceKey('cache_image_write_mtok')?.usageKey).toBe('cache_image_write_tokens')
    expect(registry.getAllUsageKeys()).toContain('input_tokens')
    expect(registry.getAllPriceKeys()).toContain('input_mtok')
    expect(new Set(registry.reportedUsageKeys())).toContain('input_tokens')
    expect(new Set(registry.reportedUsageKeys())).not.toContain('requests')
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
    expect(registry.getUnitForPriceKey('requests_kcount')).toBe(registry.getUnit('requests'))
  })

  it('returns undefined for unknown price keys', () => {
    expect(getActiveRegistry().getUnitForPriceKey('imaginary_mtok')).toBeUndefined()
  })

  it('returns the generated full usage-key set', () => {
    expect(getActiveRegistry().getAllUsageKeys()).toEqual(new Set(['requests', ...tokenUsageKeys]))
  })

  it('returns the generated full price-key set', () => {
    expect(getActiveRegistry().getAllPriceKeys()).toEqual(new Set(['requests_kcount', ...tokenPriceKeys]))
  })

  it('returns externally reported usage keys without pricing-only requests', () => {
    expect(getActiveRegistry().getAllUsageKeys()).toContain('requests')
    expect(new Set(getActiveRegistry().reportedUsageKeys())).toEqual(new Set(tokenUsageKeys))
    expect(getActiveRegistry().isReportedUsageKey('requests')).toBe(false)
  })
})
