# Phase 2: Auto-Updating Unit Definitions

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 2 makes unit definitions update atomically with provider prices.**
It adds the runtime capability deliberately excluded from the releasable static-registry Phase 1.

**Phase 2 is a future independent PR, not part of the Phase 1 release or a stacked prerequisite.**
Implementation begins only after Phase 1 is merged and released. Phase 1 remains complete and supported without this work.

**Existing v1 and v2 update contracts remain stable.** _(from "Phase 2 is a future independent PR")_
`data.json` continues serving v1 packages. At the v3 cutover, Phase 2 records and freezes the then-current `data_v2.json` and `data_v2.schema.json` bytes so static-registry packages never receive a later unit key; valid Phase 1 price updates made before that cutover are retained. This deliberately ends live price-data updates for Phase 1 packages once v3 is published. It goes against "The goal is to calculate prices as accurately as possible for a given request" in the [root spec](../spec.md), but is allowed here because continuing to evolve v2 would either break its static unit vocabulary or require a permanent filtered-publication pipeline. Phase 2 does not repurpose either URL or change either root shape.

**Phase 2 publishes a frozen slim projection of final v2.** _(from "Phase 2 is a future independent PR", "Existing v1 and v2 update contracts remain stable")_
At the v3 cutover, Phase 2 derives `data_v2_slim.json` and `data_v2_slim.schema.json` from the final full v2 provider array. The slim payload keeps the v2 top-level provider-array shape and frozen unit vocabulary, contains no unit definitions, excludes free models, omits provider `pricing_urls`, `description`, and `price_comments`, omits model `name`, `description`, and `price_comments`, and otherwise preserves the final v2 provider data. The pair is frozen when created alongside `data_v2.json` and its schema. It is an optional compatibility artifact for consumers that choose the smaller payload; package auto-updaters do not switch to it by default.

**Phase 2 publishes wrapped `data_v3.json`.** _(from "Phase 2 makes unit definitions update atomically with provider prices", "Existing v1 and v2 update contracts remain stable")_
The v3 payload contains unit definitions and providers in one versioned object. Unit definitions travel with every price and extractor field that depends on them, preventing a v3 runtime from activating provider data against an unrelated registry.

**Every response at the v3 URL remains consumable by every released v3 package.**
The URL identifies a stable wire contract, not merely the latest writer. A change that an already released v3 parser cannot safely accept requires a new versioned URL.

**V3 units are append-only by usage key.** _(from "Every response at the v3 URL remains consumable by every released v3 package")_
A publication may add a complete new unit, but it cannot remove an existing unit or change that unit's resolved `price_key`, `per`, or complete `dimensions` mapping. A new unit's dimensions cannot be a proper subset of an existing unit's dimensions, so it cannot become a new ancestor or intermediate node that changes validation or decomposition for an old price set. Ancestor and join relationships among existing units therefore remain unchanged.

**The v3 wrapper and unit-definition shapes are frozen.** _(from "Every response at the v3 URL remains consumable by every released v3 package")_
The wrapper has exactly `units` and `providers`. A unit definition has exactly `per`, optional `price_key`, and `dimensions`. Adding a structural member or changing either object shape requires another versioned URL.

**The v3 provider structure is frozen.** _(from "Every response at the v3 URL remains consumable by every released v3 package")_
Provider/model records may add and remove array entries and change values within the field names and value shapes published at the v3 cutover. The frozen schema models price maps as string-keyed records of the existing price-value shape and extractor destinations as strings; runtime and publication validation resolve those dynamic names against units in the same payload. Adding another structural provider field or changing a field's value shape requires a new versioned URL; `data_v3.schema.json` remains byte-for-byte fixed after cutover.

**V3-capable packages point only at the v3 URL.** _(from "Phase 2 publishes wrapped `data_v3.json`")_
Older packages remain on their versioned URLs. V3 runtimes do not require a shape-detection migration path for v1 or v2 auto-update responses because their default updater requests the contract they implement.

**Registry and provider activation is atomic.** _(from "Phase 2 makes unit definitions update atomically with provider prices", "Phase 2 publishes wrapped `data_v3.json`")_
A runtime first constructs a side-effect-free candidate containing both the fetched registry and parsed providers. Standard package entry points obtain registry and providers from one process-global state object. Activation is one state-reference replacement after preparation succeeds; parse, validation, rejected-promise, or stale-update failure performs no replacement and therefore preserves both previous values.

**Remote v3 activation validates the complete candidate before the swap.** _(from "Registry and provider activation is atomic", "Every response at the v3 URL remains consumable by every released v3 package")_
The wrapper and every nested unit/provider field are decoded from untrusted input with unknown fields, missing fields, and invalid value shapes rejected. Unit public-key safety, unique identities, family normalization, interval closure, and join-closedness are validated before providers are parsed against that candidate. Every provider price key, required ancestor and join price, and extractor destination is then validated before activation. Bundled Phase 1 registry construction may trust generated data; remote v3 construction may not.

