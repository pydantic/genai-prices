# Code Spec: Phase 1 Python Internal Registry Refactor

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Baseline:** this phase starts from the pre-registry Python package and current provider-array `data.json` / `data_slim.json` contract.

**Historical implementation note.**
A discarded proof-of-concept exists on branch `feat/token-unit-registry`. Implementers may use that branch's decomposition test vectors and rough unit inventory as references, but must not copy its runtime architecture. That branch predates this phased spec and mixes future unit definitions, standalone `units*.json` artifacts, schema polish, provider-data edits, and Python/JavaScript runtime changes that now belong in separate phases.

**Start from the shared model, then implement the Python slice.** _(implements "Phase 1 is the first implementation slice of the shared pricing goal", "The Phase 1 registry model has four runtime pieces")_
Read [../spec](../spec.md) for the pricing invariants and vocabulary: accurate pricing, complete price data, incomplete usage data, unit families, usage keys, price keys, dimensions, and registry-driven decomposition. This code spec only describes the Python delta needed for Phase 1.

**Phase 1 adds Python registry modules for the current unit surface.** _(implements "Phase 1 proves the Python registry model without changing public behavior")_
Add these hand-written Python runtime modules:

- `packages/python/genai_prices/units.py`
- `packages/python/genai_prices/decompose.py`
- `packages/python/genai_prices/validation.py`

Add `prices/units.yml` as the checked-in source registry for the current public unit surface used by this phase. Generated Python package data embeds a filtered/current unit-family dict as `unit_families_data`. Do not change `prices/data.json` or `prices/data_slim.json` into wrapped payloads in Phase 1.

Do not introduce a standalone runtime `units*.json` artifact. The source registry is checked-in YAML and runtime delivery is generated package data in Phase 1, then shared wrapped price payloads in Phase 3. Do not generate source-code fields into handwritten runtime modules; registry-derived behavior is implemented with runtime lookups.

**`prices/units.yml` starts as the current Python public unit subset.** _(implements "The active registry is limited to the current Python unit surface")_
The source registry shape is the long-term raw unit shape even though Phase 1 filters it to the current Python public surface:

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
    input_audio_tokens:
      price_key: input_audio_mtok
      dimensions: { direction: input, modality: audio }
    cache_audio_read_tokens:
      price_key: cache_audio_read_mtok
      dimensions: { direction: input, modality: audio, cache: read }
    output_audio_tokens:
      price_key: output_audio_mtok
      dimensions: { direction: output, modality: audio }

requests:
  per: 1_000
  description: Request counts. Explicit special case: one per Usage object passed to calc_price; not caller-supplied Usage.
  units:
    requests:
      price_key: requests_kcount
      dimensions: {}
```

Usage keys are raw unit dict keys. `price_key` defaults to the usage key when omitted. Do not add text/image/video units, cache-by-modality units that are not already public, or any other new registered Python usage/price keys in Phase 1. Review those definitions with Phase 3, when the shared payload can carry units and prices together.

**`units.py` defines dataclass runtime models and an immutable-by-convention registry.** _(implements "`UnitRegistry` owns Python's runtime unit graph")_
Use one runtime model per concept:

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
    units: dict[str, UnitDef]


class UnitRegistry:
    families: dict[str, UnitFamily]
    units: dict[str, UnitDef]
    price_keys: dict[str, str]
    _units_by_dimension: dict[str, dict[frozenset[tuple[str, str]], UnitDef]]
    _ancestor_usage_keys: dict[str, frozenset[str]]

    def __init__(self, raw_families: dict[str, dict] | None = None) -> None:
        """Parse raw families, validate structure, and fill indexes."""

    @staticmethod
    def are_compatible(a: UnitDef, b: UnitDef) -> bool:
        """Return whether two units can overlap without conflicting dimensions."""
```

`UnitRegistry.__init__(raw_families)` parses raw dicts, promotes raw unit keys into `usage_key`, defaults `price_key` to `usage_key`, fills indexes and back-references, and validates uniqueness plus interval closure. It skips full join-closedness for the current-unit subset but exposes relationship helpers so price-level validation can reject priced pairs whose join is missing. It exposes no public mutation APIs in this phase.

