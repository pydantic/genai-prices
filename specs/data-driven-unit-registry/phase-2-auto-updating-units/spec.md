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
Context: the repository now generates and releases all three packages. Phase 2 gives each one a language-appropriate
way to consume the same paired unit/provider payload rather than leaving Go on the static v2 feed.

**Phase 2 preserves the shared registry and pricing semantics.** _(from "Phase 2 ships as an independent change", "The Phase 2 product outcome")_
The [root specification](../spec.md) remains authoritative for unit identities, normalization, dimension relationships,
explicit-only usage, price coverage, decomposition, runtime tolerance of unknown names, and generated-output purity.
Phase 2 changes publication and runtime lifecycle boundaries, not calculation semantics.

**Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements.**
This avoids treating incidental implementation details as an undocumented contract.

**Bundled calculation remains network-independent.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
Every released package contains one generated provider set and its matching registry. Python and JavaScript use that
pair until an update is activated; each Go `Calculator` constructed from bundled data owns that pair permanently.

**Python `UpdatePrices.fetch()` remains a side-effect-free parse-and-return operation.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
It keeps returning `DataSnapshot | None` and does not change the process-global provider or registry state. Callers may
inspect and use the returned snapshot before deciding whether to pass it to `set_custom_snapshot(...)`.

**Python custom-snapshot activation remains explicit.** _(from "Python `UpdatePrices.fetch()` remains a side-effect-free parse-and-return operation")_
`set_custom_snapshot(snapshot)` remains the operation that activates a manually fetched or caller-created snapshot, and
`set_custom_snapshot(None)` remains the operation that returns standard entry points to bundled providers. The public
`DataSnapshot(providers, from_auto_update)` constructor and its provider-facing fields remain compatible.

**Python's background updater remains a single process-global owner.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
At most one background `UpdatePrices` instance may be active. `start()`, `wait()`, and `stop()` retain their current
roles; stopping joins the worker and returns standard entry points to bundled providers.

**JavaScript keeps its storage-factory API.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
`updatePrices(factory)` still supplies `onCalc`, `remoteDataUrl`, and `setProviderData`; `calcPrice(...)` and
`waitForUpdate()` retain their public roles. `setProviderData` continues accepting provider arrays, `null`, and promises,
and Phase 2 widens that same callback rather than adding a replacement updater API.

**JavaScript retains its current non-null update ordering.** _(from "JavaScript keeps its storage-factory API")_
A later non-null `setProviderData(...)` invocation supersedes an older pending promise by replacing the promise identity
checked before commit. `null` means no update and does not supersede a pending attempt. A current rejected promise leaves
provider data unchanged, remains observable through `waitForUpdate()`, and is also warned for fire-and-forget callers.

**Go keeps its immutable-calculator API.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
`Calculate(...)`, `NewCalculator()`, and `NewCalculatorFromJSON(...)` retain their names, parameters, and result shapes.
`NewCalculatorFromJSON(...)` continues accepting a v2 provider array and returns a new independent `Calculator` without
changing any existing calculator or package-global state.

**Legacy provider-array inputs remain provider-only inputs.** _(from "Python custom-snapshot activation remains explicit", "JavaScript keeps its storage-factory API", "Go keeps its immutable-calculator API")_
Python and JavaScript decode a v2-shaped provider array against the active registry without replacing that registry. Go
pairs a v2-shaped provider array with the registry bundled in that Go release. The provider structures and conditional
price forms accepted on this path are exactly those described by the final v2 full-data schema.

**The existing v1 artifacts remain byte-frozen.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
The four root `prices/data*` payload and schema files remain the digest-pinned compatibility snapshots enforced by
`tests/test_frozen_v1_data.py`. This records the completed implementation and intentionally supersedes earlier root and
Phase 1 prose that allowed byte-changing compatible maintenance.

**The v2 URLs, array roots, schemas, and unit vocabulary remain compatible with every Phase 1 package.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
`prices/new_data/v2/data.json` and `data_slim.json` remain provider arrays, both schemas remain byte-for-byte unchanged,
and no later build places a new price key or extractor destination in either payload.

