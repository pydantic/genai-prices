# Code Spec: Phase 1 Python Internal Registry Refactor

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Baseline:** this phase starts from the pre-registry Python package and current provider-array `data.json` / `data_slim.json` contract.

**Historical implementation note.**
A discarded proof-of-concept exists on branch `feat/token-unit-registry`. Implementers may use that branch's decomposition test vectors and rough unit inventory as references, but must not copy its runtime architecture. That branch predates this phased spec and mixes future unit definitions, standalone `units*.json` artifacts, schema polish, provider-data edits, and Python/JavaScript runtime changes that now belong in separate phases.

**Start from the shared model, then implement the Python slice.** _(implements "Phase 1 is the first implementation slice of the shared pricing goal", "The Phase 1 registry model has four runtime pieces")_
Read [../spec](../spec.md) for the pricing invariants and vocabulary: accurate pricing, complete price data, incomplete usage data, unit families, usage keys, price keys, dimensions, and registry-driven decomposition. This code spec only describes the Python delta needed for Phase 1.

**Phase 1 adds Python registry modules for the current unit surface.** _(implements "Phase 1 preserves supported entry points while changing unsafe internals")_
Add these hand-written Python runtime modules:

- `packages/python/genai_prices/units.py`
- `packages/python/genai_prices/decompose.py`
- `packages/python/genai_prices/validation.py`

Add `prices/units.yml` as the checked-in source registry for the current public unit surface used by this phase. Generated Python package data embeds a filtered/current unit-family dict as `unit_families_data` in `packages/python/genai_prices/data_units.py`, separate from provider-heavy generated `data.py`. Do not change `prices/data.json` or `prices/data_slim.json` into wrapped payloads in Phase 1.

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
@dataclass(eq=False)
class UnitDef:
    usage_key: str
    price_key: str
    family_id: str
    family: UnitFamily
    dimensions: dict[str, str]


@dataclass(eq=False)
class UnitFamily:
    id: str
    per: int
    description: str
    units: dict[str, UnitDef]
    units_by_dimension: dict[frozenset[tuple[str, str]], UnitDef]

    def find_join(self, a: UnitDef, b: UnitDef) -> UnitDef | None:
        """Return the most specific registered unit joining two family units, if present."""


class UnitRegistry:
    families: dict[str, UnitFamily]
    units: dict[str, UnitDef]
    _units_by_price_key: dict[str, UnitDef]
    _ancestor_usage_keys: dict[str, frozenset[str]]

    def __init__(self, raw_families: dict[str, dict] | None = None) -> None:
        """Parse raw families, validate structure, and fill indexes."""

    def unit_for_price_key(self, price_key: str) -> UnitDef:
        """Return the registered unit priced by price_key."""
```

`UnitRegistry.__init__(raw_families)` parses raw dicts, promotes raw unit keys into `usage_key`, defaults `price_key` to `usage_key`, fills indexes and back-references, and validates uniqueness plus interval closure. It skips full join-closedness for the current-unit subset but exposes relationship helpers so price-level validation can reject priced pairs whose join is missing. `UnitDef` and `UnitFamily` use `eq=False` because they form an object graph with back-references; identity equality keeps family objects hashable for grouping and avoids recursive value comparisons. The registry exposes no public mutation APIs in this phase.

The parsed graph owns relationship indexes that keep downstream checks simple. `UnitFamily.units_by_dimension` maps each dimension set in that family to its `UnitDef`, and `UnitFamily.find_join(...)` owns join lookup for units in that family. `UnitRegistry._units_by_price_key` maps each price key to the priced `UnitDef`, and `unit_for_price_key(...)` is the public lookup boundary. `UnitRegistry._ancestor_usage_keys` maps each usage key to the registered ancestor usage keys in the same family. Validation is written against model-priced units plus these indexes, not by scanning every registry unit for every model.

Relationship predicates must not be public `UnitRegistry` static methods. Keep dimension-set helpers and compatibility checks as module-private implementation details, or use the existing decomposition helper for containment checks where that already expresses the needed relationship. Public relationship surface may be added later only when there is a caller-facing API need.

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
def validate_price_keys(price_keys: set[str], registry: UnitRegistry) -> None: ...
def validate_ancestor_coverage(
    priced_usage_keys: set[str], family: UnitFamily, registry: UnitRegistry
) -> None: ...
def validate_join_coverage(priced_usage_keys: set[str], family: UnitFamily) -> None: ...
def validate_model_price(price_keys: set[str], registry: UnitRegistry) -> None: ...
def validate_extractor_destinations(dest_keys: set[str], reported_usage_keys: set[str]) -> None: ...
```

`validate_join_coverage(...)` must fail when a compatible priced pair's join unit is absent from the Phase 1 subset. Do not add trust markers, fingerprints, weak maps, dirty sets, or cache builders.

This module does not own raw registry structural checks such as dimension-set uniqueness, interval closure, or join-closedness; those stay in `UnitRegistry`. Ancestor and join validation helpers receive both the family under validation and the registry that owns the relationship indexes. Validation helpers work from model-priced units plus registry indexes and relationship helpers. They must not scan every registry unit for every model when direct indexes are available, and they must not hardcode ordinary usage or price key names. The only name-aware exception is excluding `requests` from caller/extractor usage.

