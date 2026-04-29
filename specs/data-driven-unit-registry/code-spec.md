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

The runtime packages continue loading generated code at startup; they do not parse `prices/units.yml` directly. Generated data exports contain units and prices only. They must not include serialized decomposition caches, decomposition coefficients, or bulky per-model validation artifacts; those are runtime-private state built or marked in memory.

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
    units: dict[str, UnitDef]  # usage_key -> UnitDef
```

There is no `RawUnitDef`/`RawUnitFamily`/`RawFamiliesDict` model layer in Python runtime code. Raw registry data stays as plain dictionaries until `UnitRegistry` constructs these objects.

**`UnitRegistry` owns all runtime unit state.** _(implements "`UnitRegistry` is the runtime representation of unit definitions", "Users can define custom units at runtime", "Registry interval closure", "Registry join-closedness: compatible unit pairs must have their join in the family")_

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
        units: dict[str, dict],
    ) -> None:
        """Add and validate a new family."""

    def add_units(
        self,
        family_id: str,
        units: dict[str, dict],
    ) -> None:
        """Atomically add one or more units to an existing family, then validate."""

    def copy(self) -> UnitRegistry:
        """Return an independent copy. Useful internally; not required for ordinary user patches."""

    @staticmethod
    def are_compatible(a: UnitDef, b: UnitDef) -> bool:
        """Return True when the two units do not conflict on any dimension key."""
```

Registry construction and mutation perform all structural validation:

- usage keys are globally unique
- price keys are globally unique
- no two units in a family share the same dimension set
- every comparable pair in a family has all intermediate dimension sets present
- every compatible pair in a family has its join present in that family

`add_units(...)` is the only existing-family unit-addition API. It stages all supplied units against a candidate family, validates the complete candidate registry once, and commits only if the final state is valid. Passing a one-unit mapping handles the simple case; passing several units handles changes that would be invalid one unit at a time under interval closure or join-closedness. Unit dimension maps are the only source of dimension keys and values: adding a unit with `{modality: video}` or `{region: us}` introduces that value or axis if the final registry validates. Existing units that omit a dimension remain catch-all units for that axis. Extending an axis does not require copying the unit shape used by other values on that axis; only the supplied final registry must satisfy structural validation.

`UnitRegistry.copy()` may remain available as a low-level helper, but it is not the required public workflow for custom pricing. `DataSnapshot` should expose or forward supported unit-editing operations so callers can patch the snapshot they are working with. The implementation may still copy the registry internally to validate and roll back failed edits.

The registry also owns any private relationship indexes needed to keep downstream checks simple: ancestor lookup by usage key, join lookup by dimension union, family grouping, or equivalent caches. These are implementation details, but validation should be written against model-priced units plus these indexes rather than by scanning every registry unit for every model.

`validation_id` is an opaque identity/version value used only for model-price known-valid state and optional decomposition caches. An independently constructed or destructively mutated registry must get a different validation id from the source registry unless the mutation path can prove compatibility for existing validation state, so a `ModelPrice` validated or cached against one snapshot is not accidentally trusted against another snapshot whose units may have changed incompatibly. Purely additive registry mutations must preserve validation compatibility for unchanged trusted prices whose referenced units and price-key mappings still exist with the same meaning. The implementation may do this by preserving an inherited compatibility id for those prices, recording compatible prior validation ids on the new registry, or using an equivalent private mechanism. A raw validation-id mismatch is not enough by itself to revalidate a trusted built-in price.

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
@dataclass(frozen=True)
class CachedFamilyDecomposition:
    family: UnitFamily
    leaf_coefficients: Mapping[str, tuple[tuple[str, int], ...]]
    """Optional cache: priced usage key -> terms for computing that exclusive bucket."""


@dataclass(frozen=True)
class CachedPricingPlan:
    registry_id: object
    price_key_fingerprint: frozenset[str]
    price_key_to_usage_key: Mapping[str, str]
    families: tuple[CachedFamilyDecomposition, ...]


def is_descendant_or_self(ancestor: UnitDef, descendant: UnitDef) -> bool:
    """Return True when ancestor.dimensions is a subset of descendant.dimensions."""


def build_family_decomposition_cache(
    priced_usage_keys: set[str],
    family: UnitFamily,
) -> CachedFamilyDecomposition:
    """Optionally precompute reusable decomposition instructions for one model/family."""


