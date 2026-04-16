# Code Spec: Data-Driven Unit Registry

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**

---

## Data Shapes

**`prices/units.yml` gains a `requests` family.** _(implements "requests_kcount becomes a unit in a requests family")_
The existing `tokens` family (20 units) is unchanged. A `requests` family is added:

```yaml
requests:
  per: 1_000
  description: Request counts
  dimensions: {}
  units:
    requests_kcount:
      usage_key: requests
      dimensions: {}
```

**`prices/data.json` becomes `{"unit_families": {...}, "providers": [...]}`** _(implements "data.json becomes a top-level dict")_
Currently a bare JSON array. After: a dict with `unit_families` (the raw families dict from `units.yml`) and `providers` (the existing array). `data_slim.json` undergoes the same change.

**`packages/python/genai_prices/data.py` (generated) exports `unit_families_data` alongside `providers`.** _(implements "Unit definitions are generated into language-native code")_

```python
# Generated — do not edit
__all__ = ('providers', 'unit_families_data')

unit_families_data: dict = { ... }  # raw families dict for UnitRegistry construction
providers: list[Provider] = [ ... ]
```

**`packages/js/src/data.ts` (generated) exports `unitFamiliesData` alongside `data`.** Same structural change as Python.

```typescript
// Generated — do not edit
export const unitFamiliesData = { ... }
export const data: Provider[] = [ ... ]
```

---

## Python Package: `packages/python/genai_prices/`

### `units.py` — rewritten

Currently contains Pydantic models (`UnitDef`, `RawUnitDef`, `UnitFamily`, `RawUnitFamily`, `RawFamiliesDict`), `_load_families()` reading from `units_data.json`, and module-level dicts (`_FAMILIES`, `TOKENS_FAMILY`, `_ALL_UNITS`). All of these are replaced.

**Removals:**

- `RawUnitDef`, `RawUnitFamily`, `RawFamiliesDict` classes and `_validate_dimensions` validator
- `_load_families()` function
- `_FAMILIES`, `TOKENS_FAMILY`, `_ALL_UNITS` module-level state
- `units_data.json` file dependency (file deleted)

#### `UnitDef` — dataclass _(implements "UnitDef and UnitFamily are plain classes")_

Replaces the current Pydantic `UnitDef`. Constructed by `UnitRegistry` — all fields are populated at construction, including back-references. Not intended to be constructed directly by users; use `UnitRegistry.add_unit` or construct via the raw families dict.

```python
@dataclass
class UnitDef:
    id: str                        # e.g. 'input_mtok'
    family_id: str                 # e.g. 'tokens'
    family: UnitFamily             # direct reference to the family object
    usage_key: str                 # e.g. 'input_tokens'
    dimensions: dict[str, str]     # e.g. {'direction': 'input'}
```

#### `UnitFamily` — dataclass _(implements "UnitDef and UnitFamily are plain classes")_

Constructed by `UnitRegistry`. Not intended to be constructed directly; use `UnitRegistry.add_family` or construct via the raw families dict.

```python
@dataclass
class UnitFamily:
    id: str                            # e.g. 'tokens'
    per: int                           # e.g. 1_000_000
    description: str                   # e.g. 'Token counts'
    dimensions: dict[str, list[str]]   # e.g. {'direction': ['input', 'output'], ...}
    units: dict[str, UnitDef]          # populated by UnitRegistry
```

#### `UnitRegistry` — single class owning all unit state _(implements "UnitRegistry is the runtime representation")_

Replaces `_FAMILIES`, `_ALL_UNITS`, `_load_families`, `RawFamiliesDict`, and all structural validation. Constructed from a raw dict (the `unit_families` section of `data.json` or `units.yml`). Parses, validates structural integrity, builds a flat index, fills back-references. Public class — users interact with it for custom unit flows.

