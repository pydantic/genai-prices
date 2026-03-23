# Unit Registry & Decomposition — Spec

**Date:** 2026-03-23
**Status:** Draft
**Companion specs:** Conditional Prices (`2026-03-23-conditional-prices-spec.md`), Provider-Level Prices (`2026-03-23-provider-level-prices-spec.md`), Non-Token Units (`2026-03-23-non-token-units-spec.md`)
**Reference:** `2026-03-23-unit-registry-reference.md` — coverage analysis, algorithm details, edge cases

---

## 1. Overview

Replace the fixed-field pricing and usage model with an extensible, registry-driven unit system. A standalone YAML registry defines all pricing units, grouped into families with typed dimensions. Data-driven decomposition — based on dimension metadata — replaces the hardcoded subtraction chain in the current `calc_price`.

---

## 2. Unit Registry

A standalone YAML file (e.g., `prices/units.yml`) defines all pricing units. Units can also be declared at runtime in Python/JS.

### 2.1 Unit Families

A family groups units whose numbers can be meaningfully added together. Each family carries a fixed normalization factor (`per`).

```yaml
families:
  tokens:
    per: 1_000_000
    description: Token counts
    dimensions:
      direction: [input, output]
      modality: [text, audio, image, video]
      cache: [read, write]
    units:
      input_mtok:
        usage_key: input_tokens
        dimensions: { direction: input }
      output_mtok:
        usage_key: output_tokens
        dimensions: { direction: output }

      cache_read_mtok:
        usage_key: cache_read_tokens
        dimensions: { direction: input, cache: read }
      cache_write_mtok:
        usage_key: cache_write_tokens
        dimensions: { direction: input, cache: write }

      input_text_mtok:
        usage_key: input_text_tokens
        dimensions: { direction: input, modality: text }
      output_text_mtok:
        usage_key: output_text_tokens
        dimensions: { direction: output, modality: text }
      cache_read_text_mtok:
        usage_key: cache_read_text_tokens
        dimensions: { direction: input, modality: text, cache: read }
      cache_write_text_mtok:
        usage_key: cache_write_text_tokens
        dimensions: { direction: input, modality: text, cache: write }

      input_audio_mtok:
        usage_key: input_audio_tokens
        dimensions: { direction: input, modality: audio }
      output_audio_mtok:
        usage_key: output_audio_tokens
        dimensions: { direction: output, modality: audio }
      cache_audio_read_mtok:
        usage_key: cache_audio_read_tokens
        dimensions: { direction: input, modality: audio, cache: read }
      cache_write_audio_mtok:
        usage_key: cache_write_audio_tokens
        dimensions: { direction: input, modality: audio, cache: write }

      input_image_mtok:
        usage_key: input_image_tokens
        dimensions: { direction: input, modality: image }
      output_image_mtok:
        usage_key: output_image_tokens
        dimensions: { direction: output, modality: image }
      cache_read_image_mtok:
        usage_key: cache_read_image_tokens
        dimensions: { direction: input, modality: image, cache: read }
      cache_write_image_mtok:
        usage_key: cache_write_image_tokens
        dimensions: { direction: input, modality: image, cache: write }

      input_video_mtok:
        usage_key: input_video_tokens
        dimensions: { direction: input, modality: video }
      output_video_mtok:
        usage_key: output_video_tokens
        dimensions: { direction: output, modality: video }
      cache_read_video_mtok:
        usage_key: cache_read_video_tokens
        dimensions: { direction: input, modality: video, cache: read }
      cache_write_video_mtok:
        usage_key: cache_write_video_tokens
        dimensions: { direction: input, modality: video, cache: write }
```

Non-token families (tool calls, duration, characters, training, storage, compute) are defined in the companion Non-Token Units spec (`2026-03-23-non-token-units-spec.md`).

Every modality defines all four token slots (input, output, cache read, cache write) even where no provider currently uses them. This keeps the registry symmetric. Models simply don't define prices for unused units.

### 2.2 Dimensions

Categorical attributes scoped to a family. Each dimension has a fixed set of valid values, extensible by updating the registry.

- A unit's dimension keys must be registered for its family.
- A unit's dimension values must be in that dimension's declared value set.
- Unspecified dimensions mean "unspecified / catch-all" — the unit prices whatever isn't claimed by a more specific unit.
- Specificity is determined by set inclusion: a unit with dimensions `{direction: input, modality: audio, cache: read}` is more specific than one with `{direction: input, modality: audio}`.

### 2.3 Usage Keys

Each unit has a `usage_key` — the attribute name used to look up the value from a usage object. This is an explicit field on the unit definition, not derived from a convention.

**Default:** If `usage_key` is not specified, it equals the unit ID.

**Why they can differ:** Unit IDs like `input_mtok` encode normalization (per-million). Usage values like `input_tokens` are raw counts. The `usage_key` bridges the two — the system looks up `input_tokens` on the usage object and applies the `input_mtok` price with the family's `per: 1_000_000`.

