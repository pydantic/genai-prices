# Phase 2: Auto-Updating Unit Definitions

**This prose spec is the complete Phase 2 source of truth.**
The existing [code spec](code-spec.md) predates the completed Phase 1 implementation and the Go package. It must be
rewritten from this document before implementation; where the two disagree, this document wins.

**Phase 2 ships as an independent change on top of the completed Phase 1 release.**
Phase 1 remains a supported static-registry release without any Phase 2 code or artifact.

**The Phase 2 product outcome is that a published unit and every provider field that depends on it become usable without another package release.**
The registry and provider data travel together and become one calculation snapshot, so a newly published price key or
extractor destination is never interpreted against an unrelated registry.

**Python, JavaScript, and Go all support the Phase 2 v3 contract.** _(from "The Phase 2 product outcome")_
Context: Phase 1 originally covered Python and JavaScript; the repository now also generates and releases a native Go
package whose `Calculator` already owns an immutable provider/registry pair. Phase 2 includes all three maintained
runtimes, with language-appropriate lifecycle behavior rather than leaving Go on the static v2 feed.

**Phase 2 preserves the shared registry and pricing semantics.** _(from "Phase 2 ships as an independent change", "The Phase 2 product outcome")_
The [root specification](../spec.md) remains authoritative for unit identities, normalization, dimension relationships,
explicit-only usage, price coverage, decomposition, runtime tolerance of unknown names, and generated-output purity.
Phase 2 changes publication and runtime lifecycle boundaries, not calculation semantics.

**Existing behavior we preserve is the default compatibility boundary.**
Phase 2 changes an existing public data lifecycle, so behavior not required for paired unit/provider updates remains as
it is in the completed Phase 1 code.

**Bundled calculation remains network-independent.** _(from "Existing behavior we preserve")_
Every released package contains one generated provider set and its matching registry. Python and JavaScript use that
pair until an update is activated; each Go `Calculator` constructed from bundled data owns that pair permanently.

**Existing calculation and custom-data APIs keep their recognizable callable shapes.** _(from "Existing behavior we preserve")_
Python retains `calc_price(...)`, `DataSnapshot`, `UpdatePrices.fetch()`, and `set_custom_snapshot(...)`; JavaScript
retains `calcPrice(...)`, `updatePrices(...)`, its storage-factory callback, and provider-array inputs; Go retains
`Calculate(...)`, `NewCalculator()`, and `NewCalculatorFromJSON(...)`. Phase 2 may widen accepted update payload types
and add private state needed to bind a registry, but it does not require callers to adopt a replacement API.

**Legacy provider-array inputs remain provider-only updates.** _(from "Existing calculation and custom-data APIs")_
Python and JavaScript continue accepting v2-shaped provider arrays from custom URLs, storage adapters, and tests. Such
an array is decoded against the currently active registry and never replaces that registry. Go
`NewCalculatorFromJSON(...)` continues accepting a v2 provider array and pairs it with the registry bundled in that Go
release.

**The existing v1 artifacts remain byte-frozen.** _(from "Existing behavior we preserve")_
The four root `prices/data*` payload and schema files remain the digest-pinned compatibility snapshots already enforced
by `tests/test_frozen_v1_data.py`. Phase 2 neither regenerates nor redefines them.

**The v2 URLs, array roots, and unit vocabulary remain compatible with every Phase 1 package.** _(from "Existing behavior we preserve")_
`prices/new_data/v2/data.json` and `data_slim.json` remain provider arrays, their schemas remain the existing frozen v2
schemas, and no later build places a new price key or extractor destination in either payload.

**Behavior we change is limited to versioned publication and paired runtime state.**
Phase 2 introduces the smallest new data contract and runtime lifecycle needed to deliver its product outcome.

**Phase 2 publishes one full wrapped v3 payload.** _(from "Behavior we change", "The Phase 2 product outcome")_
`prices/new_data/v3/data.json` is an object with exactly `units` and `providers`. `units` is keyed by usage key and
`providers` is the full provider array. The colocated `prices/new_data/v3/data.schema.json` describes that wire
contract. A v3 slim variant is not required for automatic unit updates.

**V3 unit definitions use the existing minimal runtime projection.** _(from "Phase 2 publishes one full wrapped v3 payload", "Phase 2 preserves the shared registry and pricing semantics")_
Each unit contains exactly a positive integer `per`, an optional `price_key` that defaults to its usage key, and a
non-empty string-to-string `dimensions` mapping containing `family`. Source-only fields such as
`dimension_requirements` remain in `prices/units.yml` and do not become wire or installed-runtime fields.

**The v3 provider member keeps the full v2 provider wire shape at cutover.** _(from "Phase 2 publishes one full wrapped v3 payload", "Existing calculation and custom-data APIs")_
Provider/model entries and values may continue changing within that shape. Price maps and extractor destinations remain
dynamically keyed and are resolved against the units beside them. A new structural provider field or value shape that
an already released v3 decoder cannot safely consume requires a new versioned contract rather than silently widening
v3.

