# Code Spec: Data-Driven Unit Registry

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Baseline:** this document describes the final `main` -> target-state diff for the PR. It intentionally ignores the current branch's partial implementation state.

---

## PR Shape

**New tracked source files.**
The final diff adds these hand-written files:

- `prices/units.yml`
- `packages/python/genai_prices/units.py`
- `packages/python/genai_prices/decompose.py`
- `packages/python/genai_prices/validation.py`
- `packages/js/src/units.ts`
- `packages/js/src/decompose.ts`
- `packages/js/src/validation.ts`

**Modified tracked source files.**
The final diff modifies these existing files from `main`:

- `packages/python/genai_prices/types.py`
- `packages/python/genai_prices/data_snapshot.py`
- `packages/python/genai_prices/update_prices.py`
- `packages/python/genai_prices/_cli_impl.py`
- `packages/python/genai_prices/data.py` (generated)
- `packages/js/src/types.ts`
- `packages/js/src/engine.ts`
- `packages/js/src/api.ts`
- `packages/js/src/extractUsage.ts`
- `packages/js/src/examples/browser/main.ts`
- `packages/js/src/examples/node-script.ts`
- `packages/js/src/data.ts` (generated)
- `prices/src/prices/prices_types.py`
- `prices/src/prices/build.py`
- `prices/src/prices/package_data.py`
- generated JSON outputs and JSON schemas under `prices/`

**No separate runtime `units*.json` artifact is introduced.** _(implements "Unit definitions travel with prices, not just with the package", "No new code generation")_
The final design has one checked-in source registry file (`prices/units.yml`), plus generated embeddings of that same registry inside `prices/data*.json`, `packages/python/genai_prices/data.py`, and `packages/js/src/data.ts`. The PR diff from `main` does not add or remove any standalone bundled units JSON file.

---

## Data Shapes

**`prices/units.yml` is a new source-of-truth registry file.** _(implements "The registry is a YAML file that defines all built-in units", "`requests_kcount` becomes a unit in a `requests` family", "The registry defines units symmetrically across modalities")_
The file is a top-level mapping of `family_id -> family data`. It is checked into the repo and becomes the only handwritten definition of built-in units.

```yaml
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
    cache_audio_read_mtok:
      usage_key: cache_audio_read_tokens
      dimensions: { direction: input, modality: audio, cache: read }
    # ... the full symmetric family, including text/audio/image/video variants

requests:
  per: 1_000
  description: Request counts
  dimensions: {}
  units:
    requests_kcount:
      usage_key: requests
      dimensions: {}
```

Unit IDs live only as dict keys in the raw data. `usage_key` defaults to the unit ID when omitted. The `tokens` family contains the full built-in unit lattice needed by the prose spec, not just the currently hardcoded fields from `main`.

**`prices/data.json` and `prices/data_slim.json` become top-level dicts.** _(implements "`data.json` becomes a top-level dict, not a bare list", "Unit definitions travel with prices, not just with the package")_
Both generated JSON payloads change from a bare provider list to this shape:

```json
{
  "unit_families": {
    "tokens": { "...": "..." },
    "requests": { "...": "..." }
  },
  "providers": [{ "...": "..." }]
}
```

`unit_families` carries the raw registry data from `prices/units.yml`. `providers` keeps the existing provider payload shape.

**Generated language-native data exports include unit families.** _(implements "Unit definitions are generated into language-native code alongside prices")_

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

The runtime packages continue loading generated code at startup; they do not parse `prices/units.yml` directly.

---

## Python Package: `packages/python/genai_prices/`

### `units.py` — new file

**`UnitDef` and `UnitFamily` are plain dataclasses.** _(implements "`UnitRegistry` is the runtime representation of unit definitions")_

```python
@dataclass
class UnitDef:
    id: str
    family_id: str
    family: UnitFamily
    usage_key: str
    dimensions: dict[str, str]


@dataclass
class UnitFamily:
    id: str
    per: int
    description: str
    dimensions: dict[str, list[str]]
    units: dict[str, UnitDef]
```

