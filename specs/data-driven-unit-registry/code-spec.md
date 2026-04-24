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
- `packages/js/src/usage.ts`
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

**`prices/units.yml` is a new source-of-truth registry file.** _(implements "The registry is a YAML file that defines all built-in units", "`requests_kcount` becomes the price key for a unit in a `requests` family", "The registry defines units symmetrically across modalities")_
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
    input_tokens:
      price_key: input_mtok
      dimensions: { direction: input }
    output_tokens:
      price_key: output_mtok
      dimensions: { direction: output }
    cache_read_tokens:
      price_key: cache_read_mtok
      dimensions: { direction: input, cache: read }
    cache_write_tokens:
      price_key: cache_write_mtok
      dimensions: { direction: input, cache: write }
    input_text_tokens:
      price_key: input_text_mtok
      dimensions: { direction: input, modality: text }
    cache_audio_read_tokens:
      price_key: cache_audio_read_mtok
      dimensions: { direction: input, modality: audio, cache: read }
    # ... the full symmetric family, including text/audio/image/video variants

requests:
  per: 1_000
  description: Request counts
  dimensions: {}
  units:
    requests:
      price_key: requests_kcount
      dimensions: {}
```

Usage keys live as dict keys in the raw data. `price_key` defaults to the usage key when omitted. The `tokens` family contains the full built-in unit lattice needed by the prose spec, not just the currently hardcoded fields from `main`.

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

`unit_families` carries the raw registry data from `prices/units.yml`. `providers` keeps the existing provider payload shape. Both full and slim payloads keep the unit family runtime fields; slimming applies to the provider payload.

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

The runtime packages continue loading generated code at startup; they do not parse `prices/units.yml` directly. Model price objects built from these generated repo data exports are marked as validated for the bundled registry during startup, because build-time validation has already accepted the source provider YAML and registry before the generated files are written.

---

## Python Package: `packages/python/genai_prices/`

### `units.py` — new file

**`UnitDef` and `UnitFamily` are plain dataclasses.** _(implements "`UnitRegistry` is the runtime representation of unit definitions")_

```python
@dataclass
class UnitDef:
    usage_key: str
    price_key: str
    family_id: str
    family: UnitFamily
    dimensions: dict[str, str]


@dataclass
class UnitFamily:
    id: str
    per: int
    description: str
    dimensions: dict[str, list[str]]
    units: dict[str, UnitDef]  # usage_key -> UnitDef
```

There is no `RawUnitDef`/`RawUnitFamily`/`RawFamiliesDict` model layer in Python runtime code. Raw registry data stays as plain dictionaries until `UnitRegistry` constructs these objects.

**`UnitRegistry` owns all runtime unit state.** _(implements "`UnitRegistry` is the runtime representation of unit definitions", "Users can define custom units at runtime", "Registry join-closedness: compatible unit pairs must have their join in the family")_

```python
class UnitRegistry:
    families: dict[str, UnitFamily]
    units: dict[str, UnitDef]          # usage_key -> UnitDef across all families
    price_keys: dict[str, str]         # price_key -> usage_key across all families
    validation_id: object              # changes for every independently constructed/mutated registry

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
        usage_key: str,
        *,
        price_key: str | None = None,
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
- usage keys are globally unique
- price keys are globally unique
- no two units in a family share the same dimension set
- every compatible pair in a family has its join present in that family

`add_unit(...)` validates after adding one unit and is appropriate only when the resulting family is valid immediately. The implementation must also provide an atomic existing-family edit path for join-dependent changes, but the exact public API shape is not settled by this spec yet. That path must stage changes to an existing family, merge dimension-declaration changes, add unit definitions, validate the complete candidate registry, and commit only if the final state is valid. A new dimension key adds a whole dimension axis, while values under an existing key extend that axis. This supports changes like adding `video` to an existing `modality` axis or adding a new dimension such as `region`. Existing units that omit the new dimension remain catch-all units for that axis. Extending an axis does not require copying the unit shape used by other values on that axis; only the supplied final registry must satisfy structural validation.