Join coverage applies to manually constructed `ModelPrice` objects at standard base-pricing time. A current-surface price set such as `{input_mtok, cache_read_mtok, input_audio_mtok}` is rejected without `cache_audio_read_mtok`; the previous parent-bucket fallback is not preserved because the registry contract treats missing overlap prices as incomplete price data.

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

The function computes exclusive buckets only for priced units in one family. It reads selected priced usage keys through `Usage.__getattr__(...)`, so stored values return directly, safe missing values read as zero, and missing priced ancestors or joins raise through the same registry-driven usage-read path used by direct attribute access. Use the shared behavior in [../algorithm](../algorithm.md) and [../examples](../examples.md).

Phase 1 does not infer missing usage values. Decomposition should not duplicate the missing-ancestor or missing-join read rules from `Usage`; it decides which priced keys matter for the selected model and asks for only those keys. This preserves the existing behavior where `{input_tokens: 100, cache_read_tokens: 200}` can price a model that only has `input_mtok`: the explicit priced ancestor is read directly, and the unpriced descendant is ignored because the model has no cache bucket.

Do not add cached decomposition plans, cached coefficients, or model-wide pricing-plan objects in Phase 1. Correctness comes from validation plus direct decomposition through `Usage` reads. Negative exclusive values raise user-facing errors that describe impossible usage relationships rather than Mobius inversion, leaves, coefficients, or posets.

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
        """Return a stored registered value, zero for an unambiguous missing value, or raise."""

    def __setattr__(self, name: str, value: int | None) -> None:
        """Update a registered reported value, or assign an ordinary object attribute."""

    def __add__(self, other: Usage) -> Usage: ...
    def __radd__(self, other: Usage | int) -> Usage: ...
    def __eq__(self, other: object) -> bool: ...
    def __repr__(self) -> str: ...
```

Direct construction is strict for registered externally reported usage keys and rejects unknown keyword names and non-reported pricing-only keys such as `requests`. `from_raw(...)` reads known externally reported usage keys from mappings or objects and ignores extras. Construction stores reported values only; it does not infer ancestors, normalize values, remember explicit-versus-inferred provenance, or reject contradictory registered values.

For registered attribute reads:

1. If the value was reported, return it directly without auditing descendants.
2. If the value is missing and no positive reported related value could make it non-zero, return `0` without storing that zero or making the key count as reported.
3. If the value is missing and positive reported related values mean answering would require inferring an omitted ancestor or overlap, raise a user-facing missing-usage error.

The missing-read check is registry-driven. A missing read is ambiguous when either a positive reported strict descendant of the requested unit exists, or the requested unit is the join of two positive reported compatible units that are incomparable with each other. A missing descendant of a reported ancestor is not ambiguous by itself; for example `Usage(input_tokens=100).cache_read_tokens` returns `0` rather than raising because missing more-specific usage is allowed to mean "not reported".

For example, `Usage(input_audio_tokens=300).input_tokens` raises in Phase 1 because `input_tokens` was omitted and answering would require inferring an ancestor total. `Usage(output_tokens=100).input_tokens` returns `0` because no input-side usage was reported. `Usage.__repr__` orders stored reported values by active registry unit order; do not keep a separate hardcoded legacy field-order tuple.

Unlike the previous dataclass implementation, `Usage` does not preserve `dataclasses.asdict(...)`, `dataclasses.is_dataclass(...)`, or fixed-field dataclass introspection compatibility. That is an intentional Phase 1 exception to behavior preservation because fixed dataclass fields do not fit registry-defined usage keys without regenerating handwritten runtime fields.

To keep ordinary field mutation viable after leaving dataclasses, assignment to a registered externally reported usage key stores the value as reported usage, and assigning `None` removes the stored value. Assignment to non-registered names remains ordinary object assignment. Do not add public APIs for dynamically defining usage keys; the active registry decides which names are stored usage values.

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
5. compute per-family leaf values with explicit-only missing-usage checks
6. read the `input_tokens` tier threshold through `Usage` when any selected price uses `TieredPrices`
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

The tier threshold remains the `input_tokens` total in Phase 1, read through `Usage.__getattr__(...)`. Stored `input_tokens` returns directly, safely missing `input_tokens` returns zero and selects the base tier, and ambiguous missing `input_tokens` raises through the usage-read path instead of inferring the threshold. If no configured price uses `TieredPrices`, pass a neutral threshold value because non-tiered prices ignore it. Families without a `direction` dimension contribute only to `total_price`; `input_price` and `output_price` are direction-filtered compatibility aggregates.

Attribute assignment and deletion on `ModelPrice` do not run ancestor or join validation immediately. Phase 1 validates the final effective price-key set every time standard base `calc_price()` calculates against that `ModelPrice`. Snapshot activation does not perform model-price validation until Phase 5 adds runtime-private trust state. Subclass-only fields that are not registered price keys remain subclass-owned state and must not trigger registry validation.

**Python runtime extractor destinations become registry strings without certifying consistency.** _(implements "`Usage` becomes registry-aware and remains permissive for raw caller objects")_
`packages/python/genai_prices/types.py` `UsageExtractorMapping.dest` becomes a string destination that must name an externally reported registry usage key when validation has a registry context:

```python
@dataclass
class UsageExtractorMapping:
    path: ExtractPath
    dest: str
    required: bool
