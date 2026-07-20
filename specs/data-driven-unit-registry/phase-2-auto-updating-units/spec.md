# Phase 2: Auto-Updating Unit Definitions

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 2 makes unit definitions update atomically with provider prices.**
It adds the runtime capability deliberately excluded from the releasable static-registry Phase 1.

**Phase 2 is a future independent PR, not part of the Phase 1 release or a stacked prerequisite.**
Implementation begins only after Phase 1 is merged and released. Phase 1 remains complete and supported without this work.

**Existing v1 and v2 update contracts remain stable.** _(from "Phase 2 is a future independent PR")_
`data.json` continues serving v1 packages. Phase 2 freezes `data_v2.json` and `data_v2.schema.json` at their last Phase 1-compatible bytes so static-registry packages never receive a later unit key. This deliberately ends live price-data updates for Phase 1 packages once v3 is published. It goes against "The goal is to calculate prices as accurately as possible for a given request" in the [root spec](../spec.md), but is allowed here because continuing to evolve v2 would either break its static unit vocabulary or require a permanent filtered-publication pipeline. Phase 2 does not repurpose either URL or change either root shape.

**Phase 2 publishes wrapped `data_v3.json`.** _(from "Phase 2 makes unit definitions update atomically with provider prices", "Existing v1 and v2 update contracts remain stable")_
The v3 payload contains unit definitions and providers in one versioned object. Unit definitions travel with every price and extractor field that depends on them, preventing a v3 runtime from activating provider data against an unrelated registry.

**Every response at the v3 URL remains consumable by every released v3 package.** _(from "Phase 2 publishes wrapped `data_v3.json`")_
The URL identifies a stable wire contract, not merely the latest writer. A change that an already released v3 parser cannot safely accept requires a new versioned URL.

**V3 units are append-only by usage key.** _(from "Every response at the v3 URL remains consumable by every released v3 package")_
A publication may add a complete new unit, but it cannot remove an existing unit or change that unit's resolved `price_key`, `per`, or complete `dimensions` mapping.

**The v3 wrapper and unit-definition shapes are frozen.** _(from "Every response at the v3 URL remains consumable by every released v3 package")_
The wrapper has exactly `units` and `providers`. A unit definition has exactly `per`, optional `price_key`, and `dimensions`. Adding a structural member or changing either object shape requires another versioned URL.

**The v3 provider schema evolves only compatibly.** _(from "Every response at the v3 URL remains consumable by every released v3 package")_
Provider values may change, while provider records may use only fields and value shapes accepted by every released v3 parser. A provider-schema change outside that compatibility envelope requires another versioned URL.

**V3-capable packages point only at the v3 URL.** _(from "Phase 2 publishes wrapped `data_v3.json`")_
Older packages remain on their versioned URLs. V3 runtimes do not require a shape-detection migration path for v1 or v2 auto-update responses because their default updater requests the contract they implement.

**Registry and provider activation is atomic.** _(from "Phase 2 publishes wrapped `data_v3.json`")_
A runtime first constructs a side-effect-free candidate containing both the fetched registry and parsed providers. Standard package entry points obtain registry and providers from one process-global state object. Activation is one state-reference replacement after preparation succeeds; parse, validation, rejected-promise, or stale-update failure performs no replacement and therefore preserves both previous values.

**Remote v3 activation validates the complete candidate before the swap.** _(from "Registry and provider activation is atomic", "Every response at the v3 URL remains consumable by every released v3 package")_
Fetched unit structure, public-key safety, unique identities, family normalization, interval closure, and join-closedness are validated before providers are parsed against that candidate. Every provider price key, required ancestor and join price, and extractor destination is then validated before activation. Bundled Phase 1 registry construction may trust generated data; remote v3 construction may not.

**The active v3 registry remains process-global and provider snapshots remain provider-only.** _(from "Registry and provider activation is atomic")_
Pricing, usage, extraction, and validation consult the one active registry. `DataSnapshot` does not embed a second registry, and custom provider snapshot activation does not independently change unit definitions.

**Detached pricing APIs capture one active registry per call.** _(from "The active v3 registry remains process-global and provider snapshots remain provider-only", "V3 units are append-only by usage key")_
This is an explicit compatibility exception to the paired-provider read in "Registry and provider activation is atomic": direct `DataSnapshot.calc(...)`, `ModelInfo.calc_price(...)`, and `ModelPrice.calc_price(...)` calls use the provider/model object supplied by the caller and capture the active registry once at call entry. This is safe because v3 unit evolution preserves every existing unit meaning. Each standalone `Usage` construction, read, assignment, equality, addition, or representation operation likewise captures one active registry and does not observe a mid-operation replacement.

**Stopping Python's v3 updater restores bundled state.** _(from "The active v3 registry remains process-global and provider snapshots remain provider-only")_
`UpdatePrices.stop()` replaces the paired runtime state with the provider snapshot and registry generated with the installed package. JavaScript's storage-factory API has no package-owned stop lifecycle: `null` continues to mean a failed update that leaves state untouched, and a wrapped update or explicit provider-array update is the only state-change input.

**V3 publication compares against the deployed v3 registry.** _(from "V3 units are append-only by usage key", "The v3 wrapper and unit-definition shapes are frozen")_
After the initial v3 publication, the release job fetches the currently deployed `data_v3.json`, records its content digest, and compares every old unit definition with the candidate before publishing. Missing current data, an invalid current wrapper, a removed unit, or any changed semantic field fails publication. The initial publication compares the candidate with the Phase 1 bundled registry. Runtime packages need no history database because this compatibility check belongs to the publisher.

**V3 publication is conditional on the compared digest.** _(from "Every response at the v3 URL remains consumable by every released v3 package", "V3 publication compares against the deployed v3 registry")_
The release job serializes publication and replaces the deployed artifact only if its content digest still equals the baseline just compared. A concurrent change aborts the write and requires fetching, validating, and comparing again, so two releases cannot both validate against one baseline and then erase each other's unit additions.

**Generated and fetched v3 outputs remain pure data.**
Payloads and generated modules contain raw units, providers, and raw prices only. Validation markers, trust flags, fingerprints, cache records, and decomposition plans remain runtime concerns rather than serialized contract fields.

**Phase 2 does not include validation or decomposition caching.**
Registry replacement may later motivate cache identities and invalidation, but those optimizations require fresh benchmarks and a separate decision. They are not part of enabling atomic unit updates.

**Tests prove version isolation and atomic activation.** _(from "Existing v1 and v2 update contracts remain stable", "Remote v3 activation validates the complete candidate before the swap", "V3 publication is conditional on the compared digest")_
Coverage verifies frozen v1/v2 artifacts, wrapped v3 schemas, publisher rejection of removed or changed units, conditional-publication conflicts, matching unit/provider activation, no state change after unit, provider, extractor, promise, or stale-update failure, consistent detached calls and `Usage` operations during replacement, Python restoration of bundled state, use of newly fetched units in both runtimes, and absence of runtime cache state in serialized outputs.
