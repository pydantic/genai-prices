# Code Spec: Phase 2 Auto-Updating Unit Definitions

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**

**A released Phase 1 is the implementation precondition.** _(implements "Phase 2 is a future independent PR, not part of the Phase 1 release or a stacked prerequisite")_
Start Phase 2 from the released static-registry implementation, not as commits stacked on the Phase 1 review branch. The Phase 1 release tag and its checked-in v1/v2 artifact digests become the immutable compatibility fixtures for this PR.

**Phase 2 adds a versioned wrapped artifact while treating v1 and v2 as read-only fixtures.** _(implements "Existing v1 and v2 update contracts remain stable", "Phase 2 publishes wrapped `data_v3.json`")_
`prices/src/prices/build.py` emits `prices/data_v3.json` and `prices/data_v3.schema.json` as:

```json
{
  "units": { "input_tokens": { "...": "..." } },
  "providers": [{ "...": "..." }]
}
```

The v3 unit object uses the same usage-keyed raw shape as `prices/units.yml`. The v3 schema closes the wrapper and unit-definition objects to the fields defined in the prose spec. `build.py` and `prices/src/prices/package_data.py` do not write v1 or v2; regression tests hash those files against the Phase 1 release fixtures. Provider slimming and additional v3 variants are excluded.

**V3 package generation remains split.** _(implements "Generated and fetched v3 outputs remain pure data")_
`prices/src/prices/package_data.py::package_data()` reads the v3 wrapper and passes its two members separately to `package_python_data(providers, units)` and `package_ts_data(providers, units)`. The functions write providers to Python `data.py` and JavaScript `data.ts`, and units to Python `data_units.py` and JavaScript `dataUnits.ts`. Generated modules contain no validation or cache state.

**Python owns registry and provider activation through one immutable runtime-state reference.** _(implements "Phase 2 makes unit definitions update atomically with provider prices", "Registry and provider activation is atomic", "The active v3 registry remains process-global and provider snapshots remain provider-only")_
Add `packages/python/genai_prices/runtime_state.py` with frozen `RuntimeData(registry: UnitRegistry, snapshot: DataSnapshot)`, a lazily created bundled `RuntimeData`, and private `get_runtime_data()`, `activate_runtime_data(candidate)`, `replace_snapshot(snapshot: DataSnapshot | None)`, and `restore_bundled_runtime_data()` functions. A lock serializes writers; activation occurs by assigning the single `_runtime_data` reference after the candidate is complete. Public pricing, lookup, and extraction entry points capture one `RuntimeData` and pass its registry explicitly through internal `DataSnapshot`, `ModelInfo`, `ModelPrice`, validation, usage, and decomposition calls, so one operation cannot mix providers from one state with a registry from another. `DataSnapshot` itself retains only provider data and metadata.

**Python v3 fetch prepares, validates, and commits before returning.** _(implements "V3-capable packages point only at the v3 URL", "Registry and provider activation is atomic")_
In `packages/python/genai_prices/update_prices.py`, point `DEFAULT_UPDATE_URL` at `data_v3.json`. `UpdatePrices.fetch()` parses the exact wrapper, constructs a candidate `UnitRegistry`, passes that registry explicitly to `_providers_from_raw(...)` and extractor validation, constructs a provider-only `DataSnapshot`, and finally calls `activate_runtime_data(RuntimeData(candidate_registry, candidate_snapshot))`. A successful manual or background `fetch()` therefore activates both values before returning the active snapshot; `_update_prices()` no longer performs a second `set_custom_snapshot(...)` step. Any exception before the single activation call leaves the previous state untouched.

**Python stop and custom-snapshot transitions preserve their distinct ownership.** _(implements "Stopping Python's v3 updater restores bundled state", "The active v3 registry remains process-global and provider snapshots remain provider-only")_
`UpdatePrices.stop()` waits for the worker to exit and then calls `restore_bundled_runtime_data()`. `set_custom_snapshot(...)` calls `replace_snapshot(...)`, which builds a new `RuntimeData` with the current registry and the requested provider snapshot, using bundled providers when passed `None`; it never infers a registry from a snapshot.