**Behavior we change is limited to versioned publication and paired runtime state.**
Phase 2 introduces the smallest new data contract and runtime lifecycle needed to deliver its product outcome.

**Phase 2 publishes one full wrapped v3 payload.** _(from "Behavior we change", "The Phase 2 product outcome")_
`prices/new_data/v3/data.json` is an object with exactly `units` and `providers`. `units` is keyed by usage key and
`providers` is the full provider array. The colocated `prices/new_data/v3/data.schema.json` describes that wire
contract.

**V3 unit definitions use the existing minimal runtime projection.** _(from "Phase 2 publishes one full wrapped v3 payload", "Phase 2 preserves the shared registry and pricing semantics")_
Each unit contains exactly `per`, an optional `price_key` that defaults to its usage key, and a non-empty
string-to-string `dimensions` mapping containing `family`. Source-only fields such as `dimension_requirements` remain in
`prices/units.yml` and do not become wire or installed-runtime fields.

**V3 normalization factors fit every runtime exactly.** _(from "V3 unit definitions use the existing minimal runtime projection", "Python, JavaScript, and Go all support the Phase 2 v3 contract")_
`per` is an integer in the inclusive range 1 through 9,007,199,254,740,991, JavaScript's maximum safe integer and the
largest integer the Go runtime's current `float64` normalization can represent exactly. The v3 schema, publisher, and
all runtime decoders enforce the same bound.

**The v3 provider member keeps the final full-v2 provider wire shape.** _(from "Phase 2 publishes one full wrapped v3 payload", "Legacy provider-array inputs remain provider-only inputs")_
Provider/model entries and values may continue changing within that shape. Price maps and extractor destinations remain
dynamically keyed strings resolved against the units beside them. A new structural provider field or value shape that
an already released v3 decoder cannot safely consume requires a new versioned contract.

**Every later response at the v3 URL remains consumable by every released v3 package.** _(from "V3 unit definitions use the existing minimal runtime projection", "The v3 provider member keeps the final full-v2 provider wire shape")_
The initial v3 schema is the permanent compatibility oracle: later v3 payloads validate against it, and the published
schema file does not change. Provider and model records may be added, removed, or updated within that frozen shape,
while unit evolution follows the stricter append-only rules below.

**V3 units are append-only by usage key.** _(from "Every later response at the v3 URL remains consumable by every released v3 package")_
A publication may add a complete unit, but it may not remove an existing unit or change that unit's resolved
`price_key`, `per`, or complete `dimensions` mapping. A new unit's dimensions may not be a proper subset of an existing
unit's dimensions, so it cannot become a new ancestor or intermediate node that changes validation or decomposition
for an old price set. Existing ancestor and join relationships therefore remain stable.

**Every wrapped-v3 runtime candidate must be append-only relative to the registry it could replace.** _(from "V3 units are append-only by usage key")_
Python and JavaScript compare a candidate with the active registry both when preparing it and immediately before an
atomic activation, so state that advanced between those steps cannot be rolled back or redefined. Go compares a wrapped
candidate with its bundled registry before constructing a calculator. A legacy provider array carries no registry and
is exempt because it cannot change unit definitions.

**The bootstrap compatibility baseline is the exact target-branch source registry.** _(from "V3 units are append-only by usage key")_
For the initial v3 pull request, CI reads `prices/units.yml` from the exact target-branch Git object, validates it, and
derives its minimal runtime projection without consulting the candidate working tree. The candidate must be append-only
compatible with that projection. The check records the full target object ID, and the merged initial v3 payload becomes
the durable runtime baseline for later publications.

**Later compatibility checks use both deployed v3 data and the target-branch unit source.** _(from "The bootstrap compatibility baseline is the exact target-branch source registry")_
Later pull requests read `prices/new_data/v3/data.json`, `data.schema.json`, and `prices/units.yml` from the exact target
Git object. They reject an invalid or missing baseline, a removed or changed runtime unit, a new ancestor of an old unit,
a prohibited source-rule change, a changed schema, or candidate data that does not validate against the deployed schema.