def compute_leaf_values(
    priced_usage_keys: set[str],
    usage: Usage,
    family: UnitFamily,
    *,
    default_usage: int = 0,
    cache: CachedFamilyDecomposition | None = None,
) -> dict[str, int]:
    """Return exclusive usage buckets for one family.

    If a cache is supplied, use it; otherwise compute the decomposition directly.

    `default_usage` exists for backward-compat pricing rules such as requests=1 when
    the requests family is priced and no `requests` value was supplied.
    """
```

`compute_leaf_values(...)` uses the family dimension lattice and only priced units become returned cost buckets. A cached `CachedFamilyDecomposition` is allowed when it keeps the implementation simple, but it is not required. Decomposition coefficients depend on the registry/family shape and the model's priced usage keys; the resulting leaf values also depend on the current usage values. The full-depth sign rule is valid because registry interval closure, registry join-closedness, price ancestor coverage, and price join coverage remove the structural gaps that would otherwise break it. Reading a missing usage value may trigger lazy inference on `Usage`. Unpriced reported usage keys do not participate in consistency checks unless they are needed to infer a missing priced value. For example, `input_tokens=100` and `cache_read_tokens=200` must not fail for a model that only has an input catch-all price, but must fail when `cache_read_tokens` is also priced. Negative leaf values, contradictory usage that affects priced buckets, or required values that cannot be inferred coherently raise `ValueError` with user-facing messages that describe the usage data problem, not the underlying algorithm.

---

### `validation.py` — new file

**Price-level validation is centralized here.** _(implements "Validation is split between the registry and `set_custom_snapshot`", "Validation rules are expressed in terms of dimensions, not unit names")_

```python
def validate_price_keys(price_keys: set[str], price_key_index: Mapping[str, str]) -> None:
    """Every model price key must be a registered price key."""


def validate_ancestor_coverage(priced_usage_keys: set[str], family: UnitFamily) -> None:
    """Every priced unit's required ancestors in the same family must also be priced."""


def validate_join_coverage(priced_usage_keys: set[str], family: UnitFamily) -> None:
    """Every priced compatible pair must price its join unit."""


def validate_model_price(price_keys: set[str], registry: UnitRegistry) -> None:
    """Validate one model's price keys, ancestor coverage, and join coverage."""


def mark_model_price_known_valid(model_price: object, registry: UnitRegistry) -> None:
    """Record build/runtime validation provenance without building a decomposition plan."""


def build_pricing_plan_cache(model_price: object, registry: UnitRegistry) -> CachedPricingPlan:
    """Optional helper to build reusable pricing/decomposition state for a known-valid price."""


def validate_extractor_destinations(dest_keys: set[str], usage_keys: set[str]) -> None:
    """Every extractor mapping destination must be a registered usage key."""
```

This module does not validate raw registry structure. That stays in `UnitRegistry`. `validate_ancestor_coverage(...)` checks registered ancestors after registry interval closure has guaranteed that structurally required intermediates exist. `validate_join_coverage(...)` can assume a compatible pair's join exists because registry join-closedness already proved it.

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
        """Store non-None reported values for registered usage keys."""

    @classmethod
    def from_raw(cls, obj: object) -> Usage:
        """Wrap arbitrary usage input.

        - Usage: return as-is
        - Mapping: read known usage keys and construct, ignoring extras
        - Other object: read known usage keys via getattr and construct, ignoring extras
        """

    def __getattr__(self, name: str) -> int:
        """For registered usage keys, return the stored value, lazily infer it, or return 0 if absent.

        Raise AttributeError for names that are not registered usage keys.
        Raise ValueError only if a missing requested value must be inferred and
        that inference depends on contradictory or underdetermined reported usage.
        """

    def __add__(self, other: Usage) -> Usage: ...
    def __radd__(self, other: Usage | int) -> Usage: ...
    def __eq__(self, other: object) -> bool: ...
    def __repr__(self) -> str: ...
```

Construction does not infer ancestor totals and must not reject contradictory registered values. It stores the non-`None` values reported by the caller or extractor so provider APIs can be represented faithfully even when their usage payload is internally inconsistent. Reported values are never overwritten. `_values` contains reported values only. Do not add explicit-vs-inferred provenance unless implementation work finds a concrete diagnostic that cannot be produced from the reported values and the current missing-value inference context.