The registry also owns any private relationship indexes needed to keep downstream checks simple: ancestor lookup by usage key, join lookup by dimension union, family grouping, or equivalent caches. These are implementation details, but validation should be written against model-priced units plus these indexes rather than by scanning every registry unit for every model.

`validation_id` is an opaque identity/version value used only for model-price validation marks. A copied or mutated registry must get a different validation id from the source registry, so a `ModelPrice` validated against one snapshot is not accidentally trusted against another snapshot whose units may have changed.

**Module-level registry access is one lazy helper.** _(implements "There is one global DataSnapshot")_

```python
def _get_registry() -> UnitRegistry:
    """Return get_snapshot().unit_registry via a lazy import."""
```

Other modules use `_get_registry().units[...]`, `_get_registry().families[...]`, and `_get_registry().price_keys[...]` directly. Code that needs the set of usage keys reads `_get_registry().units.keys()`.

---

### `decompose.py` — new file

**Dimension-driven decomposition lives in a dedicated module.** _(implements "Decomposition uses dimensions, not hardcoded subtraction chains", "Only priced units participate in decomposition", "Decomposition operates within a family")_

```python
def is_descendant_or_self(ancestor: UnitDef, descendant: UnitDef) -> bool:
    """Return True when ancestor.dimensions is a subset of descendant.dimensions."""


def compute_leaf_values(
    priced_usage_keys: set[str],
    usage: Usage,
    family: UnitFamily,
    *,
    default_usage: int = 0,
) -> dict[str, int]:
    """Compute exclusive usage for the priced usage-keyed units in one family.

    `default_usage` exists for backward-compat pricing rules such as requests=1 when
    the requests family is priced and no `requests` value was supplied.
    """
```

`compute_leaf_values` uses the family dimension lattice and only the currently priced units. Negative leaf values raise `ValueError` with user-facing messages that describe the contradictory usage relationship, not the underlying algorithm.

Important unresolved dependency: the prose spec's sparse-registry ancestor-closure question must be resolved before this function is implemented. If sparse family shapes are allowed, the current simple `(-1)^(depth difference)` formula may be wrong; the implementation may need to compute Mobius coefficients from the actual priced/registered unit poset instead. Do not hard-code the full-depth sign rule until that decision is made.

---

### `validation.py` — new file

**Price-level validation is centralized here.** _(implements "Validation is split between the registry and `set_custom_snapshot`", "Validation rules are expressed in terms of dimensions, not unit names")_

```python
def validate_price_keys(price_keys: set[str], price_key_index: Mapping[str, str]) -> None:
    """Every model price key must be a registered price key."""


def validate_ancestor_coverage(priced_usage_keys: set[str], family: UnitFamily) -> None:
    """Every priced unit's required ancestors in the same family must also be priced."""


def validate_join_coverage(priced_usage_keys: set[str], family: UnitFamily) -> None:
    """Every priced compatible pair whose join exists in the family must price that join."""


def validate_model_price(price_keys: set[str], registry: UnitRegistry) -> None:
    """Validate one model's price keys, ancestor coverage, and join coverage."""


def mark_model_price_validated(model_price: object, registry: UnitRegistry) -> None:
    """Record that one ModelPrice has been validated for this registry validation id."""


def validate_extractor_destinations(dest_keys: set[str], usage_keys: set[str]) -> None:
    """Every extractor mapping destination must be a registered usage key."""
```

This module does not validate raw registry structure. That stays in `UnitRegistry`.

The meaning of "required ancestors" is tied to the unresolved sparse-registry question in the prose spec. If the final design requires registry ancestor/downward closure, this helper can validate registered ancestors after structural validation has guaranteed the relevant units exist. If the final design allows sparse registry shapes, this helper and `compute_leaf_values(...)` must agree on the actual poset used for decomposition.

---

### `types.py` — modified

**`AbstractUsage` becomes a compatibility alias rather than a real protocol.** _(implements "The usage parameter type is `object`, not a library-specific type", "Backward compatibility is preserved unless clearly impractical")_

