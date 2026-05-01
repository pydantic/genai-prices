# Code Spec: Phase 3 Shared Data Contract and Base Dynamic Price Keys

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Previous phase:** [Phase 2 JavaScript Internal Registry Refactor](../phase-2-javascript-internal-registry/code-spec.md).

**Phase 3 changes the shared generated data contract.** _(implements "`data.json` and `data_slim.json` become wrapped top-level objects", "Unit definitions travel with the prices that depend on them")_
Change both generated JSON payloads to:

```json
{
  "unit_families": {
    "tokens": { "...": "..." },
    "requests": { "...": "..." }
  },
  "providers": [{ "...": "..." }]
}
```

`unit_families` carries raw registry data from `prices/units.yml`. `providers` keeps the existing provider object shape. `data_slim.json` keeps the runtime unit-family fields and applies slimming only to provider data.

Do not keep writing a provider-array compatibility payload in parallel, and do not add a separate runtime unit artifact. The wrapper is the single shared runtime-update contract for this phase.

The generated `data.json` schema also changes to describe this wrapped payload shape. Provider YAML authoring schemas are different: they remain editor/autocomplete support and become registry-derived in Phase 4, after the authoritative wrapped payload and export validation exist.

**`prices/units.yml` expands to the complete repo-defined registry.** _(implements "The complete repo-defined registry starts here")_
The built-in `tokens` family now includes the complete symmetric Phase 3 unit lattice needed by the prose spec. Each modality gets the same valid input/output/cache-read/cache-write patterns where those concepts make sense; nonsensical combinations such as output cache reads are not added. The `requests` family remains the explicit one-request-per-usage-object pricing unit.

`UnitRegistry` construction now validates full join-closedness for every family. The Phase 1/2 missing-join exception is removed for complete registries.

**Generated package data reads and emits wrapped payloads.** _(implements "Unit definitions travel with the prices that depend on them")_
Update `prices/src/prices/package_data.py` so Python and JavaScript package data generation reads wrapped `data.json`, splits `providers` and `unit_families`, and emits:

```python
def package_data() -> None: ...
def package_python_data(data_path: Path) -> None: ...
def package_ts_data(data_path: Path) -> None: ...
```

```python
# packages/python/genai_prices/data.py
__all__ = ('providers', 'unit_families_data')
unit_families_data: dict[str, dict] = { ... }
providers: list[Provider] = [ ... ]
```

```typescript
// packages/js/src/data.ts
export const unitFamiliesData: RawFamiliesDict = { ... }
export const data: Provider[] = [ ... ]
```

Generated outputs contain raw unit and price data only. They must not contain validation markers, trust flags, fingerprints, or decomposition caches.

**Build/export validation becomes the publication trust boundary.** _(implements "Provider prices and extractor destinations validate against the same registry payload")_
Expose and use a reusable helper:

```python
def validate_export_payload(
    providers: list[Provider],
    unit_families: dict[str, dict],
) -> UnitRegistry:
    """Validate registry structure and all provider model prices before export."""
```

`build()` should load `prices/units.yml`, parse provider YAML, call `validate_export_payload(...)`, validate extractor destinations against externally reported usage keys, and only then write wrapped `data.json` and `data_slim.json`. External publishers can reuse the helper before hosting a payload for `UpdatePrices(url=...)`.

The complete Phase 3 build/write flow is:

```python
def build() -> None:
    """Build provider/editor schemas plus wrapped runtime data payloads."""

def write_prices(
    providers: list[Provider],
    unit_families: dict[str, dict],
    prices_file: str,
    *,
    slim: bool = False,
) -> None:
    """Write one wrapped prices payload."""
```

`UpdatePrices.fetch()` and JavaScript runtime update code do not call this helper for every fetched payload. They parse the wrapper, construct/structurally validate the registry, parse providers, and treat fetched model prices as prevalidated by the publisher.

The helper name and boundary are intentional. Do not bury full price-level validation only inside a repo-local command that discovers YAML files and writes outputs. The reusable helper accepts already parsed providers plus raw `unit_families`, constructs and validates `UnitRegistry`, validates model price keys, resolves price keys to usage keys, checks ancestor and join coverage, validates extractor destinations, and returns the validated registry or raises.

