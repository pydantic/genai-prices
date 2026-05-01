# Code Spec: Phase 6 Runtime Custom Units

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Previous phase:** [Phase 5 Runtime Validation Performance Optimization](../phase-5-runtime-validation-performance/code-spec.md).
**Next phase:** [Phase 7 Global Snapshot Semi-Enforcement](../phase-7-global-snapshot-enforcement/code-spec.md).

**Phase 6 extends the Phase 5 registry instead of introducing a parallel unit system.** _(implements "Phase 6 adds runtime unit editing on top of the optimized registry runtime")_
Modify the existing `UnitRegistry`, `DataSnapshot`, validation helpers, Python/JavaScript validation-trust invalidation helpers, and JavaScript registry activation. Do not add a second runtime unit model or a separate custom-unit registry.

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

`add_units(...)` stages all supplied units against a candidate family, validates the complete candidate registry once, and commits only if the final state is valid. Unit dimension maps remain the only source of dimension keys and values.

**Registry validation identity gains additive-compatibility semantics.** _(implements "Pure additive unit additions preserve trusted unchanged prices")_
Phase 5 introduced exact registry validation identities. Phase 6 extends that model with explicit compatible validation ids:

```python
class UnitRegistry:
    validation_id: object
    compatible_validation_ids: frozenset[object]
```

A pure additive registry mutation creates a fresh `validation_id` and carries forward the previous registry's `validation_id` plus its `compatible_validation_ids`. An independently constructed or destructively mutated registry gets a fresh `validation_id` and an empty compatibility set. Validation trust can be reused when the current effective price-key fingerprint matches and the price was validated against either the exact current `validation_id` or one of the current registry's compatible ids.

**`DataSnapshot` exposes the supported custom-unit editing surface.** _(implements "Runtime unit and price patches happen through `DataSnapshot`", "Borrowed registry staging uses copy-on-write detachment")_

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

The methods must detach or otherwise stage a borrowed registry before mutation so an inactive snapshot edit cannot mutate the currently active registry. Failed registry edits leave the snapshot's previous registry visible and unchanged.

**`set_custom_snapshot()` validates against the staged custom registry.** _(implements "Snapshot activation validates custom units, prices, and extractors together", "Pure additive unit additions preserve trusted unchanged prices")_

```python
def set_custom_snapshot(snapshot: DataSnapshot | None) -> None:
    """Activate a snapshot or reset to bundled default.

    For non-None snapshots:
    - validate the snapshot registry structure before activation
    - skip price-level validation for model prices that have compatible validation trust
      for their current price-key fingerprint
    - validate missing/stale custom, changed, runtime-authored, or otherwise untrusted model
      prices against snapshot.unit_registry.price_keys
    - validate extractor destinations against snapshot.unit_registry reported usage keys
    - after all validation succeeds, record validation trust for newly validated ModelPrice objects
    - leave the previous snapshot active if any validation fails
    """
```

Runtime-authored extractor mappings can target custom usage keys only after those keys exist in the staged registry being activated.

**Price mutation helpers preserve subclass behavior and invalidate trust.** _(implements "Runtime unit and price patches happen through `DataSnapshot`")_
Runtime `ModelPrice` continues to distinguish registered price keys, candidate dynamic price keys, and declared subclass-only custom fields. Adding or removing effective registered price keys through supported mutation paths clears validation trust and any cached decomposition state for that model price. Subclass-only fields that are not registered price keys still do not trigger registry validation.

**Python custom unit flow.** _(implements "Runtime unit and price patches happen through `DataSnapshot`", "Snapshot activation validates custom units, prices, and extractors together")_

```text
snapshot = get_snapshot() or an inactive snapshot returned from fetch()
  -> edit the snapshot through supported mutation APIs
  -> snapshot.add_unit_family(...), snapshot.add_units(...)
  -> mutate relevant ModelPrice objects for the new registered price keys
       -> mutation invalidates validation trust and any decomposition cache for changed prices
  -> if snapshot is inactive: set_custom_snapshot(snapshot)
       -> validate only missing/stale custom, changed, or otherwise untrusted ModelPrice objects
          against expanded registry
       -> preserve trust for unchanged compatible built-in/fetched prices across pure unit additions
       -> record validation trust for newly validated prices
       -> activate on success
  -> if snapshot is already active: supported mutations have already updated the active snapshot,
       and changed prices are validated either by the mutation helper or by the one-model calc fallback
```

**JavaScript gets staged family mutation helpers parallel to Python.** _(implements "Runtime unit patches use the same batch boundary in every language")_

```typescript
export function addUnitFamily(families: ParsedFamilies, familyId: string, family: RawFamilyData): ParsedFamilies

export function addUnits(
  families: ParsedFamilies,
  familyId: string,
  units: Record<string, RawUnitData>,
): ParsedFamilies
```

The helpers return a structurally valid parsed registry only after validation succeeds. Validation-trust compatibility checks must account for pure additive extensions.

**JavaScript validation and activation stay atomic.** _(implements "Snapshot activation validates custom units, prices, and extractors together", "Pure additive unit additions preserve trusted unchanged prices")_
`validateProviderData(stagedProviders, stagedFamilies)` validates changed/new model prices and extractor destinations against the staged parsed registry. If validation fails, neither active provider data nor active unit families change. Module-private trust state remains fail-closed and fingerprint-based, while compatible pure additions can preserve trust for unchanged prices.

**JavaScript custom unit flow.** _(implements "Runtime unit patches use the same batch boundary in every language")_

```text
stagedFamilies/stagedProviders = patch the active or fetched payload through supported helpers
  -> batch unit edit on one family:
       add the units required by the final registry shape
  -> patch providerData/model prices through supported helpers
  -> validateProviderData(stagedProviders, stagedFamilies)
       -> preserve compatible trust for unchanged built-in/fetched prices across pure additions
       -> validate changed/new prices and record validation trust
  -> setUnitFamilies(stagedFamilies)
  -> setProviderData(stagedProviders)
```