```python
AbstractUsage = object
```

This keeps the exported name from `main` while removing the false implication that callers must satisfy a fixed protocol.

**`Usage` becomes a registry-aware class with no hardcoded fields.** _(implements "`Usage` is a registry-aware class that infers and serves correct values", "`Usage` infers ancestor values from descendants")_

```python
class Usage:
    _values: dict[str, int]

    def __init__(self, **kwargs: int | None) -> None:
        """Store non-None values for registered usage keys and infer ancestor totals."""

    @classmethod
    def from_raw(cls, obj: object) -> Usage:
        """Wrap arbitrary usage input.

        - Usage: return as-is
        - Mapping: read known usage keys and construct, ignoring extras
        - Other object: read known usage keys via getattr and construct, ignoring extras
        """

    def __getattr__(self, name: str) -> int:
        """For registered usage keys, return the stored value or 0 if absent.

        Raise AttributeError for names that are not registered usage keys.
        """

    def __add__(self, other: Usage) -> Usage: ...
    def __radd__(self, other: Usage | int) -> Usage: ...
    def __eq__(self, other: object) -> bool: ...
    def __repr__(self) -> str: ...
```

Construction-time inference fills ancestor values from descendants using the active global registry. Explicitly supplied values are never overwritten. `Usage` does not know the requests default-to-1 rule; that stays in pricing code. When `from_raw(...)` wraps arbitrary mappings/objects, it reads known usage keys and ignores extras, preserving existing permissive behavior. This may scan the registry's usage-key set; that is acceptable for now because the registry is expected to stay small and the behavior is correct. Keep the implementation straightforward and leave room for a cached extractor/normalizer later if profiling shows it matters.

Do not add a new immutability contract for `Usage` in this change. Today's Python `Usage` is a mutable dataclass, and preventing mutation is unrelated to the unit-registry goal. If registered usage-key assignment is implemented, it should keep the underlying stored values consistent; otherwise, leave mutation semantics no stricter than they are today.

**`ModelPrice` becomes a registry-backed Pydantic model.** _(implements "ModelPrice supports attribute access backed by registry data", "`calc_price` is a hot path", "`input_price` and `output_price` are backward-compat accessors over direction-filtered costs")_

```python
class ModelPrice(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='allow')

    __pydantic_extra__: dict[str, Decimal | TieredPrices]
    _validated_registry_id: object | None = pydantic.PrivateAttr(default=None)
    _validated_price_key_fingerprint: frozenset[str] | None = pydantic.PrivateAttr(default=None)

    def is_validated_for(self, registry: UnitRegistry) -> bool:
        """Return True when this price has been validated against this registry validation id."""

    def mark_validated(self, registry: UnitRegistry) -> None:
        """Record that the current stored price-key set is valid for this registry validation id."""

    def invalidate_validation(self) -> None:
        """Clear any cached validation mark after supported price mutation."""

    def calc_price(self, usage: object) -> CalcPrice:
        """Price all configured units using the active global registry."""

    def __getattr__(self, name: str) -> Decimal | TieredPrices | None:
        """For registered price keys, return the stored price or None if absent.

        Raise AttributeError for names that are not registered price keys.
        """

    def __str__(self) -> str:
        """Render prices using registry-derived labels and family normalization."""

    def is_free(self) -> bool:
        """Return True when there are no stored prices or every stored price is zero-like."""
```

The validation marker is private implementation state, not part of the serialized model-price data. It is scoped to both `registry.validation_id` and a fingerprint of the current effective stored price keys. "Effective" means keys whose value represents a present price; JS `undefined` and any Python absence/null sentinel do not count as priced. If the same `ModelPrice` object is reused in another snapshot with another registry, or if price keys are added/removed after validation, `is_validated_for(...)` returns false and the next calculation or activation path must validate again.

Supported mutation paths for price data must clear the validation marker. In Python this means overriding or centralizing `__setattr__`/`__delattr__` handling for registry-backed price keys and any explicit mapping-style helper added for extra fields. Setting a different value for an existing key does not structurally require revalidation, but clearing the mark for all supported price mutations is simpler and safe. Direct mutation of internal Pydantic storage such as `__pydantic_extra__` is not a supported public API.

