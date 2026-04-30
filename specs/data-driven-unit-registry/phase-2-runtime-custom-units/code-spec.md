# Code Spec: Phase 2 Runtime Custom Units

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Phase 1 code architecture is in [../code-spec](../code-spec.md).**
**Phase 3 global snapshot semi-enforcement is in [../phase-3-global-snapshot-enforcement/code-spec](../phase-3-global-snapshot-enforcement/code-spec.md).**

**This code spec records the future extension path.** _(implements "This phase is a future-direction guardrail for Phase 1")_
The Phase 2 code architecture exists so Phase 1 can avoid decisions that would make runtime custom units awkward later. It is intentionally secondary to the Phase 1 code spec until Phase 2 starts: Phase 1 should preserve shared data shapes, validation boundaries, and snapshot activation hooks, but it should not implement the mutation APIs below or treat every Phase 2 signature as final before the runtime-custom-unit work is active.

**Phase 2 extends the Phase 1 files instead of introducing a parallel registry.** _(implements "Phase 1 remains the source of truth for the base registry")_
The implementation modifies the Phase 1 `UnitRegistry`, `DataSnapshot`, validation helpers, Python/JS model-price invalidation helpers, and JS registry activation. It does not add a second runtime unit system.

**`UnitRegistry` gains public mutation methods.** _(implements "Registry mutations commit only structurally valid states", "Existing-family unit edits are batch operations")_

```python
class UnitRegistry:
    def add_family(
        self,
        family_id: str,
        *,
        per: int,
        description: str,
        units: dict[str, dict],
    ) -> None:
        """Atomically add and validate a new family."""

    def add_units(
        self,
        family_id: str,
        units: dict[str, dict],
    ) -> None:
        """Atomically add one or more units to an existing family, then validate."""

    def copy(self) -> UnitRegistry:
        """Return an independent registry copy for staging or rollback."""
```

`add_units(...)` stages all supplied units against a candidate family, validates the complete candidate registry once, and commits only if the final state is valid. Unit dimension maps are the only source of dimension keys and values: adding a unit with `{modality: video}` or `{region: us}` introduces that value or axis if the final registry validates.

**`validation_id` tracks mutation compatibility, not just object identity.** _(implements "Pure additive unit additions preserve trusted unchanged prices")_
An independently constructed or destructively mutated registry gets a different validation basis from its source. Purely additive registry mutations preserve validation compatibility for unchanged trusted prices whose referenced units and price-key mappings still exist with the same meaning. The implementation may preserve an inherited compatibility id, record compatible prior ids, or use an equivalent private mechanism.

**`DataSnapshot` exposes the supported custom-unit editing surface.** _(implements "Runtime unit and price patches happen through `DataSnapshot`")_

```python
@dataclass
class DataSnapshot:
    def add_unit_family(
        self,
        family_id: str,
        *,
        per: int,
        description: str,
        units: dict[str, dict],
    ) -> None:
        """Patch this snapshot with a new validated unit family."""

    def add_units(
        self,
        family_id: str,
        units: dict[str, dict],
    ) -> None:
        """Patch this snapshot with a validated batch of units for one family."""
```

The exact public names can be language-idiomatic, but the capabilities are fixed: add a unit family, add a batch of units to an existing family, update model price keys on the same snapshot, invalidate known-valid state and optional decomposition caches only for changed `ModelPrice` objects, and leave inactive snapshots as staging objects until activation.

**Snapshot unit edits are validated with rollback before becoming visible.** _(implements "Registry mutations commit only structurally valid states")_
An implementation may use internal copy-on-write, transactions, or candidate registry objects. Failed registry edits must leave the snapshot's previous registry visible and unchanged. Direct mutation of private registry indexes is not a supported public API.

**`set_custom_snapshot()` validates against the staged custom registry.** _(implements "Snapshot activation validates custom units, prices, and extractors together")_

