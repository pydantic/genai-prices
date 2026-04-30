# Code Spec: Data-Driven Unit Registry

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Phase 2 runtime custom unit architecture is in [phase-2-runtime-custom-units/code-spec](phase-2-runtime-custom-units/code-spec.md).**
**Phase 3 global snapshot semi-enforcement is in [phase-3-global-snapshot-enforcement/code-spec](phase-3-global-snapshot-enforcement/code-spec.md).**
**Baseline:** this document describes the complete Phase 1 target-state diff across delivery slices 1A, 1B, 1C, and 1D. It intentionally ignores the current branch's partial implementation state.

**Future phases are extension constraints, not Phase 1 implementation scope.** _(implements "Future phases guide Phase 1 without expanding its scope")_
This code spec should keep Phase 1 compatible with later directions, but it should not add runtime unit mutation APIs, registry transaction machinery, additive-registry cache compatibility, or non-global snapshot execution guards to the Phase 1 diff. When a later concern only affects future workflow detail, this document should preserve the underlying extension point and leave the concrete runtime workflow to that later code spec.

---

## Phase 1 Delivery Slices

**Delivery slices are review boundaries inside Phase 1, not new product phases.** _(implements "Phase 1 is delivered in behavior-preserving runtime slices before the shared data contract changes")_
Phase 1 still has one target behavior: repo-defined unit registries. The slices describe how to land that target safely:

- **1A: Python internal registry refactor.** Python moves current hardcoded unit behavior behind `UnitRegistry`, registry-aware `Usage`, registry-backed `ModelPrice`, validation helpers, and generic decomposition for the current hardcoded unit set only. The active 1A registry exposes only today's supported usage keys (`input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `input_audio_tokens`, `cache_audio_read_tokens`, `output_audio_tokens`) and their corresponding current price keys (`input_mtok`, `output_mtok`, `cache_read_mtok`, `cache_write_mtok`, `input_audio_mtok`, `cache_audio_read_mtok`, `output_audio_mtok`), plus the existing request-count pricing behavior if that slice moves `requests_kcount` behind the registry. It may keep existing `ModelPrice` dataclass fields as the storage surface for current price keys. It does not add base dynamic price-key constructor support, does not add text/image/video or other future units, does not add a full custom-snapshot validation framework, does not change `prices/data.json` or `prices/data_slim.json`, does not require JavaScript changes, and should preserve current user-visible pricing behavior.
- **1B: JavaScript internal registry refactor.** JavaScript makes the same internal move for the current hardcoded unit set while continuing to consume the current provider-array remote data shape. It does not add text/image/video or other future units, does not depend on Python internals, and should preserve current JS behavior.
- **1C: Shared data contract and base dynamic price keys.** The generated JSON payloads become wrapped objects carrying `unit_families` plus `providers`, both runtimes parse the wrapped payload, repo-defined extractor destinations validate against the registry carried by the same payload, and repo-defined new units can finally travel through generated package data and fetched auto-updates. Python base `ModelPrice` also gains dynamic price-key storage for non-hardcoded registered price keys in this slice.
- **1D: Polish and Python-specific compatibility.** CLI price presentation, provider YAML autocomplete/schema polish, generated schema hints for extractor destinations, and dataclass subclass dynamic price-key constructor support can land after the core Python and shared-data work. This slice should not block proving the registry-driven pricing model.

1A and 1B may introduce language-native embedded unit registry data or package-internal generated unit data, but they must not publish a changed shared remote payload. 1C is the intentional compatibility break: once both current runtimes can parse the wrapped payload, the shared remote `data.json` / `data_slim.json` files change shape even though older released clients that expect a bare provider array will fail when they auto-update. This spec does not require dual payloads, backward-compatible wrapper detection in old clients, or a versioned rollout URL. 1D is deliberately polish/compatibility work, not a prerequisite for the first Python proof.

**New repo-defined units are not enabled until 1C.** _(implements "Phase 1 is delivered in behavior-preserving runtime slices before the shared data contract changes")_
Before the shared payload carries `unit_families`, adding new units would create half-support: one runtime might know a unit internally, but remote price updates and the other runtime might not. 1A and 1B can validate that existing prices conform to the registry-shaped model, but their active registries stay limited to the current hardcoded unit surface and should not require provider price edits, new price keys, or data-shape changes just to preserve current behavior. New unit data becomes reviewable once 1C lands. Plain Python dataclass subclasses accepting those future price keys as undeclared constructor kwargs is a 1D compatibility enhancement, not a 1C blocker.

---

## Phase 1 Target Shape

**New tracked source files.**
The complete Phase 1 target diff adds these hand-written files:

- `prices/units.yml`
- `packages/python/genai_prices/units.py`
- `packages/python/genai_prices/decompose.py`
- `packages/python/genai_prices/validation.py`
- `packages/js/src/units.ts`
- `packages/js/src/usage.ts`
- `packages/js/src/decompose.ts`
- `packages/js/src/validation.ts`

**Modified tracked source files.**
The complete Phase 1 target diff modifies these existing files from `main`:

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
The final design has one checked-in source registry file (`prices/units.yml`), plus generated embeddings of that same registry inside `prices/data*.json`, `packages/python/genai_prices/data.py`, and `packages/js/src/data.ts`. In 1A and 1B, language-native package data may embed units while `prices/data*.json` stays unchanged. 1C adds unit families to the shared generated JSON payloads. The complete Phase 1 target diff does not add or remove any standalone bundled units JSON file.

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
    # 1C target: the full symmetric family, including text/audio/image/video variants

