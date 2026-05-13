# Code Spec: Phase 3 Shared Data Contract and Base Dynamic Price Keys

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Previous phase:** [Phase 2 JavaScript Internal Registry Refactor](../phase-2-javascript-internal-registry/code-spec.md).

**Phase 3 changes the shared generated data contract.** _(implements "`data.json` and `data_slim.json` become wrapped top-level objects", "Unit definitions travel with the prices that depend on them")_
Change both generated JSON payloads to:

```json
{
  "units": {
    "input_tokens": { "...": "..." },
    "requests": { "...": "..." }
  },
  "providers": [{ "...": "..." }]
}
```

`units` carries raw registry data from `prices/units.yml`. `providers` keeps the existing provider object shape. `data_slim.json` keeps the runtime unit fields and applies slimming only to provider data.

Do not keep writing a provider-array compatibility payload in parallel, and do not add a separate runtime unit artifact. The wrapper is the single shared runtime-update contract for this phase.

The generated `data.json` schema also changes to describe this wrapped payload shape. Provider YAML authoring schemas are different: they remain editor/autocomplete support and become registry-derived in Phase 4, after the authoritative wrapped payload and export validation exist.

**`prices/units.yml` expands to the complete repo-defined registry.** _(implements "The complete repo-defined registry starts here")_
The built-in `tokens` family-dimension value now includes the complete symmetric Phase 3 unit lattice needed by the prose spec. Each modality gets the same valid input/output/cache-read/cache-write patterns where those concepts make sense; nonsensical combinations such as output cache reads are not added. The `requests` family-dimension value remains the explicit one-request-per-usage-object pricing unit.

The complete built-in Phase 3 unit inventory is:

```yaml
input_tokens:
  per: 1_000_000
  price_key: input_mtok
  dimensions: { family: tokens, direction: input }
output_tokens:
  per: 1_000_000
  price_key: output_mtok
  dimensions: { family: tokens, direction: output }
cache_read_tokens:
  per: 1_000_000
  price_key: cache_read_mtok
  dimensions: { family: tokens, direction: input, cache: read }
cache_write_tokens:
  per: 1_000_000
  price_key: cache_write_mtok
  dimensions: { family: tokens, direction: input, cache: write }
# ... modality/cache combinations follow the same flat shape ...
requests:
  per: 1_000
  price_key: requests_kcount
  dimensions: { family: requests }
```

Every unit must declare `dimensions.family`. Build/export validation requires all units with the same family value to repeat the same `per`, rejects duplicate full dimension sets, and validates full join-closedness. Runtime registry code treats `family` as an ordinary dimension. The Phase 1/2 missing-join exception is removed for complete published registries.

`UnitRegistry` remains the runtime index builder for trusted bundled or fetched unit data. Unit-only publication validation belongs in the Python build/export pipeline, not in runtime startup or runtime update paths.

Add lightweight public-key safety validation to the build/export unit validation path, equivalent to:

```python
def validate_units(units: dict[str, dict]) -> UnitRegistry:
    """Validate publishable unit data and return the indexed registry."""
```

Implement this helper only in Python build tooling, currently `prices/src/prices/export_validation.py`. Reject obvious unsafe public names for every usage key and price key: names that are not JavaScript-compatible ASCII identifiers, names beginning with `_`, and JavaScript keywords. A tiny generic reserved set such as `__proto__`, `prototype`, and `constructor` may be rejected too, but do not build a large cross-runtime collision system and do not hardcode commercial pricing concepts. This validation runs before publication through `validate_export_payload(...)`; generated package startup and fetched wrapped-payload parsing trust the published unit data. Do not add or keep a TypeScript/runtime `validateUnits` helper; JavaScript should construct `new UnitRegistry(...)` directly from trusted generated or fetched unit data.

**Generated package data reads wrapped payloads and emits split modules.** _(implements "Unit definitions travel with the prices that depend on them")_
Update `prices/src/prices/package_data.py` so Python and JavaScript package data generation reads wrapped `data.json`, splits `providers` and `units`, and emits providers separately from unit definitions:

Python provider parsing during package generation installs the in-memory registry built from the same wrapped payload while rebuilding and validating the Pydantic provider schema, then resets the active registry in a `finally` block. This avoids validating provider prices and extractor destinations against stale bundled `data_units.py` while regenerating those files.

```python
def package_data() -> None: ...
def package_python_data(data_path: Path) -> None: ...
def package_ts_data(data_path: Path) -> None: ...
```

```python
# packages/python/genai_prices/data.py
__all__ = ('providers',)
providers: list[Provider] = [ ... ]
```

```python
# packages/python/genai_prices/data_units.py
__all__ = ('unit_data',)
unit_data: dict[str, dict] = { ... }
```

```typescript
// packages/js/src/data.ts
export const data: Provider[] = [ ... ]
```

```typescript
// packages/js/src/dataUnits.ts
export const unitData: RawUnitsDict = { ... }
```

Generated outputs contain raw unit and price data only. They must not contain validation markers, trust flags, fingerprints, or decomposition caches.