Registered attribute access is the inference boundary. If a value is stored, return it without scanning the rest of the usage object for possible contradictions. If it is missing, infer it from descendants only when the active registry relationships and currently stored values determine a coherent value. Do not cache inferred usage values; recompute them when requested. This avoids subtle bugs where derived ancestors start behaving like reported data in `__add__`, equality, representation, or later diagnostics. If there is no data for the requested unit, return zero. If the missing-value inference needs values that cross independent dimensions without enough totals/intersections to determine a unique answer, or if it must reconcile contradictory reported values, raise `ValueError` with a user-facing message. `Usage.__add__` should sum reported values only, letting the result infer lazily again. `Usage` does not know the requests default-to-1 rule; that stays in pricing code. When `from_raw(...)` wraps arbitrary mappings/objects, it reads known usage keys and ignores extras, preserving existing permissive behavior. This may scan the registry's usage-key set; that is acceptable for now because the registry is expected to stay small and the behavior is correct. Keep the implementation straightforward.

Do not add a new immutability contract for `Usage` in this change. Today's Python `Usage` is a mutable dataclass, and preventing mutation is unrelated to the unit-registry goal. If registered usage-key assignment is implemented, it should keep the underlying stored values consistent; otherwise, leave mutation semantics no stricter than they are today.

**`ModelPrice` becomes a registry-backed Pydantic model.** _(implements "ModelPrice supports attribute access backed by registry data", "`calc_price` is a hot path", "`input_price` and `output_price` are backward-compat accessors over direction-filtered costs")_