**A stale compatibility comparison cannot authorize publication.** _(from "Later compatibility checks use both deployed v3 data and the target-branch unit source")_
The required CI result is tied to the candidate and target revisions it compared. If the target branch advances, the
branch must be updated and the comparison rerun before merge. Two candidates therefore cannot independently pass
against one base and then bypass cross-release checks when merged sequentially.

**Conditional-dimension rules remain monotone source-only implications.** _(from "V3 unit definitions use the existing minimal runtime projection", "Phase 2 preserves the shared registry and pricing semantics")_
A conditional rule may only say that the presence of one dimension key requires fixed companion key/value assignments,
and every concrete source unit containing the trigger must contain those assignments. The union of two conflict-free
valid units therefore remains conditionally valid: whichever unit contributes the trigger also contributes its required
companions. Join compatibility among concrete wire units is consequently derivable without shipping the source rule.
Changing this implication model requires a new wire contract.

**Conditional rules attached to an existing v3 unit cannot change.** _(from "Conditional-dimension rules remain monotone source-only implications", "Later compatibility checks use both deployed v3 data and the target-branch unit source")_
The normalized `dimension_requirements` mapping in `prices/units.yml` is part of publisher compatibility for each old
usage key even though it is not serialized in v3. A new unit may introduce a rule that follows the same monotone model.

**Source-level structural validation remains the authoritative publication boundary.** _(from "Conditional-dimension rules remain monotone source-only implications", "Later compatibility checks use both deployed v3 data and the target-branch unit source")_
The build validates public-name safety, identity and family normalization, conditional rules, exact interval closure,
join-closedness, provider price coverage, and extractor destinations on the complete `prices/units.yml` and provider
source before writing v3.

**Candidate preparation performs no state change.** _(from "The Phase 2 product outcome")_
Each runtime decodes and validates a complete registry/provider candidate before any global replacement or Go
constructor return. A failure at any preparation step leaves Python and JavaScript state untouched and returns no Go
calculator.

**Runtime unit validation enforces every invariant derivable from the v3 projection.** _(from "Candidate preparation performs no state change", "Conditional-dimension rules remain monotone source-only implications")_
It rejects an invalid wrapper or unit shape, an out-of-range normalization, unsafe public keys, duplicate price or
dimension identities, a missing `family`, inconsistent family normalization, or a missing join for two conflict-free
units. Usage-key uniqueness follows from the closed `units` object after duplicate JSON member names are rejected by
the v3 decoder.

**Exact interval-closure validation remains publisher-only.** _(from "V3 unit definitions use the existing minimal runtime projection", "Source-level structural validation remains the authoritative publication boundary")_
The runtime projection omits the conditional metadata needed to decide whether every dimension set between an ancestor
and descendant is valid. Runtimes therefore do not claim to repeat that source check; accepting custom wrapped data is
not a supported way to bypass the publication contract or define arbitrary unit semantics.

**Runtime provider validation uses the frozen v3 provider schema and candidate registry.** _(from "Candidate preparation performs no state change", "The v3 provider member keeps the final full-v2 provider wire shape")_
The wrapper's provider member is decoded with the structural and value shapes frozen in the initial v3 schema. Dynamic
price keys and extractor destinations are resolved against the candidate registry, and recognized model prices must
have complete ancestor and join coverage before a wrapped candidate can activate or a Go calculator can be returned.

**Unknown provider price keys and extractor destinations retain the shared runtime-tolerance behavior.** _(from "Runtime provider validation uses the frozen v3 provider schema and candidate registry", "Phase 2 preserves the shared registry and pricing semantics")_
They produce deterministic warnings and are omitted from standard calculation or extraction. Invalid values and
incomplete ancestor or join coverage among recognized units remain errors. Official v3 publication remains stricter
and may not emit names absent from the accompanying registry.