The registry owns two private relationship indexes that keep downstream checks simple. `_units_by_dimension` maps each family id and dimension set to its `UnitDef`. `_ancestor_usage_keys` maps each usage key to the registered ancestor usage keys in the same family. Join lookup unions two compatible dimension sets and reads `_units_by_dimension[family_id]`. Validation is written against model-priced units plus these indexes, not by scanning every registry unit for every model.

There is no `RawUnitDef` / `RawUnitFamily` runtime model layer in Python. Raw registry data stays as dictionaries until `UnitRegistry` constructs `UnitDef` and `UnitFamily`. `units.py` must remain pure enough for the build package to import: it must not import generated `data.py`, bundled snapshots, update machinery, or runtime global snapshot state.

Add a single lazy module helper for active-registry access where needed:

```python
def _get_registry() -> UnitRegistry:
    """Return get_snapshot().unit_registry via a lazy import."""
```

Code that needs caller/extractor usage keys reads the registry and skips the explicit non-reported `requests` unit.

**`validation.py` centralizes price-level checks.** _(implements "Validation protects pricing semantics without runtime trust caching", "Full registry join-closedness starts in Phase 3")_
Provide helpers equivalent to:

```python
def validate_price_keys(price_keys: set[str], price_key_index: Mapping[str, str]) -> None: ...
def validate_ancestor_coverage(priced_usage_keys: set[str], family: UnitFamily) -> None: ...
def validate_join_coverage(priced_usage_keys: set[str], family: UnitFamily) -> None: ...
def validate_model_price(price_keys: set[str], registry: UnitRegistry) -> None: ...
def validate_extractor_destinations(dest_keys: set[str], reported_usage_keys: set[str]) -> None: ...
```

`validate_join_coverage(...)` must fail when a compatible priced pair's join unit is absent from the Phase 1 subset. Do not add trust markers, fingerprints, weak maps, dirty sets, or cache builders.

This module does not own raw registry structural checks such as dimension-set uniqueness, interval closure, or join-closedness; those stay in `UnitRegistry`. Validation helpers work from model-priced units plus registry indexes and relationship helpers. They must not scan every registry unit for every model when direct indexes are available, and they must not hardcode ordinary usage or price key names. The only name-aware exception is excluding `requests` from caller/extractor usage.

**`decompose.py` implements dimension-driven decomposition.** _(implements "Validation protects pricing semantics without runtime trust caching")_
Add:

```python
def is_descendant_or_self(ancestor: UnitDef, descendant: UnitDef) -> bool: ...

def compute_leaf_values(
    priced_usage_keys: set[str],
    usage: Usage,
    family: UnitFamily,
) -> dict[str, int]: ...
```

The function computes exclusive buckets only for priced units in one family, reads missing values through `Usage`, ignores unpriced reported values unless needed to infer a missing priced value, and raises user-facing usage errors for contradictory or underdetermined priced buckets. Use the shared behavior in [../algorithm](../algorithm.md) and [../examples](../examples.md).

Do not add cached decomposition plans, cached coefficients, or model-wide pricing-plan objects in Phase 1. Correctness comes from validation plus direct decomposition. Negative exclusive values raise user-facing errors that describe impossible usage relationships rather than Mobius inversion, leaves, coefficients, or posets.

**`types.py` changes `Usage` and `ModelPrice` without changing public signatures.** _(implements "`Usage` becomes registry-aware and remains permissive for raw caller objects", "`ModelPrice` remains subclass-friendly and uses current legacy fields for storage")_
`AbstractUsage` becomes a compatibility alias to `object`:

```python
AbstractUsage = object
```

This keeps the exported name from `main` while removing the false implication that callers must satisfy a fixed protocol.

`Usage` becomes a normal class backed by `_values: dict[str, int]`:

```python
class Usage:
    _values: dict[str, int]

    def __init__(self, **kwargs: int | None) -> None:
        """Store non-None reported values for externally reported usage keys."""

    @classmethod
    def from_raw(cls, obj: object) -> Usage:
        """Wrap arbitrary usage input while ignoring unknown raw-object extras."""

    def __getattr__(self, name: str) -> int:
        """Return a stored registered value, lazily infer it, or raise a user-facing error."""

    def __add__(self, other: Usage) -> Usage: ...
    def __radd__(self, other: Usage | int) -> Usage: ...
    def __eq__(self, other: object) -> bool: ...
    def __repr__(self) -> str: ...
```