```python
class ModelPrice(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='allow')

    __pydantic_extra__: dict[str, Decimal | TieredPrices]
    _known_valid_registry_id: object | None = pydantic.PrivateAttr(default=None)
    _known_valid_price_key_fingerprint: frozenset[str] | None = pydantic.PrivateAttr(default=None)
    _pricing_plan_cache: CachedPricingPlan | None = pydantic.PrivateAttr(default=None)

    def is_known_valid_for(self, registry: UnitRegistry) -> bool:
        """Return True when this price-key set is already known valid for this registry or a compatible extension."""

    def mark_known_valid(self, registry: UnitRegistry) -> None:
        """Record that the current stored price-key set is valid for this registry's validation basis."""

    def get_cached_pricing_plan(self, registry: UnitRegistry) -> CachedPricingPlan | None:
        """Optionally return cached decomposition state for this registry or a compatible extension."""

    def invalidate_validation_and_decomposition_cache(self) -> None:
        """Clear known-valid state and any decomposition cache after structural price mutation."""

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

Known-valid state and any cached pricing plan are private implementation state, not part of serialized model-price data. Both are scoped to registry validation compatibility and a fingerprint of the current effective stored price keys. "Effective" means keys whose value represents a present price; JS `undefined` and any Python absence/null sentinel do not count as priced. Known-valid state means price-level validation has already accepted this price-key set for the registry basis that matters to that price, either in the repo build pipeline or during runtime snapshot activation. A cached pricing plan, if implemented, stores the resolved price-key/usage-key mapping, family groupings, and per-family decomposition coefficients or equivalent decomposition instructions. It does not depend on a particular usage object. This cache is optional; `calc_price` may compute the same decomposition directly from the model's priced keys and registry indexes. Pure unit additions do not make unchanged trusted prices or their pricing plans stale. If the same `ModelPrice` object is reused in another snapshot whose registry deletes or changes units referenced by the price, or if price keys are added/removed after validation, `is_known_valid_for(...)` returns false and any cached plan is stale.

Supported mutation paths that add or remove effective price keys must clear known-valid state and any cached decomposition state. In Python this means overriding or centralizing `__setattr__`/`__delattr__` handling for registry-backed price keys and any explicit mapping-style helper added for extra fields. Setting a different value for an existing key does not structurally require revalidation or recomputing coefficients if the cache does not bake in price values; clearing only the cache is acceptable if the implementation cannot cheaply prove price values are unbound from the cache. Direct mutation of internal Pydantic storage such as `__pydantic_extra__` is not a supported public API.

`ModelPrice.calc_price()` changes from hardcoded token arithmetic to this flow:

1. Fetch the active global registry.
2. If `is_known_valid_for(registry)` is false, validate this one model price and mark it known valid.
3. Wrap non-`Usage` input with `Usage.from_raw`.
4. Resolve stored price keys through `registry.price_keys` to usage keys and group those units by family, or read an equivalent cached pricing plan if present.
5. For tiered prices, read `usage.input_tokens`; if it is stored, use it without reconciling descendant values. If it is missing and cannot be inferred coherently, raise a usage error instead of guessing a tier.
6. For each priced family, compute leaf values from the registry-aware usage, optionally using cached decomposition instructions, while ignoring unpriced reported usage values unless they are needed to infer a missing priced value.
7. Pass `default_usage=1` only for the `requests` family.
8. Price each leaf using the price stored under the unit's `price_key` and the family's `per` normalization.
9. Aggregate per-unit costs into `input_price`, `output_price`, and `total_price`.

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

`dest` is a registered usage key from the snapshot registry, not an arbitrary string and not a model-price key. Repo-defined extractor mappings are validated against the build-time registry. Runtime-authored extractor mappings are validated against the staged snapshot's registry during `set_custom_snapshot()`, which lets a custom extractor target a runtime custom unit only after that unit has been added to the same snapshot.

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

`DataSnapshot` is the public editing surface for runtime customizations. Callers should be able to patch the snapshot they are working with by using supported mutation helpers for unit definitions and model prices; they should not need to manually deep-copy the registry, provider tree, models, or `ModelPrice` objects just to add one unit or one price. The exact snapshot convenience method names are still open, but the required capabilities are:

- add a unit family or a batch of units to `snapshot.unit_registry`
- update a model's effective price keys on the snapshot
- invalidate known-valid state and optional decomposition caches only for changed `ModelPrice` objects
- validate/rollback registry structure before a registry edit becomes visible
- leave inactive snapshots as staging objects until `set_custom_snapshot(snapshot)` validates and activates them

An implementation may use internal copy-on-write, transactions, or candidate objects to keep rollback simple. That is an implementation detail; the public API should read as editing a snapshot.

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

Bundled startup does not serialize, import, validate, or eagerly compute decomposition plans for every built-in model. The generated repo data was already validated by the build pipeline, so built-in model prices may be treated as known valid for the bundled registry without running price-level validation. The mechanism may be a lightweight private marker attached while generated data is constructed, a snapshot-level trusted-provenance marker, or equivalent state that does not increase generated/downloaded data size. If the implementation uses a decomposition cache, each built-in `ModelPrice` builds that cache lazily the first time `calc_price` needs it. This avoids increasing package/download size and avoids startup work for models that are never priced in the current process.

**`set_custom_snapshot()` validates before activation.** _(implements "Validation is split between the registry and `set_custom_snapshot`", "Expensive validation happens once at construction/activation time, not on every `calc_price` call")_

```python
def set_custom_snapshot(snapshot: DataSnapshot | None) -> None:
    """Activate a snapshot or reset to bundled default.

    For non-None snapshots:
    - skip price-level validation for model prices already known valid for snapshot.unit_registry
      and their current price-key fingerprint
    - skip trusted built-in or official auto-update model prices made compatible by pure
      additive registry changes; unit additions do not make those prices stale
    - validate missing/stale custom, changed, runtime-authored, or otherwise untrusted model
      prices against snapshot.unit_registry.price_keys
    - resolve their price keys to usage keys, then validate ancestor and join coverage per family
      using registry relationship indexes rather than full-registry scans
    - validate extractor destinations against snapshot.unit_registry.units.keys()
    - after all validation succeeds, mark newly validated ModelPrice objects known valid
    - optionally build decomposition caches for newly validated ModelPrice objects, but do not
      compute caches for every trusted built-in price eagerly
    - leave the previous snapshot active if any validation fails
    """