**The v3 cutover turns both v2 variants into exact compatibility snapshots.** _(from "The v2 URLs, array roots, schemas, and unit vocabulary remain compatible with every Phase 1 package", "Phase 2 publishes one full wrapped v3 payload")_
At cutover, Phase 2 records and pins the bytes of the full and slim v2 payload/schema pairs and removes all four from
normal build output. The final slim payload excludes free models; omits provider `pricing_urls`, `description`, and
`price_comments`; omits model `name`, `description`, and `price_comments`; and otherwise exactly projects the final full
v2 provider data. This deliberately ends Phase 1 price updates instead of maintaining a lossy post-v2 unit filter.

**Package generation consumes the v3 wrapper and keeps generated concerns separated in all three runtimes.** _(from "Python, JavaScript, and Go all support the Phase 2 v3 contract", "Phase 2 publishes one full wrapped v3 payload")_
The build feeds the wrapper's members separately to Python, JavaScript, and Go generation. Python `data.py` and
JavaScript `data.ts` still contain providers while their unit modules contain units. Go still embeds provider JSON and
generates unit definitions and constants. Generated package files contain no updater or validation state.

**V3-capable remote entry points use the v3 URL by default.** _(from "Package generation consumes the v3 wrapper and keeps generated concerns separated in all three runtimes", "Legacy provider-array inputs remain provider-only inputs")_
Python's default updater URL, JavaScript's exported remote-data URL, and Go's `RemoteDataURL` point to
`prices/new_data/v3/data.json`. They do not shape-detect v1 or v2 data fetched from that URL; explicit custom inputs may
still use the legacy provider-array path.

**Python and JavaScript each activate one paired runtime-state reference.** _(from "Candidate preparation performs no state change", "The Phase 2 product outcome")_
After preparation and the final append-only comparison succeed, activation replaces one process-global reference that
contains the candidate registry and provider set. Top-level pricing, matching, and extraction capture that reference
once rather than independently reading provider and registry globals.

**A Python snapshot decoded from v3 privately retains its candidate registry.** _(from "Python `UpdatePrices.fetch()` remains a side-effect-free parse-and-return operation", "The Phase 2 product outcome")_
Its own calculation and extraction methods use that registry, so the detached snapshot is internally paired before
global activation. The association is private and does not change the public `DataSnapshot` constructor or
provider-facing fields. A provider-array snapshot has no replacement registry and uses the active one.

**Python background activation installs the fetched pair atomically.** _(from "Python's background updater remains a single process-global owner", "A Python snapshot decoded from v3 privately retains its candidate registry", "Python and JavaScript each activate one paired runtime-state reference")_
The updater's existing worker calls the same activation path as `set_custom_snapshot(...)` after `fetch()` returns; it
does not make `fetch()` itself stateful.

**A caller-created Python provider snapshot retains the active registry.** _(from "Python custom-snapshot activation remains explicit", "Python and JavaScript each activate one paired runtime-state reference")_
Only a validated wrapped-v3 snapshot may propose a registry replacement. Activating a snapshot constructed directly
from providers replaces providers against the current registry.

**Clearing a Python snapshot restores bundled providers without rolling the registry back.** _(from "A caller-created Python provider snapshot retains the active registry", "V3 units are append-only by usage key")_
The latest active registry is a compatible superset for bundled providers and remains available to detached objects that
use fetched units. A process restart restores the fully bundled provider/registry pair.

**Stopping Python's updater cannot reinstall an in-flight fetched pair.** _(from "Python's background updater remains a single process-global owner", "Clearing a Python snapshot restores bundled providers without rolling the registry back")_
`stop()` signals and joins the worker before restoring bundled providers. State replacements are serialized, but Phase 2
does not add a process-wide generation protocol or new ordering promises among unrelated manual snapshot writes.

**JavaScript widens `setProviderData` to wrapped-v3 values.** _(from "JavaScript keeps its storage-factory API", "Python and JavaScript each activate one paired runtime-state reference")_
The accepted value becomes a wrapped v3 payload, a legacy provider array, `null`, or a promise of those. A wrapper can
replace the pair after complete validation; an array replaces providers against the active registry.