There is no `RawUnitDef`/`RawUnitFamily`/`RawFamiliesDict` model layer in Python runtime code. Raw registry data stays as plain dictionaries until `UnitRegistry` constructs these objects.

**`UnitRegistry` owns all runtime unit state.** _(implements "`UnitRegistry` is the runtime representation of unit definitions", "Users can define custom units at runtime", "Registry join-closedness: compatible unit pairs must have their join in the family")_

```python
class UnitRegistry:
    families: dict[str, UnitFamily]
    units: dict[str, UnitDef]          # unit_id -> UnitDef across all families
    usage_keys: dict[str, str]         # usage_key -> unit_id across all families

    def __init__(self, raw_families: dict[str, dict] | None = None) -> None:
        """Parse raw families, validate structure, fill indexes and back-references."""

    def add_family(
        self,
        family_id: str,
        *,
        per: int,
        description: str,
        dimensions: dict[str, list[str]],
        units: dict[str, dict],
    ) -> None:
        """Add and validate a new family."""

    def add_unit(
        self,
        family_id: str,
        unit_id: str,
        *,
        usage_key: str | None = None,
        dimensions: dict[str, str],
    ) -> None:
        """Add and validate one unit in an existing family."""

    def copy(self) -> UnitRegistry:
        """Return an independent copy suitable for user mutation."""

    @staticmethod
    def are_compatible(a: UnitDef, b: UnitDef) -> bool:
        """Return True when the two units do not conflict on any dimension axis."""
```

Registry construction and mutation perform all structural validation:

- unit dimension keys and values must exist in the family declaration
- unit IDs are globally unique
- usage keys are globally unique
- no two units in a family share the same dimension set
- every compatible pair in a family has its join present in that family

**Module-level registry access is one lazy helper.** _(implements "There is one global DataSnapshot")_

```python
def _get_registry() -> UnitRegistry:
    """Return get_snapshot().unit_registry via a lazy import."""
```

Other modules use `_get_registry().units[...]`, `_get_registry().families[...]`, and `_get_registry().usage_keys[...]` directly.

---

### `decompose.py` — new file

**Dimension-driven decomposition lives in a dedicated module.** _(implements "Decomposition uses dimensions, not hardcoded subtraction chains", "Only priced units participate in decomposition", "Decomposition operates within a family")_

```python
def is_descendant_or_self(ancestor: UnitDef, descendant: UnitDef) -> bool:
    """Return True when ancestor.dimensions is a subset of descendant.dimensions."""


def compute_leaf_values(
    priced_unit_ids: set[str],
    usage: Usage,
    family: UnitFamily,
    *,
    default_usage: int = 0,
) -> dict[str, int]:
    """Compute exclusive usage for the priced units in one family.

    `default_usage` exists for backward-compat pricing rules such as requests=1 when
    the requests family is priced and no `requests` value was supplied.
    """
```

`compute_leaf_values` uses the family dimension lattice and only the currently priced units. Negative leaf values raise `ValueError` with user-facing messages that describe the contradictory usage relationship, not the underlying algorithm.

---

### `validation.py` — new file

**Price-level validation is centralized here.** _(implements "Validation is split between the registry and `set_custom_snapshot`", "Validation rules are expressed in terms of dimensions, not unit names")_

```python
def validate_price_keys(price_keys: set[str], all_unit_ids: set[str]) -> None:
    """Every model price key must be a registered unit ID."""


def validate_ancestor_coverage(priced_unit_ids: set[str], family: UnitFamily) -> None:
    """Every priced unit's ancestors in the same family must also be priced."""


def validate_join_coverage(priced_unit_ids: set[str], family: UnitFamily) -> None:
    """Every priced compatible pair whose join exists in the family must price that join."""


def validate_extractor_destinations(dest_keys: set[str], usage_keys: set[str]) -> None:
    """Every extractor mapping destination must be a registered usage key."""


def validate_price_sanity(
    prices: dict[str, Decimal | TieredPrices],
    family: UnitFamily,
) -> None:
    """Build-time economic sanity checks expressed in terms of dimensions."""
```

This module does not validate raw registry structure. That stays in `UnitRegistry`.

---

### `types.py` — modified