```python
class UnitRegistry:
    families: dict[str, UnitFamily]
    units: dict[str, UnitDef]             # flat: unit_id -> UnitDef across all families
    usage_keys: dict[str, str]            # usage_key -> unit_id across all families

    def __init__(self, raw_families: dict[str, dict] | None = None) -> None:
        """Parse raw families dict, validate, build index, fill back-references.

        Validates on construction: dimension key/value validity, ID uniqueness across
        families, usage key uniqueness, dimension-set uniqueness within family,
        join-closedness per family. usage_key defaults to unit_id if not specified
        in the raw dict.
        """

    def add_family(
        self, family_id: str, *, per: int, description: str,
        dimensions: dict[str, list[str]], units: dict[str, dict],
    ) -> None:
        """Add a new family. Validates, creates UnitFamily/UnitDef objects,
        updates families/units/usage_keys.
        Raises ValueError if family_id already exists or if any validation fails.
        """

    def add_unit(
        self, family_id: str, unit_id: str, *,
        usage_key: str | None = None, dimensions: dict[str, str],
    ) -> None:
        """Add a unit to an existing family. Validates incrementally: ID uniqueness,
        usage key uniqueness, dimension validity, dimension-set uniqueness,
        and re-checks join-closedness for the modified family.
        usage_key defaults to unit_id if not provided.
        Raises KeyError if family doesn't exist.
        Raises ValueError if unit_id or usage_key already exists, or validation fails.
        """

    def copy(self) -> UnitRegistry:
        """Return an independent copy. Re-serializes to raw dict and re-parses."""

    @staticmethod
    def are_compatible(a: UnitDef, b: UnitDef) -> bool:
        """True if a and b share no dimension axis with conflicting values.
        Public — also used by validate_join_coverage in validation.py."""
```