**Every later response at the v3 URL remains consumable by every released v3 package.** _(from "V3 unit definitions use the existing minimal runtime projection", "The v3 provider member keeps the full v2 provider wire shape")_
The initial v3 schema is the permanent compatibility oracle: later v3 payloads validate against it, and the published
schema file does not change. Provider and model records may be added, removed, or updated within the frozen shape, while
unit evolution follows the stricter append-only rules below.

**V3 units are append-only by usage key.** _(from "Every later response at the v3 URL remains consumable")_
A publication may add a complete unit, but it may not remove an existing unit or change that unit's resolved
`price_key`, `per`, or complete `dimensions` mapping. A new unit's dimensions may not be a proper subset of an existing
unit's dimensions, so it cannot become a new ancestor or intermediate node that changes validation or decomposition
for an old price set. Existing ancestor and join relationships therefore remain stable.

**The initial v3 publication is compatible with the final Phase 1 registry, and later publications are compatible with the deployed v3 registry.** _(from "V3 units are append-only by usage key")_
The publisher compares the initial candidate with the recorded final v2 unit projection. On later pull requests it
reads `prices/new_data/v3/data.json` and `data.schema.json` from the exact target-branch Git object being proposed for
replacement. It rejects an invalid or missing baseline, a changed old unit, a removed unit, a new ancestor of an old
unit, a changed schema, or a candidate payload that does not validate against the deployed schema.

**A stale compatibility comparison cannot authorize publication.** _(from "The initial v3 publication is compatible with the final Phase 1 registry")_
The required CI result is tied to the candidate and target-branch revisions it compared. If the target branch advances,
the branch must be updated and the comparison rerun before merge. This prevents two individually compatible candidates
from bypassing cross-release checks when combined sequentially on `main`.

**Source-level structural validation remains a publisher responsibility.** _(from "V3 unit definitions use the existing minimal runtime projection", "The initial v3 publication is compatible with the final Phase 1 registry")_
The build validates the complete `prices/units.yml` representation, including public-name safety, identity and family
normalization, conditional-dimension rules, exact interval closure, join-closedness, provider price coverage, and
extractor destinations before writing v3. This remains the authoritative check because conditional source metadata is
deliberately absent from the wire projection.

**Runtime validation is strict about the v3 data that can affect calculation.** _(from "Source-level structural validation remains a publisher responsibility", "The Phase 2 product outcome")_
A runtime prepares a side-effect-free candidate before activation. It rejects an invalid wrapper or unit shape,
non-positive normalization, unsafe or duplicate public identities, duplicate dimension sets, inconsistent family
normalization, or a missing compatible join. It decodes providers using the runtime's existing v2 wire rules, resolves
their dynamic keys against the candidate registry, and requires recognized prices to have complete ancestor and join
coverage before the candidate can become active. Runtime interval-closure validation is intentionally not required:
the minimal wire form omits the conditional-dimension metadata needed to distinguish invalid intermediate dimension
sets, while publisher validation still enforces the full rule.

**Unknown provider price keys and extractor destinations retain the shared runtime-tolerance behavior.** _(from "Runtime validation is strict about the v3 data that can affect calculation", "Phase 2 preserves the shared registry and pricing semantics")_
They produce deterministic warnings and are omitted from standard calculation or extraction. Invalid values and
incomplete ancestor or join coverage among recognized units remain errors. This tolerance protects custom or
mismatched inputs; an official v3 payload is still required to use only its accompanying registry.

**The v3 cutover turns both v2 variants into exact compatibility snapshots.** _(from "The v2 URLs, array roots, and unit vocabulary remain compatible", "Phase 2 publishes one full wrapped v3 payload")_
At cutover, Phase 2 records and pins the bytes of the full and slim v2 payload/schema pairs and removes all four from
normal build output. The final slim payload must be the existing exact slim projection of the final full v2 provider
data. This deliberately ends price updates for Phase 1 packages instead of maintaining a permanent lossy projection
that would silently discard post-v2 units; v3-capable packages become the live feed.

**Package generation consumes the v3 wrapper and keeps generated concerns separated in all three runtimes.** _(from "Python, JavaScript, and Go all support the Phase 2 v3 contract", "Phase 2 publishes one full wrapped v3 payload")_
The build validates one source registry/provider pair, writes the v3 wrapper, and then feeds its two members separately
to Python, JavaScript, and Go generation. Python `data.py` and JavaScript `data.ts` still contain providers while their
unit modules contain units. Go still embeds provider JSON and generates its unit definitions/constants. No generated
package file embeds updater state or validation machinery.

**V3-capable remote entry points use only the v3 URL by default.** _(from "Package generation consumes the v3 wrapper", "Legacy provider-array inputs remain provider-only updates")_
Python's default updater URL, JavaScript's exported remote-data URL, and Go's `RemoteDataURL` point to
`prices/new_data/v3/data.json`. They do not shape-detect data fetched from v1 or v2 at that URL. Explicit custom inputs
may still use the legacy provider-array path described above.

**An activated Python or JavaScript state always pairs one registry with one provider set.** _(from "The Phase 2 product outcome", "Runtime validation is strict about the v3 data that can affect calculation")_
Candidate preparation performs no global writes. After decoding and validation succeeds, activation replaces one
process-global state reference. Failure at any earlier step leaves the complete previous pair active. Top-level
pricing, matching, and extraction operations capture that reference once rather than independently reading provider
and registry globals.

