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
- `prices/src/prices/package_data.py`

Do not change `prices/data.json` or `prices/data_slim.json` into wrapped payloads in this phase.

Also add generated startup data module `packages/js/src/dataUnits.ts`.

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
  per: number
  price_key?: string
}

export type RawUnitsDict = Record<string, RawUnitData>

export interface UnitDef {
  usageKey: string
  priceKey: string
  per: number
  dimensions: Record<string, string>
}

export class UnitRegistry {
  units: Map<string, UnitDef>
  unitsByPriceKey: Map<string, UnitDef>
  unitsByDimension: Map<string, UnitDef>
  ancestorUsageKeysByUsageKey: Map<string, Set<string>>
  allUsageKeys: Set<string>
  allPriceKeys: Set<string>
  reportedUsageKeys: Set<string>
}
```

Add raw unit types with usage keys as raw unit keys and `price_key` defaulting to the usage key. Each unit carries duplicated `per` and a required `dimensions.family` value in generated data. `UsageExtractorMapping.dest` becomes `string` so JavaScript can consume generated current-subset data and extractor outputs through registry-aware helpers. Because this widens the TypeScript surface, Phase 2 must validate every local or runtime-updated provider-data extractor destination against the active registry's externally reported usage keys before that provider data becomes active. Generated startup provider data is trusted because the build already validated it against the same registry source.

The JavaScript `UnitRegistry` class is internal to the package and mirrors Python's registry shape. It owns indexed parsed state rather than exposing loose raw dictionaries. It must keep direct indexes for usage keys, price keys, full dimension sets for join lookup, all usage keys, all price keys, reported usage keys excluding `requests`, and an ancestor usage-key index equivalent to Python's `ancestor_usage_keys`.

Public JavaScript callers still pass plain usage objects. Registry-aware reads operate on those objects directly rather than requiring a wrapper class. This preserves the existing call surface while allowing `calcPrice()`, decomposition, and extraction to share registry-aware reads internally.

**`units.ts` parses generated unit data and manages the active registry.** _(implements "The active JavaScript registry is limited to the current JavaScript unit surface")_
Implement:

```typescript
export class UnitRegistry {
  constructor(raw: RawUnitsDict)
  ancestorUsageKeys(usageKey: string): Set<string>
  findJoin(left: UnitDef, right: UnitDef): UnitDef | undefined
}
export function getActiveRegistry(): UnitRegistry
export function setActiveRegistry(registry: UnitRegistry | null): void
export function getUnit(usageKey: string): UnitDef
export function getUnitForPriceKey(priceKey: string): UnitDef
export function getUsageKeyForPriceKey(priceKey: string): string
export function getAllUsageKeys(): Set<string>
export function getAllPriceKeys(): Set<string>
```

`new UnitRegistry(raw)` indexes usage keys, price keys, and full dimension sets, validates uniqueness and interval closure, builds ancestor indexes, and skips full join-closedness for the current subset. The `family` dimension is only one entry in each unit's dimension map; units with conflicting `family` values are incompatible through ordinary dimension comparison. Active state is held as:

```typescript
const generatedRegistry = new UnitRegistry(unitData)
let activeRegistry = generatedRegistry
```

`setActiveRegistry(null)` restores `generatedRegistry`. `setActiveRegistry(registry)` installs an already-constructed registry for internal tests and future internal activation paths only. Do not export `UnitRegistry` from `packages/js/src/index.ts`, do not expose public runtime unit mutation APIs, and do not let Phase 2 provider-array runtime updates replace the active registry.

Like Python, the active current-unit subset excludes future public keys until Phase 3. Any priced compatible pair whose join is absent from that subset must fail model-price validation before decomposition.

**`usage.ts` provides registry-aware reads over plain objects.** _(implements "JavaScript preserves its plain-object public usage contract")_
Implement:

```typescript
export type NormalizedUsage = Usage
export function normalizeUsage(obj: unknown): NormalizedUsage
export function getUsageValue(usage: NormalizedUsage, usageKey: string): number
```

`normalizeUsage(...)` reads `getActiveRegistry().reportedUsageKeys`, skips the pricing-only `requests` unit, ignores extras, and stores reported values only. `getUsageValue(...)` returns stored values directly, returns `0` for unambiguous missing registered values, and raises when a missing read would require inferring an omitted ancestor or overlap. It does not infer missing values, cache derived values, or store provenance.

`calcPrice(...)` must pass caller usage directly into `getUsageValue(...)` and `computeLeafValues(...)`; it must not first call `normalizeUsage(...)` and silently drop caller-provided keys. `getUsageValue(...)` owns the registry-aware safety checks: after the fast path for a stored requested value, relationship and ambiguity scans skip usage entries whose keys are absent from the active registry. The pricing-only `requests` unit always reads as one request, regardless of any caller-provided `usage.requests` value.

The missing-read check is registry-driven and mirrors Python: a missing read is ambiguous when either a positive reported strict descendant of the requested unit exists, or the requested unit is the join of two positive reported compatible units that are incomparable with each other. A missing descendant of a reported ancestor returns `0` rather than raising because missing more-specific usage is allowed to mean "not reported".

`normalizeUsage(...)` must not reject contradictory registered values because extractor output can faithfully report provider data even when that data is internally inconsistent. Contradictions become errors only when `getUsageValue(...)` or `calcPrice(...)` must interpret affected usage. It is not the trust boundary for pricing.

**`decompose.ts` mirrors Python's dimension-driven decomposition.** _(implements "JavaScript validation mirrors Python's Phase 1 split")_
Implement:

```typescript
export function isDescendantOrSelf(ancestor: UnitDef, descendant: UnitDef): boolean