**Invalid JavaScript updates never partially replace state.** _(from "JavaScript widens `setProviderData` to wrapped-v3 values", "Candidate preparation performs no state change")_
`null`, rejection, invalid wrapper or provider structure, invalid units, failed append-only comparison, and incomplete
recognized price coverage leave the complete previous pair active.

**JavaScript applies its existing promise ordering to whole pairs.** _(from "JavaScript retains its current non-null update ordering", "JavaScript widens `setProviderData` to wrapped-v3 values")_
An older pending non-null update cannot replace a newer non-null provider or pair update. `waitForUpdate()` continues to
represent the current update attempt and resolves to its active provider set rather than exposing a second registry API.

**Go represents v3 atomicity with immutable calculator construction.** _(from "Go keeps its immutable-calculator API", "Candidate preparation performs no state change", "The Phase 2 product outcome")_
`NewCalculatorFromJSON(...)` additionally accepts a wrapped v3 payload and returns a `Calculator` owning that validated
registry/provider pair. New remote usage names remain expressible through the existing open `UsageKey` string type even
when the installed package has no generated constant for them.

**Detached operations capture one applicable registry per call.** _(from "V3 units are append-only by usage key", "Python and JavaScript each activate one paired runtime-state reference")_
Python `DataSnapshot` methods use their associated registry when present; other detached base pricing and standalone
`Usage` operations capture the active registry once at entry. JavaScript helpers likewise receive or capture one
registry for an operation. Custom Python `ModelPrice.calc_price(...)` overrides keep their existing signature and remain
responsible for registry lookups they initiate themselves.

**Serialized v3 and generated package data remain pure.** _(from "Phase 2 preserves the shared registry and pricing semantics", "Package generation consumes the v3 wrapper and keeps generated concerns separated in all three runtimes")_
They contain runtime-semantic units, providers, and prices only. Trust markers, schema fingerprints, generations, locks,
prepared validation results, and decomposition plans stay out of serialized contracts.

**Publication tests prove version isolation and source compatibility.** _(from "The existing v1 artifacts remain byte-frozen", "The v3 cutover turns both v2 variants into exact compatibility snapshots", "Later compatibility checks use both deployed v3 data and the target-branch unit source", "A stale compatibility comparison cannot authorize publication")_
They pin v1 and final v2 artifacts, verify the final slim projection, validate candidate v3 data against the frozen
schema, and reject old-unit or conditional-rule changes, removals, new ancestors, invalid source structure, and stale
target comparisons.

**Runtime tests prove failure atomicity and preserved lifecycle behavior.** _(from "Candidate preparation performs no state change", "Python and JavaScript each activate one paired runtime-state reference", "Go represents v3 atomicity with immutable calculator construction")_
They cover legacy provider arrays, side-effect-free Python `fetch()`, Python stop and clearing behavior, JavaScript null,
rejection and stale-promise behavior, append-only activation checks, invalid wrapper/unit/provider data, incomplete
recognized price coverage, one-state-per-operation capture, and failed Go construction without an externally visible
partial candidate.

**Parity tests prove a remotely added unit works in every maintained runtime.** _(from "Python, JavaScript, and Go all support the Phase 2 v3 contract", "Runtime provider validation uses the frozen v3 provider schema and candidate registry")_
One integration fixture adds a unit absent from bundled data plus provider prices and extraction mappings that use it.
Python, JavaScript, and Go must extract and price it consistently, including use through Go's open `UsageKey` type.

**Arbitrary caller-defined registry semantics remain excluded.**
Wrapped custom inputs must obey the frozen v3 contract and append-only rules; runtime acceptance does not replace the
publisher-only validation required for supported unit definitions.

**A v3 slim payload remains excluded.**
Phase 2 publishes the one full payload used by automatic updates. A smaller v3 projection requires separate product and
compatibility requirements.

**Validation caches, decomposition caches, and persisted fetched state remain excluded.**
Phase 2 keeps runtime state limited to the active pair and existing provider lookup caches. Process restart uses bundled
data, and performance or persistence mechanisms require separate specifications.