`ModelPrice.calc_price()` changes from hardcoded token arithmetic to this flow:

1. Fetch the active global registry.
2. If `is_validated_for(registry)` is false, run `validate_model_price(...)` for this one price object and call `mark_validated(registry)`.
3. Wrap non-`Usage` input with `Usage.from_raw`.
4. Resolve stored price keys through `registry.price_keys` to usage keys, then group those usage-keyed units by family.
5. For each family, call `compute_leaf_values(...)`.
6. Pass `default_usage=1` only for the `requests` family.
7. Price each leaf using the price stored under the unit's `price_key` and the family's `per` normalization.
8. Aggregate per-unit costs into `input_price`, `output_price`, and `total_price`.

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
The method still accepts a usage object and returns `PriceCalculation`; internally it relies on `ModelPrice.calc_price()` rather than the hardcoded token-only logic from `main`. It does not guard against the `ModelInfo` having been obtained from an inactive `DataSnapshot`. That pattern is unsupported but allowed; it uses the active global registry, matching the rest of the pricing path.

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

    snapshot = DataSnapshot(
        providers=providers,
        from_auto_update=False,
        unit_registry=UnitRegistry(unit_families_data),
    )
    _mark_all_model_prices_validated(snapshot.providers, snapshot.unit_registry)
    return snapshot
```

`_mark_all_model_prices_validated(...)` is a `data_snapshot.py` traversal helper that marks each `ModelPrice` in a provider payload. It does not perform price-level validation in the bundled startup path; it records the private marker on built-in `ModelPrice` objects because the generated repo data was already validated by the build pipeline before `data.py` was written.

**`set_custom_snapshot()` validates before activation.** _(implements "Validation is split between the registry and `set_custom_snapshot`", "Expensive validation happens once at construction/activation time, not on every `calc_price` call")_

```python
def set_custom_snapshot(snapshot: DataSnapshot | None) -> None:
    """Activate a snapshot or reset to bundled default.

    For non-None snapshots:
    - validate every model price key against snapshot.unit_registry.price_keys
    - resolve price keys to usage keys, then validate ancestor and join coverage per family
      using registry relationship indexes rather than full-registry scans per model
    - validate extractor destinations against snapshot.unit_registry.units.keys()
    - after all validation succeeds, mark each ModelPrice for snapshot.unit_registry
    - leave the previous snapshot active if any validation fails
    """
