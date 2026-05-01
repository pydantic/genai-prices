# Code Spec: Phase 1 Python Internal Registry Refactor

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Baseline:** this phase starts from the pre-registry Python package and current provider-array `data.json` / `data_slim.json` contract.

**Start from the shared model, then implement the Python slice.** _(implements "Phase 1 is the first implementation slice of the shared pricing goal", "The Phase 1 registry model has four runtime pieces")_
Read [../spec](../spec.md) for the pricing invariants and vocabulary: accurate pricing, complete price data, incomplete usage data, unit families, usage keys, price keys, dimensions, and registry-driven decomposition. This code spec only describes the Python delta needed for Phase 1.

**Phase 1 adds Python registry modules for the current unit surface.** _(implements "Phase 1 proves the Python registry model without changing public behavior")_
Add these hand-written Python runtime modules:

- `packages/python/genai_prices/units.py`
- `packages/python/genai_prices/decompose.py`
- `packages/python/genai_prices/validation.py`

Add `prices/units.yml` as the checked-in source registry for the current public unit surface used by this phase. Generated Python package data embeds a filtered/current unit-family dict as `unit_families_data`. Do not change `prices/data.json` or `prices/data_slim.json` into wrapped payloads in Phase 1.

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

**`data_snapshot.py` carries a registry and preserves current snapshot workflows.** _(implements "`DataSnapshot` carries the Python registry but keeps current activation behavior")_
Add `unit_registry: UnitRegistry | None = None` to `DataSnapshot`. `_bundled_snapshot()` imports generated `providers` and `unit_families_data`, builds `UnitRegistry(unit_families_data)`, and passes it explicitly. `DataSnapshot.__post_init__` defaults a missing registry from the current global snapshot for backward-compatible custom snapshot construction.

`set_custom_snapshot(snapshot)` keeps the public signature. For non-`None` snapshots, it validates only custom, changed, or otherwise untrusted model prices needed for registry-driven pricing, ignores subclass-only custom fields handled by custom overrides, and leaves the previous active snapshot in place on failure. It does not bulk-validate generated data and does not install validation trust state.

**Build and package-data changes are Python-only and payload-preserving.** _(implements "The remote `data.json` and `data_slim.json` payloads remain provider arrays")_
Update `prices/src/prices/package_data.py` so generated Python `data.py` exports both `providers` and current-subset `unit_families_data`. Any build helper that validates or filters the current subset should reuse `genai_prices.units` and `genai_prices.validation`; do not duplicate registry relationship logic in the build package.

**Tests prove behavior preservation plus registry semantics.** _(implements "Phase 1 proves the registry model in Python without changing public behavior")_
Add focused Python tests for current price parity, current request pricing, `Usage` strict construction and permissive raw wrapping, lazy inference, inconsistent usage interpretation, ancestor and join validation, missing-join rejection for the current subset, custom `ModelPrice` subclass preservation, `DataSnapshot` registry defaults, and unchanged provider-array update parsing.