The `families`, `units`, and `usage_keys` dicts are public attributes. They are not frozen — users _can_ mutate them directly, but doing so bypasses validation and may leave the registry in an inconsistent state (e.g., a unit in `families` that isn't in `units`). The `add_family` and `add_unit` methods are the validated path.

#### Module-level convenience _(implements "convenience functions delegate to get_snapshot().unit_registry")_

One helper to get the registry from the global snapshot. Replaces the old `_FAMILIES` / `_ALL_UNITS` module-level dicts. Uses a lazy import of `data_snapshot.get_snapshot()` to avoid circular imports.

```python
def _get_registry() -> UnitRegistry:
    """Get the UnitRegistry from the current global snapshot."""
```

Callers use `_get_registry().units[unit_id]`, `_get_registry().families[family_id]`, etc. directly — no wrapper functions.

---

### `types.py` — modified

#### `ModelPrice` — rewritten as Pydantic BaseModel _(implements "ModelPrice supports attribute access backed by registry data")_

Currently a `@dataclass` with 8 explicit price fields. Becomes a Pydantic `BaseModel` with `extra='allow'` and no explicit price fields. All prices are stored in `__pydantic_extra__`.

```python
class ModelPrice(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='allow')

    __pydantic_extra__: dict[str, Decimal | TieredPrices]

    def calc_price(self, usage: object) -> CalcPrice:
        """Wraps usage in Usage.from_raw(usage) if not already a Usage.
        Groups price keys by family, decomposes each family via compute_leaf_values,
        prices each leaf, buckets costs by direction dimension.

        For the requests family, default_usage=1 (one API call).
        Costs from families without a 'direction' dimension go only to total_price.

        total_input_tokens for TieredPrices: simply smart_usage.input_tokens — always
        correct because Usage infers ancestor values from descendants.
        """

    def __str__(self) -> str:
        """Derives display labels from registry metadata (unit.usage_key, family.per),
        not hardcoded string patterns."""

    def is_free(self) -> bool:
        """True if there are no prices, or all price values are zero/None."""

    # Attribute access: model_price.input_mtok returns
    # self.__pydantic_extra__.get('input_mtok') — Pydantic provides this.
    # __getattr__ override returns None for missing keys (backward compat).
```

**Removals from `ModelPrice`:**

- `__post_init__` _(implements "ModelPrice construction does not validate against the registry")_
- All 8 explicit fields (`input_mtok`, `output_mtok`, `cache_read_mtok`, `cache_write_mtok`, `input_audio_mtok`, `cache_audio_read_mtok`, `output_audio_mtok`, `requests_kcount`)

#### `calc_unit_price` — replaces `calc_mtok_price` _(implements "The system is general across unit families")_

```python
def calc_unit_price(
    price: Decimal | TieredPrices | None,
    count: int | None,
    total_input_tokens: int,
    per: int,
) -> Decimal:
    """Calculate the price for a given usage count, generic over the normalization
    factor (family.per). For TieredPrices, tier is determined by total_input_tokens."""
```

**Removal:** `calc_mtok_price` function (subsumed by `calc_unit_price`).

#### `Usage` — registry-aware class _(implements "Usage is a registry-aware class that infers, decomposes, and serves correct values")_

Currently a `@dataclass` with 7 explicit fields. Becomes a registry-aware class that infers ancestor values, provides leaf value decomposition, and serves correct totals for any usage key. Immutable after construction. Uses the global unit registry (`get_snapshot().unit_registry`).

```python
class Usage:
    _values: dict[str, int]  # flat dict: provided + inferred, no distinction

    def __init__(self, **kwargs: int | None) -> None:
        """Store non-None values, then infer ancestor values from descendants
        using the global unit registry. Provided values are never overridden.
        Inference uses inclusion-exclusion over the dimension structure."""

    @classmethod
    def from_raw(cls, obj: object) -> Usage:
        """Construct from an arbitrary object. If obj is already a Usage, return it.
        If Mapping: validate keys against registry.usage_keys, then construct.
        Otherwise: extract known usage keys via getattr, then construct."""

    def __getattr__(self, name: str) -> int:
        """Returns stored value (provided or inferred), or 0 for keys not present.
        Does NOT return None — zero means 'no data for this key'."""

    def __setattr__(self, name: str, value: object) -> None:
        """Raises AttributeError — Usage is immutable."""

    def __add__(self, other: Usage) -> Usage:
        """Sum all stored values, then re-infer ancestors on the result.
        Correct because inferred ancestors are always derivable from descendants."""

    def __radd__(self, other: Usage) -> Usage: ...
    def __eq__(self, other: object) -> bool: ...
    def __repr__(self) -> str: ...
```

#### `UsageExtractorMapping.dest` — becomes `str` _(implements "dest becomes a plain string")_

Currently typed as `UsageField` (a `Literal` union of 7 field names). Becomes plain `str`.

**Removal:** `UsageField` literal type.

#### `UsageExtractor.extract()` — modified for immutable `Usage`

Currently builds `Usage()` then uses `setattr` to populate fields. Changed to collect values in a `dict[str, int]` and construct `Usage(**values)` at the end. Signature unchanged.

---

### `decompose.py` — modified

The Mobius inversion algorithm stays here. `calc_price` wraps raw usage in `Usage` (which infers ancestors), then passes the smart `Usage` to `compute_leaf_values`. Since `Usage` always has correct ancestor values, the decomposition no longer needs inference logic — negative leaves are always genuine errors.

#### `compute_leaf_values`

```python
def compute_leaf_values(
    priced_unit_ids: set[str],
    usage: Usage,
    family: UnitFamily,
) -> dict[str, int]:
    """Compute leaf values via Mobius inversion. Usage is a smart Usage object
    with correct (provided + inferred) values — no inference logic here.
    Negative leaf values are always contradictions: raise ValueError with
    human-readable message. No error may mention leaves, Mobius inversion,
    posets, depth, coefficients, or dimensions."""
```

Note: `usage` is now typed as `Usage`, not `object` — `calc_price` wraps raw objects before calling.

**Unchanged:** `is_descendant_or_self` signature and behavior.

**Removal:** `get_usage_value` (use `getattr(usage, key)` directly — smart `Usage` returns `int`, never `None`). `_has_usage_value` (no longer needed). `default_usage` parameter (the requests default-to-1 is handled by `Usage` construction or by `calc_price` before decomposition). `validate_ancestor_coverage` moves to `validation.py`. `get_priced_descendants` removed (unused).

---

### `validation.py` — new file _(implements "Validation is split between the registry and set_custom_snapshot")_

Price-level validation functions. Used by `set_custom_snapshot` (runtime) and the build pipeline (build time). Structural validation lives in `UnitRegistry`, not here.

**Constraint:** All validation logic operates on dimensions and registry structure. No validation code references `input_mtok` or any other specific unit by name. _(implements "Validation rules are expressed in terms of dimensions, not unit names")_

```python
def validate_ancestor_coverage(priced_unit_ids: set[str], family: UnitFamily) -> None:
    """Raise ValueError if any priced unit's ancestor in the family is not priced.
    Moved from decompose.py — same signature and behavior.
    Uses is_descendant_or_self from decompose.py."""

def validate_join_coverage(priced_unit_ids: set[str], family: UnitFamily) -> None:
    """Raise ValueError if two priced, compatible units have a join in the registry
    that is not priced. Uses UnitRegistry.are_compatible for compatibility check."""

def validate_price_keys(price_keys: set[str], all_unit_ids: set[str]) -> None:
    """Raise ValueError if any price key is not a registered unit ID.
    Catches typos like 'inptu_mtok'."""

def validate_price_sanity(
    prices: dict[str, Decimal | TieredPrices],
    family: UnitFamily,
) -> None:
    """Raise ValueError on violations of economic inequalities.
    Rules expressed in terms of dimensions, not unit names:
    - Within same direction+modality: cache=read <= uncached <= cache=write
    - Text (catch-all without modality) is the cheapest modality
    Starts as errors — investigate and downgrade individual rules if needed.
    Build-pipeline only — not run at set_custom_snapshot time."""
```

---

### `data_snapshot.py` — modified

#### `DataSnapshot` — gains `unit_registry` field _(implements "Unit families live in the data snapshot")_

```python
@dataclass
class DataSnapshot:
    providers: list[types.Provider]
    from_auto_update: bool
    unit_registry: UnitRegistry | None = None  # new
    _lookup_cache: ...  # unchanged
    timestamp: ...      # unchanged
```

#### `_bundled_snapshot()` — constructs registry from generated code _(implements "the bundled snapshot includes a unit registry")_

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

#### `set_custom_snapshot()` — gains validation _(implements "Validation is split between the registry and set_custom_snapshot")_

```python
def set_custom_snapshot(snapshot: DataSnapshot | None) -> None:
    """Validate and activate a snapshot, or reset to bundled default (None).

    1. If snapshot.unit_registry is None, fill from current global snapshot's registry.
    2. Validate every model's prices against the registry:
       - validate_price_keys: every price key is a registered unit ID
       - validate_ancestor_coverage: per family, per model
       - validate_join_coverage: per family, per model
    3. Validate extractor dest values: every dest in every extractor mapping must be
       a recognized usage key in the registry (registry.usage_keys).
    4. If validation fails, raise ValueError — previous snapshot remains active.
    """
```

#### Global guards on `calc` and `extract_usage` _(implements "calc and extract_usage require it to be the current global")_

Both methods raise `RuntimeError` if `self is not get_snapshot()`. `find_provider_model` and `find_provider` are unguarded — they work on any snapshot. _(implements "find_provider_model works on any snapshot")_

---

### `update_prices.py` — modified

#### `UpdatePrices.fetch()` — parses new `data.json` format

```python
def fetch(self) -> DataSnapshot | None:
    """Parse the dict-format data.json: extract 'providers' and 'unit_families',
    construct UnitRegistry from unit_families, return DataSnapshot with both."""
```

Currently calls `providers_schema.validate_json(r.content)` directly. After: parses JSON to dict, extracts `providers` and `unit_families` separately, constructs `UnitRegistry(raw.get('unit_families'))`.

---

### `_cli_impl.py` — modified

**`_collect_model_price_fields`**: currently uses `dataclasses.fields(ModelPrice)`. Changed to iterate `result.model_price.__pydantic_extra__` across results, collecting field names in encountered order.

**`_price_field_label`**: currently a hardcoded dict. Changed to derive labels from registry metadata (`unit.usage_key`, `family.per`).

**`_format_model_prices`** and **`_format_model_price_value`**: currently use `dataclasses.fields(model_price)`. Changed to iterate `__pydantic_extra__`.

---

### `__init__.py` — unchanged

Public API is preserved: `Usage, calc_price, UpdatePrices, wait_prices_updated_sync, wait_prices_updated_async, __version__`. `UnitRegistry`, `UnitFamily`, `UnitDef` are public classes importable from `genai_prices.units`.

---

## Build Pipeline: `prices/src/prices/`

### `prices_types.py` — modified

#### `ModelPrice` — `extra='allow'` _(implements "Validation replaces what hardcoded fields gave us")_

Currently has 8 explicit price fields (`input_mtok`, ..., `requests_kcount`). Changed to `extra='allow'` with no explicit fields:

```python
class ModelPrice(_Model, extra='allow'):
    __pydantic_extra__: dict[str, DollarPrice | TieredPrices]

    def is_free(self) -> bool: ...
```

**Removal:** `UsageField` literal type. `UsageExtractorMapping.dest` becomes `str`.

### `build.py` — modified

**Registry validation at build time** _(implements "Expensive validation happens once at construction/activation time")_:
After loading providers, construct `UnitRegistry` from `units.yml`. Construction validates structural integrity automatically. Additionally, validate each model's prices:

```python
def build():
    # ... existing provider loading ...

    # Registry validation (structural — UnitRegistry constructor)
    registry = UnitRegistry(unit_families_data)

    # Per-model price validation
    for provider in providers:
        for model in provider.models:
            # Extract price keys from ModelPrice.__pydantic_extra__
            # Call validate_price_keys, validate_ancestor_coverage, validate_join_coverage
            # Call validate_price_sanity (warnings only)
```

**Dict-format output** _(implements "data.json becomes a top-level dict")_:
`write_prices` wraps providers in `{"unit_families": ..., "providers": [...]}`. The `unit_families` value is the inner dict of family_id -> family_data (not wrapped in a `{"families": ...}` key — that `families` key is a YAML-level artifact stripped at build time).

**JSON schema generation** _(implements "Generated JSON schemas provide editor autocomplete")_:
The provider YAML JSON schema (`.schema.json`) is updated so that `ModelPrice` fields and extractor `dest` values are derived from the registry. Price keys: all unit IDs from all families. Extractor dest: all usage keys from all families. This replaces the implicit enumeration from hardcoded Pydantic fields.

### `package_data.py` — modified

**`package_units()`**: currently generates `units_data.json` for Python and JS. Changed to embed unit families into `data.json` (via `build.py`) and into generated `data.py`/`data.ts` (via `package_python_data`/`package_ts_data`).

**`package_python_data()`**: reads `unit_families` from `data.json`, includes `unit_families_data` in generated `data.py`.

**`package_ts_data()`**: reads `unit_families` from `data.json`, includes `unitFamiliesData` in generated `data.ts`.

**Removal:** `units_data.json` (Python) and `units-data.json` (JS) files.

---

## JS Package: `packages/js/src/`

### `types.ts` — modified _(implements "Units are data, not code")_

```typescript
// Was: interface with 7 fixed fields
export type Usage = Record<string, number | undefined>

// Was: interface with 8 fixed fields
export type ModelPrice = Record<string, number | TieredPrices | undefined>

// UsageExtractorMapping.dest: was a literal union of 7 usage keys
export interface UsageExtractorMapping {
  dest: string // any registry usage key
  path: ExtractPath
  required: boolean
}

// StorageFactoryParams gains setUnitFamilies
export interface StorageFactoryParams {
  onCalc: (cb: () => void) => void
  remoteDataUrl: string
  setProviderData: (data: ProviderDataPayload) => void
  setUnitFamilies: (data: RawFamiliesDict | null) => void // new
}
```

`RawFamiliesDict` is the type for what `data.json` carries in `unit_families` — a flat dict of family_id to family data, no wrapper:

```typescript
interface RawUnitData {
  dimensions: Record<string, string>
  usage_key?: string // defaults to unit id if absent
}

interface RawFamilyData {
  description: string
  dimensions: Record<string, string[]>
  per: number
  units: Record<string, RawUnitData>
}

export type RawFamiliesDict = Record<string, RawFamilyData>
```

This matches the Python `UnitRegistry(raw_families: dict[str, dict])` — both receive the flat dict, not the YAML-level `{"families": {...}}` wrapper.

### `units.ts` — rewritten

**Removals:** `import unitsData from './units-data.json'`, `TOKENS_FAMILY` export, `ALL_UNITS` module-level dict, `loadFamilies()`.

The module manages unit family state: bootstrap from generated `data.ts`, allow override via `setUnitFamilies` (auto-update path).

```typescript
export function parseFamilies(raw: RawFamiliesDict): Record<string, UnitFamily>
// Parses raw dict into UnitFamily/UnitDef objects. Fills in id, familyId, usageKey.

export function setUnitFamilies(raw: RawFamiliesDict | null): void
// Validate (structure + join-closedness), then set as active. null resets to bootstrap.

export function getFamily(familyId: string): UnitFamily
export function getUnit(unitId: string): UnitDef
export function getAllUsageKeys(): Set<string>
export function getAllUnitIds(): Set<string>
```

`UnitDef` interface is unchanged: `id`, `familyId`, `usageKey`, `dimensions`. Note: JS `UnitDef` has `familyId` (string) but no `family` object back-reference (unlike Python). JS code resolves family data via `getFamily(unit.familyId)`.

`UnitFamily` interface is unchanged: `id`, `per`, `description`, `dimensions`, `units`.

> **Note:** JS `decompose.ts` retains `hasUsageValue` and inference logic because JS has no smart `Usage` class — it uses plain `Record<string, unknown>`. The inference that Python's `Usage.__init__` handles at construction time is instead handled inline in `computeLeafValues` on the JS side. The `defaultUsage` parameter also stays in JS's `computeLeafValues` for the requests family.

### `engine.ts` — modified _(implements "calc_price is a hot path")_

**Removals:** `import { TOKENS_FAMILY } from './units'`, `calcMtokPrice` function, hardcoded `requests_kcount` special case.

```typescript
function calcUnitPrice(
  price: number | TieredPrices | undefined,
  count: number | undefined,
  totalInputTokens: number,
  per: number,
): number
// Generic over normalization factor. Replaces calcMtokPrice.

export function calcPrice(usage: Usage, modelPrice: ModelPrice): ModelPriceCalculationResult
// Multi-family: groups price keys by family (via getUnit(unitId).familyId), gets
// family object via getFamily(familyId) for family.per. Decomposes each family
// independently. For 'requests' family, defaultUsage = 1. Costs without 'direction'
// dimension go only to total_price.
// Validates ancestor coverage and join coverage per family (JS has no set_custom_snapshot,
// so price-level validation runs at calc time — O(k²) where k is priced units per model).
```

### `decompose.ts` — modified _(JS equivalent of Python's Usage.leaf_value logic)_

JS has no smart `Usage` class — it uses plain `Record<string, unknown>`. The decomposition logic (inference, Mobius inversion, error messages) lives in `computeLeafValues` as a standalone function, called by `calcPrice` in `engine.ts`.

```typescript
function getUsageValue(usage: Record<string, unknown>, key: string, defaultValue?: number): number

function hasUsageValue(usage: Record<string, unknown>, key: string): boolean

export function computeLeafValues(
  pricedUnitIds: Set<string>,
  usage: Record<string, unknown>,
  family: UnitFamily,
  defaultUsage?: number, // defaults to 0
): Record<string, number>
// Inference: if leaf < 0 and own usage was NOT provided (hasUsageValue returns false),
// set leaf to 0. If own usage WAS provided, raise error.
// Human-readable error messages. defaultUsage for requests family.
```

**Removal:** `TOKENS_FAMILY` usage in tests.

### `validation.ts` — new file

Structural validation (used by `setUnitFamilies`) and price-level validation (used by `calcPrice`):

```typescript
// Structural — called from setUnitFamilies
export function validateRegistryStructure(families: Record<string, UnitFamily>): void
// ID uniqueness, usage key uniqueness, dimension-set uniqueness.

export function validateRegistryJoinClosedness(family: UnitFamily): void
// Compatible pairs must have their join in the family.

// Price-level — called from calcPrice per family
export function validateAncestorCoverage(pricedUnitIds: Set<string>, family: UnitFamily): void
// Moved from decompose.ts. Every priced unit's ancestors must also be priced.

export function validateJoinCoverage(pricedUnitIds: Set<string>, family: UnitFamily): void
// Two priced compatible units must have their join priced if it exists in the registry.
```

### `api.ts` — modified

`updatePrices` passes `setUnitFamilies` to the storage factory. Auto-update path parses the new dict-format `data.json` and calls `setUnitFamilies(parsed.unit_families)` alongside `setProviderData(parsed.providers)`.

### `extractUsage.ts` — modified

`UsageExtractorMapping.dest` is now `string` (from `types.ts` change). The `extractUsage` function builds a `Usage` (now `Record<string, number | undefined>`) from extracted values — no code change needed beyond the type.

---

## Call Relationships

### Price calculation hot path (`calc_price`)

```
ModelPrice.calc_price(usage)
  -> smart_usage = Usage.from_raw(usage)        # wrap if not already Usage; infers ancestors
  -> registry = get_snapshot().unit_registry
  -> if Mapping usage: validate keys against registry.usage_keys (in from_raw)
  -> total_input_tokens = smart_usage.input_tokens  # always correct (provided or inferred)
  -> group price keys by unit.family_id
  -> for each family:
       compute_leaf_values(priced_ids, smart_usage, family)  # Mobius, raises on negative
  -> for each unit_id, leaf_count:
       cost = calc_unit_price(price, leaf_count, total_input_tokens, unit.family.per)
       bucket cost by unit.dimensions.get('direction')
  -> return {input_price, output_price, total_price}
```

### Snapshot activation (`set_custom_snapshot`)

```
set_custom_snapshot(snapshot)
  -> if snapshot.unit_registry is None: fill from get_snapshot().unit_registry
  -> for each provider, model, model_price:
       price_keys = set(model_price.__pydantic_extra__)
       validate_price_keys(price_keys, set(registry.units))
       for each family with priced units:
         validate_ancestor_coverage(family_priced_ids, family)
         validate_join_coverage(family_priced_ids, family)
  -> on success: _custom_snapshot = snapshot
  -> on failure: raise ValueError, previous snapshot unchanged
```

### Registry construction (`UnitRegistry.__init__`)

```
UnitRegistry(raw_families_dict)
  -> for each family_id, raw_family:
       create UnitFamily with empty units dict
       for each unit_id, raw_unit:
         validate dimension keys/values against family.dimensions
         validate unit ID uniqueness (across all families)
         validate usage key uniqueness (across all families)
         validate dimension-set uniqueness (within family)
         create UnitDef with back-reference to family
         add to family.units, registry.units, registry.usage_keys
       validate join-closedness for family
       add to registry.families
```

### Build pipeline

```
build()
  -> load providers from YAML
  -> registry = UnitRegistry(unit_families_data)           # structural validation
  -> for each provider, model:
       validate_price_keys / validate_ancestor_coverage / validate_join_coverage
       validate_price_sanity (errors — investigate and downgrade if needed)
  -> write_prices: {"unit_families": ..., "providers": [...]}  # dict format

package_data()
  -> read data.json (dict format)
  -> package_python_data: generate data.py with unit_families_data + providers
  -> package_ts_data: generate data.ts with unitFamiliesData + data
```

### Custom unit flow (user-facing)

```python
from genai_prices.data_snapshot import get_snapshot, set_custom_snapshot, DataSnapshot
from genai_prices.units import UnitRegistry

# Copy current registry and add a custom family
registry = get_snapshot().unit_registry.copy()
registry.add_family('characters', per=1, description='Characters', dimensions={},
    units={'char_count': {'usage_key': 'characters', 'dimensions': {}}})

# Build snapshot with custom registry
snapshot = DataSnapshot(providers=get_snapshot().providers, from_auto_update=False,
    unit_registry=registry)

# Activate — validates prices against the expanded registry
set_custom_snapshot(snapshot)
```

---

## Open Items

These are unresolved code-level questions. See also spec.md's Open Items for design-level gaps.

**1. `requests` default-to-1: where in the code?**
The `calc_price` docstring above says "For the requests family, default_usage=1", but `compute_leaf_values` no longer has a `default_usage` parameter (removed per the smart Usage design). `decompose.py`'s removal list says "handled by `Usage` construction or by `calc_price` before decomposition" — undecided. Two concrete options:

- In `Usage.from_raw`: if the wrapped object has no `requests` key, inject `requests=1`. Pro: all downstream code (including `usage.requests`) sees 1. Con: `Usage.from_raw` needs to know which keys get defaults — registry coupling.
- In `calc_price`: before calling `compute_leaf_values` for the requests family, check `smart_usage.requests` and if 0 (meaning no data), set it to 1 on a copy or pass it differently. Con: `Usage` is immutable, so this is awkward without a mechanism to override.

This needs resolution before implementing Tasks 6–7. **Note:** JS keeps `defaultUsage` in `computeLeafValues` (see JS section above), which is a simpler approach — consider whether Python should do the same instead of removing the parameter.

**2. Plan tasks 6 and 8 need rewriting.**
Task 6 adds `_has_usage_value`, `default_usage`, and inference in `compute_leaf_values`. Task 8 describes Usage with `__getattr__` returning `None`. Both are stale. The current code-spec design:

- **Usage.**init\*\*\*\*: infers ancestors via inclusion-exclusion, stores provided + inferred in one flat dict
- **Usage.**getattr\*\*\*\*: returns `int` (0 for missing), never `None`
- **Usage.from_raw**: wraps arbitrary objects, validates Mapping keys
- **compute_leaf_values**: takes `Usage` (not `object`), no `_has_usage_value`, no `default_usage`, negative leaves always errors

**3. Plan test code uses `get_family()`/`get_unit()` wrappers.**
The code spec says: `_get_registry()` is the only convenience function; callers do `_get_registry().units[unit_id]` directly. The plan's test code blocks use `get_family('tokens')` and `get_unit(unit_id)` in ~40 places. These are mechanical fixes but they need to be done before the plan is executable.