**`AbstractUsage` becomes a compatibility alias rather than a real protocol.** _(implements "The usage parameter type is `object`, not a library-specific type", "Backward compatibility is preserved unless clearly impractical")_

```python
AbstractUsage = object
```

This keeps the exported name from `main` while removing the false implication that callers must satisfy a fixed protocol.

**`Usage` becomes a registry-aware class with no hardcoded fields.** _(implements "`Usage` is a registry-aware class that infers, decomposes, and serves correct values", "`Usage` infers ancestor values from descendants", "Mapping usage keys are validated against the registry")_

```python
class Usage:
    _values: dict[str, int]

    def __init__(self, **kwargs: int | None) -> None:
        """Store non-None values, validate keyword names, infer ancestor totals."""

    @classmethod
    def from_raw(cls, obj: object) -> Usage:
        """Wrap arbitrary usage input.

        - Usage: return as-is
        - Mapping: validate keys against registry usage keys, then construct
        - Other object: read known usage keys via getattr and construct
        """

    def has_value(self, usage_key: str) -> bool:
        """Return True when the key exists in stored provided-or-inferred values."""

    def __getattr__(self, name: str) -> int:
        """For registered usage keys, return the stored value or 0 if absent.

        Raise AttributeError for names that are not registered usage keys.
        """

    def __setattr__(self, name: str, value: object) -> None:
        """Prevent mutation after construction."""

    def __add__(self, other: Usage) -> Usage: ...
    def __radd__(self, other: Usage | int) -> Usage: ...
    def __eq__(self, other: object) -> bool: ...
    def __repr__(self) -> str: ...
```

Construction-time inference fills ancestor values from descendants using the active global registry. Explicitly supplied values are never overwritten. `Usage` does not know the requests default-to-1 rule; that stays in pricing code.

**`ModelPrice` becomes a registry-backed Pydantic model.** _(implements "ModelPrice supports attribute access backed by registry data", "`calc_price` is a hot path", "`input_price` and `output_price` are backward-compat accessors over direction-filtered costs")_

```python
class ModelPrice(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='allow')

    __pydantic_extra__: dict[str, Decimal | TieredPrices]

    def calc_price(self, usage: object) -> CalcPrice:
        """Price all configured units using the active global registry."""

    def __getattr__(self, name: str) -> Decimal | TieredPrices | None:
        """For registered unit IDs, return the stored price or None if absent.

        Raise AttributeError for names that are not registered unit IDs.
        """

    def __str__(self) -> str:
        """Render prices using registry-derived labels and family normalization."""

    def is_free(self) -> bool:
        """Return True when there are no stored prices or every stored price is zero-like."""
```

`ModelPrice.calc_price()` changes from hardcoded token arithmetic to this flow:

1. Wrap non-`Usage` input with `Usage.from_raw`.
2. Use the flat registry index to group stored price keys by family.
3. For each family, call `compute_leaf_values(...)`.
4. Pass `default_usage=1` only for the `requests` family.
5. Price each leaf with the family's `per` normalization.
6. Aggregate per-unit costs into `input_price`, `output_price`, and `total_price`.

Families without a `direction` dimension contribute only to `total_price`.

**`calc_unit_price` replaces `calc_mtok_price`.** _(implements "The system is general across unit families", "TieredPrices is not refactored in this change")_

```python
def calc_unit_price(
    price: Decimal | TieredPrices | None,
    count: int | None,
    total_input_tokens: int,
    per: int,
) -> Decimal:
    """Price one unit count using the family's normalization factor."""
```

The tier threshold input remains `usage.input_tokens`, preserving current tiered-pricing semantics.

**`UsageExtractorMapping.dest` becomes `str`.** _(implements "The extraction pipeline is data-driven end-to-end")_

```python
@dataclass
class UsageExtractorMapping:
    path: ExtractPath
    dest: str
    required: bool
```

**`UsageExtractor.extract()` constructs `Usage` from a dict of collected values.** _(implements "The extraction pipeline is data-driven end-to-end")_
The method stops mutating dataclass fields directly. It accumulates extracted counts in `dict[str, int]`, then returns `Usage(**values)`.