requests:
  per: 1_000
  description: Request counts
  units:
    requests:
      price_key: requests_kcount
      dimensions: {}
```

Usage keys live as dict keys in the raw data. `price_key` defaults to the usage key when omitted. In the complete 1C target, the `tokens` family contains the full built-in unit lattice needed by the prose spec, not just the currently hardcoded fields from `main`.

1A and 1B use a current-unit subset of this registry. That subset exposes only the hardcoded usage/price keys that already exist in the target language, plus the `requests` family if the slice moves existing request-count pricing behind the registry. Do not add text/image/video units, cache-by-modality units that are not already public, or any other new registered usage/price keys in 1A or 1B. Review those new unit definitions together with 1C, when the shared payload can carry units and prices together. If full interval/join closure for the future expanded lattice requires structural units that are not part of today's public surface, defer those units and the corresponding stricter structural validation to 1C rather than exposing behavior-changing keys early.

**1C changes `prices/data.json` and `prices/data_slim.json` into top-level dicts.** _(implements "`data.json` becomes a top-level dict, not a bare list", "Unit definitions travel with prices, not just with the package")_
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

1A and 1B keep the remote JSON payload shape as a bare provider list. Do not merge this wrapped JSON change until both current runtimes can parse it. After that point, 1C accepts the remote-payload break for older released clients instead of preserving the old bare-list contract in parallel.

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

Python may gain `unit_families_data` in 1A containing only the current-unit subset, JavaScript may gain `unitFamiliesData` in 1B containing only the current-unit subset, and 1C expands both generated exports and aligns them with the wrapped JSON payload.

---

## 1A/1C/1D Python Package: `packages/python/genai_prices/`

### `units.py` — new file

**`UnitDef` and `UnitFamily` are plain dataclasses.** _(implements "`UnitRegistry` owns the runtime unit graph")_

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

**`UnitRegistry` owns all runtime unit state.** _(implements "`UnitRegistry` owns the runtime unit graph", "`UnitRegistry` is not a public mutation surface in Phase 1", "Registry interval closure", "Registry join-closedness: compatible unit pairs must have their join in the family")_

```python
class UnitRegistry:
    families: dict[str, UnitFamily]
    units: dict[str, UnitDef]          # usage_key -> UnitDef across all families
    price_keys: dict[str, str]         # price_key -> usage_key across all families
    validation_id: object              # unique for each independently constructed registry

    def __init__(self, raw_families: dict[str, dict] | None = None) -> None:
        """Parse raw families, validate structure, fill indexes and back-references."""

    @staticmethod
    def are_compatible(a: UnitDef, b: UnitDef) -> bool:
        """Return True when the two units do not conflict on any dimension key."""
```

Registry construction performs all structural validation:

- usage keys are globally unique
- price keys are globally unique
- no two units in a family share the same dimension set
- every comparable pair in a family has all intermediate dimension sets present
- every compatible pair in a family has its join present in that family

Phase 1 does not add public `add_family(...)`, `add_units(...)`, or `copy()` mutation APIs. Runtime custom unit mutation APIs belong to the Phase 2 code spec.

The registry also owns any private relationship indexes needed to keep downstream checks simple: ancestor lookup by usage key, join lookup by dimension union, family grouping, or equivalent caches. These are implementation details, but validation should be written against model-priced units plus these indexes rather than by scanning every registry unit for every model.

`validation_id` is an optional opaque identity value used only if a runtime needs an exact-registry validation marker or a small optional decomposition cache. 1A may omit this until the implementation has a concrete need. Any runtime marker or cache matches only when the exact registry identity and price-key fingerprint match. Broader compatibility across additive/destructive runtime registry mutations belongs to Phase 2.

**Module-level registry access is one lazy helper.** _(implements "Phase 1 assumes one active global DataSnapshot")_

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

`compute_leaf_values(...)` uses the family dimension lattice and only priced units become returned cost buckets. 1A should compute decomposition directly unless a tiny `CachedFamilyDecomposition` helper makes the code simpler; it does not need a model-wide pricing-plan cache. Decomposition coefficients depend on the registry/family shape and the model's priced usage keys; the resulting leaf values also depend on the current usage values. The full-depth sign rule is valid because registry interval closure, registry join-closedness, price ancestor coverage, and price join coverage remove the structural gaps that would otherwise break it. Reading a missing usage value may trigger lazy inference on `Usage`. Unpriced reported usage keys do not participate in consistency checks unless they are needed to infer a missing priced value. For example, `input_tokens=100` and `cache_read_tokens=200` must not fail for a model that only has an input catch-all price, but must fail when `cache_read_tokens` is also priced. Negative leaf values, contradictory usage that affects priced buckets, or required values that cannot be inferred coherently raise `ValueError` with user-facing messages that describe the usage data problem, not the underlying algorithm.

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


def validate_extractor_destinations(dest_keys: set[str], usage_keys: set[str]) -> None:
    """Every extractor mapping destination must be a registered usage key."""
```

This module does not validate raw registry structure. That stays in `UnitRegistry`. `validate_ancestor_coverage(...)` checks registered ancestors after registry interval closure has guaranteed that structurally required intermediates exist. `validate_join_coverage(...)` can assume a compatible pair's join exists because registry join-closedness already proved it. 1A does not require validation-provenance helpers or pricing-plan cache builders; if repeated validation becomes a concrete problem, a simple exact-registry marker can live on `ModelPrice` without becoming a broader framework.

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