```

This activation step is what turns a snapshot from staged data into trusted runtime state. Before activation, a snapshot may contain `ModelPrice` objects and extractor configs whose unit references have not yet been checked against that snapshot's registry. After successful activation, the snapshot becomes the sole registry/provider set used for execution, and its model prices carry validation marks for that registry.

This also covers user patching of bundled prices. A caller can copy the current provider/model data, add missing fields such as cache-token prices to the staged `ModelPrice` objects, and activate the new snapshot. The mutations invalidate any bundled validation marks; `set_custom_snapshot()` validates the updated price-key set and marks the prices again before activation.

**`DataSnapshot.calc()` and `DataSnapshot.extract_usage()` require `self is get_snapshot()`.** _(implements "`calc` and `extract_usage` on DataSnapshot require it to be the current global")_
Both methods raise `RuntimeError` when called on a non-active snapshot. This is intentional discouragement of "standalone snapshot" execution: inactive snapshots are staging objects, not validated execution contexts. This guard applies to snapshot execution methods only; `ModelInfo.calc_price()` does not carry snapshot provenance and is not guarded. `find_provider_model()` and `find_provider()` stay pure lookup helpers and remain usable on inactive snapshots. _(implements "`find_provider_model` works on any snapshot, global or not")_

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

## Python Build/Runtime Boundary

**Registry and validation code should be shared when the dependency direction is clean, but duplication is acceptable at the build-package boundary.** _(implements "Derive, don't duplicate", "Validation replaces what hardcoded fields gave us implicitly, and adds more")_
The `prices/` build package already has build-time types that mirror runtime package types. This is not ideal, but it is an established boundary in the repo: build-time parsing and schema generation operate before generated runtime data exists, while the published runtime package must not depend on the build package.

The implementation should first try to make the registry and structural validation modules pure enough for both sides to use:

- `UnitRegistry`, `UnitDef`, `UnitFamily`, and dimension/relationship helpers should avoid importing generated package data, `data_snapshot`, update machinery, or runtime globals.
- Price-level validation helpers should accept plain mappings, registry objects, and protocol-shaped price values where possible, instead of requiring runtime-only model objects.
- Build-time code may import those pure helpers from the runtime package if that does not create import cycles, generated-data dependencies, or awkward coupling to runtime-only Pydantic models.

If that clean sharing turns out to be awkward, the fallback is explicit and acceptable: keep a small build-side mirror under `prices/src/prices/` following the existing `prices_types.py` pattern. In that case, keep the duplicated surface narrow and mechanical:

- one source registry file (`prices/units.yml`) remains the source of truth
- runtime and build-time registry objects must parse the same raw `unit_families` shape
- tests should cover parity for structural validation, price-key resolution, ancestor coverage, and join coverage
- any deliberate duplication should be named in comments as a package-boundary copy, not a second design

This is a structural implementation decision, not a detail hidden inside `build()`. The final implementation should make the boundary obvious in module placement and tests.

---

## Build Pipeline: `prices/src/prices/`

### `prices_types.py` — modified

**Build-time `ModelPrice` becomes registry-permissive.** _(implements "Validation replaces what hardcoded fields gave us implicitly, and adds more", "Generated JSON schemas provide editor autocomplete for provider YAML files")_

```python
class ModelPrice(_Model, extra='allow'):
    __pydantic_extra__: dict[str, DollarPrice | TieredPrices]

    def is_free(self) -> bool: ...
```

The explicit hardcoded price fields from `main` are removed as the source of truth. Validation of allowed keys moves to registry-derived build checks and schema generation.

**`UsageExtractorMapping.dest` becomes `str`.** _(implements "The extraction pipeline is data-driven end-to-end")_
The literal `UsageField` union is removed from build-time types.

---

### `build.py` — modified

**Build starts from the registry file, then validates provider data against it.** _(implements "Expensive validation happens once at construction/activation time, not on every `calc_price` call", "Price key validation: every key in a model's prices must be a registered price key", "Ancestor coverage is validated", "Join coverage is validated")_

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
   - resolve price keys to usage keys
   - validate ancestor coverage
   - validate join coverage
5. Validate extractor destinations against registry usage keys.
6. Write wrapped `data.json` and `data_slim.json`.

**JSON schema generation becomes registry-derived.** _(implements "Generated JSON schemas provide editor autocomplete for provider YAML files", "Validation rules are expressed in terms of dimensions, not unit names")_
The provider YAML schema no longer relies on hardcoded `ModelPrice` fields or a hardcoded extractor `dest` union. Instead, `build.py` derives:

- allowed price keys from `registry.price_keys`
- allowed extractor destinations from `registry.units`
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

**Usage, price, and unit data shapes live in shared TS types.** _(implements "Units are data, not code", "The system is general across unit families")_

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
  dimensions: Record<string, string[]>
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
  dimensions: Record<string, string[]>
  units: Record<string, UnitDef> // usageKey -> UnitDef
}

export type ParsedFamilies = Record<string, UnitFamily>

export interface StorageFactoryParams {
  onCalc: (cb: () => void) => void
  remoteDataUrl: string
  setProviderData: (data: ProviderDataPayload) => void
  setUnitFamilies: (families: ParsedFamilies | null) => void
}
```

Public JS callers still pass plain usage objects. The only extra behavior is an internal normalization step that returns another plain usage object.

---

### `units.ts` — new file

**JS gets a runtime registry module parallel to Python's `UnitRegistry`.** _(implements "`UnitRegistry` is the runtime representation of unit definitions", "Unit definitions travel with prices, not just with the package")_