**Tokens family:** Every token unit has an explicit `usage_key` because unit IDs encode normalization (`_mtok` for per-million) while usage fields use raw counts (`_tokens`). This naming split is preserved for backward compatibility.

```python
def get_usage_key(unit: UnitDef) -> str:
    return unit.usage_key if unit.usage_key else unit.id
```

---

## 3. Usage Model

### 3.1 Representation

Usage is a flat mapping from string keys to numeric values. The engine accepts both objects and dicts:

```python
def get_usage_value(usage, key: str) -> int | None:
    if isinstance(usage, Mapping):
        return usage.get(key)
    return getattr(usage, key, None)
```

### 3.2 Backward Compatibility

`AbstractUsage` is replaced with a simple type alias (`AbstractUsage = object`) to preserve imports. The engine accesses all usage values dynamically via `getattr`/Mapping access — no typed Protocol needed. Users can pass any object with the right attributes, or any `Mapping`.

### 3.3 Overlapping Semantics

Usage values retain their current overlapping meaning. More specific values are subsets of less specific values:

```
input_tokens  {direction: input}
  cache_read_tokens    {direction: input, cache: read}
    cache_audio_read_tokens  {direction: input, modality: audio, cache: read}
  cache_write_tokens   {direction: input, cache: write}
  input_audio_tokens   {direction: input, modality: audio}
    cache_audio_read_tokens  {direction: input, modality: audio, cache: read}
```

### 3.4 Partial Data

Callers provide whatever they have. Missing values are treated as zero (no carve-out).

- **Minimal (OTel):** `{input_tokens: 1000, output_tokens: 500}` — all at catch-all rates.
- **Standard:** `{input_tokens: 1000, cache_read_tokens: 200, output_tokens: 500}` — cached portion carved out.
- **Detailed:** full breakdown including audio, image, cache variants.

---

## 4. Decomposition

When a model prices multiple units within the same family that have overlapping usage, the engine computes a **leaf value** for each priced unit: the portion of usage not claimed by any more specific priced unit. This avoids double-charging.

**Only priced units participate.** If a model doesn't price `input_audio_mtok`, audio tokens remain part of the `input_mtok` catch-all — they are not carved out. The decomposition is determined by the set of units that have prices for the current model, not the full registry.

**Negative leaf values are errors.** If decomposition produces a negative leaf value (e.g., `cache_read_tokens` exceeds `input_tokens`), the engine raises an error. The error message should identify which units are inconsistent and their values.

**Scope:** Decomposition operates within a family. Token decomposition does not affect tool call pricing. Families without hierarchical usage (e.g., tool calls, where exact counts are reported) don't need decomposition.

### Example

A model prices three token units:

- `input_mtok` at $3/M (catch-all input)
- `cache_read_mtok` at $0.30/M (cached input)
- `input_audio_mtok` at $100/M (audio input)

Usage: `{input_tokens: 1000, cache_read_tokens: 200, input_audio_tokens: 300}`

Leaf values (each unit gets only its exclusive portion):

- `input_audio_mtok`: 300 (no more-specific priced unit)
- `cache_read_mtok`: 200 (no more-specific priced unit)
- `input_mtok`: 1000 − 200 − 300 = 500 (remainder)

Cost: `(500/1M)×3 + (200/1M)×0.30 + (300/1M)×100 = $0.03156`

If the model also priced `cache_audio_read_mtok` at $0.10/M, it would be carved out of both `cache_read_mtok` and `input_audio_mtok`. The engine uses dimension relationships to determine which units overlap and applies inclusion-exclusion to avoid double-counting in the lattice structure (see reference doc for algorithm details).

---

## 5. Default Modality Convention

There is no explicit "default modality" field. Instead:

- `input_mtok` (no modality dimension) is the catch-all — it prices whatever input tokens aren't claimed by a more specific unit.
- For **text-primary models** (most models): just define `input_mtok`. The catch-all IS the text price.
- For **image-primary models**: set `input_mtok` and `input_image_mtok` to the same value (the image price), and define `input_text_mtok` with the text price.

```yaml
# Text-primary (common case)
prices:
  input_mtok: 3
  output_mtok: 15

# Image-primary with separate text pricing
prices:
  input_mtok: 5             # catch-all = image price
  input_image_mtok: 5       # explicit image = same value
  input_text_mtok: 3        # text is the exception
  output_mtok: 20
  output_image_mtok: 20
  output_text_mtok: 10
```

---

## 6. Examples

These examples use approximate prices to show how the unit system handles real pricing patterns.

### 6.1 Audio Model — OpenAI GPT-4o Realtime

