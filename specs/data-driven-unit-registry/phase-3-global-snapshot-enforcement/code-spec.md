# Code Spec: Global Snapshot Semi-Enforcement

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Phase 1 code architecture is in [../code-spec](../code-spec.md).**

**This code spec adds guardrails without adding a new execution context.** _(implements "This phase turns the active-global-snapshot assumption into guardrails", "This is semi-enforcement, not multi-snapshot architecture")_
The implementation modifies the existing Python snapshot and model pricing paths. It does not add snapshot parameters to public APIs, does not create context objects, and does not make inactive snapshots safely executable.

**This change is independently mergeable.** _(implements "Phase numbering is bookkeeping, not a required implementation order")_
The code changes are small runtime guards around existing APIs. They can land before or after the Phase 1 unit-registry implementation as long as they are rebased onto the current shape of `DataSnapshot` and `ModelInfo.calc_price()`.

**`DataSnapshot` gets an active-execution assertion.** _(implements "`DataSnapshot.calc` and `DataSnapshot.extract_usage` require the active snapshot")_

```python
@dataclass
class DataSnapshot:
    def _assert_active_for_execution(self, operation: str) -> None:
        """Raise if this snapshot is not the active global snapshot for an execution operation."""
```

`operation` is used only to produce a clear error message such as "DataSnapshot.calc requires the active global snapshot." The helper is private because this phase is a guardrail around existing APIs, not a new public snapshot-state API.

**`DataSnapshot.calc()` and `DataSnapshot.extract_usage()` call the assertion first.** _(implements "Only execution paths are blocked")_

```python
class DataSnapshot:
    def calc(...) -> types.PriceCalculation:
        """Require this snapshot to be active, then calculate the price."""

    def extract_usage(...) -> types.ExtractedUsage:
        """Require this snapshot to be active, then extract usage."""
```

The assertion happens before provider/model lookup or extractor execution. `find_provider`, `find_provider_model`, and lookup cache behavior are unchanged.

**`ModelInfo.calc_price()` gets an active provider/model assertion.** _(implements "Escaped model pricing is rejected when identity can prove it is inactive")_

```python
class ModelInfo:
    def calc_price(
        self,
        usage: AbstractUsage,
        provider: Provider,
        *,
        genai_request_timestamp: datetime | None = None,
        auto_update_timestamp: datetime | None = None,
    ) -> PriceCalculation:
        """Require the provider/model pair to belong to the active snapshot, then price usage."""
```

The guard checks the current active snapshot by identity, not by provider ID or model name alone. If the exact provider/model objects are not part of the active snapshot, the method raises with a message that points callers toward activating the snapshot or using the top-level pricing API.

**Lookup-only methods stay callable on inactive snapshots.** _(implements "Pure lookups remain allowed on inactive snapshots")_
`DataSnapshot.find_provider`, `DataSnapshot.find_provider_model`, and supporting lookup caches are not guarded. They remain the way callers inspect and patch fetched snapshots before activation.

**JavaScript does not need a parallel Phase 3 snapshot object.** _(implements "This is semi-enforcement, not multi-snapshot architecture")_
The JavaScript runtime already routes pricing through module-global active provider data and active parsed unit families. This phase does not add a separate JS snapshot abstraction. If a future JS API exposes inactive snapshot objects with execution methods, it should apply the same execution-only guardrail described here.