```

`UsageExtractor.__post_init__()` validates every mapping destination against externally reported usage keys before any response data is extracted. Runtime-created extractors validate against the active registry. Generated bundled provider-data import is a special construction context: `UsageExtractor.__post_init__` must validate against the bundled units-data module without importing the provider-heavy generated `data.py` through the active snapshot path.

`UsageExtractor.extract(...)` accumulates extracted counts in `dict[str, int]` and returns `Usage(**values)`. Extraction does not mutate dataclass usage fields directly, does not target price keys, and does not target the non-reported `requests` unit. If a provider response contains contradictory registered usage counts, extraction still returns those reported values; contradictions become errors only when pricing needs to interpret affected priced buckets.

Do not change `prices/src/prices/prices_types.py` `UsageField`, the build-time `UsageExtractorMapping.dest` annotation, or the generated provider/data JSON schema enum in Phase 1. Build/package-data validation still rejects invalid current provider extractor destinations after parsing. Registry-derived provider YAML schema/autocomplete is Phase 4 work.

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

`_bundled_snapshot()` imports generated `providers` from `data.py` and `unit_families_data` from the small generated `data_units.py`, builds `UnitRegistry(unit_families_data)`, and passes it explicitly:

```python
@cache
def _bundled_snapshot() -> DataSnapshot:
    """Build the bundled snapshot from generated providers and unit families."""
```

`set_custom_snapshot(snapshot)` keeps the public signature. For non-`None` snapshots, it installs the staged snapshot without model-price validation. Price-key validity, ancestor coverage, join coverage, and missing-join safety are checked by standard base `ModelPrice.calc_price()` every time it calculates against a selected model price. Activation-time model-price validation and any resulting trust records are deferred to Phase 5.

`DataSnapshot.calc()` and `DataSnapshot.extract_usage()` keep their callable shape in Phase 1. Phase 1 does not add `self is get_snapshot()` execution guards; it relies on the ordinary active-global-snapshot workflow. `find_provider()`, `find_provider_model()`, and lookup caches remain pure lookup/staging helpers that work on inactive snapshots.

**Build and package-data changes are Python-only and payload-preserving.** _(implements "The remote `data.json` and `data_slim.json` payloads remain provider arrays", "Python unit data stays separate from generated provider data")_
Update `prices/src/prices/package_data.py` so generated Python `data.py` exports only providers, and generated Python `data_units.py` exports current-subset `unit_families_data`. Any build helper that validates or filters the current subset should reuse `genai_prices.units` and `genai_prices.validation`; do not duplicate registry relationship logic in the build package.

Build/runtime sharing is intentional. The build package may import pure registry and validation helpers, but those helpers must not import generated package data or runtime globals. Tests should cover structural validation, price-key resolution, ancestor coverage, join coverage, and missing-join safety through the shared helpers.

**The Phase 1 Python call flow stays active-snapshot based.** _(implements "`DataSnapshot` carries the Python registry but keeps current activation behavior", "`ModelPrice` remains subclass-friendly and uses current legacy fields for storage")_
The pricing path is:

```text
ModelInfo.calc_price(usage, provider, ...)
  -> selected ModelPrice.calc_price(usage)
       -> read get_snapshot().unit_registry
       -> validate this model price against the active registry
       -> smart_usage = Usage.from_raw(usage)
       -> resolve price keys to usage keys
       -> group priced units by family
       -> compute leaf values per priced family with explicit-only missing-usage checks
       -> read input_tokens through Usage if a tiered price is configured
       -> price requests as {"requests": 1}
       -> aggregate by direction into the existing result shape
```

`ModelInfo.calc_price(...)` passes the original usage object to the selected price object so custom overrides can inspect non-registry fields before or after calling `super().calc_price(usage)`.

`__init__.py` does not gain new top-level exports in this phase. Existing top-level exports such as `Usage`, `calc_price`, `UpdatePrices`, wait helpers, and `__version__` stay where they are. `UnitRegistry`, `UnitFamily`, and `UnitDef` are available from `genai_prices.units` for introspection, not re-exported from the package root.

**Tests prove entry-point preservation plus registry semantics.** _(implements "Phase 1 preserves supported entry points while changing unsafe internals")_
Add focused Python tests for current price parity, current request pricing, `Usage` strict construction and permissive raw wrapping, unambiguous missing registered reads returning zero without becoming reported, ambiguous missing registered reads raising, explicit-only missing-usage pricing errors, inconsistent usage interpretation, ancestor and join validation, missing-join rejection for the current subset, custom `ModelPrice` subclass preservation, `DataSnapshot` registry defaults, and unchanged provider-array update parsing.
Include coverage that an invalid staged/custom model price is not rejected by `set_custom_snapshot(...)` in Phase 1, but is rejected when standard base pricing calculates against that model price.
