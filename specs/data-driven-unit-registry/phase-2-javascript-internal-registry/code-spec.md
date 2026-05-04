# Code Spec: Phase 2 JavaScript Internal Registry Refactor

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Previous phase:** [Phase 1 Python Internal Registry Refactor](../phase-1-python-internal-registry/code-spec.md).

**Phase 2 changes only the JavaScript package and shared packaging needed for JavaScript startup data.** _(implements "Phase 2 brings JavaScript to the same internal model as Phase 1 Python")_
Add these hand-written JavaScript/TypeScript modules:

- `packages/js/src/units.ts`
- `packages/js/src/usage.ts`
- `packages/js/src/decompose.ts`
- `packages/js/src/validation.ts`

Modify:

- `packages/js/src/types.ts`
- `packages/js/src/engine.ts`
- `packages/js/src/api.ts`
- `packages/js/src/extractUsage.ts`
- `packages/js/src/data.ts` (generated)
- `packages/js/src/dataUnits.ts` (generated)
- `prices/src/prices/package_data.py`

Do not change `prices/data.json` or `prices/data_slim.json` into wrapped payloads in this phase.

**`types.ts` becomes registry-compatible for usage, prices, and units.** _(implements "JavaScript preserves its plain-object public usage contract")_
Represent caller usage and model prices as open records:

```typescript
export type Usage = Record<string, number | undefined>
export type ModelPrice = Record<string, number | TieredPrices | undefined>

export interface UsageExtractorMapping {
  dest: string
  path: ExtractPath
  required: boolean
}

export interface RawUnitData {
  dimensions: Record<string, string>
  price_key?: string
}

export interface RawFamilyData {
  description: string
  per: number
  units: Record<string, RawUnitData>
}

export type RawFamiliesDict = Record<string, RawFamilyData>

export interface UnitDef {
  usageKey: string
  priceKey: string
  familyId: string
  family: UnitFamily
  dimensions: Record<string, string>
}

export interface UnitFamily {
  id: string
  per: number
  description: string
  units: Record<string, UnitDef>
}

export type ParsedFamilies = Record<string, UnitFamily>
```

Add raw and parsed unit-family types with usage keys as raw unit keys and `price_key` defaulting to the usage key. `UsageExtractorMapping.dest` becomes `string` so JavaScript can consume generated current-subset data and extractor outputs through registry-aware helpers. Phase 2 does not add authoritative extractor-destination validation to runtime updates or the remote authoring surface; that starts in Phase 3 when wrapped payload export validation owns providers and unit families together.

Public JavaScript callers still pass plain usage objects. The normalization step returns another plain object rather than a wrapper class. This preserves the existing call surface while allowing `calcPrice()`, decomposition, and extraction to share registry-aware reads internally.

**`units.ts` parses generated unit family data and manages the active registry.** _(implements "The active JavaScript registry is limited to the current JavaScript unit surface")_
Implement:

```typescript
export function parseFamilies(raw: RawFamiliesDict): ParsedFamilies
export function setUnitFamilies(families: ParsedFamilies | null): void
export function getFamily(familyId: string): UnitFamily
export function getUnit(usageKey: string): UnitDef
export function getUnitForPriceKey(priceKey: string): UnitDef
export function getUsageKeyForPriceKey(priceKey: string): string
export function getAllUsageKeys(): Set<string>
export function getAllPriceKeys(): Set<string>
```

`parseFamilies(...)` fills family back-references, indexes price keys, validates uniqueness and interval closure, and skips full join-closedness for the current subset. `setUnitFamilies(null)` restores the generated bundled registry. Do not expose public runtime unit mutation APIs.

Like Python, the active current-unit subset excludes future public keys until Phase 3. Any priced compatible pair whose join is absent from that subset must fail model-price validation before decomposition.

**`usage.ts` provides registry-aware reads over plain objects.** _(implements "JavaScript preserves its plain-object public usage contract")_
Implement:

```typescript
export type NormalizedUsage = Usage
export function normalizeUsage(obj: unknown): NormalizedUsage
export function getUsageValue(usage: NormalizedUsage, usageKey: string): number
```

`normalizeUsage(...)` reads known externally reported usage keys, skips the pricing-only `requests` unit, ignores extras, and stores reported values only. `getUsageValue(...)` returns stored values directly, lazily infers missing values when uniquely determined, returns zero for no relevant data, and throws user-facing errors for contradictory or underdetermined required inference. It does not cache inferred values or store provenance.

`normalizeUsage(...)` must not reject contradictory registered values because extractor output can faithfully report provider data even when that data is internally inconsistent. Contradictions become errors only when `getUsageValue(...)` or `calcPrice(...)` must interpret them.

**`decompose.ts` mirrors Python's dimension-driven decomposition.** _(implements "JavaScript validation mirrors Python's Phase 1 split")_
Implement:

```typescript
export function isDescendantOrSelf(ancestor: UnitDef, descendant: UnitDef): boolean

export function computeLeafValues(
  pricedUsageKeys: Set<string>,
  usage: NormalizedUsage,
  family: UnitFamily,
): Record<string, number>
```

Use the same semantics as Phase 1 Python and the shared [../algorithm](../algorithm.md). The requests family is priced explicitly in engine code, not read from caller usage.

Do not introduce cached decomposition plans or coefficients in this phase. Direct decomposition reads missing values through `getUsageValue(...)`, ignores unpriced reported values unless needed to infer a missing priced value, and raises user-facing errors for impossible priced buckets.

**`validation.ts` mirrors Python's structural and price-level checks.** _(implements "JavaScript validation mirrors Python's Phase 1 split")_
Implement helpers for registry structure, interval closure, price-key validity, ancestor coverage, join coverage, model prices, and provider data. Extractor-destination validation helpers may exist for parity with Python and Phase 3 reuse, but Phase 2 only uses them in tests or local helper-level checks, not as an authoritative runtime-update gate. In Phase 2, join coverage must fail if the current-unit subset lacks a compatible pair's join. Standard `calcPrice(...)` calls model-price validation every time before decomposition. Do not add activation-time model-price validation, validation marker APIs, registry validation ids, `WeakMap` trust state, or decomposition caches.

Validation iterates the current model's effective price keys and uses parsed registry indexes or relationship helpers. It must not repeatedly scan the whole registry for every model when direct indexes are available, and it must not hardcode ordinary unit names. The explicit `requests` exclusion is allowed for caller/extractor usage.

**`engine.ts` switches from hardcoded arithmetic to registry-driven pricing.** _(implements "Phase 2 brings JavaScript to the same internal model as Phase 1 Python")_
`calcUnitPrice(...)` replaces token-specific helper logic, and `calcPrice(...)` becomes registry-driven:

```typescript
function calcUnitPrice(
  price: number | TieredPrices | undefined,
  count: number | undefined,
  totalInputTokens: number,
  per: number,
): number

export function calcPrice(usage: Usage, modelPrice: ModelPrice): ModelPriceCalculationResult
```

`calcPrice(usage, modelPrice)` should:

1. read the active parsed registry
2. validate the current model price's effective registered price-key set
3. normalize raw usage
4. read `input_tokens` only when tiered prices need the threshold
5. resolve price keys and group by family
6. compute per-family leaf values
7. price `requests` as one request per usage object
8. normalize by `family.per`
9. aggregate into the existing result shape

Keep tiered-price semantics aligned with Python: a stored `input_tokens` total is used directly for tier selection, and missing totals are inferred only when coherent.

Aggregation stays compatible with the current result shape. Costs from units whose dimensions include `{direction: input}` contribute to the existing input aggregate, units whose dimensions include `{direction: output}` contribute to the output aggregate, and families without a direction dimension such as `requests` contribute only to total.

**`api.ts` and generated startup data remain provider-array compatible.** _(implements "The shared remote payload shape remains unchanged", "JavaScript unit data stays separate from generated provider data", "Runtime updates stay atomic for provider data and registry state")_
Generated `data.ts` exports only current provider data. Generated `dataUnits.ts` exports current-subset `unitFamiliesData`. Startup initializes the active parsed registry from `dataUnits.ts`, so code that supplies custom provider data can reuse the default registry without importing the bundled provider list.

Runtime update URLs still return provider arrays. Phase 2 therefore keeps update parsing compatible with the existing provider-array payload and preserves the active generated registry while replacing provider data. Local staged provider data can be parsed and structurally checked against the active parsed registry, but Phase 2 does not reject a staged update for model-price coverage; standard pricing validates the selected model price on use and leaves activation-time model-price validation to Phase 5.

**`extractUsage.ts` returns normalized plain usage without proving consistency.** _(implements "JavaScript preserves its plain-object public usage contract", "JavaScript behavior stays aligned with Python semantics")_
Extractor output keys are registry usage keys, not fixed TypeScript unions. Extraction builds a plain object of counts, normalizes it through `normalizeUsage(...)`, and returns that normalized plain object. It does not prove provider-reported counts are mutually consistent. Contradictory registered usage values remain stored until `getUsageValue(...)` or `calcPrice(...)` needs to infer a missing value or compute a priced bucket.

**Tests prove JavaScript parity and cross-language alignment.** _(implements "Phase 2 brings JavaScript to the same internal model as Phase 1 Python")_
Add JavaScript tests for current price parity, request pricing, usage normalization, lazy inference, contradictory usage interpreted only when needed, missing-join rejection, extractor output normalization, provider-array runtime update compatibility, and alignment with the Python decomposition examples.