```

This activation step is what turns a snapshot from staged data into trusted runtime state. Before activation, a snapshot may contain `ModelPrice` objects and extractor configs whose unit references have not yet been checked against that snapshot's registry. After successful activation, the snapshot becomes the sole registry/provider set used for execution, and any custom, changed, runtime-authored, or otherwise untrusted model prices that needed runtime validation carry known-valid state for that registry. Unchanged model prices from trusted bundled or official auto-update data are not revalidated in bulk. They keep known-valid state when the registry validation id still matches, and pure unit additions must also preserve validation compatibility for those prices. If a destructive registry change makes an affected trusted price stale, the one-model `calc_price` fallback validates it only if it is actually used.

This also covers user patching of bundled prices. A caller can edit a snapshot, add missing fields such as cache-token prices to the relevant `ModelPrice` objects, and activate the snapshot if it is not already active. The mutations invalidate known-valid state and any decomposition cache for the changed model prices only; `set_custom_snapshot()` validates those updated price-key sets before activation without validating every unchanged built-in price.

**`DataSnapshot.calc()` and `DataSnapshot.extract_usage()` require `self is get_snapshot()`.** _(implements "`calc` and `extract_usage` on DataSnapshot require it to be the current global")_
Both methods raise `RuntimeError` when called on a non-active snapshot. This is intentional discouragement of "standalone snapshot" execution: inactive snapshots are staging objects, not validated execution contexts. This guard applies to snapshot execution methods only; `ModelInfo.calc_price()` does not carry snapshot provenance and is not guarded. `find_provider_model()` and `find_provider()` stay pure lookup helpers and remain usable on inactive snapshots. _(implements "`find_provider_model` works on any snapshot, global or not")_

---

### `update_prices.py` — modified

**`UpdatePrices.fetch()` parses the new top-level JSON wrapper.** _(implements "Unit definitions travel with prices, not just with the package")_

```python
def fetch(self) -> DataSnapshot | None:
    """Fetch data.json, parse unit_families and providers, build a snapshot."""
```

Instead of validating the whole payload as `list[Provider]`, `fetch()` parses the wrapper object, validates the provider object shape, constructs `UnitRegistry(raw['unit_families'])`, and returns a `DataSnapshot` containing both. Because this fetch path reads official repo-built data, it treats returned model prices as known valid for that fetched registry without running price-level validation for every model or computing decomposition caches.

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
- tests should cover parity for structural validation (including interval closure and join-closedness), price-key resolution, ancestor coverage, and join coverage
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
2. Construct `UnitRegistry(unit_families)`; this performs structural validation, including interval closure and join-closedness.
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
// back-references, and validates structure, interval closure, and
// join-closedness without mutating active runtime state. Raw unit keys are usage keys; priceKey is
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

The module bootstraps itself from generated `unitFamiliesData` and allows the active registry to be replaced from runtime-updated JSON. JS needs the same existing-family batch unit-addition capability as Python. Whatever API name is chosen must let callers patch the snapshot/update payload they are working with rather than manually copy the active parsed families and provider data. Internally, the implementation can stage parsed families and return or commit a structurally valid parsed registry only after validation succeeds. The active parsed families object identity can be part of the JS `registryValidationId`, but known-valid checks need validation compatibility rather than raw object identity. Replacing the registry with a pure additive extension must not make unchanged trusted built-in prices stale; deleting or changing referenced unit definitions may. Stale trusted built-in prices caused by destructive changes are not bulk-revalidated during activation; `calcPrice()` validates one such price if that model is later priced.

---

### `decompose.ts` — new file

**JS decomposition logic becomes dimension-driven too.** _(implements "Decomposition uses dimensions, not hardcoded subtraction chains", "Only priced units participate in decomposition")_

```typescript
export function isDescendantOrSelf(ancestor: UnitDef, descendant: UnitDef): boolean

export type CachedFamilyDecomposition = {
  family: UnitFamily
  leafCoefficients: Record<string, Array<[string, number]>>
}

export type CachedPricingPlan = {
  registryValidationId: object
  priceKeyFingerprint: string
  priceKeyToUsageKey: Record<string, string>
  families: CachedFamilyDecomposition[]
}

export function buildFamilyDecompositionCache(
  pricedUsageKeys: Set<string>,
  family: UnitFamily,
): CachedFamilyDecomposition