**`ModelPrice` remains a subclass-friendly registry-backed price object.** _(implements "ModelPrice supports attribute access backed by registry data", "Normal `ModelPrice` handles new registry price keys without code changes", "Dataclass subclass dynamic price-key constructor support is 1D polish", "`calc_price` is a hot path", "`input_price` and `output_price` are backward-compat accessors over direction-filtered costs", "Manual custom pricing remains supported")_

```python
@dataclass(init=False)
class ModelPrice:
    # Legacy typed fields remain compatibility surface; they are not the registry-backed key whitelist.
    input_mtok: Decimal | TieredPrices | None = None
    cache_write_mtok: Decimal | TieredPrices | None = None
    cache_read_mtok: Decimal | TieredPrices | None = None
    output_mtok: Decimal | TieredPrices | None = None
    input_audio_mtok: Decimal | TieredPrices | None = None
    cache_audio_read_mtok: Decimal | TieredPrices | None = None
    output_audio_mtok: Decimal | TieredPrices | None = None
    requests_kcount: Decimal | None = None

    _extra_prices: dict[str, Decimal | TieredPrices | None]  # 1C: candidate non-hardcoded price keys
    _validation_marker_registry_id: object | None
    _validation_marker_price_key_fingerprint: frozenset[str] | None

    def __init__(self, **prices: Decimal | TieredPrices | None) -> None:
        """1C: accept legacy fields plus candidate registry-backed price keys on base ModelPrice."""

    def has_validation_marker_for(self, registry: UnitRegistry) -> bool:
        """Return True when this price-key set was already validated for this exact registry."""

    def mark_validated_for(self, registry: UnitRegistry) -> None:
        """Optionally record that the current price-key set is valid for this exact registry."""

    def invalidate_validation_and_decomposition_cache(self) -> None:
        """Clear the validation marker and any small optional cache after structural price mutation."""

    def calc_price(self, usage: object) -> CalcPrice:
        """Price all configured units using the active global registry."""

    def __getattr__(self, name: str) -> Decimal | TieredPrices | None:
        """Return stored dynamic prices, or None for absent active-registry price keys.

        Raise AttributeError for names that are neither stored nor active-registry price keys.
        """

    def __str__(self) -> str:
        """Render prices using registry-derived labels and family normalization."""

    def is_free(self) -> bool:
        """Return True when there are no stored prices or every stored price is zero-like."""
```

1A may keep the existing dataclass fields as the storage surface for current registered price keys. Pricing and validation still use registry metadata, but 1A does not need `_extra_prices` or non-hardcoded price-key constructor support because no new repo-defined price keys are enabled yet.

In 1C, base runtime `ModelPrice` accepts price-key kwargs that are not declared as dataclass fields. Those kwargs are stored in `_extra_prices` as candidate dynamic price keys, then accepted or rejected only when validation receives a `UnitRegistry`. A non-hardcoded registered key such as a future `image_mtok` price key works on base `ModelPrice` without adding a new dataclass field; a misspelled candidate key fails during build or snapshot validation. Base constructor behavior must not use legacy dataclass fields as a closed-world whitelist once 1C enables new repo-defined units.

Runtime `ModelPrice` must remain compatible with the current Python pattern where users define `@dataclass` subclasses, add custom fields, override `calc_price()`, and optionally call `super().calc_price(usage)` with existing inherited price fields. Do not make runtime `ModelPrice` a `pydantic.BaseModel` unless the implementation also preserves that existing dataclass-subclass constructor behavior. A custom subclass field such as `sausage_price` is not a registry price key just because it is present on the object; it is owned by the custom override unless it is also a registered price key.

1D may add support for plain dataclass subclasses accepting undeclared dynamic price-key kwargs. If normal Python dataclass subclass constructors reject non-hardcoded candidate price-key kwargs before `ModelPrice` can store them, use a metaclass, constructor wrapper, or equivalent interception point to preserve both behaviors: declared subclass fields pass through as subclass fields, and undeclared candidate price keys are captured in `_extra_prices`. This is a Python-specific compatibility polish item, not part of the 1A core proof or the 1C shared data contract.

Any validation marker or cached decomposition helper is private implementation state, not part of serialized model-price data. 1A does not require a provenance or pricing-plan framework. If a marker is useful, it is scoped to the active registry identity and a fingerprint of the current effective registered price keys. "Effective" means registered keys whose value represents a present price; JS `undefined`, any Python absence/null sentinel, and Python subclass-only custom fields do not count as priced registry units. Validation must inspect present legacy compatibility fields and, once 1C adds `_extra_prices`, every `_extra_prices` candidate key. Any `_extra_prices` key that is not registered in the validation registry is an invalid price key, not a silently ignored custom field. Declared subclass fields outside the base compatibility surface are ignored unless the validation registry also names them as price keys. A marker means price-level validation has accepted this price-key set for that exact registry, either in the repo build pipeline or during runtime snapshot activation. `calc_price` may compute decomposition directly from the model's priced keys and registry indexes. If price keys are added/removed after validation or the active registry identity changes, `has_validation_marker_for(...)` returns false and any small optional cache is stale. Compatibility across additive runtime registry mutations belongs to Phase 2.