**Concurrent update ordering is last-invocation-wins.** _(from "Registry and provider activation is atomic")_
Every accepted update attempt receives a monotonically increasing process-local generation before asynchronous work begins, including attempts supplied as synchronous data, promises, manual Python fetches, background Python fetches, `null`, stop, or custom-snapshot changes. A candidate may commit only while its generation is still current. A later accepted invocation therefore supersedes an earlier pending attempt even when the later attempt performs no data replacement or fails. A Python `fetch()` rejected synchronously because that `UpdatePrices` instance is already stopping never enters the update pipeline, receives no generation, and is the explicit exception.

**The active v3 registry remains process-global and provider snapshots remain provider-only.** _(from "Registry and provider activation is atomic")_
Pricing, usage, extraction, and validation consult the one active registry. `DataSnapshot` does not embed a second registry, and custom provider snapshot activation does not independently change unit definitions.

**Detached base pricing APIs capture one active registry per call.** _(from "The active v3 registry remains process-global and provider snapshots remain provider-only", "V3 units are append-only by usage key")_
This is an explicit compatibility exception to the paired-provider read in "Registry and provider activation is atomic": direct `DataSnapshot.calc(...)`, `ModelInfo.calc_price(...)`, and base `ModelPrice.calc_price(...)` calls use the provider/model object supplied by the caller and capture the active registry once at call entry. This is safe because v3 unit evolution preserves every existing unit relationship. Each standalone `Usage` construction, read, assignment, equality, addition, or representation operation likewise captures one active registry and does not observe a mid-operation replacement. An arbitrary overridden `ModelPrice.calc_price(...)` retains its unchanged signature and owns its internal behavior; Phase 2 does not guarantee one captured registry across registry lookups that custom override code initiates itself.

**Stopping Python's v3 updater restores bundled providers without rolling the registry back.** _(from "V3 units are append-only by usage key", "Concurrent update ordering is last-invocation-wins", "The active v3 registry remains process-global and provider snapshots remain provider-only")_
`UpdatePrices.stop()` conditionally replaces fetched providers with the snapshot generated with the installed package while retaining the latest active registry. The append-only registry is a compatible superset for bundled providers and remains available to detached `Usage`, `DataSnapshot`, and model-price objects that contain fetched units. Stop uses the generation assigned when invoked, so a later custom-snapshot or update invocation wins rather than being overwritten when the worker finishes. Process restart restores the fully bundled provider/registry pair. JavaScript's storage-factory API has no package-owned stop lifecycle: `null` continues to mean a failed update that leaves state untouched, and a wrapped update or explicit provider-array update is the only state-change input.

**V3 publication compares against the deployed v3 contract.** _(from "V3 units are append-only by usage key", "The v3 wrapper and unit-definition shapes are frozen", "The v3 provider structure is frozen")_
For every candidate PR after the initial v3 publication, the required compatibility check reads `prices/data_v3.json` and `prices/data_v3.schema.json` from the exact target `main` Git object ID. It compares every old unit definition, requires the schema bytes to remain identical, and validates the candidate payload against that deployed schema. Missing current data, an invalid current wrapper, a schema change, a removed or changed unit, or a new ancestor of an old unit fails the check. The initial publication compares candidate units with the final Phase 1 bundled registry and records the v3 schema at cutover. Runtime packages need no history database because this compatibility check belongs to the publisher.

**V3 publication is conditional on the compared Git object.** _(from "Every response at the v3 URL remains consumable by every released v3 package", "V3 publication compares against the deployed v3 contract")_
`main` branch protection requires the v3 compatibility check in strict up-to-date mode. The check records the target `main` object ID it compared; GitHub may merge the candidate only while that object ID is still the PR base, and the Git ref update is the atomic compare-and-swap. A concurrent `main` update makes the check stale and requires updating the branch and comparing again, so the raw-GitHub artifact served from `main` cannot be replaced after a stale comparison.

**Generated and fetched v3 outputs remain pure data.**
Payloads and generated modules contain raw units, providers, and raw prices only. Validation markers, trust flags, fingerprints, cache records, and decomposition plans remain runtime concerns rather than serialized contract fields.

**Phase 2 does not include validation or decomposition caching.**
Registry replacement may later motivate cache identities and invalidation, but those optimizations require fresh benchmarks and a separate decision. They are not part of enabling atomic unit updates.

**Tests prove version isolation and atomic activation.** _(from "Existing v1 and v2 update contracts remain stable", "Phase 2 publishes a frozen slim projection of final v2", "Remote v3 activation validates the complete candidate before the swap", "V3 publication is conditional on the compared Git object")_
Coverage verifies frozen v1/v2 artifacts, the slim v2 projection and schema, wrapped v3 schemas, publisher rejection of removed or changed units, conditional-publication conflicts, matching unit/provider activation, no state change after unit, provider, extractor, promise, or stale-update failure, consistent detached calls and `Usage` operations during replacement, Python restoration of bundled providers while fetched units and detached objects remain usable, use of newly fetched units in both runtimes, and absence of runtime cache state in serialized outputs.