**`ModelInfo.calc_price()` keeps its public signature but delegates to the new generic pricing path.** _(implements "All public API signatures are preserved")_
The method still accepts a usage object and returns `PriceCalculation`; internally it relies on `ModelPrice.calc_price()` rather than the hardcoded token-only logic from `main`.

---

### `data_snapshot.py` — modified

**`DataSnapshot` gains `unit_registry`, defaulting from the current global snapshot when omitted.** _(implements "Unit families live in the data snapshot alongside prices", "There is one global DataSnapshot")_

```python
@dataclass
class DataSnapshot:
    providers: list[types.Provider]
    from_auto_update: bool
    unit_registry: UnitRegistry | None = None
    _lookup_cache: dict[tuple[str | None, str | None, str], tuple[types.Provider, types.ModelInfo]] = ...
    timestamp: datetime = ...

    def __post_init__(self) -> None:
        """If unit_registry is None, borrow the active global snapshot's registry."""
```

`_bundled_snapshot()` always passes an explicit registry built from generated data, so it never depends on the fallback.

**`_bundled_snapshot()` builds the registry from generated code.** _(implements "Unit definitions are generated into language-native code alongside prices")_

```python
@cache
def _bundled_snapshot() -> DataSnapshot:
    from .data import providers, unit_families_data

    return DataSnapshot(
        providers=providers,
        from_auto_update=False,
        unit_registry=UnitRegistry(unit_families_data),
    )
```

**`set_custom_snapshot()` validates before activation.** _(implements "Validation is split between the registry and `set_custom_snapshot`", "Expensive validation happens once at construction/activation time, not on every `calc_price` call")_

```python
def set_custom_snapshot(snapshot: DataSnapshot | None) -> None:
    """Activate a snapshot or reset to bundled default.

    For non-None snapshots:
    - validate every model price key against snapshot.unit_registry
    - validate ancestor and join coverage per family
    - validate extractor destinations against snapshot.unit_registry.usage_keys
    - leave the previous snapshot active if any validation fails
    """
```

`validate_price_sanity()` is not part of `set_custom_snapshot()`; it remains build-time-only.

This activation step is what turns a snapshot from staged data into trusted runtime state. Before activation, a snapshot may contain `ModelPrice` objects and extractor configs whose unit references have not yet been checked against that snapshot's registry. After successful activation, the snapshot becomes the sole registry/provider set used for execution.

**`DataSnapshot.calc()` and `DataSnapshot.extract_usage()` require `self is get_snapshot()`.** _(implements "`calc` and `extract_usage` on DataSnapshot require it to be the current global")_
Both methods raise `RuntimeError` when called on a non-active snapshot. This is intentional discouragement of "standalone snapshot" execution: inactive snapshots are staging objects, not validated execution contexts. `find_provider_model()` and `find_provider()` stay pure lookup helpers and remain usable on inactive snapshots. _(implements "`find_provider_model` works on any snapshot, global or not")_

---

### `update_prices.py` — modified

**`UpdatePrices.fetch()` parses the new top-level JSON wrapper.** _(implements "Unit definitions travel with prices, not just with the package")_

```python
def fetch(self) -> DataSnapshot | None:
    """Fetch data.json, parse unit_families and providers, build a snapshot."""
```

Instead of validating the whole payload as `list[Provider]`, `fetch()` parses the wrapper object, validates the `providers` section, constructs `UnitRegistry(raw['unit_families'])`, and returns a `DataSnapshot` containing both.

---

### `_cli_impl.py` — modified

**CLI price presentation becomes registry-driven.** _(implements "Backward compatibility is preserved unless clearly impractical", "Derive, don't duplicate")_

- `_collect_model_price_fields()` no longer uses `dataclasses.fields(ModelPrice)`; it iterates stored price keys from each `ModelPrice`.
- `_price_field_label()` derives labels from unit metadata and family normalization rather than a hardcoded field-name map.
- `_format_model_price_value()` and `_format_model_prices()` iterate stored price keys and format them generically from registry data.

This preserves the current CLI output shape while allowing new units to appear without code changes.