Supported mutation paths that add or remove effective registered price keys must clear any validation marker and any small optional cache. In Python this means overriding or centralizing `__setattr__`/`__delattr__` handling for registry-backed price keys and, in 1C, any explicit mapping-style helper added for dynamic registry price fields. Non-hardcoded names assigned through supported normal-`ModelPrice` mutation paths are candidate dynamic price keys and are stored for later registry validation once 1C introduces that storage. Setting a different value for an existing key does not structurally require revalidation. Direct mutation of private storage such as `_extra_prices` is not a supported public API. Subclass-only custom fields that are not registered price keys should not trigger registry validation/cache invalidation.

Base `ModelPrice.calc_price()` changes from hardcoded token arithmetic to this flow:

1. Fetch the active global registry.
2. If a simple exact-registry validation marker exists and is stale or missing, validate this one model price and update the marker.
3. Wrap non-`Usage` input with `Usage.from_raw` for an internal local variable only; do not mutate or replace the caller's original object.
4. Resolve stored price keys through `registry.price_keys` to usage keys and group those units by family.
5. For tiered prices, read `usage.input_tokens`; if it is stored, use it without reconciling descendant values. If it is missing and cannot be inferred coherently, raise a usage error instead of guessing a tier.
6. For each priced family, compute leaf values from the registry-aware usage while ignoring unpriced reported usage values unless they are needed to infer a missing priced value.
7. Pass `default_usage=1` only for the `requests` family.
8. Price each leaf using the price stored under the unit's `price_key` and the family's `per` normalization.
9. Aggregate per-unit costs into `input_price`, `output_price`, and `total_price`.

Families without a `direction` dimension contribute only to `total_price`.
Custom `ModelPrice` subclasses may override this method and bypass or augment the base flow. The outer pricing orchestration must dispatch to the selected object's method with the original usage object so custom overrides can read arbitrary non-registry usage fields before or after calling `super().calc_price(usage)`.

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
Callers should only demand an inferred input-token total when a `TieredPrices` value needs it; non-tiered prices can pass a neutral value because they ignore the threshold parameter.

**Runtime `UsageExtractorMapping.dest` becomes `str` with the 1A `Usage` refactor.** _(implements "The extraction pipeline is data-driven end-to-end")_

```python
@dataclass
class UsageExtractorMapping:
    path: ExtractPath
    dest: str
    required: bool
```

`dest` is a registered usage key from the snapshot registry, not an arbitrary string and not a model-price key. Runtime-authored extractor mappings in custom provider snapshots are validated against the staged snapshot's registry during `set_custom_snapshot()`. Repo-defined and fetched-payload extractor destinations are validated during 1C build/export validation against the registry that ships with the same payload. In Phase 1 they can target only repo-defined or fetched-update usage keys; runtime custom unit extractor targets belong to Phase 2. 1D only adds generated provider-YAML schema/autocomplete for these destinations.

**`UsageExtractor.extract()` constructs `Usage` from a dict of collected values.** _(implements "The extraction pipeline is data-driven end-to-end")_
The method stops mutating dataclass fields directly. It accumulates extracted counts in `dict[str, int]`, then returns `Usage(**values)`.

**`ModelInfo.calc_price()` keeps its public signature but delegates to the new generic pricing path.** _(implements "All public API signatures are preserved", "Phase 1 does not block non-global snapshot execution")_
The method still accepts a usage object and returns `PriceCalculation`. Phase 1 does not add an active-snapshot identity guard here; it relies on the ordinary active global snapshot path and lets `ModelPrice.calc_price()` read the active registry. It passes the original usage object unchanged to the selected model price object's `calc_price()` method rather than wrapping usage before dispatch. This preserves custom `ModelPrice` overrides that inspect non-registry usage fields. It relies on `ModelPrice.calc_price()` rather than the hardcoded token-only logic from `main`. Active-snapshot identity guards belong to Phase 3.

---

### `data_snapshot.py` — modified

**`DataSnapshot` gains `unit_registry`, defaulting from the current global snapshot when omitted.** _(implements "Unit families live in the data snapshot alongside prices", "Phase 1 assumes one active global DataSnapshot")_

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

`DataSnapshot` remains the staging object for runtime customizations, but Phase 1 customizations are limited to provider/model price data that references registered units. It does not expose public unit-registry mutation helpers. Supported price mutation helpers, if added, should update a model's effective price keys on the snapshot and invalidate only the changed `ModelPrice` object's simple validation marker or small optional cache. Runtime unit editing, copy-on-write registry transactions, and registry rollback behavior belong to Phase 2.

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

Bundled startup does not serialize, import, validate, or eagerly compute decomposition plans for every built-in model. The generated repo data was already validated by the build pipeline, so built-in model prices may be trusted by construction for the bundled registry without a per-model runtime provenance framework. If the implementation uses a tiny decomposition cache, each built-in `ModelPrice` builds it lazily the first time `calc_price` needs it. This avoids increasing package/download size and avoids startup work for models that are never priced in the current process.

**`set_custom_snapshot()` validation stays minimal in 1A and becomes stricter in 1C.** _(implements "Validation is split between the registry and `set_custom_snapshot`", "`set_custom_snapshot` validation stays narrow in 1A", "Expensive validation happens once at construction/activation time, not on every `calc_price` call")_

