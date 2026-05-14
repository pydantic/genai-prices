# Code Spec: Phase 3 Core Registry and Shared Data Contract

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Baseline:** this consolidated phase includes the completed Python registry runtime, JavaScript registry runtime, and shared wrapped payload contract.

**Keep the shared behavior in the root spec central.** _(implements "Phase 3 makes repo-defined units work end to end")_
Read [../spec](../spec.md) for the pricing invariants and [../algorithm](../algorithm.md) plus [../examples](../examples.md) for decomposition examples. This code spec is the implementation source of truth for the core registry system; Phase 4 and Phase 5 describe only later polish and performance deltas.

**Source units are flat, usage-keyed data.** _(implements "The registry is the source of unit truth")_
Maintain `prices/units.yml` as the checked-in source registry. Each raw unit is keyed by usage key and carries:

```yaml
input_tokens:
  per: 1_000_000
  price_key: input_mtok
  dimensions: { family: tokens, direction: input }
requests:
  per: 1_000
  price_key: requests_kcount
  dimensions: { family: requests }
```

`price_key` defaults to the usage key when omitted. `per` is duplicated on every unit, and build/export validation requires one `per` value per `dimensions.family` value. The built-in token registry includes the complete repo-defined lattice needed for input/output, cache read/write, and modality overlaps where those concepts make sense; nonsensical combinations such as output cache reads are not added. `requests` remains the only pricing-only built-in unit and represents one request per pricing calculation.

Built-in token symmetry is a data choice, not a validation law. Future family dimension values do not need every dimension value to have the same shape; they only need to satisfy the structural rules for the units they actually define.

**Runtime registries own parsed graph indexes.** _(implements "The registry is the source of unit truth")_
Python `genai_prices.units` and JavaScript `units.ts` define `UnitDef` plus `UnitRegistry`. Runtime registry construction promotes trusted raw usage keys into parsed units, defaults missing price keys, and fills direct indexes for usage keys, price keys, full dimension sets, ancestor usage keys, joins, all usage keys, all price keys, and externally reported usage keys. `UnitRegistry` is an indexing/parsing object, not the runtime unit validation boundary; bundled and fetched unit payloads are trusted publisher output. `family` is an ordinary dimension, so units from different families are incompatible by ordinary dimension conflict.

Build/export unit validation has two separate structural closure checks. For interval closure, if unit `A` is an ancestor of unit `B`, every dimension set formed by adding a non-empty proper subset of `B.dimensions - A.dimensions` to `A.dimensions` must also exist as a unit. For join-closedness, two units are compatible when they have no conflicting value for the same dimension key; their join is the union of both dimension sets and must exist in the complete registry.

Do not generate source-code fields into handwritten runtime modules. Generated package files may contain raw unit data, but behavior belongs in runtime lookups against `UnitRegistry`.

**Build/export validation is reusable and authoritative.** _(implements "Publication validation is the trust boundary")_
Expose a Python build/export helper equivalent to:

```python
def validate_export_payload(
    providers: list[Provider],
    units: dict[str, dict],
) -> UnitRegistry:
    """Validate registry structure, provider prices, and extractor destinations."""
```

The helper validates publishable unit data, public key safety, provider model price keys, ancestor coverage, join coverage, and extractor destinations. It accepts already parsed providers plus raw units so external payload publishers can reuse the same trust boundary before hosting update data. Runtime package startup and runtime fetch paths do not re-run publication validation for every payload.

Public key validation rejects obvious unsafe names for usage keys and price keys: names outside the shared ASCII identifier subset, names beginning with `_`, Python keywords, JavaScript keywords, and tiny generic prototype-like hazards such as `__proto__`, `prototype`, and `constructor`. It must not hardcode commercial pricing names.

**Generated data is split and pure.** _(implements "The shared payload is a wrapped object")_
`build()` writes both runtime JSON payloads as:

```json
{
  "units": { "input_tokens": { "...": "..." } },
  "providers": [{ "...": "..." }]
}
```

