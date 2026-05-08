# Code Spec: Phase 5 Runtime Validation Performance Optimization

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Previous phase:** [Phase 4 Polish and Compatibility Hardening](../phase-4-polish-compat-hardening/code-spec.md).

**Phase 5 adds runtime-private performance state only.** _(implements "Phase 5 adds benchmark-backed performance state after the data model is proven", "Performance optimizations must be behavior-preserving")_
Do not change accepted data shapes, validation rules, decomposition semantics, generated payloads, or public API signatures. Add benchmarks for repeated `calc_price` before introducing validation or decomposition caches.

**The active global registry has an opaque validation identity.** _(implements "Validation caching is global-registry-specific")_
Add an identity to the active registry state:

```python
class UnitRegistry:
    validation_id: object
```

Each registry construction gets a fresh opaque `object()`. Global registry replacement installs a registry with a new identity and clears runtime-private caches that are keyed by the previous active registry.

**Python validation caching is module-global.** _(implements "Validation caching is global-registry-specific", "Fingerprint checks fail closed")_
Add runtime-private structures equivalent to:

```python
import weakref


@dataclass
class PriceValidationRecord:
    model_price_ref: weakref.ReferenceType[ModelPrice]
    registry_validation_id: object
    fingerprint: frozenset[str]


_price_validation_cache: dict[int, PriceValidationRecord]
```

Records are keyed by `id(model_price)` and store a weak reference so module-global caching does not keep transient model-price objects alive. Cache lookups must treat a dead weak reference or a weak reference to a different object as a miss, which also avoids id-reuse ambiguity. The cache is module-private runtime state, never serialized into generated data and never stored on `DataSnapshot`.

**Python hot-path validation becomes cache-gated.** _(implements "Provider activation is not a bulk model-price validation boundary")_
`ModelPrice.calc_price(...)` checks the module-global cache before running one-model validation. It skips validation only when the same model object, exact active registry `validation_id`, and current effective price-key fingerprint all match a cached record. Missing or stale cache records fall back to one-model validation and update the cache before pricing.

`set_custom_snapshot(snapshot)` remains a provider-data activation function and does not need to bulk-validate model prices or seed validation cache records.

**ModelPrice mutation does not need a validation transaction system.** _(implements "Fingerprint checks fail closed")_
Supported mutation paths may clear the module-global validation cache for performance hygiene, but correctness must come from recomputing and comparing the current effective price-key fingerprint. Assignment of a different value to an already-present key keeps the same structural fingerprint. Direct mutation of private storage remains unsupported.

**JavaScript registry and validation modules gain fail-closed cache helpers.** _(implements "Validation caching is global-registry-specific", "Fingerprint checks fail closed")_
Add helpers equivalent to:

```typescript
export function getRegistryValidationId(): object
export function hasModelPriceValidationCache(modelPrice: ModelPrice, registry: UnitRegistry): boolean
export function markModelPriceValidated(modelPrice: ModelPrice, registry: UnitRegistry): void
export function clearModelPriceValidationCache(): void
```

`setUnitFamilies(...)` creates a fresh opaque validation id for each active `UnitRegistry` and clears module-private validation caches. Use `WeakMap` state keyed by model price object, exact registry validation id, and effective price-key fingerprint. Because model prices are plain objects, every cache lookup recomputes and compares the fingerprint.

**Decomposition caches require benchmark evidence and exact keys.** _(implements "Decomposition caches are benchmark-gated")_
If benchmarks justify caching decomposition coefficients, key caches by exact active registry validation id plus the effective priced usage-key set. Do not serialize caches. Do not add caches that change error timing or user-facing decomposition behavior.

**Usage registry-key caches require exact registry identity.** _(implements "Usage registry-key lookups are a Phase 5 optimization target")_
Benchmark the repeated active-registry lookups used by `Usage` construction, assignment, reads, and representation. If the cost is material, cache the reported usage key set and registry-order reported key tuple by exact active registry `validation_id`. Registry replacement must clear or bypass stale cached key sets.

**Tests and benchmarks prove no behavior drift.** _(implements "Performance optimizations must be behavior-preserving")_
Add tests for cache hits, stale cache on registry replacement, stale cache on key additions/removals, no stale cache on value-only changes, Python id-reuse protection, JavaScript fail-closed fingerprint mismatches, generated-output purity, no `DataSnapshot` validation-cache state, and parity with Phase 4 behavior. Add benchmarks that justify any decomposition cache included in the phase.