Direct construction is strict for registered externally reported usage keys and rejects unknown keyword names and non-reported pricing-only keys such as `requests`. `from_raw(...)` reads known externally reported usage keys from mappings or objects and ignores extras. Construction stores reported values only; it does not infer ancestors, normalize values, remember explicit-versus-inferred provenance, or reject contradictory registered values. Derived values are recomputed lazily on reads so they never start behaving like caller-supplied data in `__add__`, equality, representation, or diagnostics.

`ModelPrice` keeps existing dataclass fields for current price keys, including `requests_kcount`, and keeps subclass-friendly behavior. `ModelPrice.calc_price(usage: object)` changes from hardcoded token arithmetic to:

```python
@dataclass
class ModelPrice:
    input_mtok: Decimal | TieredPrices | None = None
    cache_write_mtok: Decimal | TieredPrices | None = None
    cache_read_mtok: Decimal | TieredPrices | None = None
    output_mtok: Decimal | TieredPrices | None = None
    input_audio_mtok: Decimal | TieredPrices | None = None
    cache_audio_read_mtok: Decimal | TieredPrices | None = None
    output_audio_mtok: Decimal | TieredPrices | None = None
    requests_kcount: Decimal | None = None

    def calc_price(self, usage: object) -> CalcPrice:
        """Price all configured current units using the active global registry."""

    def __getattr__(self, name: str) -> Decimal | TieredPrices | None:
        """Return None for absent active-registry price keys; raise otherwise."""

    def __str__(self) -> str:
        """Render prices using current compatibility labels."""

    def is_free(self) -> bool:
        """Return whether every stored price is absent or zero-like."""
```

The generic pricing flow is:

1. read the active snapshot registry
2. validate this model's effective current price-key set
3. wrap raw usage through `Usage.from_raw(...)` for the base method only
4. resolve price keys to usage keys and group by family
5. read `input_tokens` only when tiered pricing needs a threshold
6. compute per-family leaf values
7. price `requests` as one request per usage object
8. normalize by `family.per`
9. aggregate into the existing input/output/total result shape

Pass the original usage object through `ModelInfo.calc_price(...)` to the selected model price object's method so custom overrides can inspect non-registry usage fields.

`calc_unit_price(...)` replaces token-specific helper logic:

```python
def calc_unit_price(
    price: Decimal | TieredPrices | None,
    count: int | None,
    total_input_tokens: int,
    per: int,
) -> Decimal: ...
```

The tier threshold remains the provided-or-inferable `input_tokens` total. If no configured price uses `TieredPrices`, pass a neutral threshold value because non-tiered prices ignore it. Families without a `direction` dimension contribute only to `total_price`; `input_price` and `output_price` are direction-filtered compatibility aggregates.

Attribute assignment and deletion on `ModelPrice` do not run ancestor or join validation immediately. Phase 1 validates the final effective price-key set every time standard base `calc_price()` calculates against that `ModelPrice`. Snapshot activation does not perform model-price validation until Phase 5 adds runtime-private trust state. Subclass-only fields that are not registered price keys remain subclass-owned state and must not trigger registry validation.

**Python extractor destinations become registry strings without certifying consistency.** _(implements "`Usage` becomes registry-aware and remains permissive for raw caller objects")_
`UsageExtractorMapping.dest` becomes a string destination that must name an externally reported registry usage key when validation has a registry context:

```python
@dataclass
class UsageExtractorMapping:
    path: ExtractPath
    dest: str
    required: bool
```

`UsageExtractor.extract(...)` accumulates extracted counts in `dict[str, int]` and returns `Usage(**values)`. Extraction does not mutate dataclass usage fields directly, does not target price keys, and does not target the non-reported `requests` unit. If a provider response contains contradictory registered usage counts, extraction still returns those reported values; contradictions become errors only when a missing inferred value or priced bucket needs interpretation.