export function computeLeafValues(
  pricedUsageKeys: Set<string>,
  usage: NormalizedUsage,
  family: UnitFamily,
  defaultUsage?: number,
  cache?: CachedFamilyDecomposition,
): Record<string, number>
```

`buildFamilyDecompositionCache(...)` is an optional cache helper. `computeLeafValues()` consumes registry-normalized usage data, not raw caller input, and may use a cached decomposition if one is available. Reading a missing value goes through the same lazy inference helper used by the rest of JS pricing. Missing keys with no relevant data read as zero. Unpriced reported usage keys are ignored unless needed to infer a missing priced value. Negative leaves, contradictory usage that affects priced buckets, or required values that cannot be inferred coherently raise a user-facing error rather than reporting a negative or nonsensical cost. Usage values do not need explicit-vs-inferred provenance unless implementation work finds a concrete diagnostic that cannot be produced from the reported values and the current missing-value inference context.

Like Python, the JS requests default is passed in by pricing code via `defaultUsage=1`.

---

### `usage.ts` — new file

**JS gets a plain-object normalization helper.** _(implements "`Usage` infers ancestor values from descendants", "Incomplete usage is handled gracefully, not rejected")_

```typescript
type NormalizedUsage = Usage

export function normalizeUsage(obj: unknown): NormalizedUsage
export function getUsageValue(usage: NormalizedUsage, usageKey: string): number
```

`normalizeUsage(...)` accepts a plain JS usage object, reads known usage keys, ignores extra unknown keys, and returns a plain `Usage` object containing the reported values. It does not infer ancestors and must not reject contradictory registered usage values. It also must not add explicit-vs-inferred provenance unless implementation work finds a concrete diagnostic that needs it. This may scan the registry's usage-key set; that is acceptable for now because it keeps the permissive API correct and the registry is expected to stay small.

`getUsageValue(...)` is the JS inference boundary used by `calcPrice()`, `computeLeafValues()`, and any internal code that needs registry-aware usage reads. It returns a stored value without proactively checking the rest of the object for contradictions, lazily infers a missing value when the answer is coherent, returns zero when there is no relevant data, and throws a user-facing error only when the missing requested value cannot be inferred because the reported values are contradictory or underdetermine the answer. It does not cache inferred usage values. This keeps JS behavior aligned with Python without introducing a wrapper class that provides little value.

---

### `validation.ts` — new file

**JS validation mirrors the Python split between registry structure and price payloads.** _(implements "Validation replaces what hardcoded fields gave us implicitly, and adds more", "Expensive validation happens once at construction/activation time, not on every `calc_price` call")_

```typescript
export function validateRegistryStructure(families: ParsedFamilies): void
export function validateRegistryIntervalClosure(family: UnitFamily): void
export function validateRegistryJoinClosedness(family: UnitFamily): void
export function validatePriceKeys(priceKeys: Set<string>, allPriceKeys: Set<string>): void
export function validateAncestorCoverage(pricedUsageKeys: Set<string>, family: UnitFamily): void
export function validateJoinCoverage(pricedUsageKeys: Set<string>, family: UnitFamily): void
export function validateModelPrice(modelPrice: ModelPrice, families: ParsedFamilies): void
export function validateExtractorDestinations(destKeys: Set<string>, usageKeys: Set<string>): void
export function validateProviderData(providers: Provider[], families: ParsedFamilies): void
export function isModelPriceKnownValid(modelPrice: ModelPrice, families: ParsedFamilies): boolean
export function markModelPriceKnownValid(modelPrice: ModelPrice, families: ParsedFamilies): void
export function getCachedPricingPlan(modelPrice: ModelPrice, families: ParsedFamilies): CachedPricingPlan | undefined
export function buildPricingPlanCache(modelPrice: ModelPrice, families: ParsedFamilies): CachedPricingPlan
export function invalidateModelPriceValidation(modelPrice: ModelPrice): void
export function invalidateModelPriceDecompositionCache(modelPrice: ModelPrice): void
```

`setUnitFamilies()` is the activation step for the active parsed registry. `validateProviderData()` validates a staged provider payload against a staged parsed registry so runtime updates can be atomic: if validation fails, neither the active registry nor active provider data changes. It skips model prices that are already known valid for the staged registry and current price-key fingerprint, and it also skips unchanged trusted built-in or official auto-update prices across pure additive registry changes. It validates only missing/stale custom, changed, runtime-authored, or otherwise untrusted model prices, and marks newly validated prices known valid after all checks succeed. Official generated/auto-update provider data can be marked known valid from trusted repo provenance without running price-level validation for every model. The update path must then install the same parsed registry object; parsing the raw unit data a second time would produce a different raw object identity, but the known-valid layer must preserve compatibility across pure unit additions for unchanged trusted prices. Known-valid state and optional decomposition caches can be stored in module-private `WeakMap`s or equivalent; they are not part of serialized provider data. JS model prices are plain objects, so arbitrary caller mutation cannot be intercepted; `isModelPriceKnownValid(...)` and any cache lookup must always compare the current price-key fingerprint with stored fingerprints. Library-provided helpers for patching snapshot/provider data should invalidate known-valid state when effective price keys are added/removed and invalidate cached decomposition state when the cache may be stale, without requiring callers to manually clone the whole provider payload. Validation and any plan-building should iterate each model's stored price keys and use parsed registry indexes/relationship caches; avoid repeatedly scanning every registry unit for every model.

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
2. if `isModelPriceKnownValid(modelPrice, activeFamilies)` is false, validates and marks that one model price known valid
3. normalizes raw input with `normalizeUsage(...)`
4. reads `totalInputTokens` with `getUsageValue(usage, 'input_tokens')` when tiered prices need it
5. resolves price keys and groups priced units by family, or reads an equivalent cached pricing plan if present
6. computes per-family leaf values from registry-normalized usage, optionally using cached decomposition instructions
7. passes `defaultUsage=1` for the requests family
8. prices each leaf using the value stored under the unit's price key and `family.per`
9. aggregates by `direction` into the existing result shape

For tiered prices, the threshold input is this provided-or-inferable `input_tokens` total, preserving Python's behavior: tier selection is based on the full input-token count, not on any one decomposed leaf. If `input_tokens` is stored on the usage object, `calcPrice()` uses it directly and does not reconcile descendant values for tier selection. If `input_tokens` is missing and the reported usage does not determine a coherent total, `calcPrice()` raises instead of selecting a tier.

It no longer contains hardcoded logic for cache/audio/request arithmetic. It does not validate every calculation; after activation or first use has marked a model price known valid, the hot path pays only a cheap known-valid check. Caching decomposition coefficients is allowed if useful, but not required. The one-model validation fallback exists for custom or bypassed model-price objects whose known-valid state is missing or stale, and for trusted prices made stale by non-additive registry changes. Pure unit additions do not make unchanged trusted prices stale.

---

### `api.ts` — modified

**Runtime data activation now handles wrapped JSON plus unit families.** _(implements "Unit definitions travel with prices, not just with the package")_

`updatePrices()` passes both `setProviderData` and `setUnitFamilies` to the storage factory. The official runtime update path stages the new repo-built payload in this order:

1. parse wrapped JSON
2. `stagedFamilies = parseFamilies(parsed.unit_families)`
3. mark parsed provider data as known valid for `stagedFamilies` using trusted repo-update provenance, without price-level validation of every model
4. on success only: `setUnitFamilies(stagedFamilies)` and `setProviderData(parsed.providers)`

If parsing or structural registry validation fails, both the active registry and active provider data remain unchanged. User-provided provider data that lacks trusted repo provenance still goes through `validateProviderData(...)`, which validates only missing/stale custom, changed, runtime-authored, or otherwise untrusted model prices and marks them known valid before activation.

The embedded startup path still uses generated `data.ts`, but the active registry is initialized from `unitFamiliesData` instead of being implicit in engine code. Generated `data.ts` came from build-validated repo data, but it does not contain decomposition caches. Embedded provider data may build a decomposition cache for one model price lazily on first calculation, using the same optional private runtime cache as Python.

The checked-in JS examples must be updated to cache and restore the wrapped payload shape, not a bare provider array, and to parse families before calling both `setUnitFamilies(stagedFamilies)` and `setProviderData(...)`.

---

### `extractUsage.ts` — modified

**Extractor output keys are no longer a fixed union.** _(implements "The extraction pipeline is data-driven end-to-end")_
The existing extraction logic still builds a plain object of counts. The change here is both structural and semantic:

- `UsageExtractorMapping.dest` is now `string`, so extracted usage can target any registry-defined usage key
- after extraction, the raw count object is normalized through `normalizeUsage(...)`
- `extractUsage(...)` returns that normalized plain object without trying to prove the provider's reported counts are mutually consistent

Extractor destinations are usage keys, not arbitrary strings and not price keys. Repo-defined extractor config is checked against the generated registry schema/build registry. Runtime-authored extractor config is accepted only after validation against the staged parsed registry, so custom extractor destinations and custom units travel through the same snapshot activation boundary.

If a provider response contains contradictory registered usage counts, `extractUsage(...)` still returns them. Direct reads of supplied properties keep returning the supplied values. Contradictions become hard errors only when code asks for a missing inferred value through `getUsageValue(...)` or when `calcPrice(...)` must reconcile the contradiction to compute a priced bucket.

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
       -> validate dimension rules, uniqueness, interval closure, join-closedness
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
       -> do not compute decomposition caches for every generated ModelPrice eagerly
```