`data_slim.json` slims provider descriptive data only; unit runtime fields remain present. `prices/src/prices/package_data.py` reads the wrapped payload and emits provider data separately from unit data:

- Python `data.py` exports `providers`
- Python `data_units.py` exports `unit_data`
- JavaScript `data.ts` exports provider data
- JavaScript `dataUnits.ts` exports `unitData`

Generated JSON and language-native files contain raw units, providers, and raw prices only. They must not contain validation markers, trust flags, price-key fingerprints, cached decomposition plans, or generated runtime behavior.

**Python usage is registry-aware and stores reported values only.** _(implements "Usage remains explicit-only", "Python keeps compatibility while accepting dynamic price keys")_
`Usage` is a normal class backed by reported values, not a fixed dataclass field list. Direct `Usage(...)` construction accepts externally reported registry usage keys and rejects unknown keys plus pricing-only `requests`. `Usage.from_raw(obj)` reads known externally reported attributes from dataclasses, namespace objects, and other attribute objects while ignoring extras. It does not read plain mappings as Python `calc_price` input compatibility.

Registered attribute reads return stored values directly, return zero for safe missing values without materializing that zero, and raise when positive related values make the missing read ambiguous. Missing ancestors and missing overlaps are not inferred. Assignment to a registered externally reported usage key stores or clears a reported value; assignment to non-registered names remains ordinary object assignment.

`Usage` does not preserve fixed-field dataclass introspection such as `dataclasses.asdict(...)`; construction, attribute reads, equality, representation, addition, raw wrapping, and field mutation are the supported compatibility surface.

**Python `ModelPrice` prices through the active registry.** _(implements "Python keeps compatibility while accepting dynamic price keys", "Complete price data is required before pricing")_
Keep legacy dataclass fields for existing price keys and add `_extra_prices` for candidate non-hardcoded price keys. Base construction, runtime provider parsing, assignment, deletion, `__getattr__`, string rendering, and effective price-key iteration must include both legacy fields and dynamic extra prices. Every non-`None` `_extra_prices` key participates in validation, including misspellings.

Base `ModelPrice.calc_price(usage)`:

1. reads the active global registry
2. validates this model price's effective price-key set against that registry
3. wraps raw usage through `Usage.from_raw(...)` for the base method only
4. resolves price keys to usage-keyed units
5. computes exclusive values for all non-`requests` priced units
6. reads `input_tokens` through `Usage` only when a selected price uses `TieredPrices`
7. prices `requests` as one request per calculation
8. normalizes each unit by its `per`
9. aggregates costs by `direction` into existing input/output/total results

`ModelInfo.calc_price(...)` passes the original usage object to the selected price object so custom overrides can inspect non-registry fields. Declared subclass-only fields remain custom override state unless the active registry also names them as price keys. Plain dataclass subclass constructors accepting undeclared dynamic price-key kwargs are Phase 4 polish.

**Python snapshots remain provider-only while units are global.** _(implements "The active runtime registry is global")_
`DataSnapshot` does not gain a unit registry field. Bundled provider snapshots load generated providers from `data.py`; the bundled registry loads generated unit data from `data_units.py`. `set_custom_snapshot(snapshot)` keeps its public signature and does not bulk-validate model prices. Standard base pricing validates the selected model price on use.

`UpdatePrices.fetch()` parses wrapped JSON, builds `UnitRegistry(raw["units"])` as trusted published data, saves the previous active registry, installs the candidate registry, parses providers into a `DataSnapshot`, and restores the previous registry if provider parsing or activation fails. It does not compare fetched units against bundled or previously fetched units, because published registry evolution is expected to be compatible and additive in practice. `UpdatePrices.stop()` resets the active registry to bundled units when it clears the auto-updated provider snapshot.