```python
def set_custom_snapshot(snapshot: DataSnapshot | None) -> None:
    """Activate a snapshot or reset to bundled default.

    In 1A, for non-None snapshots:
    - preserve existing custom snapshot behavior
    - skip trusted built-in model prices from prevalidated generated data
    - validate only custom or changed model prices needed to avoid wrong registry-driven pricing
    - ignore subclass-only custom ModelPrice fields that are handled by custom calc_price()
      override logic
    - leave the previous snapshot active if validation fails

    In 1C, when base ModelPrice accepts candidate dynamic price keys:
    - validate candidate dynamic keys against snapshot.unit_registry.price_keys
    - resolve validated price keys to usage keys
    - validate ancestor and join coverage per family
    - validate extractor destinations against snapshot.unit_registry.units.keys()
    - optionally record a simple exact-registry validation marker
    """
```

This activation step is what turns a snapshot from staged data into trusted runtime state. Before activation, a snapshot may contain `ModelPrice` objects and extractor configs whose unit references have not yet been checked against that snapshot's registry. In 1A, existing dataclass fields still catch many price-key typos before activation, so activation validation should stay narrow. After 1C adds base dynamic price-key storage, activation becomes the main place where candidate dynamic keys are accepted or rejected against the snapshot registry and where runtime-authored extractor destinations are checked. Unchanged model prices from trusted bundled or fetched auto-update data are not revalidated in bulk.

This also covers user patching of bundled prices. A caller can edit a snapshot, add missing fields such as cache-token prices to the relevant `ModelPrice` objects, and activate the snapshot if it is not already active. The mutations invalidate any simple validation marker or optional small cache for the changed model prices only; `set_custom_snapshot()` validates those updated price-key sets before activation without validating every unchanged built-in price.

**`DataSnapshot.calc()` and `DataSnapshot.extract_usage()` keep their existing callable shape.** _(implements "Phase 1 does not block non-global snapshot execution", "`find_provider_model` works on any snapshot, global or not")_
Phase 1 does not add `self is get_snapshot()` guards to these methods. The registry-aware internals still use the active global registry, so the expected path is to activate a snapshot before using it for pricing or extraction. Explicitly rejecting non-active snapshots and escaped inactive-snapshot models belongs to Phase 3. `find_provider_model()` and `find_provider()` stay pure lookup helpers and remain usable on inactive snapshots.

---

### `update_prices.py` — modified in 1C

**`UpdatePrices.fetch()` parses the new top-level JSON wrapper.** _(implements "Unit definitions travel with prices, not just with the package")_

```python
def fetch(self) -> DataSnapshot | None:
    """Fetch data.json, parse unit_families and providers, build a snapshot."""
```

Instead of validating the whole payload as `list[Provider]`, `fetch()` parses the wrapper object, validates the provider object shape, constructs `UnitRegistry(raw['unit_families'])`, and returns a `DataSnapshot` containing both. Fetching a data URL is a trusted prevalidated data-feed operation regardless of which URL the caller configured. `fetch()` therefore treats returned model prices as already validated for that fetched registry without running price-level validation for every model or precomputing decomposition state. Runtime parsing still rejects malformed provider shapes and structurally invalid unit registries; it does not prove that every model price in the fetched payload satisfies price-key, ancestor, or join coverage rules.

1A leaves `UpdatePrices.fetch()` compatible with the existing provider-array remote payload and uses the bundled/generated Python registry for runtime pricing.

---

### `_cli_impl.py` — modified in 1D

**CLI price presentation becomes registry-driven in 1D.** _(implements "Backward compatibility is preserved unless clearly impractical", "Derive, don't duplicate")_

- `_collect_model_price_fields()` no longer uses `dataclasses.fields(ModelPrice)`; it iterates stored price keys from each `ModelPrice`.
- `_price_field_label()` derives labels from unit metadata and family normalization rather than a hardcoded field-name map.
- `_format_model_price_value()` and `_format_model_prices()` iterate stored price keys and format them generically from registry data.

This preserves the current CLI output shape while allowing new units to appear without code changes. In 1A, the CLI may keep using existing flags and legacy `ModelPrice` fields as long as current CLI behavior still works.

---

### `__init__.py` — unchanged

**Top-level public exports remain the same.** _(implements "All public API signatures are preserved")_
`Usage`, `calc_price`, `UpdatePrices`, `wait_prices_updated_sync`, `wait_prices_updated_async`, and `__version__` stay exported from the same module.

---

## 1A/1C Python Build/Runtime Boundary

**Registry and validation code should be shared when the dependency direction is clean, but duplication is acceptable at the build-package boundary.** _(implements "Derive, don't duplicate", "Validation replaces what hardcoded fields gave us implicitly, and adds more")_
The `prices/` build package already has build-time types that mirror runtime package types. This is not ideal, but it is an established boundary in the repo: build-time parsing and schema generation operate before generated runtime data exists, while the published runtime package must not depend on the build package.

The implementation should first try to make the registry and structural validation modules pure enough for both sides to use:

- `UnitRegistry`, `UnitDef`, `UnitFamily`, and dimension/relationship helpers should avoid importing generated package data, `data_snapshot`, update machinery, or runtime globals.
- Price-level validation helpers should accept plain mappings, registry objects, and protocol-shaped price values where possible, instead of requiring runtime-only model objects.
- Build-time code may import those pure helpers from the runtime package if that does not create import cycles, generated-data dependencies, or awkward coupling to runtime-only `ModelPrice` subclassing behavior.

If that clean sharing turns out to be awkward, the fallback is explicit and acceptable: keep a small build-side mirror under `prices/src/prices/` following the existing `prices_types.py` pattern. In that case, keep the duplicated surface narrow and mechanical:

- one source registry file (`prices/units.yml`) remains the source of truth
- runtime and build-time registry objects must parse the same raw `unit_families` shape
- tests should cover parity for structural validation (including interval closure and join-closedness), price-key resolution, ancestor coverage, and join coverage
- any deliberate duplication should be named in comments as a package-boundary copy, not a second design

This is a structural implementation decision, not a detail hidden inside `build()`. The final implementation should make the boundary obvious in module placement and tests.

**Build/export validation should be reusable by external payload producers.** _(implements "Validation is split between the registry and `set_custom_snapshot`", "Expensive validation happens once at construction/activation time, not on every `calc_price` call")_
`UpdatePrices(url=...)` trusts fetched model prices from any URL as prevalidated, so the validation that makes a `data.json` safe to publish must live in code that third-party publishers are likely to reuse. Do not bury full price-level validation only inside a repo-specific `build()` command that also discovers local provider YAML files and writes repo outputs. The build package should expose a small importable validation/export helper used by the official build and available to external producers that start from provider objects or parsed YAML:

```python
def validate_export_payload(
    providers: list[Provider],
    unit_families: dict[str, dict],
) -> UnitRegistry:
    """Validate registry structure and all provider model prices before export."""
```

The exact name can change, but the boundary should stay: accept already parsed providers plus raw `unit_families`, construct/validate `UnitRegistry`, validate every model price key, ancestor coverage, and join coverage, and return the validated registry or raise. `build()` and any wrapper that writes `data.json` / `data_slim.json` call this helper before serialization. External publishers who do not want to hand-author wrapped JSON from scratch can reuse the same helper or CLI path before hosting a payload for `UpdatePrices(url=...)`. Runtime `UpdatePrices.fetch()` does not call this helper; the trust boundary is at publication time, not every client fetch.

---

## 1A/1C/1D Build Pipeline: `prices/src/prices/`

### `prices_types.py` — modified

**Build-time `ModelPrice` becomes registry-permissive in 1C.** _(implements "Validation replaces what hardcoded fields gave us implicitly, and adds more")_

```python
class ModelPrice(_Model, extra='allow'):
    __pydantic_extra__: dict[str, DollarPrice | TieredPrices]

    def is_free(self) -> bool: ...
```

The explicit hardcoded price fields from `main` are removed as the source of truth. Validation of allowed price keys moves to registry-derived build checks. Provider-editor schema/autocomplete polish can follow in 1D.

1A should avoid visible provider-YAML acceptance changes unless they are required to preserve existing behavior through the internal Python refactor. Broader price-key acceptance belongs with 1C because new repo-defined units do not become usable until the shared data contract changes.

**Build-time `UsageExtractorMapping.dest` becomes `str` in 1C.** _(implements "The extraction pipeline is data-driven end-to-end")_
The literal `UsageField` union is removed from build-time types so provider data can reference any registered usage key carried by the 1C unit registry. Registry-derived validation replaces the removed literal type: the reusable export-validation helper rejects extractor destinations that are not registered usage keys. Generated provider-YAML schema/autocomplete for extractor destinations is 1D polish.

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

The complete 1C `build()` changes in this order for prices and wrapped payloads:

1. Load `prices/units.yml`.
2. Load and validate provider YAML files with `prices_types.py`.
3. Call the reusable export-validation helper over the parsed providers and raw unit families. Internally, it constructs `UnitRegistry(unit_families)` for structural validation and, for every model price payload, it:
   - validate price keys
   - resolve price keys to usage keys
   - validate ancestor coverage
   - validate join coverage
     It also validates every extractor destination against `registry.units`.
4. Write wrapped `data.json` and `data_slim.json`.

1D adds generated provider-YAML schema/autocomplete for extractor destinations; it does not introduce the authoritative validation rule.

In 1A and 1B, build/package code may read `prices/units.yml` to generate or validate language-native runtime data for the current-unit subset only, but it must not write wrapped `data.json` / `data_slim.json`.

**JSON schema generation is split between 1C payload shape and 1D authoring polish.** _(implements "Generated JSON schemas provide editor autocomplete for provider YAML files", "Validation rules are expressed in terms of dimensions, not unit names")_
1C updates the generated `data.json` schema for the wrapped payload including `unit_families`. 1D updates the provider YAML/editor schema so it no longer relies on hardcoded `ModelPrice` fields or a hardcoded extractor `dest` union. That generated schema is for IDE autocomplete and inline feedback only; 1C build/export validation is the authoritative check. In 1D, `build.py` derives:

- allowed price keys from `registry.price_keys`
- allowed extractor destinations from `registry.units`
- the top-level wrapped `data.json` schema including `unit_families` in 1C

No schema code references specific unit names.

1A and 1B may use registry-derived checks internally, but should not change the published editor schema/autocomplete surface if that would turn the runtime refactor into an authoring behavior change.

---

### `package_data.py` — modified

**Generated package data now embeds both providers and unit families.** _(implements "Unit definitions are generated into language-native code alongside prices")_

```python
def package_data() -> None: ...
def package_python_data(data_path: Path) -> None: ...
def package_ts_data(data_path: Path) -> None: ...
```

In the complete 1C target, `package_python_data()` and `package_ts_data()` both read the wrapped `data.json`, split out `providers` and `unit_families`, and emit both into generated package data files. Before 1C, the package-data path may combine the existing provider-array data with `prices/units.yml` or another package-internal generated unit source, as long as the published `prices/data*.json` contract does not change.