**JavaScript owns registry and providers through one immutable runtime-state reference.** _(implements "Phase 2 makes unit definitions update atomically with provider prices", "Registry and provider activation is atomic", "The active v3 registry remains process-global and provider snapshots remain provider-only")_
Add `packages/js/src/runtimeState.ts` with `RuntimeData = Readonly<{ registry: UnitRegistry; providers: Provider[] }>`, `bundledRuntimeData`, `getRuntimeData()`, and internal `activateRuntimeData(candidate)`. `packages/js/src/api.ts` captures one `RuntimeData` at the start of pricing, lookup, or extraction and passes `state.registry` explicitly to engine, usage, decomposition, and validation helpers while using `state.providers` for lookup. Activation replaces one module-level state reference; `packages/js/src/units.ts` owns registry construction and indexes but no mutable active-registry variable.

**JavaScript provider activation prepares the v3 wrapper before one commit.** _(implements "V3-capable packages point only at the v3 URL", "Registry and provider activation is atomic")_
Point `REMOTE_DATA_JSON_URL` in `packages/js/src/api.ts` at `data_v3.json`. `setProviderData` accepts `null`, a `WrappedProviderData`, a local `Provider[]`, or a promise resolving to one of those values. A wrapper path constructs `UnitRegistry(data.units)`, validates `data.providers` against it, then calls `activateRuntimeData({ registry, providers })` once. A provider-array path validates against `getRuntimeData().registry` and commits a new state with that same registry. `null`, malformed data, validation failure, and rejection leave state untouched. A promise may commit only if it is still the latest promise registered by `setProviderData`; stale resolution or rejection cannot replace state or the newer wait handle.

The official updater and checked-in examples use the v3 wrapper. The provider-array path remains only for the existing local storage-factory compatibility surface and never changes the active registry. JavaScript has no package-owned stop operation or automatic restoration transition; `null` and provider arrays therefore never reset the registry.

**Registry replacement remains private and uncached.** _(implements "The active v3 registry remains process-global and provider snapshots remain provider-only", "Phase 2 does not require validation or decomposition caching")_
Only the runtime-state modules expose internal activation and restoration functions. Neither package root exports arbitrary registry mutation. Every `UnitRegistry` is immutable after construction, and no runtime state or generated output contains validation IDs, weak maps, price fingerprints, prepared plans, or decomposition caches.

**V3 publication validation covers the wrapper and append-only evolution.** _(implements "Published registry evolution must preserve existing unit meanings", "V3 publication compares against the deployed v3 registry")_
`prices/src/prices/export_validation.py` adds `validate_unit_evolution(previous_units, candidate_units) -> None`. It requires every previous usage key in the candidate with identical `price_key` default resolution, `per`, and full `dimensions`; candidate-only units are allowed and removed or changed units raise. The release job fetches and parses the deployed v3 wrapper, runs this comparison, then runs `validate_export_payload(candidate.providers, candidate.units)` before writing/publishing. The bootstrap path uses the Phase 1 release's bundled units as `previous_units`. Failure to retrieve or validate the deployed baseline aborts publication rather than skipping the comparison.

**Tests exercise both runtime transactions and version isolation.** _(implements "Tests prove version isolation and atomic activation")_
Add Python and JavaScript integration tests for a new unit absent from bundled Phase 1 data but present in a fetched v3 wrapper. Assert a pricing call captures one paired state; activation happens only after registry, provider parsing, and extractor validation succeed; malformed wrappers, invalid extractors, rejected/stale promises, and failed publication comparisons do not change state; Python stop restores bundled units/providers; provider-only custom activation preserves the current registry; v1/v2 bytes remain pinned; `DataSnapshot` stays provider-only; and serialized outputs contain no cache state.