```typescript
export type { ParsedFamilies, RawFamiliesDict, UnitDef, UnitFamily } from './types'

export function parseFamilies(raw: RawFamiliesDict): ParsedFamilies
// Parses raw family data into UnitFamily/UnitDef objects, fills family
// back-references, and validates structure and join-closedness without mutating
// active runtime state. Raw unit keys are usage keys; priceKey is
// raw.price_key ?? usageKey.

export function setUnitFamilies(families: ParsedFamilies | null): void
// Replaces the active parsed registry. For null input, restores the generated
// bundled registry.

export function getFamily(familyId: string): UnitFamily
export function getUnit(usageKey: string): UnitDef
export function getUnitForPriceKey(priceKey: string): UnitDef
export function getUsageKeyForPriceKey(priceKey: string): string
export function getAllUsageKeys(): Set<string>
export function getAllPriceKeys(): Set<string>
export function getRegistryValidationId(): object
```

The module bootstraps itself from generated `unitFamiliesData` and allows the active registry to be replaced from runtime-updated JSON. JS needs the same atomic existing-family edit capability as Python, but the exact public API shape is still open. It may be a builder, a transaction-like helper, a replace-family helper, or a batch update function. Whatever API is chosen must work on staged parsed families and return or commit a structurally valid parsed registry without mutating the active registry in place. The active parsed families object identity is the JS `registryValidationId`; replacing the registry produces a new validation id, so model-price validation marks from the previous registry are not reused.

---

### `decompose.ts` — new file

**JS decomposition logic becomes dimension-driven too.** _(implements "Decomposition uses dimensions, not hardcoded subtraction chains", "Only priced units participate in decomposition")_

```typescript
export function isDescendantOrSelf(ancestor: UnitDef, descendant: UnitDef): boolean

export function computeLeafValues(
  pricedUsageKeys: Set<string>,
  usage: Usage,
  family: UnitFamily,
  defaultUsage?: number,
): Record<string, number>
```

`computeLeafValues()` consumes normalized plain usage data, not raw caller input. By the time decomposition runs, JS behavior matches Python behavior: ancestor totals have already been inferred, missing keys read as zero, and negative leaves indicate a genuine contradiction rather than an inference gap.

Like Python, the JS requests default is passed in by pricing code via `defaultUsage=1`.

---

### `usage.ts` — new file

**JS gets a plain-object normalization helper.** _(implements "`Usage` infers ancestor values from descendants", "Incomplete usage is handled gracefully, not rejected")_

```typescript
export function normalizeUsage(obj: unknown): Usage
```

`normalizeUsage(...)` accepts a plain JS usage object, reads known usage keys, ignores extra unknown keys, infers ancestor totals from descendants, and returns a plain `Usage` object containing the provided plus inferred values. This may scan the registry's usage-key set; that is acceptable for now because it keeps the permissive API correct and the registry is expected to stay small. This keeps JS behavior aligned with Python without introducing a wrapper class that provides little value.

---

### `validation.ts` — new file

**JS validation mirrors the Python split between registry structure and price payloads.** _(implements "Validation replaces what hardcoded fields gave us implicitly, and adds more", "Expensive validation happens once at construction/activation time, not on every `calc_price` call")_

```typescript
export function validateRegistryStructure(families: ParsedFamilies): void
export function validateRegistryJoinClosedness(family: UnitFamily): void
export function validatePriceKeys(priceKeys: Set<string>, allPriceKeys: Set<string>): void
export function validateAncestorCoverage(pricedUsageKeys: Set<string>, family: UnitFamily): void
export function validateJoinCoverage(pricedUsageKeys: Set<string>, family: UnitFamily): void
export function validateModelPrice(modelPrice: ModelPrice, families: ParsedFamilies): void
export function validateExtractorDestinations(destKeys: Set<string>, usageKeys: Set<string>): void
export function validateProviderData(providers: Provider[], families: ParsedFamilies): void
export function isModelPriceValidated(modelPrice: ModelPrice, families: ParsedFamilies): boolean
export function markModelPriceValidated(modelPrice: ModelPrice, families: ParsedFamilies): void
export function invalidateModelPriceValidation(modelPrice: ModelPrice): void
```