---

### `__init__.py` — unchanged

**Top-level public exports remain the same.** _(implements "All public API signatures are preserved")_
`Usage`, `calc_price`, `UpdatePrices`, `wait_prices_updated_sync`, `wait_prices_updated_async`, and `__version__` stay exported from the same module.

---

## Build Pipeline: `prices/src/prices/`

### `prices_types.py` — modified

**Build-time `ModelPrice` becomes registry-permissive.** _(implements "Validation replaces what hardcoded fields gave us implicitly, and adds more", "Generated JSON schemas provide editor autocomplete for provider YAML files")_

```python
class ModelPrice(_Model, extra='allow'):
    __pydantic_extra__: dict[str, DollarPrice | TieredPrices]

    def is_free(self) -> bool: ...
```

The explicit hardcoded price fields from `main` are removed as the source of truth. Validation of allowed keys moves to build-time registry checks and schema generation.

**`UsageExtractorMapping.dest` becomes `str`.** _(implements "The extraction pipeline is data-driven end-to-end")_
The literal `UsageField` union is removed from build-time types.

---

### `build.py` — modified

**Build starts from the registry file, then validates provider data against it.** _(implements "Expensive validation happens once at construction/activation time, not on every `calc_price` call", "Price key validation: every key in a model's prices must be a registered unit ID", "Ancestor coverage is validated", "Join coverage is validated")_

```python
def build() -> None:
    """Build provider/editor schemas plus data.json and data_slim.json."""


def write_prices(
    providers: list[Provider],
    unit_families: dict[str, dict],
    prices_file: str,
    *,
    slim: bool = False,
) -> None:
    """Write one wrapped prices payload."""
```

`build()` changes in this order:

1. Load `prices/units.yml`.
2. Construct `UnitRegistry(unit_families)`; this performs structural validation.
3. Load and validate provider YAML files with `prices_types.py`.
4. For every model price payload:
   - validate price keys
   - validate ancestor coverage
   - validate join coverage
5. Validate extractor destinations against registry usage keys.
6. Run build-time price sanity checks.
7. Write wrapped `data.json` and `data_slim.json`.

**JSON schema generation becomes registry-derived.** _(implements "Generated JSON schemas provide editor autocomplete for provider YAML files", "Validation rules are expressed in terms of dimensions, not unit names")_
The provider YAML schema no longer relies on hardcoded `ModelPrice` fields or a hardcoded extractor `dest` union. Instead, `build.py` derives:

- allowed price keys from `registry.units`
- allowed extractor destinations from `registry.usage_keys`
- the top-level wrapped `data.json` schema including `unit_families`

No schema code references specific unit names.

---

### `package_data.py` — modified

**Generated package data now embeds both providers and unit families.** _(implements "Unit definitions are generated into language-native code alongside prices")_

```python
def package_data() -> None: ...
def package_python_data(data_path: Path) -> None: ...
def package_ts_data(data_path: Path) -> None: ...
```

`package_python_data()` and `package_ts_data()` both read the wrapped `data.json`, split out `providers` and `unit_families`, and emit both into generated package data files.

---

## JS Package: `packages/js/src/`

### `types.ts` — modified

**Usage and price shapes become open-ended records.** _(implements "Units are data, not code", "The system is general across unit families")_

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
  usage_key?: string
}

export interface RawFamilyData {
  description: string
  dimensions: Record<string, string[]>
  per: number
  units: Record<string, RawUnitData>
}

export type RawFamiliesDict = Record<string, RawFamilyData>

export interface StorageFactoryParams {
  onCalc: (cb: () => void) => void
  remoteDataUrl: string
  setProviderData: (data: ProviderDataPayload) => void
  setUnitFamilies: (data: RawFamiliesDict | null) => void
}
```

---

### `units.ts` — new file

**JS gets a runtime registry module parallel to Python's `UnitRegistry`.** _(implements "`UnitRegistry` is the runtime representation of unit definitions", "Unit definitions travel with prices, not just with the package")_

```typescript
export interface UnitDef {
  id: string
  familyId: string
  usageKey: string
  dimensions: Record<string, string>
}

