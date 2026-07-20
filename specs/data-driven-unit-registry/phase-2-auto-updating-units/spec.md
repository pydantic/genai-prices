# Phase 2: Auto-Updating Unit Definitions

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 2 makes unit definitions update atomically with provider prices.**
It adds the runtime capability deliberately excluded from the releasable static-registry Phase 1.

**Phase 2 is a future independent PR, not part of the Phase 1 release or a stacked prerequisite.**
Implementation begins only after Phase 1 is merged and released. Phase 1 remains complete and supported without this work.

**Existing v1 and v2 update contracts remain stable.** _(from "Phase 2 is a future independent PR")_
`data.json` continues serving v1 packages and `data_v2.json` continues serving static-registry Phase 1 packages. Phase 2 does not repurpose either URL or change either root shape.

**Phase 2 publishes wrapped `data_v3.json`.** _(from "Phase 2 makes unit definitions update atomically with provider prices", "Existing v1 and v2 update contracts remain stable")_
The v3 payload contains unit definitions and providers in one versioned object. Unit definitions travel with every price and extractor field that depends on them, preventing a v3 runtime from activating provider data against an unrelated registry.

**V3-capable packages point only at the v3 URL.** _(from "Phase 2 publishes wrapped `data_v3.json`")_
Older packages remain on their versioned URLs. V3 runtimes do not require a shape-detection migration path for v1 or v2 auto-update responses because their default updater requests the contract they implement.

**Registry and provider activation is atomic.** _(from "Phase 2 publishes wrapped `data_v3.json`")_
A runtime constructs a candidate registry from fetched units, parses and validates provider activation against that candidate, then makes both active together. Any failure preserves the previous registry and provider data.

**The active v3 registry remains process-global and provider snapshots remain provider-only.** _(from "Registry and provider activation is atomic")_
Pricing, usage, extraction, and validation consult the one active registry. `DataSnapshot` does not embed a second registry, and custom provider snapshot activation does not independently change unit definitions.

**Stopping a v3 updater restores bundled state.** _(from "The active v3 registry remains process-global and provider snapshots remain provider-only")_
When the updater clears fetched providers, it restores the registry generated with the installed package so provider and unit state return to the same bundled release boundary.

**Published registry evolution must preserve existing unit meanings.** _(from "Existing v1 and v2 update contracts remain stable", "Registry and provider activation is atomic")_
V3 publication may add units and compatible metadata, but existing usage keys, price keys, dimensions, normalization factors, and commercial meanings remain stable. Phase 2 validates each current payload but does not require a runtime history database or attach registry versions to every provider object.

**Generated and fetched v3 outputs remain pure data.** _(from "Phase 2 publishes wrapped `data_v3.json`")_
Payloads and generated modules contain raw units, providers, and raw prices only. Validation markers, trust flags, fingerprints, cache records, and decomposition plans remain runtime concerns rather than serialized contract fields.

**Phase 2 does not require validation or decomposition caching.** _(from "Phase 2 is a future independent PR")_
Registry replacement may later motivate cache identities and invalidation, but those optimizations require fresh benchmarks and a separate decision. They are not part of enabling atomic unit updates.

**Tests prove version isolation and atomic activation.** _(from "Existing v1 and v2 update contracts remain stable", "Registry and provider activation is atomic")_
Coverage verifies unchanged v1/v2 artifacts, wrapped v3 schemas, matching unit/provider activation, rollback after parse or extractor failure, restoration of bundled state, use of newly fetched units in both runtimes, and absence of runtime cache state in serialized outputs.