### Python snapshot activation

```text
set_custom_snapshot(snapshot)
  -> if snapshot is None: clear custom snapshot
  -> else validate extractor destinations against snapshot.unit_registry
  -> for each ModelPrice:
       if known-valid state matches snapshot.unit_registry and current price-key fingerprint:
         skip price-level validation
       else if unchanged trusted built-in/official price remains compatible after pure unit additions:
         skip price-level validation
       else:
         validate this ModelPrice against snapshot.unit_registry
  -> after all validation succeeds, mark newly validated ModelPrice objects known valid
  -> optionally build decomposition caches for newly validated ModelPrice objects
  -> on success: activate snapshot as the only trusted execution snapshot
  -> on failure: raise and keep previous snapshot
```

### Python custom unit flow

```text
snapshot = get_snapshot() or an inactive snapshot returned from fetch()
  -> edit the snapshot or fetched inactive snapshot through supported mutation APIs
  -> mutate relevant ModelPrice objects as needed
       -> mutation invalidates inherited known-valid/decomposition-cache state for changed prices
  -> snapshot.add_family(...), snapshot.add_units(...)
  -> if snapshot is inactive: set_custom_snapshot(snapshot)
       -> validate only missing/stale custom, changed, or otherwise untrusted ModelPrice objects
          against expanded registry
       -> do not revalidate unchanged trusted built-in prices just because units were added
       -> mark validated prices known valid
       -> activate on success
  -> if snapshot is already active: supported mutations have already updated the active snapshot,
       and changed prices are validated either by the mutation helper or by the one-model calc fallback
```