For reviewable green commits, package-data readers may be made transition-compatible before the wrapped JSON files are regenerated: they can accept the current bare provider-list payload with a build-only `units.yml` fallback, and the new wrapped payload without that fallback. Once `data.json` is wrapped, remove the temporary bare-list path and any package-generation reload of `units.yml` in the follow-up cleanup.

**Build/export validation becomes the publication trust boundary.** _(implements "Provider prices and extractor destinations validate against the same registry payload")_
Expose and use a reusable helper:

```python
def validate_export_payload(
    providers: list[Provider],
    units: dict[str, dict],
) -> UnitRegistry:
    """Validate registry structure, provider model prices, and extractor destinations before export."""
```

`build()` should load `prices/units.yml`, parse provider YAML, call `validate_export_payload(...)`, and only then write wrapped `data.json` and `data_slim.json`. Extractor destination validation lives inside `validate_export_payload(...)` so external publishers get the same authoritative checks before hosting a payload for `UpdatePrices(url=...)`.

The complete Phase 3 build/write flow is:

```python
def build() -> None:
    """Build provider/editor schemas plus wrapped runtime data payloads."""

def write_prices(
    providers: list[Provider],
    units: dict[str, dict],
    prices_file: str,
    *,
    slim: bool = False,
) -> None:
    """Write one wrapped prices payload."""
```

`UpdatePrices.fetch()` and JavaScript runtime update code do not call this helper for every fetched payload. They parse the wrapper, build runtime registry indexes from trusted `units`, install that registry as global runtime state, parse or activate providers, and treat fetched unit data and model prices as prevalidated by the publisher.

The helper name and boundary are intentional. Do not bury publication validation only inside a repo-local command that discovers YAML files and writes outputs. The reusable Python build/export helper accepts already parsed providers plus raw `units`, validates unit publication rules, builds the `UnitRegistry`, validates model price keys, resolves price keys to usage keys, checks ancestor and join coverage, validates extractor destinations, and returns the validated registry or raises. Runtime packages do not carry unit-only publication validators.

**Build-time provider models become registry-permissive.** _(implements "Provider prices and extractor destinations validate against the same registry payload")_
In `prices/src/prices/prices_types.py`, build-time `ModelPrice` no longer uses hardcoded fields as the accepted price-key whitelist. Keep the existing explicit legacy price fields for provider YAML schema/autocomplete until Phase 4 derives those authoring schemas from the registry, and add typed extras for non-hardcoded registry keys. Set `model_config = ConfigDict(extra='allow')` and annotate `__pydantic_extra__: dict[str, DollarPrice | TieredPrices]` so Pydantic v2 validates each extra natively (`Gt(0)`, tier shape, JSON schema `additionalProperties` all derive from this annotation). `ModelPrice.is_free()` must evaluate declared fields plus typed extras so slim-data generation does not drop paid models whose prices are only registry-defined extras. Export validation then rejects unknown price keys against the registry. `UsageExtractorMapping.dest` becomes `str`; export validation rejects destinations that are not externally reported usage keys or that target pricing-only `requests`.

**Python base `ModelPrice` gains dynamic price-key storage.** _(implements "Python base `ModelPrice` accepts registered non-hardcoded price keys")_
Add `_extra_prices: dict[str, Decimal | TieredPrices | None]` to base `ModelPrice`. Its constructor accepts legacy fields plus candidate non-hardcoded price keys, stores candidates in `_extra_prices`, and defers acceptance/rejection until validation receives a registry.

Dynamic price-key storage must work for provider data parsed through the runtime Pydantic boundary, not only for direct Python construction. `providers_schema.validate_json(...)` must preserve non-hardcoded model price keys from provider payloads into `ModelPrice._extra_prices`, with values validated/coerced the same way as legacy model price values. A post-decoration `__init__(**extras)` override is insufficient unless the Pydantic dataclass parsing path also routes unknown price-key properties into `_extra_prices`.

`__getattr__`, supported assignment, deletion, `is_free()`, string rendering, and effective price-key iteration must include both legacy fields and `_extra_prices`. Effective-key collection may filter dataclass fields through the active registry so subclass-only custom fields remain outside registry pricing, but it must not pre-filter `_extra_prices` through registry resolution. Every non-`None` `_extra_prices` key is validation input, including misspellings, and resolution to `UnitDef` happens only after `validate_model_price(...)` succeeds. Any `_extra_prices` key that is not registered in the validation registry is invalid. Declared subclass-only custom fields remain custom override state unless their names are also registered price keys.

**Python pricing validates dynamic price data on use.** _(implements "Python base `ModelPrice` accepts registered non-hardcoded price keys", "Runtime validation caching still waits for Phase 5")_
`set_custom_snapshot(snapshot)` does not perform model-price validation in Phase 3. Standard base `ModelPrice.calc_price(...)` validates candidate dynamic keys, ancestor coverage, and join coverage against the active global registry every time before calculating against the selected model price. Misspelled dynamic keys and incomplete dynamic price sets therefore fail on use. Runtime validation caches remain Phase 5 work.

