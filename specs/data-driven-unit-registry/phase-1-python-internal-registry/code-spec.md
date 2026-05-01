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
```

`UnitRegistry.__init__(raw_families)` parses raw dicts, promotes raw unit keys into `usage_key`, defaults `price_key` to `usage_key`, fills indexes and back-references, and validates uniqueness plus interval closure. It skips full join-closedness for the current-unit subset but exposes relationship helpers so price-level validation can reject priced pairs whose join is missing. It exposes no public mutation APIs in this phase.

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
`AbstractUsage` becomes a compatibility alias to `object`. `Usage` becomes a normal class backed by `_values: dict[str, int]` with strict direct construction, permissive `from_raw(...)`, lazy `__getattr__` inference, `__add__`, equality, and representation over reported values only. Do not cache inferred values and do not store explicit-vs-inferred provenance.

`ModelPrice` keeps existing dataclass fields for current price keys, including `requests_kcount`, and keeps subclass-friendly behavior. `ModelPrice.calc_price(usage: object)` changes from hardcoded token arithmetic to:

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

Attribute assignment and deletion on `ModelPrice` do not run ancestor or join validation immediately. Validation is final-state validation at snapshot activation or a one-model defensive `calc_price()` fallback. Subclass-only fields that are not registered price keys remain subclass-owned state and must not trigger registry validation.

**`data_snapshot.py` carries a registry and preserves current snapshot workflows.** _(implements "`DataSnapshot` carries the Python registry but keeps current activation behavior")_
Add `unit_registry: UnitRegistry | None = None` to `DataSnapshot`. `_bundled_snapshot()` imports generated `providers` and `unit_families_data`, builds `UnitRegistry(unit_families_data)`, and passes it explicitly. `DataSnapshot.__post_init__` defaults a missing registry from the current global snapshot for backward-compatible custom snapshot construction.

`set_custom_snapshot(snapshot)` keeps the public signature. For non-`None` snapshots, it validates only custom, changed, or otherwise untrusted model prices needed for registry-driven pricing, ignores subclass-only custom fields handled by custom overrides, and leaves the previous active snapshot in place on failure. It does not bulk-validate generated data and does not install validation trust state.

`DataSnapshot.calc()` and `DataSnapshot.extract_usage()` keep their callable shape in Phase 1. Phase 1 does not add `self is get_snapshot()` execution guards; it relies on the ordinary active-global-snapshot workflow. `find_provider()`, `find_provider_model()`, and lookup caches remain pure lookup/staging helpers that work on inactive snapshots.

**Build and package-data changes are Python-only and payload-preserving.** _(implements "The remote `data.json` and `data_slim.json` payloads remain provider arrays")_
Update `prices/src/prices/package_data.py` so generated Python `data.py` exports both `providers` and current-subset `unit_families_data`. Any build helper that validates or filters the current subset should reuse `genai_prices.units` and `genai_prices.validation`; do not duplicate registry relationship logic in the build package.

Build/runtime sharing is intentional. The build package may import pure registry and validation helpers, but those helpers must not import generated package data or runtime globals. Tests should cover structural validation, price-key resolution, ancestor coverage, join coverage, and missing-join safety through the shared helpers.

`__init__.py` does not gain new top-level exports in this phase. Existing top-level exports such as `Usage`, `calc_price`, `UpdatePrices`, wait helpers, and `__version__` stay where they are. `UnitRegistry`, `UnitFamily`, and `UnitDef` are available from `genai_prices.units` for introspection, not re-exported from the package root.

**Tests prove behavior preservation plus registry semantics.** _(implements "Phase 1 proves the registry model in Python without changing public behavior")_
Add focused Python tests for current price parity, current request pricing, `Usage` strict construction and permissive raw wrapping, lazy inference, inconsistent usage interpretation, ancestor and join validation, missing-join rejection for the current subset, custom `ModelPrice` subclass preservation, `DataSnapshot` registry defaults, and unchanged provider-array update parsing.