---

## 1B JS Package: `packages/js/src/`

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

**JS gets a runtime registry module parallel to Python's `UnitRegistry`.** _(implements "`UnitRegistry` owns the runtime unit graph", "Unit definitions travel with prices, not just with the package")_

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

The module bootstraps itself from generated `unitFamiliesData` and allows the active registry to be replaced from fetched runtime-update JSON. Phase 1 does not add JS APIs for callers to add or mutate unit families at runtime. The active parsed families object identity can be part of the JS `registryValidationId` only if the implementation needs a simple exact-registry validation marker. Runtime custom unit staging, additive-registry compatibility, and broader cache compatibility belong to Phase 2.

---

### `decompose.ts` — new file

**JS decomposition logic becomes dimension-driven too.** _(implements "Decomposition uses dimensions, not hardcoded subtraction chains", "Only priced units participate in decomposition")_

```typescript
export function isDescendantOrSelf(ancestor: UnitDef, descendant: UnitDef): boolean

export type CachedFamilyDecomposition = {
  family: UnitFamily
  leafCoefficients: Record<string, Array<[string, number]>>
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

`buildFamilyDecompositionCache(...)` is an optional tiny helper, not a required pricing-plan framework. `computeLeafValues()` consumes registry-normalized usage data, not raw caller input, and can compute decomposition directly. Reading a missing value goes through the same lazy inference helper used by the rest of JS pricing. Missing keys with no relevant data read as zero. Unpriced reported usage keys are ignored unless needed to infer a missing priced value. Negative leaves, contradictory usage that affects priced buckets, or required values that cannot be inferred coherently raise a user-facing error rather than reporting a negative or nonsensical cost. Usage values do not need explicit-vs-inferred provenance unless implementation work finds a concrete diagnostic that cannot be produced from the reported values and the current missing-value inference context.

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
export function hasModelPriceValidationMarker(modelPrice: ModelPrice, families: ParsedFamilies): boolean
export function markModelPriceValidated(modelPrice: ModelPrice, families: ParsedFamilies): void
export function invalidateModelPriceValidation(modelPrice: ModelPrice): void
export function invalidateModelPriceDecompositionCache(modelPrice: ModelPrice): void
```

`setUnitFamilies()` is the activation step for the active parsed registry. `validateProviderData()` validates a staged provider payload against a staged parsed registry so runtime updates can be atomic: if validation fails, neither the active registry nor active provider data changes. Like Python, JS should keep this minimal until dynamic/shared-data work makes stricter validation necessary: trusted generated or fetched update provider data is treated as prevalidated, and custom/changed provider data validates only the affected model prices. A simple validation marker can be stored in a module-private `WeakMap` keyed by model price object, exact active registry identity, and current price-key fingerprint if repeated validation is a concrete problem. JS model prices are plain objects, so arbitrary caller mutation cannot be intercepted; any marker lookup must compare fingerprints and fail closed. Library-provided helpers for patching provider price data should invalidate the marker when effective price keys are added/removed. Validation should iterate each model's stored price keys and use parsed registry indexes/relationship helpers; avoid repeatedly scanning every registry unit for every model.

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

1. reads the active parsed registry
2. if a simple exact-registry marker exists and is stale or missing, validates this one model price and updates the marker
3. normalizes raw input with `normalizeUsage(...)`
4. reads `totalInputTokens` with `getUsageValue(usage, 'input_tokens')` when tiered prices need it
5. resolves price keys and groups priced units by family
6. computes per-family leaf values from registry-normalized usage
7. passes `defaultUsage=1` for the requests family
8. prices each leaf using the value stored under the unit's price key and `family.per`
9. aggregates by `direction` into the existing result shape

For tiered prices, the threshold input is this provided-or-inferable `input_tokens` total, preserving Python's behavior: tier selection is based on the full input-token count, not on any one decomposed leaf. If `input_tokens` is stored on the usage object, `calcPrice()` uses it directly and does not reconcile descendant values for tier selection. If `input_tokens` is missing and the reported usage does not determine a coherent total, `calcPrice()` raises instead of selecting a tier.

It no longer contains hardcoded logic for cache/audio/request arithmetic. It does not need a broad validation/cache framework; after activation or first use has recorded a simple exact-registry marker, the hot path pays only a cheap marker check. The one-model validation fallback exists for custom or bypassed model-price objects whose marker is missing or stale. Additive/destructive runtime registry change behavior belongs to Phase 2.

---

### `api.ts` — modified in 1C

**Runtime data activation now handles wrapped JSON plus unit families.** _(implements "Unit definitions travel with prices, not just with the package")_

`updatePrices()` passes both `setProviderData` and `setUnitFamilies` to the storage factory. The runtime update path for any configured data URL stages the fetched payload in this order:

1. parse wrapped JSON
2. `stagedFamilies = parseFamilies(parsed.unit_families)`
3. treat parsed provider data as prevalidated for `stagedFamilies`, without price-level validation of every model
4. on success only: `setUnitFamilies(stagedFamilies)` and `setProviderData(parsed.providers)`

If parsing or structural registry validation fails, both the active registry and active provider data remain unchanged. Direct user-provided provider data that did not arrive through the trusted fetched-payload path still goes through `validateProviderData(...)`, which validates only custom, changed, or otherwise untrusted model prices before activation.