**Python extractor destinations are registry usage keys.** _(implements "Extractor destinations are externally reported usage keys")_
Runtime `UsageExtractorMapping.dest` is `str`. `UsageExtractor` construction validates every destination against externally reported usage keys from the active registry, rejecting price keys, arbitrary strings, and pricing-only `requests`. Extraction accumulates counts by usage key and returns `Usage(**values)`. It does not certify that provider usage counts are internally coherent.

**JavaScript types are open records with registry validation.** _(implements "JavaScript keeps plain-object usage and provider APIs")_
Represent public usage and model prices as open records:

```typescript
export type Usage = Record<string, number | undefined>
export type ModelPrice = Record<string, number | TieredPrices | undefined>
export interface UsageExtractorMapping {
  dest: string
  path: ExtractPath
  required: boolean
}
```

`RawUnitData`, `RawUnitsDict`, `UnitDef`, and internal `UnitRegistry` mirror the Python unit model. Do not export public registry mutation APIs from the package root. Provider data accepted through public APIs or runtime updates validates extractor destinations before it becomes active; generated startup provider data is trusted because export validation already checked it.

**JavaScript usage and pricing read caller objects directly.** _(implements "JavaScript keeps plain-object usage and provider APIs", "Usage remains explicit-only")_
`normalizeUsage(...)` returns a plain object reduced to externally reported registry usage keys for extractor output and other normalized-return paths. Standard pricing must not normalize first and silently discard caller-provided registered keys. `getUsageValue(usage, usageKey)` reads the caller object directly, skips unknown extras during ambiguity scans, returns stored values directly, returns zero for safe missing reads, and raises when a missing value would require inference.

`calcPrice(usage, modelPrice)` follows the same registry-driven flow as Python: validate effective price keys, decompose non-`requests` priced units, read `input_tokens` for tiered prices through `getUsageValue(...)`, price `requests` explicitly, normalize by `per`, and aggregate into the existing JavaScript result shape.

**JavaScript runtime updates are wrapper-aware.** _(implements "The active runtime registry is global", "JavaScript keeps plain-object usage and provider APIs")_
`api.ts` parses wrapped payloads by building `new UnitRegistry(units)`, saving the previous active registry, installing the candidate, parsing providers, and restoring the previous registry if provider activation fails. It does not enforce registry-history compatibility or attach an exact registry to each provider snapshot; a newer compatible registry may contain additional units that older provider data ignores. `setProviderData` remains the single public setter and accepts:

- `null` as a no-op
- a legacy bare provider array, which updates providers and leaves the active registry unchanged
- a wrapped `{ units, providers }` payload, which updates the active registry and providers together
- a promise resolving to one of those values

Checked-in JavaScript examples that cache provider data can keep forwarding parsed JSON into `setProviderData`; stale bare-array caches keep bundled units, and fresh fetches evolve to the wrapped shape.

**Decomposition and validation stay uncached in Phase 3.** _(implements "Runtime performance state waits for Phase 5")_
Price-level validation checks registered price keys, ancestor coverage, and join coverage every time standard base pricing calculates against a selected model price. Decomposition computes exclusive buckets directly from the active registry and explicit usage reads. Negative exclusive values raise user-facing errors about impossible usage relationships. Do not add validation ids, weak maps, fingerprints, validation caches, decomposition caches, or model-wide pricing-plan objects.

**Tests cover the consolidated core behavior.** _(implements "Phase 3 makes repo-defined units work end to end")_
Cover Python and JavaScript current price parity, request pricing, registry construction, duplicate usage keys, duplicate price keys, duplicate dimensions, interval closure, full join-closedness in export validation, public key-name rejection, usage safe-missing and ambiguous-missing reads, explicit-only pricing errors, contradictory usage interpreted only when needed, ancestor and join price validation, extractor destination rejection, wrapped full/slim payload schemas, generated package data exports, runtime update rollback on provider activation failure, Python dynamic base price keys, misspelled dynamic key rejection on use, no provider-activation model-price validation, generated-output purity, and alignment with the shared decomposition examples.