### Python hot path

```text
ModelPrice.calc_price(usage)
  -> registry = get_snapshot().unit_registry
  -> if known-valid state is missing/stale:
       validate this ModelPrice against registry and mark it known valid
       # Pure unit additions do not make unchanged trusted prices missing/stale.
  -> smart_usage = Usage.from_raw(usage)
  -> total_input_tokens = smart_usage.input_tokens
  -> resolve price keys and group by family, or read an equivalent cached plan if present
  -> for each family:
       default_usage = 1 only for requests
       leaf_values = compute decomposition from smart_usage, optionally using cached instructions
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
  -> do not compute decomposition caches for every generated model price eagerly

runtime update
  -> parse wrapped JSON
  -> stagedFamilies = parseFamilies(parsed.unit_families)
  -> for official repo-built update:
       mark parsed provider data known valid for stagedFamilies without full price validation
     for user-provided staged data:
       validate missing/stale custom, changed, or otherwise untrusted model prices and mark them known valid
       skip unchanged trusted built-in prices across pure unit additions
  -> on success only:
       setUnitFamilies(stagedFamilies)
       setProviderData(parsed.providers)
  -> on failure:
       keep both active registry and providerData unchanged
```

### JS custom unit flow

```text
stagedFamilies/stagedProviders = patch the active or fetched snapshot/update payload through supported helpers
  -> batch unit edit on 'tokens':
       add the units required by the final registry shape
     # Registry validation does not require video to mirror other modalities,
     # but the supplied batch must satisfy the structural rules we choose.
  -> patch providerData/model prices through supported helpers
  -> validateProviderData(stagedProviders, stagedFamilies)
       -> skip still-known-valid built-in prices
       -> skip unchanged trusted built-in prices across pure unit additions
       -> validate changed/new prices and mark them known valid
  -> setUnitFamilies(stagedFamilies)
  -> setProviderData(stagedProviders)
```