The embedded startup path still uses generated `data.ts`, but the active registry is initialized from `unitFamiliesData` instead of being implicit in engine code. Generated `data.ts` came from build-validated repo data, but it does not contain decomposition caches. Embedded provider data may compute decomposition directly on first calculation, using only a tiny lazy cache if it keeps the implementation simpler.

The checked-in JS examples must be updated to cache and restore the wrapped payload shape, not a bare provider array, and to parse families before calling both `setUnitFamilies(stagedFamilies)` and `setProviderData(...)`.

1B leaves `updatePrices()` and the checked-in examples compatible with the existing provider-array remote payload while registry-backed JS pricing is refactored internally.

---

### `extractUsage.ts` — modified

**Extractor output keys are no longer a fixed union.** _(implements "The extraction pipeline is data-driven end-to-end")_
The existing extraction logic still builds a plain object of counts. The change here is both structural and semantic:

- `UsageExtractorMapping.dest` is now `string`, so extracted usage can target any registry-defined usage key
- after extraction, the raw count object is normalized through `normalizeUsage(...)`
- `extractUsage(...)` returns that normalized plain object without trying to prove the provider's reported counts are mutually consistent

Extractor destinations are usage keys, not arbitrary strings and not price keys. Repo-defined extractor config is checked against the build/export registry in 1C; generated schema support only adds IDE autocomplete in 1D. Runtime-authored extractor config in custom provider data is accepted only after validation against the staged parsed registry, and in Phase 1 it can target only repo-defined or fetched-update usage keys. Runtime custom unit extractor destinations belong to Phase 2.

If a provider response contains contradictory registered usage counts, `extractUsage(...)` still returns them. Direct reads of supplied properties keep returning the supplied values. Contradictions become hard errors only when code asks for a missing inferred value through `getUsageValue(...)` or when `calcPrice(...)` must reconcile the contradiction to compute a priced bucket.

---

## Call Relationships Across 1A/1B/1C/1D

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
1C target:
build()
  -> load units.yml
  -> registry = UnitRegistry(unit_families)
  -> load provider YAML files
  -> validate model price keys
  -> resolve price keys to usage keys
  -> validate ancestor coverage / join coverage
  -> validate extractor destinations against registry usage keys
  -> write wrapped data.json and data_slim.json

package_data()
  -> read wrapped data.json
  -> package_python_data(): emit providers + unit_families_data
  -> package_ts_data(): emit data + unitFamiliesData
  -> generated runtime data is trusted because export validation succeeded first

1A/1B:
  -> generate or embed language-native unit registry data for the current hardcoded unit subset
  -> keep prices/data.json and prices/data_slim.json as provider arrays

1D:
  -> derive provider YAML schema/autocomplete from registry price keys and usage keys
```

### Python bundled startup

```text
get_snapshot()
  -> _bundled_snapshot()
       -> import providers, unit_families_data from generated data.py
       -> UnitRegistry(unit_families_data)
       -> DataSnapshot(providers=..., unit_registry=..., from_auto_update=False)
       -> do not validate every generated ModelPrice or precompute decomposition state
```

### Python snapshot activation

```text
set_custom_snapshot(snapshot)
  -> if snapshot is None: clear custom snapshot
  -> in 1A:
       preserve existing custom snapshot behavior
       skip trusted built-in generated prices
       validate only custom or changed ModelPrice objects needed for registry-driven pricing
  -> in 1C:
       validate candidate dynamic price keys against snapshot.unit_registry
       validate ancestor and join coverage for changed/custom price-key sets
       optionally record simple exact-registry validation markers
  -> on success: activate snapshot as the active runtime snapshot
  -> on failure: raise and keep previous snapshot
```

### Python custom price flow

```text
snapshot = get_snapshot() or an inactive snapshot returned from fetch()
  -> mutate relevant ModelPrice objects for registered price keys as needed
       -> mutation invalidates any simple validation marker or small optional cache for changed prices
  -> if snapshot is inactive: set_custom_snapshot(snapshot)
       -> validate only custom/changed ModelPrice objects required for the current slice
       -> do not revalidate unchanged trusted built-in prices just because one custom price changed
       -> activate on success
  -> if snapshot is already active: supported mutations have already updated the active snapshot,
       and changed prices are validated either by the mutation helper or by the one-model calc fallback
```

### Python hot path

```text
ModelInfo.calc_price(usage, provider, ...)
  -> model_price = self.get_prices(genai_request_timestamp)
  -> model_price.calc_price(usage)

ModelPrice.calc_price(usage)
  -> registry = get_snapshot().unit_registry
  -> if a simple exact-registry marker exists and is missing/stale:
       validate this ModelPrice against registry and update the marker
  -> smart_usage = Usage.from_raw(usage)
  -> total_input_tokens = smart_usage.input_tokens only if any TieredPrices value needs a threshold;
     otherwise use a neutral value because non-tiered unit prices ignore it
  -> resolve price keys and group by family
  -> for each family:
       default_usage = 1 only for requests
       leaf_values = compute decomposition from smart_usage
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
  -> do not validate every generated model price or precompute decomposition state

runtime update
  -> parse wrapped JSON
  -> stagedFamilies = parseFamilies(parsed.unit_families)
  -> for fetched data-url update:
       treat parsed provider data as prevalidated for stagedFamilies without full price validation
     for user-provided staged data:
       validate only custom, changed, or otherwise untrusted model prices
  -> on success only:
       setUnitFamilies(stagedFamilies)
       setProviderData(parsed.providers)
  -> on failure:
       keep both active registry and providerData unchanged
```