**Python `UpdatePrices.fetch()` remains parse-and-return rather than becoming a hidden activation API.** _(from "Existing calculation and custom-data APIs", "An activated Python or JavaScript state always pairs one registry")_
Context: completed Phase 1 tests and integration usage call `fetch()`, inspect the returned `DataSnapshot`, and decide
separately whether to pass it to `set_custom_snapshot(...)`. Phase 2 preserves that behavior. A snapshot decoded from a
v3 wrapper privately retains its candidate registry so its own calculation and extraction methods use the matching
pair and later activation can install both atomically. A snapshot decoded from a provider array uses the active
registry. The public `DataSnapshot` constructor and provider-facing fields remain compatible.

**Python background and custom activation use the snapshot's registry association when present.** _(from "Python `UpdatePrices.fetch()` remains parse-and-return", "An activated Python or JavaScript state always pairs one registry")_
The single supported background `UpdatePrices` instance fetches a candidate and installs it through the same atomic
path as `set_custom_snapshot(...)`. A user-created provider-only snapshot changes providers while retaining the active
registry. Clearing a custom snapshot restores bundled providers while retaining the latest active append-only registry,
which remains compatible with bundled and detached old provider objects.

**Stopping Python's updater preserves its existing ownership boundary.** _(from "Python background and custom activation use the snapshot's registry association", "V3 units are append-only by usage key")_
`UpdatePrices.stop()` signals and joins its worker before restoring bundled providers, so an in-flight worker cannot
reinstall fetched data afterward. It does not roll the registry back. Phase 2 serializes state replacement but does not
add a process-wide generation protocol or promise new ordering semantics among unrelated manual custom-snapshot writes.

**JavaScript extends its existing storage-factory update path to wrapped v3 data.** _(from "Existing calculation and custom-data APIs", "An activated Python or JavaScript state always pairs one registry")_
`setProviderData` accepts a v3 wrapper, a legacy provider array, `null`, or a promise of those values. A wrapper prepares
and conditionally installs a new pair; an array replaces providers against the active registry; `null`, rejection, and
invalid data leave the pair untouched. The existing promise-identity rule continues to prevent an older pending
non-null update from overwriting a newer non-null update, and `waitForUpdate()` continues representing the active update
attempt.

**Go represents atomicity with immutable `Calculator` construction rather than mutable global state.** _(from "Python, JavaScript, and Go all support the Phase 2 v3 contract", "The Phase 2 product outcome")_
`NewCalculatorFromJSON(...)` accepts either a wrapped v3 payload or a legacy provider array. A wrapper is fully decoded
and validated before returning a `Calculator` that owns its registry/provider pair; an array uses bundled units. Failure
returns no candidate and cannot affect an existing calculator. New remote usage names remain expressible through the
existing open `UsageKey` string type even when the installed package has no generated constant for them.

**Detached operations capture one applicable registry per call.** _(from "V3 units are append-only by usage key", "An activated Python or JavaScript state always pairs one registry")_
Python `DataSnapshot` methods use their associated registry when present; other detached base pricing and standalone
`Usage` operations capture the active registry once at entry. JavaScript helpers likewise receive or capture one
registry for an operation. Existing objects remain safe against a later registry replacement because append-only
evolution cannot change their old unit relationships. Custom Python `ModelPrice.calc_price(...)` overrides keep their
existing signature and remain responsible for any registry lookups they initiate themselves.

**Generated and fetched v3 outputs remain pure data.** _(from "Phase 2 preserves the shared registry and pricing semantics", "Package generation consumes the v3 wrapper")_
The v3 payload and generated package files contain only runtime-semantic units, providers, and prices. Trust markers,
schema fingerprints, generations, locks, prepared validation results, and decomposition plans stay out of serialized
contracts.

**Tests prove version isolation, language parity, and failure atomicity.** _(from "The existing v1 artifacts remain byte-frozen", "The v3 cutover turns both v2 variants into exact compatibility snapshots", "Runtime validation is strict about the v3 data that can affect calculation", "An activated Python or JavaScript state always pairs one registry", "Go represents atomicity with immutable `Calculator` construction")_
Coverage pins v1 and final v2 artifacts; verifies the final slim v2 projection; validates the v3 schema and append-only
publisher comparison; exercises a new unit absent from bundled data in Python, JavaScript, and Go; preserves legacy
provider-array inputs; proves Python `fetch()` has no activation side effect; proves JavaScript stale promises cannot
replace a newer update; proves invalid wrappers, units, providers, coverage, and rejected updates retain the prior
Python/JavaScript pair or fail Go construction; verifies each operation sees one matching state; and asserts that
serialized outputs contain no runtime state or source-only validation metadata.

**Scope exclusions remain explicit.**
Phase 2 does not expose arbitrary caller-defined registry mutation, add a v3 slim payload, add validation or
decomposition caches, persist fetched registry state across process restarts, or change the shared pricing algorithm.