export function computeLeafValues(
  pricedUsageKeys: Set<string>,
  usage: NormalizedUsage,
  unitsByUsageKey: Map<string, UnitDef>,
): Record<string, number>
```

Use the same semantics as Phase 1 Python and the shared [../algorithm](../algorithm.md). `requests` is priced explicitly in engine code, not read from caller usage.

Do not introduce cached decomposition plans or coefficients in this phase. Direct decomposition reads explicit values through `getUsageValue(...)`, treats missing priced units as zero only when the omission is unambiguous, ignores unpriced reported values when explicit priced ancestors make them unnecessary, and raises user-facing errors when pricing would require inferring a missing ancestor or overlap.

**`validation.ts` mirrors Python's structural and price-level checks.** _(implements "JavaScript validation mirrors Python's Phase 1 split")_
Implement helpers for registry structure, interval closure, price-key validity, ancestor coverage, join coverage, model prices, provider data, and extractor destinations:

```typescript
export function validateModelPrice(priceKeys: Iterable<string>, registry: UnitRegistry = getActiveRegistry()): void
export function validateExtractorDestinations(
  providerData: Provider[],
  registry: UnitRegistry = getActiveRegistry(),
): void
```

Extractor-destination validation rejects destinations that are not externally reported usage keys in the active `UnitRegistry`, including price keys, arbitrary strings, and pricing-only `requests`. Local provider data accepted through public package APIs and provider-array runtime updates pass through this validation before replacing active provider data; generated startup provider data is trusted because the build already validated it against the same registry. In Phase 2, join coverage must fail if the current-unit subset lacks a compatible pair's join. Standard `calcPrice(...)` calls model-price validation every time before decomposition. Do not add validation marker APIs, registry validation ids, `WeakMap` cache state, or decomposition caches.

Validation iterates the current model's effective price keys and uses `UnitRegistry` indexes or relationship helpers for price-key, usage-key, ancestor, join, and reported-key checks. It must not repeatedly scan the whole registry for every model when direct indexes are available, and it must not hardcode ordinary unit names. The explicit `requests` exclusion is allowed for caller/extractor usage.

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

1. read the active `UnitRegistry`
2. validate the current model price's effective registered price-key set
3. keep caller usage as a plain object without lossy normalization
4. resolve price keys to usage-keyed units
5. compute leaf values for all non-`requests` priced units with explicit-only missing-usage checks
6. read `input_tokens` through `getUsageValue(...)` when a selected price uses `TieredPrices`
7. price `requests` as one request per usage object
8. normalize by each priced unit's `per`
9. aggregate into the existing result shape

Keep tiered-price semantics aligned with Python: tier selection reads `input_tokens` through `getUsageValue(...)`. A stored `input_tokens` total is used directly, safely missing `input_tokens` returns zero and selects the base tier, and ambiguous missing `input_tokens` raises instead of guessing a threshold.

Aggregation stays compatible with the current result shape. Costs from units whose dimensions include `{direction: input}` contribute to the existing input aggregate, units whose dimensions include `{direction: output}` contribute to the output aggregate, and units without a direction dimension such as `requests` contribute only to total.

**`api.ts` and generated startup data remain provider-array compatible.** _(implements "The shared remote payload shape remains unchanged", "JavaScript unit data stays separate from generated provider data", "Runtime updates preserve the generated registry")_
Generated `data.ts` exports only current provider data. Generated `dataUnits.ts` exports current-subset `unitData`. Startup initializes the active `UnitRegistry` from `dataUnits.ts` and makes embedded provider data active without re-validating extractor destinations, because the build already validated them. Code that supplies custom provider data can reuse the default registry without importing the bundled provider list.

Runtime update URLs still return provider arrays. Phase 2 therefore keeps update parsing compatible with the existing provider-array payload and preserves the active generated registry while replacing provider data. Local provider data and runtime update data are parsed and structurally checked against the active `UnitRegistry`, including extractor-destination validation, before they replace active provider data. If provider parsing or extractor-destination validation fails, keep the current provider data unchanged. Phase 2 still does not reject a provider update for model-price coverage; standard pricing validates the selected model price on use.

**`extractUsage.ts` returns normalized plain usage without proving consistency.** _(implements "JavaScript preserves its plain-object public usage contract", "JavaScript behavior stays aligned with Python semantics")_
Extractor output keys are registry usage keys, not fixed TypeScript unions. Extraction builds a plain object of counts, normalizes it through `normalizeUsage(...)`, and returns that normalized plain object. It does not prove provider-reported counts are mutually consistent. Contradictory registered usage values remain stored until `calcPrice(...)` needs to compute an affected priced bucket.

**Tests prove JavaScript parity and cross-language alignment.** _(implements "Phase 2 brings JavaScript to the same internal model as Phase 1 Python")_
Add JavaScript tests for generated raw unit data constructing a `UnitRegistry`, duplicate usage keys, duplicate price keys, duplicate dimensions, interval-closure failures, indexed usage-key and price-key lookups, active-registry restoration with `setActiveRegistry(null)`, current price parity, request pricing, usage normalization, unambiguous missing registered values returning zero without being materialized, ambiguous missing registered reads raising, explicit-only missing-usage pricing errors, contradictory usage interpreted only when needed, missing-join rejection, extractor output normalization, invalid extractor-destination rejection without replacing active provider data, provider-array runtime update compatibility, and alignment with the Python decomposition examples.