`setUnitFamilies()` is the activation step for the active parsed registry. `validateProviderData()` validates a staged provider payload against a staged parsed registry so runtime updates can be atomic: if validation fails, neither the active registry nor active provider data changes. After it successfully validates a staged payload, it marks each model price as validated for that exact `registryValidationId` and its current price-key fingerprint. The update path must then install that same parsed registry object; parsing the raw unit data a second time would produce a different validation id and stale the marks immediately. The marker can be a module-private `WeakMap<ModelPrice, { registryValidationId: object; priceKeys: string }>` or equivalent; it is not part of serialized provider data. JS model prices are plain objects, so arbitrary caller mutation cannot be intercepted; `isModelPriceValidated(...)` must always compare the current price-key fingerprint with the stored fingerprint. Any library-provided helper for mutating model prices should call `invalidateModelPriceValidation(...)` explicitly. Validation should iterate each model's stored price keys and use parsed registry indexes/relationship caches; avoid repeatedly scanning every registry unit for every model.

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

1. reads the active `registryValidationId`
2. if `isModelPriceValidated(modelPrice, activeFamilies)` is false, validates this one model price and marks it
3. normalizes raw input with `normalizeUsage(...)`
4. reads `totalInputTokens` from normalized `usage.input_tokens`
5. resolves stored price keys to usage-keyed units via `getUnitForPriceKey(priceKey)`
6. groups resolved units by `unit.family` and computes leaf values per family
7. passes `defaultUsage=1` for the requests family
8. prices each leaf using the value stored under the unit's price key and `family.per`
9. aggregates by `direction` into the existing result shape

For tiered prices, the threshold input is this normalized `usage.input_tokens` total, preserving Python's behavior: tier selection is based on the full inferred-or-provided input-token count, not on any one decomposed leaf.

It no longer contains hardcoded logic for cache/audio/request arithmetic. It does not validate every calculation; after startup or activation has marked model prices, the hot path pays only a cheap validation-marker check. The one-model validation fallback exists for bypassed/standalone model-price objects.

---

### `api.ts` — modified

**Runtime data activation now handles wrapped JSON plus unit families.** _(implements "Unit definitions travel with prices, not just with the package")_

`updatePrices()` passes both `setProviderData` and `setUnitFamilies` to the storage factory. The runtime update path stages the new payload in this order:

1. parse wrapped JSON
2. `stagedFamilies = parseFamilies(parsed.unit_families)`
3. `validateProviderData(parsed.providers, stagedFamilies)`
4. on success only: `setUnitFamilies(stagedFamilies)` and `setProviderData(parsed.providers)`

If parsing or validation fails, both the active registry and active provider data remain unchanged.

The embedded startup path still uses generated `data.ts`, but the active registry is initialized from `unitFamiliesData` instead of being implicit in engine code. Because generated `data.ts` came from build-validated repo data, startup marks the embedded provider data's model prices as validated for that bundled parsed registry without rerunning full provider validation.

The checked-in JS examples must be updated to cache and restore the wrapped payload shape, not a bare provider array, and to parse families before calling both `setUnitFamilies(stagedFamilies)` and `setProviderData(...)`.

---

### `extractUsage.ts` — modified

**Extractor output keys are no longer a fixed union.** _(implements "The extraction pipeline is data-driven end-to-end")_
The existing extraction logic still builds a plain object of counts. The change here is both structural and semantic:

- `UsageExtractorMapping.dest` is now `string`, so extracted usage can target any registry-defined usage key
- after extraction, the raw count object is normalized through `normalizeUsage(...)`
- `extractUsage(...)` returns that normalized plain object, so JS callers get the same inferred-ancestor behavior that Python callers get from `Usage`

---

## Call Relationships

### Registry construction

