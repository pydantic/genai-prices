# Code Spec: Phase 7 Global Snapshot Semi-Enforcement

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Previous phase:** [Phase 6 Runtime Custom Units](../phase-6-runtime-custom-units/code-spec.md).

**Phase 7 adds guardrails without adding a new execution context.** _(implements "Phase 7 turns the active-global-snapshot assumption into guardrails", "This is semi-enforcement, not multi-snapshot architecture")_
Modify the existing Python snapshot and model pricing paths. Do not add snapshot parameters to public APIs, do not create context objects, and do not make inactive snapshots safely executable.

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

The assertion happens before provider/model lookup or extractor execution. `find_provider`, `find_provider_model`, registry edit helpers, and lookup cache behavior are unchanged.

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

The guard checks the current active snapshot by object identity, not by provider ID or model name alone. If the exact provider/model objects are not part of the active snapshot, the method raises with a message that points callers toward activating the snapshot or using the top-level pricing API.

**Lookup and staging methods stay callable on inactive snapshots.** _(implements "Pure lookups remain allowed on inactive snapshots")_
`DataSnapshot.find_provider`, `DataSnapshot.find_provider_model`, registry edit helpers, and supporting lookup caches are not guarded. They remain the way callers inspect and patch fetched snapshots before activation.

**JavaScript does not need a parallel Phase 7 snapshot object.** _(implements "This is semi-enforcement, not multi-snapshot architecture")_
The JavaScript runtime already routes pricing through module-global active provider data and active parsed unit families. This phase does not add a separate JavaScript snapshot abstraction. If a future JavaScript API exposes inactive snapshot objects with execution methods, it should apply the same execution-only guardrail described here.