**Python can replace the active global registry from trusted payloads.** _(implements "Unit definitions travel with the prices that depend on them")_
Add a private runtime helper in `units.py` for installing an indexed registry as the active global registry:

```python
def _set_registry(registry: UnitRegistry | None) -> None:
    """Replace the active global unit registry, or restore bundled units when passed None."""
```

This helper is private. Phase 3 must change `_get_registry()` from a purely cached bundled-registry constructor into an active-registry accessor: it returns the installed registry when `_set_registry(...)` has replaced the global registry, otherwise it returns the cached bundled registry built from generated `data_units.py`. Replacement stores the new registry as active global state and clears any Phase 5 registry-keyed caches when those exist. Passing `None` resets the active registry back to the bundled registry. It must not simply clear `_get_registry()` and fall back to bundled unit data on the next lookup.

**Runtime update paths install units globally.** _(implements "`data.json` and `data_slim.json` become wrapped top-level objects")_
Python `UpdatePrices.fetch()` parses `units`, constructs `UnitRegistry(raw['units'])` as trusted published data, saves the previously active registry, installs the candidate registry as the active global registry, parses `providers`, and returns `DataSnapshot(providers=...)`. If provider parsing fails after the candidate registry is installed, it restores the previous registry before surfacing the error:

```python
class UpdatePrices:
    def fetch(self) -> DataSnapshot | None:
        """Fetch wrapped data, install units globally, and return a provider snapshot."""
```

Python `UpdatePrices.stop()` keeps the current provider-snapshot behavior: stopping the updater clears the auto-updated provider snapshot and falls back to bundled provider data. Phase 3 must make the unit lifecycle match that provider lifecycle by calling `_set_registry(None)` when `stop()` clears the snapshot, so bundled providers are not left running against previously fetched units.

JavaScript `api.ts` handles runtime updates in this order:

1. parse wrapped JSON
2. build active registry indexes from trusted `units`
3. save the previously active registry
4. replace active registry
5. parse providers
6. replace active provider data

If wrapper parsing fails, both active registry and active provider data remain unchanged. If provider parsing or provider activation fails after the candidate registry is installed, restore the previous active registry and keep the previous provider data active. Runtime provider activation does not perform unit publication validation or model-price coverage validation in Phase 3; standard pricing validates the selected model price on use. Checked-in JavaScript examples that cache provider data must cache and restore the wrapped payload shape.

`updatePrices()` keeps a single public payload setter — `setProviderData` becomes wrapper-aware so existing user code that forwards the auto-update payload directly to `setProviderData(await response.json())` keeps working when the URL flips shape:

```typescript
export interface WrappedProviderData {
  units: RawUnitsDict
  providers: Provider[]
}

export type ProviderDataValue = null | Provider[] | WrappedProviderData
export type ProviderDataPayload = ProviderDataValue | Promise<ProviderDataValue>

export interface StorageFactoryParams {
  onCalc: (cb: () => void) => void
  remoteDataUrl: string
  setProviderData: (data: ProviderDataPayload) => void
}
```

Discrimination inside `setProviderData`:

- `null` → no-op; previous state unchanged.
- `Array.isArray(payload)` → legacy bare-list path; install providers, leave the active unit registry as-is.
- Object containing `providers` and `units` → wrapped path; build `new UnitRegistry(units)` as trusted published data, capture the previously active registry, install the candidate via the internal state setter, install providers, restore the previous registry if provider parsing or activation fails.
- Promise → chain the same discrimination; restore on failure.
- Anything else → throw.

Use the internal state setter `units.ts::setActiveRegistry(UnitRegistry | null)` for wrapped payload activation. There is no public registry setter.

Checked-in JavaScript browser and node examples need no behavior changes. They already forward parsed JSON to `setProviderData`, and the wrapper-aware setter handles bare-array (stale cache) and wrapped (fresh fetch) shapes transparently. Cache files evolve to the wrapped shape on the next refresh write. Pre-upgrade users were already on bundled units, so a stale bare-array cache leaves them on bundled units, which matches their pre-upgrade behavior.

Generated Python and JavaScript package data remain pure data. They must not contain validation markers, trust flags, fingerprints, marker constructor arguments, decomposition plans, or cached coefficients. Runtime-private validation caches start in Phase 5.

**Tests cover the wrapper and dynamic-key boundary.** _(implements "Phase 3 makes repo-defined units an end-to-end feature")_
Add tests for wrapped full/slim payload schemas, Python and JavaScript runtime update parsing, generated package data exports, complete-registry join-closedness in Python build/export validation, lightweight Python build-time public-name rejection, build/export validation for prices and extractor destinations, base Python `ModelPrice` with a registered non-hardcoded key, rejection of misspelled dynamic keys during pricing, no Phase 3 provider-activation model-price validation, global registry replacement from runtime payloads, and unchanged generated-output purity with no validation artifacts. JavaScript unit tests should cover runtime indexing and active-registry behavior, not unit-only publication validation.