```text
prices/units.yml
  -> build.py loads raw family dict
  -> UnitRegistry(raw_families)
       -> create UnitFamily shells
       -> create UnitDef objects
       -> fill families / units / price_keys indexes
       -> validate dimension rules, uniqueness, join-closedness
```

### Build-time validation and packaging

```text
build()
  -> load units.yml
  -> registry = UnitRegistry(unit_families)
  -> load provider YAML files
  -> validate model price keys
  -> resolve price keys to usage keys
  -> validate ancestor coverage / join coverage
  -> validate extractor destinations
  -> write wrapped data.json and data_slim.json

package_data()
  -> read wrapped data.json
  -> package_python_data(): emit providers + unit_families_data
  -> package_ts_data(): emit data + unitFamiliesData
  -> generated runtime data is trusted only because build validation succeeded first
```

### Python bundled startup

```text
get_snapshot()
  -> _bundled_snapshot()
       -> import providers, unit_families_data from generated data.py
       -> UnitRegistry(unit_families_data)
       -> DataSnapshot(providers=..., unit_registry=..., from_auto_update=False)
       -> mark generated ModelPrice objects validated for the bundled registry
```

### Python snapshot activation

```text
set_custom_snapshot(snapshot)
  -> if snapshot is None: clear custom snapshot
  -> else validate prices and extractor destinations against snapshot.unit_registry
  -> after all validation succeeds, mark ModelPrice objects for snapshot.unit_registry
  -> on success: activate snapshot as the only trusted execution snapshot
  -> on failure: raise and keep previous snapshot
```

### Python custom unit flow

```text
get_snapshot()
  -> registry = current_snapshot.unit_registry.copy()
  -> providers = copy current_snapshot.providers/models/prices
  -> mutate staged ModelPrice objects as needed
       -> mutation invalidates inherited validation marks
  -> registry.add_family(...), registry.add_unit(...), and/or atomic existing-family edit API
  -> snapshot = DataSnapshot(
       providers=providers,
       from_auto_update=False,
       unit_registry=registry,
     )
  -> set_custom_snapshot(snapshot)
       -> validate prices against expanded registry
       -> mark ModelPrice objects for expanded registry
       -> activate on success
```

### Python hot path

```text
ModelPrice.calc_price(usage)
  -> registry = get_snapshot().unit_registry
  -> if validation mark is missing/stale:
       validate this ModelPrice against registry and mark it
  -> smart_usage = Usage.from_raw(usage)
  -> total_input_tokens = smart_usage.input_tokens
  -> resolve stored price keys to usage keys and group by family
  -> for each family:
       default_usage = 1 only for requests
       leaf_values = compute_leaf_values(priced_usage_keys, smart_usage, family, default_usage=...)
  -> for each priced usage-keyed unit:
       price = stored price at unit.price_key
       cost = calc_unit_price(price, leaf_count, total_input_tokens, family.per)
       aggregate by direction
  -> return {input_price, output_price, total_price}
```

### JS runtime activation

```text
generated data.ts
  -> unitFamiliesData bootstraps units.ts
  -> data bootstraps providerData
  -> mark generated providerData model prices validated for the bundled registry

runtime update
  -> parse wrapped JSON
  -> stagedFamilies = parseFamilies(parsed.unit_families)
  -> validateProviderData(parsed.providers, stagedFamilies)
       -> mark successfully validated model prices for stagedFamilies
  -> on success only:
       setUnitFamilies(stagedFamilies)
       setProviderData(parsed.providers)
  -> on failure:
       keep both active registry and providerData unchanged
```

### JS custom unit flow

```text
copy active parsed families
  -> stagedFamilies = atomic existing-family edit on 'tokens':
       add dimension value { modality: ['video'] }
       add unit cache_video_read_tokens
     # This example intentionally adds only the unit the caller needs; registry
     # validation does not require video to mirror other modalities.
  -> stagedProviders = copy and patch providerData/model prices
  -> validateProviderData(stagedProviders, stagedFamilies)
       -> mark successfully validated model prices for stagedFamilies
  -> setUnitFamilies(stagedFamilies)
  -> setProviderData(stagedProviders)
```
