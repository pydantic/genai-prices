# Code Spec: Phase 5 Runtime Validation Performance Optimization

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Previous phase:** [Phase 4 Polish and Compatibility Hardening](../phase-4-polish-compat-hardening/code-spec.md).

**Phase 5 adds runtime-private performance state only.** _(implements "Phase 5 adds performance state after the data model is proven", "Performance optimizations must be behavior-preserving")_
Do not change accepted data shapes, validation rules, decomposition semantics, generated payloads, or public API signatures. Add benchmarks for repeated `calc_price` and custom snapshot activation before introducing caches beyond validation trust.

**Python `UnitRegistry` gains an opaque validation identity.** _(implements "Runtime validation trust is snapshot- and registry-specific")_
Add:

```python
class UnitRegistry:
    validation_id: object
```

Each registry construction gets a fresh opaque `object()`. Trust checks compare this identity exactly.

**Python `DataSnapshot` gains a runtime-private validation trust context.** _(implements "Runtime validation trust is snapshot- and registry-specific", "Generated outputs remain pure data")_
Add runtime-private structures equivalent to:

```python
@dataclass
class PriceValidationRecord:
    model_price: ModelPrice
    fingerprint: frozenset[str]


@dataclass
class TrustedPriceValidationContext:
    registry_validation_id: object
    source_id: object
    trusted_records: dict[int, PriceValidationRecord]
    validated_records: dict[int, PriceValidationRecord]
    dirty_model_price_ids: set[int]


@dataclass
class DataSnapshot:
    _trusted_price_validation: TrustedPriceValidationContext | None = None
```

Records are keyed by `id(model_price)` and store an object reference to avoid id-reuse ambiguity for the snapshot lifetime. The context is created by snapshot construction or activation, never serialized into generated data.

**Python `ModelPrice` invalidates trust on effective key-set changes.** _(implements "Supported mutation paths invalidate trust when effective price keys change")_
Add:

```python
class ModelPrice:
    def invalidate_validation_trust(self) -> None:
        """Notify runtime-private validation state after effective price-key additions/removals."""
```

Supported mutation paths that add or remove registered price keys call this hook. Assignment of a different value to an already-present key does not need structural invalidation. Direct mutation of private storage remains unsupported.

**Python hot-path validation becomes trust-gated.** _(implements "Runtime validation trust is snapshot- and registry-specific")_
`ModelPrice.calc_price(...)` checks the active snapshot trust context before running one-model validation. It skips validation only when the same model object, exact registry `validation_id`, and current effective price-key fingerprint all match a trusted record. Missing or stale trust falls back to one-model validation and updates runtime-private state before pricing.

**Snapshot activation records trust for newly validated prices.** _(implements "Runtime validation trust is snapshot- and registry-specific")_
`set_custom_snapshot(snapshot)` validates missing, stale, custom, changed, runtime-authored, or otherwise untrusted model prices. This is the first phase that performs model-price validation during snapshot activation; earlier phases validate the selected model price on every standard base pricing call. After all validation succeeds, it records validation trust in the snapshot context. If validation fails, the previous active snapshot and its trust context remain in place.

**JavaScript registry and validation modules gain fail-closed trust helpers.** _(implements "JavaScript validation trust fails closed")_
Add helpers equivalent to:

```typescript
export function getRegistryValidationId(): object
export function hasModelPriceValidationTrust(modelPrice: ModelPrice, families: ParsedFamilies): boolean
export function markModelPriceValidated(modelPrice: ModelPrice, families: ParsedFamilies): void
export function invalidateModelPriceValidation(modelPrice: ModelPrice): void
```

`setUnitFamilies(...)` creates a fresh opaque validation id for each active parsed registry. Use module-private `WeakMap` / `WeakSet` state keyed by model price object, exact registry validation id, and effective price-key fingerprint. Because model prices are plain objects, every trust lookup recomputes and compares the fingerprint.

**Decomposition caches require benchmark evidence and exact keys.** _(implements "Decomposition caches are benchmark-gated")_
If benchmarks justify caching decomposition coefficients, key caches by exact registry validation id plus the effective priced usage-key set. Do not serialize caches. Do not add caches that change error timing or user-facing decomposition behavior.

**Tests and benchmarks prove no behavior drift.** _(implements "Performance optimizations must be behavior-preserving")_
Add tests for trust hits, stale trust on registry changes, stale trust on key additions/removals, no stale trust on value-only changes, Python id-reuse protection, JavaScript fail-closed fingerprint mismatches, generated-output purity, and parity with Phase 4 behavior. Add benchmarks that justify any decomposition cache included in the phase.