**`data_snapshot.py` carries a registry and preserves current snapshot workflows.** _(implements "`DataSnapshot` carries the Python registry but keeps current activation behavior")_
Add `unit_registry: UnitRegistry | None = None` to `DataSnapshot`:

```python
@dataclass
class DataSnapshot:
    providers: list[types.Provider]
    from_auto_update: bool
    unit_registry: UnitRegistry | None = None
    _lookup_cache: dict[tuple[str | None, str | None, str], tuple[types.Provider, types.ModelInfo]]
    timestamp: datetime

    def __post_init__(self) -> None:
        """If unit_registry is None, borrow the active global snapshot registry."""
```

`_bundled_snapshot()` imports generated `providers` and `unit_families_data`, builds `UnitRegistry(unit_families_data)`, and passes it explicitly:

```python
@cache
def _bundled_snapshot() -> DataSnapshot:
    """Build the bundled snapshot from generated providers and unit families."""
```

`set_custom_snapshot(snapshot)` keeps the public signature. For non-`None` snapshots, it installs the staged snapshot without model-price validation. Price-key validity, ancestor coverage, join coverage, and missing-join safety are checked by standard base `ModelPrice.calc_price()` every time it calculates against a selected model price. Activation-time model-price validation and any resulting trust records are deferred to Phase 5.

`DataSnapshot.calc()` and `DataSnapshot.extract_usage()` keep their callable shape in Phase 1. Phase 1 does not add `self is get_snapshot()` execution guards; it relies on the ordinary active-global-snapshot workflow. `find_provider()`, `find_provider_model()`, and lookup caches remain pure lookup/staging helpers that work on inactive snapshots.

**Build and package-data changes are Python-only and payload-preserving.** _(implements "The remote `data.json` and `data_slim.json` payloads remain provider arrays")_
Update `prices/src/prices/package_data.py` so generated Python `data.py` exports both `providers` and current-subset `unit_families_data`. Any build helper that validates or filters the current subset should reuse `genai_prices.units` and `genai_prices.validation`; do not duplicate registry relationship logic in the build package.

Build/runtime sharing is intentional. The build package may import pure registry and validation helpers, but those helpers must not import generated package data or runtime globals. Tests should cover structural validation, price-key resolution, ancestor coverage, join coverage, and missing-join safety through the shared helpers.

**The Phase 1 Python call flow stays active-snapshot based.** _(implements "`DataSnapshot` carries the Python registry but keeps current activation behavior", "`ModelPrice` remains subclass-friendly and uses current legacy fields for storage")_
The pricing path is:

```text
ModelInfo.calc_price(usage, provider, ...)
  -> selected ModelPrice.calc_price(usage)
       -> read get_snapshot().unit_registry
       -> validate this model price against the active registry
       -> smart_usage = Usage.from_raw(usage)
       -> read input_tokens only if a TieredPrices value needs a threshold
       -> resolve price keys to usage keys
       -> group priced units by family
       -> compute leaf values per priced family
       -> price requests as {"requests": 1}
       -> aggregate by direction into the existing result shape
```

`ModelInfo.calc_price(...)` passes the original usage object to the selected price object so custom overrides can inspect non-registry fields before or after calling `super().calc_price(usage)`.

`__init__.py` does not gain new top-level exports in this phase. Existing top-level exports such as `Usage`, `calc_price`, `UpdatePrices`, wait helpers, and `__version__` stay where they are. `UnitRegistry`, `UnitFamily`, and `UnitDef` are available from `genai_prices.units` for introspection, not re-exported from the package root.

**Tests prove behavior preservation plus registry semantics.** _(implements "Phase 1 proves the registry model in Python without changing public behavior")_
Add focused Python tests for current price parity, current request pricing, `Usage` strict construction and permissive raw wrapping, lazy inference, inconsistent usage interpretation, ancestor and join validation, missing-join rejection for the current subset, custom `ModelPrice` subclass preservation, `DataSnapshot` registry defaults, and unchanged provider-array update parsing.
Include coverage that an invalid staged/custom model price is not rejected by `set_custom_snapshot(...)` in Phase 1, but is rejected when standard base pricing calculates against that model price.