```python
def set_custom_snapshot(snapshot: DataSnapshot | None) -> None:
    """Activate a snapshot or reset to bundled default.

    For non-None snapshots:
    - validate the snapshot registry structure before activation
    - skip price-level validation for model prices already known valid for a compatible registry
      and their current price-key fingerprint
    - validate missing/stale custom, changed, runtime-authored, or otherwise untrusted model
      prices against snapshot.unit_registry.price_keys
    - validate extractor destinations against snapshot.unit_registry.units.keys()
    - after all validation succeeds, mark newly validated ModelPrice objects known valid
    - optionally build decomposition caches for newly validated ModelPrice objects
    - leave the previous snapshot active if any validation fails
    """
```

This activation step is what turns custom units from staged data into trusted runtime state. Runtime-authored extractor mappings can target custom usage keys only after those keys exist in the staged registry being activated.

**Price mutation helpers preserve Phase 1 subclass behavior.** _(implements "Runtime unit and price patches happen through `DataSnapshot`")_
Runtime `ModelPrice` continues to distinguish registered price keys, candidate dynamic price keys, and declared subclass-only custom fields. Adding or removing effective registered price keys through supported mutation paths clears known-valid state and any cached decomposition state for that model price. Subclass-only fields that are not registered price keys still do not trigger registry validation.

**Python custom unit flow.** _(implements "Runtime unit and price patches happen through `DataSnapshot`", "Snapshot activation validates custom units, prices, and extractors together")_

```text
snapshot = get_snapshot() or an inactive snapshot returned from fetch()
  -> edit the snapshot through supported mutation APIs
  -> snapshot.add_unit_family(...), snapshot.add_units(...)
  -> mutate relevant ModelPrice objects for the new registered price keys
       -> mutation invalidates known-valid/decomposition-cache state for changed prices
  -> if snapshot is inactive: set_custom_snapshot(snapshot)
       -> validate only missing/stale custom, changed, or otherwise untrusted ModelPrice objects
          against expanded registry
       -> do not revalidate unchanged trusted built-in prices just because units were added
       -> mark validated prices known valid
       -> activate on success
  -> if snapshot is already active: supported mutations have already updated the active snapshot,
       and changed prices are validated either by the mutation helper or by the one-model calc fallback
```

**JS gets staged family mutation helpers parallel to Python.** _(implements "Runtime unit patches use the same batch boundary in every language")_

```typescript
export function addUnitFamily(families: ParsedFamilies, familyId: string, family: RawFamilyData): ParsedFamilies

export function addUnits(
  families: ParsedFamilies,
  familyId: string,
  units: Record<string, RawUnitData>,
): ParsedFamilies
```

The helpers return or commit a structurally valid parsed registry only after validation succeeds. JS can use object identity as part of `registryValidationId`, but known-valid checks need compatibility handling for pure additive extensions.

**JS validation and activation stay atomic.** _(implements "Snapshot activation validates custom units, prices, and extractors together", "Pure additive unit additions preserve trusted unchanged prices")_
`validateProviderData(stagedProviders, stagedFamilies)` validates changed/new model prices and extractor destinations against the staged parsed registry. If validation fails, neither active provider data nor active unit families change. Known-valid state and optional decomposition caches can remain in module-private `WeakMap`s, but their compatibility checks must account for pure additive unit extensions.

**JS custom unit flow.** _(implements "Runtime unit patches use the same batch boundary in every language")_

```text
stagedFamilies/stagedProviders = patch the active or fetched payload through supported helpers
  -> batch unit edit on one family:
       add the units required by the final registry shape
  -> patch providerData/model prices through supported helpers
  -> validateProviderData(stagedProviders, stagedFamilies)
       -> skip still-known-valid built-in prices
       -> skip unchanged trusted built-in prices across pure unit additions
       -> validate changed/new prices and mark them known valid
  -> setUnitFamilies(stagedFamilies)
  -> setProviderData(stagedProviders)
```