export interface UnitFamily {
  id: string
  per: number
  description: string
  dimensions: Record<string, string[]>
  units: Record<string, UnitDef>
}

export function parseFamilies(raw: RawFamiliesDict): Record<string, UnitFamily>
// Parses raw family data into UnitFamily/UnitDef objects and validates structure
// and join-closedness without mutating active runtime state.

export function setUnitFamilies(raw: RawFamiliesDict | null): void
// Replaces the active registry. For non-null input, delegates to parseFamilies()
// before activation.

export function getFamily(familyId: string): UnitFamily
export function getUnit(unitId: string): UnitDef
export function getAllUsageKeys(): Set<string>
export function getAllUnitIds(): Set<string>
```

The module bootstraps itself from generated `unitFamiliesData` and allows the active registry to be replaced from runtime-updated JSON.

---

### `decompose.ts` — new file

**JS decomposition logic becomes dimension-driven too.** _(implements "Decomposition uses dimensions, not hardcoded subtraction chains", "Only priced units participate in decomposition")_

```typescript
export function isDescendantOrSelf(ancestor: UnitDef, descendant: UnitDef): boolean

function getUsageValue(usage: Record<string, unknown>, key: string, defaultValue?: number): number

function hasUsageValue(usage: Record<string, unknown>, key: string): boolean

export function computeLeafValues(
  pricedUnitIds: Set<string>,
  usage: Record<string, unknown>,
  family: UnitFamily,
  defaultUsage?: number,
): Record<string, number>
```

JS has no smart `Usage` class. `computeLeafValues()` therefore retains the inference that Python does at `Usage` construction time:

- `getUsageValue()` reads raw usage values with an optional default
- `hasUsageValue()` distinguishes "missing value" from an explicitly supplied contradictory value
- if Möbius inversion yields a negative leaf for a unit whose own usage value was not supplied, treat that leaf as `0`
- if the unit's own usage value was supplied and the leaf is negative, raise a user-facing contradiction error

Like Python, the JS requests default is passed in by pricing code via `defaultUsage=1`.

---

### `validation.ts` — new file

**JS validation mirrors the Python split between registry structure and price payloads.** _(implements "Validation replaces what hardcoded fields gave us implicitly, and adds more", "Expensive validation happens once at construction/activation time, not on every `calc_price` call")_

```typescript
export function validateRegistryStructure(families: Record<string, UnitFamily>): void
export function validateRegistryJoinClosedness(family: UnitFamily): void
export function validatePriceKeys(priceKeys: Set<string>, allUnitIds: Set<string>): void
export function validateAncestorCoverage(pricedUnitIds: Set<string>, family: UnitFamily): void
export function validateJoinCoverage(pricedUnitIds: Set<string>, family: UnitFamily): void
export function validateExtractorDestinations(destKeys: Set<string>, usageKeys: Set<string>): void
export function validateProviderData(providers: Provider[], families: Record<string, UnitFamily>): void
```

`setUnitFamilies()` is the activation step for the active registry. `validateProviderData()` validates a staged provider payload against a staged parsed registry so runtime updates can be atomic: if validation fails, neither the active registry nor active provider data changes.

---

### `engine.ts` — modified

**JS pricing switches from hardcoded token arithmetic to registry-driven family decomposition.** _(implements "The system is general across unit families", "`calc_price` is a hot path", "`input_price` and `output_price` are backward-compat accessors over direction-filtered costs")_

```typescript
function calcUnitPrice(
  price: number | TieredPrices | undefined,
  count: number | undefined,
  totalInputTokens: number,
  per: number,
): number

