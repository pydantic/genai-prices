# Phase 2: Auto-Updating Unit Definitions

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 2 makes unit definitions update atomically with provider prices.**
It adds the runtime capability deliberately excluded from the releasable static-registry Phase 1.

**Phase 2 is a future independent PR, not part of the Phase 1 release or a stacked prerequisite.**
Implementation begins only after Phase 1 is merged and released. Phase 1 remains complete and supported without this work.

**Existing v1 and v2 update contracts remain stable.** _(from "Phase 2 is a future independent PR")_
`data.json` continues serving v1 packages. Phase 2 freezes `data_v2.json` and `data_v2.schema.json` at their last Phase 1-compatible bytes so static-registry packages never receive a later unit key. Phase 2 does not repurpose either URL or change either root shape.

**Phase 2 publishes wrapped `data_v3.json`.** _(from "Phase 2 makes unit definitions update atomically with provider prices", "Existing v1 and v2 update contracts remain stable")_
The v3 payload contains unit definitions and providers in one versioned object. Unit definitions travel with every price and extractor field that depends on them, preventing a v3 runtime from activating provider data against an unrelated registry.

**V3-capable packages point only at the v3 URL.** _(from "Phase 2 publishes wrapped `data_v3.json`")_
Older packages remain on their versioned URLs. V3 runtimes do not require a shape-detection migration path for v1 or v2 auto-update responses because their default updater requests the contract they implement.

**Registry and provider activation is atomic.** _(from "Phase 2 publishes wrapped `data_v3.json`")_
A runtime first constructs a side-effect-free candidate containing both the fetched registry and parsed providers and validates the providers against that registry. Runtime reads obtain registry and providers from one process-global state object. Activation is one state-reference replacement after preparation succeeds; parse, validation, rejected-promise, or stale-update failure performs no replacement and therefore preserves both previous values.

**The active v3 registry remains process-global and provider snapshots remain provider-only.** _(from "Registry and provider activation is atomic")_
Pricing, usage, extraction, and validation consult the one active registry. `DataSnapshot` does not embed a second registry, and custom provider snapshot activation does not independently change unit definitions.

**Stopping Python's v3 updater restores bundled state.** _(from "The active v3 registry remains process-global and provider snapshots remain provider-only")_
`UpdatePrices.stop()` replaces the paired runtime state with the provider snapshot and registry generated with the installed package. JavaScript's storage-factory API has no package-owned stop lifecycle: `null` continues to mean a failed update that leaves state untouched, and a wrapped update or explicit provider-array update is the only state-change input.

**Published registry evolution must preserve existing unit meanings.** _(from "Existing v1 and v2 update contracts remain stable", "Registry and provider activation is atomic")_
The v3 registry is append-only by usage key. A publication may add a complete new unit, but it cannot remove an existing unit or change that unit's `price_key`, `per`, or complete `dimensions` mapping. The v3 wrapper has exactly `units` and `providers`, and a v3 unit definition has exactly `per`, optional `price_key`, and `dimensions`; a new structural field or changed meaning requires another versioned URL. Provider values may change, and provider records may evolve only within the fields accepted by the published v3 schema.

**V3 publication compares against the deployed v3 registry.** _(from "Published registry evolution must preserve existing unit meanings")_
After the initial v3 publication, the release job fetches the currently deployed `data_v3.json` and compares every old unit definition with the candidate before publishing. Missing current data, an invalid current wrapper, a removed unit, or any changed semantic field fails publication. The initial publication compares the candidate with the Phase 1 bundled registry. Runtime packages need no history database because this compatibility check belongs to the publisher.

**Generated and fetched v3 outputs remain pure data.** _(from "Phase 2 publishes wrapped `data_v3.json`")_
Payloads and generated modules contain raw units, providers, and raw prices only. Validation markers, trust flags, fingerprints, cache records, and decomposition plans remain runtime concerns rather than serialized contract fields.

**Phase 2 does not require validation or decomposition caching.** _(from "Phase 2 is a future independent PR")_
Registry replacement may later motivate cache identities and invalidation, but those optimizations require fresh benchmarks and a separate decision. They are not part of enabling atomic unit updates.

**Tests prove version isolation and atomic activation.** _(from "Existing v1 and v2 update contracts remain stable", "Registry and provider activation is atomic", "V3 publication compares against the deployed v3 registry")_
Coverage verifies frozen v1/v2 artifacts, wrapped v3 schemas, publisher rejection of removed or changed units, matching unit/provider activation, no state change after parse, extractor, promise, or stale-update failure, Python restoration of bundled state, use of newly fetched units in both runtimes, and absence of runtime cache state in serialized outputs.