**Build-time provider models become registry-permissive.** _(implements "Provider prices and extractor destinations validate against the same registry payload")_
In `prices/src/prices/prices_types.py`, build-time `ModelPrice` no longer uses hardcoded fields as the accepted price-key whitelist. Use a registry-permissive shape such as Pydantic extra-allowed storage for price values, then rely on export validation to reject unknown price keys. `UsageExtractorMapping.dest` becomes `str`; export validation rejects destinations that are not externally reported usage keys or that target pricing-only `requests`.

**Python base `ModelPrice` gains dynamic price-key storage.** _(implements "Python base `ModelPrice` accepts registered non-hardcoded price keys")_
Add `_extra_prices: dict[str, Decimal | TieredPrices | None]` to base `ModelPrice`. Its constructor accepts legacy fields plus candidate non-hardcoded price keys, stores candidates in `_extra_prices`, and defers acceptance/rejection until validation receives a registry.

`__getattr__`, supported assignment, deletion, `is_free()`, string rendering, and effective price-key iteration must include both legacy fields and `_extra_prices`. Any `_extra_prices` key that is not registered in the validation registry is invalid. Declared subclass-only custom fields remain custom override state unless their names are also registered price keys.

**Python pricing validates dynamic price data on use.** _(implements "Python base `ModelPrice` accepts registered non-hardcoded price keys", "Runtime validation caching still waits for Phase 5")_
`set_custom_snapshot(snapshot)` does not perform model-price validation in Phase 3. Standard base `ModelPrice.calc_price(...)` validates candidate dynamic keys, ancestor coverage, and join coverage against the active snapshot registry every time before calculating against the selected model price. Misspelled dynamic keys and incomplete dynamic price sets therefore fail on use. Activation-time model-price validation and trust records remain Phase 5 work.

**Runtime update paths parse wrapped payloads atomically.** _(implements "`data.json` and `data_slim.json` become wrapped top-level objects")_
Python `UpdatePrices.fetch()` parses `unit_families` and `providers`, constructs `UnitRegistry(raw['unit_families'])`, and returns `DataSnapshot(providers=..., unit_registry=...)`:

```python
class UpdatePrices:
    def fetch(self) -> DataSnapshot | None:
        """Fetch wrapped data, parse unit_families and providers, and return a staged snapshot."""
```

JavaScript `api.ts` stages runtime updates in this order:

1. parse wrapped JSON
2. parse and structurally validate `unit_families`
3. parse providers
4. on success only, replace active unit families and active provider data

If parsing or structural registry validation fails, both active registry and active provider data remain unchanged. Runtime update activation does not perform model-price coverage validation in Phase 3; standard pricing validates the selected model price on use. Checked-in JavaScript examples that cache provider data must cache and restore the wrapped payload shape.

`updatePrices()` passes both provider-data and unit-family activation callbacks through the storage factory:

```typescript
export interface StorageFactoryParams {
  onCalc: (cb: () => void) => void
  remoteDataUrl: string
  setProviderData: (data: ProviderDataPayload) => void
  setUnitFamilies: (families: ParsedFamilies | null) => void
}
```

Checked-in JavaScript browser and node examples that cache provider data must cache and restore the wrapped payload shape, not a bare provider array, and parse families before calling both `setUnitFamilies(stagedFamilies)` and `setProviderData(...)`.

Generated Python and JavaScript package data remain pure data. They must not contain validation markers, trust flags, fingerprints, marker constructor arguments, decomposition plans, or cached coefficients. Runtime-private trust state starts in Phase 5.

**Tests cover the wrapper and dynamic-key boundary.** _(implements "Phase 3 makes repo-defined units an end-to-end feature")_
Add tests for wrapped full/slim payload schemas, Python and JavaScript runtime update parsing, generated package data exports, complete-registry join-closedness, build/export validation for prices and extractor destinations, base Python `ModelPrice` with a registered non-hardcoded key, rejection of misspelled dynamic keys during pricing, no Phase 3 activation-time model-price validation, and unchanged generated-output purity with no validation artifacts.