export function calcPrice(usage: Usage, modelPrice: ModelPrice): ModelPriceCalculationResult
```

`calcPrice()` now:

1. groups stored price keys by family via `getUnit(unitId).familyId`
2. computes leaf values per family
3. passes `defaultUsage=1` for the requests family
4. prices each leaf using `family.per`
5. aggregates by `direction` into the existing result shape

It no longer contains hardcoded logic for cache/audio/request arithmetic, and it does not run price-payload validation on the hot path.

---

### `api.ts` — modified

**Runtime data activation now handles wrapped JSON plus unit families.** _(implements "Unit definitions travel with prices, not just with the package")_

`updatePrices()` passes both `setProviderData` and `setUnitFamilies` to the storage factory. The runtime update path stages the new payload in this order:

1. parse wrapped JSON
2. `stagedFamilies = parseFamilies(parsed.unit_families)`
3. `validateProviderData(parsed.providers, stagedFamilies)`
4. on success only: `setUnitFamilies(parsed.unit_families)` and `setProviderData(parsed.providers)`

If parsing or validation fails, both the active registry and active provider data remain unchanged.

The embedded startup path still uses generated `data.ts`, but the active registry is initialized from `unitFamiliesData` instead of being implicit in engine code.

The checked-in JS examples must be updated to cache and restore the wrapped payload shape, not a bare provider array, and to call both `setUnitFamilies(...)` and `setProviderData(...)` after parsing it.

---

### `extractUsage.ts` — modified

**Extractor output keys are no longer a fixed union.** _(implements "The extraction pipeline is data-driven end-to-end")_
The existing extraction logic already builds a plain object of counts. The change here is structural: `UsageExtractorMapping.dest` is now `string`, so extracted usage can target any registry-defined usage key.

---

## Call Relationships

### Registry construction

```text
prices/units.yml
  -> build.py loads raw family dict
  -> UnitRegistry(raw_families)
       -> create UnitFamily shells
       -> create UnitDef objects
       -> fill families / units / usage_keys indexes
       -> validate dimension rules, uniqueness, join-closedness
```

### Build-time validation and packaging

```text
build()
  -> load units.yml
  -> registry = UnitRegistry(unit_families)
  -> load provider YAML files
  -> validate model price keys / ancestor coverage / join coverage
  -> validate extractor destinations
  -> validate price sanity
  -> write wrapped data.json and data_slim.json

package_data()
  -> read wrapped data.json
  -> package_python_data(): emit providers + unit_families_data
  -> package_ts_data(): emit data + unitFamiliesData
```

### Python bundled startup

```text
get_snapshot()
  -> _bundled_snapshot()
       -> import providers, unit_families_data from generated data.py
       -> UnitRegistry(unit_families_data)
       -> DataSnapshot(providers=..., unit_registry=..., from_auto_update=False)
```

### Python snapshot activation

```text
set_custom_snapshot(snapshot)
  -> if snapshot is None: clear custom snapshot
  -> else validate prices and extractor destinations against snapshot.unit_registry
  -> on success: activate snapshot as the only trusted execution snapshot
  -> on failure: raise and keep previous snapshot
```

### Python custom unit flow

```text
get_snapshot()
  -> registry = current_snapshot.unit_registry.copy()
  -> registry.add_family(...) and/or registry.add_unit(...)
  -> snapshot = DataSnapshot(
       providers=current_snapshot.providers,
       from_auto_update=False,
       unit_registry=registry,
     )
  -> set_custom_snapshot(snapshot)
       -> validate prices against expanded registry
       -> activate on success
```

### Python hot path

```text
ModelPrice.calc_price(usage)
  -> smart_usage = Usage.from_raw(usage)
  -> registry = get_snapshot().unit_registry
  -> total_input_tokens = smart_usage.input_tokens
  -> group stored price keys by family
  -> for each family:
       default_usage = 1 only for requests
       leaf_values = compute_leaf_values(priced_ids, smart_usage, family, default_usage=...)
  -> for each priced unit:
       cost = calc_unit_price(price, leaf_count, total_input_tokens, family.per)
       aggregate by direction
  -> return {input_price, output_price, total_price}
```

### JS runtime activation

```text
generated data.ts
  -> unitFamiliesData bootstraps units.ts
  -> data bootstraps providerData

runtime update
  -> parse wrapped JSON
  -> stagedFamilies = parseFamilies(parsed.unit_families)
  -> validateProviderData(parsed.providers, stagedFamilies)
  -> on success only:
       setUnitFamilies(parsed.unit_families)
       setProviderData(parsed.providers)
  -> on failure:
       keep both active registry and providerData unchanged
```