```yaml
- id: gpt-4o-realtime-preview
  prices:
    input_mtok: 5
    output_mtok: 20
    cache_read_mtok: 2.5
    input_audio_mtok: 100
    output_audio_mtok: 200
    cache_audio_read_mtok: 2.5
```

Audio tokens are much more expensive than text. The catch-all `input_mtok` is the text price. Decomposition: `input_mtok` leaf = input_tokens − cache_read_tokens − input_audio_tokens + cache_audio_read_tokens.

### 6.2 Image Generation — OpenAI gpt-image-1.5

```yaml
- id: gpt-image-1-5
  prices:
    input_mtok: 5
    input_image_mtok: 8
    output_mtok: 32
    output_image_mtok: 32
```

Catch-all convention: `input_mtok` is text since there's no `input_text_mtok`. `output_mtok` and `output_image_mtok` are the same price (image is the default output modality). If someone sends only `{input_tokens: 1000, output_tokens: 500}` with no breakdown, they pay text input ($5) and image output ($32).

### 6.3 Multimodal Input — Google Gemini 2.5 Pro

```yaml
- id: gemini-2.5-pro
  prices:
    input_mtok: 1.25
    output_mtok: 10
    cache_read_mtok: 0.13
    input_audio_mtok: 0.30
    cache_audio_read_mtok: 0.03
    input_video_mtok: 0.30
    cache_read_video_mtok: 0.03
    input_image_mtok: 0.30
    cache_read_image_mtok: 0.03
```

Separate rates per modality. The catch-all `input_mtok` ($1.25) is the text rate; other modalities are cheaper. Cached variants defined for each. This model also has long-context tiers handled by the existing `TieredPrices` mechanism.

### 6.4 Image-Primary — Catch-All Convention

```yaml
- id: hypothetical-image-model
  prices:
    input_mtok: 5
    input_image_mtok: 5
    input_text_mtok: 2
    output_mtok: 20
    output_image_mtok: 20
    output_text_mtok: 10
```

Image is the default modality. Someone sending `input_tokens: 1000` with no breakdown pays the image rate ($5). Someone sending `input_tokens: 1000` and `input_text_tokens: 300` gets 300 at text ($2) and 700 at image ($5).

### 6.5 Transcription — OpenAI

```yaml
- id: gpt-4o-transcribe
  prices:
    input_mtok: 2.5
    input_audio_mtok: 2.5
    output_mtok: 10
```

Audio in (audio tokens), text out (output tokens). `input_mtok` and `input_audio_mtok` are the same price — this model only takes audio input, but the catch-all ancestor is required.

---

## 7. Data-Driven ModelPrice

### 7.1 Principle

The YAML registry is the single source of truth for valid unit IDs. **No unit IDs are hardcoded as field names in Python or JavaScript code.** Adding a new unit to `prices/units.yml` requires zero code changes — the new unit is immediately available for pricing.

### 7.2 Representation

`ModelPrice` is a dict from unit IDs to prices:

```python
# Python — dict-based, validated against registry
prices: dict[str, Decimal | TieredPrices]

# JavaScript — plain object
prices: Record<string, number | TieredPrices>
```

`requests_kcount` remains a separate field outside the registry until the Non-Token Units spec adds a `requests` family.

### 7.3 Data Pipeline

The Pydantic `ModelPrice` in the build pipeline (`prices/src/prices/prices_types.py`) validates price keys against the registry at build time. The `UsageField` literal is replaced with dynamic validation against the registry's `usage_key` values. This ensures YAML files can only reference registered unit IDs.

### 7.4 Public API

The published Python and JS packages load the compiled registry (`units_data.json`) and accept any registered unit ID as a price key. The engine iterates the registry to discover which units are priced, then runs decomposition. No code enumerates specific unit names.

### 7.5 Backward Compatibility

- `AbstractUsage` is a type alias (`= object`) preserving imports. Usage access is dynamic via `getattr`/Mapping.
- `ModelPrice` changes from fixed fields to dict-based. This is a breaking change to the construction API (`ModelPrice(input_mtok=...)` → `ModelPrice({'input_mtok': ...})`), but `calc_price` behavior is unchanged.
- Adding new units (image, video, tool calls) requires only a YAML edit — no Protocol, dataclass, or interface changes.

---

## 8. Validation Rules

- Every key in a model's `prices` must be a registered unit ID (or `requests_kcount`).
- Unit dimension keys must be registered for the unit's family.
- Unit dimension values must be in the dimension's declared value set.
- **Ancestor coverage:** If a model prices a unit, it must also price all ancestors of that unit within the same family. For example, pricing `output_image_mtok` requires also pricing `output_mtok`. Without the ancestor, usage reported at the catch-all level (e.g., `output_tokens` with no modality breakdown) would have no price.
- **Join coverage:** If a model prices two units whose join (union of dimensions) exists in the registry, it must also price the join. Without this, the Möbius inversion double-counts tokens in the intersection — each token must be in exactly one pricing bucket.
