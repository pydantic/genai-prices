# Phase 2: Auto-Updating Unit Definitions

**This prose spec is the complete Phase 2 source of truth.**
No code-level document may introduce Phase 2 behavior or expand its scope.

**Code-level architecture is in [code-spec](code-spec.md).** _(from "This prose spec is the complete Phase 2 source of truth")_
The code spec derives file, type, signature, and call-boundary decisions from this document without adding product
behavior.

**Phase 2 ships as an independent change on top of the completed Phase 1 release.**
Phase 2 implementation and publication land independently after the completed Phase 1 work.

**The audited Phase 1 behavioral baseline is Git object `076f45bda74f18b21d7ccd9bbaf9f5c9332ab4fa`.** _(from "Phase 2 ships as an independent change on top of the completed Phase 1 release")_
The compatibility claims in this document refer to the Python, JavaScript, and Go implementations at that object.
Implementation starts by checking the Phase 2 branch's target object against this baseline and updating this prose spec
for any intentional intervening behavior change; an unreviewed implementation drift does not silently become contract.

**The first audited intervening target is Git object `af5190edb9afaf0a810b1e8a26d451f097c44072`.** _(from "The audited Phase 1 behavioral baseline is Git object `076f45bda74f18b21d7ccd9bbaf9f5c9332ab4fa`.")_
Relative to the behavioral baseline, that target contains one intentional change: OpenAI's long-context rates begin at
exactly 272,000 input tokens. Provider data encodes the tier start as 271,999 because all three existing pricing engines
select a tier when usage is greater than its start. Phase 2 preserves this target behavior without changing tier
selection semantics. If the implementation target advances beyond this object, its additional changes require the same
audit before implementation.

**The Phase 2 implementation target is Git object `da0f68d42702505a7bd5fe62152437541191b7ff`.** _(from "The first audited intervening target is Git object `af5190edb9afaf0a810b1e8a26d451f097c44072`.")_
Relative to the first audited intervening target, this target contains one additional intentional runtime behavior
change: xAI `response.done` realtime extraction reads billable fields from the event's top-level `usage` object rather
than the nested `response.usage` object. Phase 2 preserves that provider-specific extraction shape. The other intervening
changes only refine these Phase 2 specifications and do not add another Phase 1 runtime behavior to preserve.

**Changes: Phase 2 is limited to versioned publication and paired runtime state.**
This is the complete change body. Phase 2 introduces the smallest new contract and lifecycle needed for wrapped
unit/provider updates.

---

**Changes — Shared contract and runtime behavior: every client consumes one versioned unit/provider pair.** _(from "Changes: Phase 2 is limited to versioned publication and paired runtime state")_
This subsection defines the wire contract and the invariants shared by the build and all three clients.

**A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them.** _(from "Changes — Shared contract and runtime behavior")_
A new price key or extractor destination becomes usable without another package release, and no wrapped update is
activated against an unrelated registry.

**New v3 features degrade locally on older clients.** _(from "Changes — Shared contract and runtime behavior")_
An older client applies every portion of a newer v3 payload that it understands. An unsupported addition is ignored at
the smallest independently usable boundary rather than causing rejection of the wrapper, provider, or model around it.

**Partial v3 support is explicit.** _(from "New v3 features degrade locally on older clients")_
Ignoring an unsupported addition emits a deterministic upgrade warning through the client's existing warning channel,
with enough member or provider/model context to identify what was skipped and that upgrading the package enables fuller
support.

**Incomplete old-client support does not require a new data version.** _(from "New v3 features degrade locally on older clients")_
V3 may add features that older clients cannot use completely. Those clients continue receiving providers, models, and
prices expressed through constructs they understand; a new endpoint version is reserved for a framing or core-semantic
change that prevents safe use of the understood projection.

**Python, JavaScript, and Go each consume the wrapped v3 contract.** _(from "Changes — Shared contract and runtime behavior")_
Context: the build now generates and releases all three packages. Phase 2 gives each package a wrapped-v3 ingestion path.

**Every data-ingestion API shape-detects wrapped v3 objects and legacy provider arrays.**
Python `fetch()`, JavaScript `setProviderData`, and Go `NewCalculatorFromJSON` accept either form regardless of URL or
caller provenance.

**Provider-only inputs are an explicit exception to wrapped-pair activation.** _(from "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them", "Every data-ingestion API shape-detects wrapped v3 objects and legacy provider arrays")_
They cannot introduce a unit definition and therefore never replace a registry. Their selected registry must still
validate recognized price keys and extractor destinations when those providers are used.

**Provider-only candidates use runtime-selected compatibility registries.** _(from "Provider-only inputs are an explicit exception to wrapped-pair activation")_
Python and JavaScript select the active registry. Go selects bundled units because it has no process-global active
registry and every immutable calculator owns the registry selected at construction.

**The v2 provider contract is pinned at the Phase 2 cutover.**
The authoritative legacy-array shape is `prices/new_data/v2/data.schema.json` from the exact target-branch Git object
used by the initial v3 compatibility check.

**Phase 2 publishes one full wrapped v3 payload.** _(from "Changes: Phase 2 is limited to versioned publication and paired runtime state", "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them")_
`prices/new_data/v3/data.json` has two required core members: a usage-keyed `units` object and a `providers` array. The
colocated `prices/new_data/v3/data.schema.json` describes the current complete wire shape.

**V3 unit definitions use the minimal runtime projection.**
Only data required to construct the runtime registry is published with each unit.

**V3 unit definitions have three stable core members.** _(from "V3 unit definitions use the minimal runtime projection", "New v3 features degrade locally on older clients")_
Each unit contains required `per`, optional `price_key`, and required `dimensions`. Additional members are extensions;
clients that do not understand them ignore them and construct the unit from its understood core.

**An omitted v3 `price_key` resolves to the usage key.** _(from "V3 unit definitions have three stable core members")_
The wire omission and an explicit matching value construct the same runtime price-key identity.

**V3 dimensions are a non-empty string mapping containing `family`.** _(from "V3 unit definitions have three stable core members")_
Every dimension key and value is a string, and every unit declares its family.

**Source-only conditional metadata is omitted from v3 unit definitions.** _(from "V3 unit definitions use the minimal runtime projection")_
Conditional implications remain publisher input rather than runtime wire data.

**V3 normalization factors fit every runtime exactly.** _(from "V3 unit definitions have three stable core members", "Python, JavaScript, and Go each consume the wrapped v3 contract")_
`per` is an integer from 1 through 9,007,199,254,740,991 inclusive: JavaScript's `Number.MAX_SAFE_INTEGER`, the largest
positive integer through which consecutive integer values have unique exact `Number` identities and safe integer
round-tripping. Go converts only values in this range to `float64`. The schema, publisher, and all decoders enforce the
same range.

**The v3 provider member begins with the cutover v2 provider contract and evolves additively.** _(from "The v2 provider contract is pinned at the Phase 2 cutover", "Phase 2 publishes one full wrapped v3 payload", "New v3 features degrade locally on older clients")_
It supports every provider field and value form in the v2 schema pinned above. Price maps and extractor destinations
remain dynamically keyed strings resolved against the adjacent units. Later schemas may add optional members and new
structural variants without removing or redefining the core forms older clients understand.

**Unknown object members are ignorable v3 extensions.** _(from "New v3 features degrade locally on older clients")_
An added field alone never rejects a candidate. Recognized wrapper and unit members are validated during candidate
preparation; recognized provider, model, extractor, match, constraint, and price members retain each runtime's existing
decoding or use-time validation boundary.

**Unsupported structural variants skip only their containing capability.** _(from "New v3 features degrade locally on older clients", "Partial v3 support is explicit")_
For example, an unknown extractor variant skips that extractor while other extractors, models, prices, and providers
remain usable. An unsupported match, constraint, or price variant skips the smallest containing entry that cannot be
interpreted. A new provider or model whose usable parts are entirely unsupported may be omitted without blocking the
rest of the update.

**Behavior-changing extensions must be distinguishable from existing forms.** _(from "Unknown object members are ignorable v3 extensions", "Unsupported structural variants skip only their containing capability")_
An added member may be ignored only when the recognized form remains correct without it. A new extractor, match,
constraint, price, or other variant whose omitted behavior could change a result uses a distinguishable variant shape or
discriminator, allowing an older client to skip that capability instead of misinterpreting it as an existing form.

**The stable v3 core never changes meaning.** _(from "Incomplete old-client support does not require a new data version")_
The required wrapper members and the names, types, defaults, and meanings of existing recognized fields remain stable.
An optional member does not become required, and an existing object or variant does not acquire a new required member.
Removing or redefining that core requires a new endpoint version because older clients could not recover an equivalent
understood projection.

**The v3 schema evolves with the payload.** _(from "The stable v3 core never changes meaning", "New v3 features degrade locally on older clients", "Behavior-changing extensions must be distinguishable from existing forms")_
Each publication regenerates `data.schema.json` for the current complete shape. Compatibility checks permit additive
extensions but reject removal or incompatible redefinition of the stable core.

**Runtime compatibility is capability-based, not schema-version equality.** _(from "The v3 schema evolves with the payload", "Incomplete old-client support does not require a new data version")_
An older v3 client does not reject a payload merely because the current schema contains fields or variants absent from
the schema shipped with that client. Its decoder validates and uses the projection it understands, so compatible model
and price updates continue flowing without a package upgrade.

**An existing v3 unit's runtime definition never changes.**
A later publication cannot remove an existing usage key or change its resolved `price_key`, `per`, or complete
`dimensions` mapping.

**Existing usage-key order is stable and new units append.**
The relative object-member order of every already published usage key remains unchanged, because registry iteration
affects extraction output, warning presentation, and accumulation order. Every newly published key follows all existing
keys; multiple new keys retain their source order. Publisher and wrapped-runtime append-only validation enforce this.

**A new v3 unit never becomes an ancestor or intermediate of an existing unit.**
Its dimensions cannot be a proper subset of an existing unit's dimensions. Ancestor and join relationships among old
units therefore remain stable when new descendants, intersections, or families are appended.

**Conditional rules are monotone source-only implications.**
A rule may only say that the presence of one dimension key requires fixed companion key/value assignments. Negative,
disjunctive, value-dependent-trigger, and removal rules are outside the Phase 2 source model.

**Every source unit conforms to all conditional implications that apply to it.** _(from "Conditional rules are monotone source-only implications")_
For each unit, recursively apply rules whose trigger dimension is present until reaching a fixed point. The unit's
dimensions must already contain every resulting required assignment. Conflicting required values are invalid; a cycle
is valid only when fixed-point expansion adds no conflict.

**Conflict-free valid units remain valid under union.** _(from "Every source unit conforms to all conditional implications that apply to it")_
The unit contributing a trigger also contributes its complete fixed-point companion assignments, so the union of two
conflict-free valid units satisfies the same implications.

**Conditional semantics normalize per usage key.** _(from "Every source unit conforms to all conditional implications that apply to it")_
For each concrete unit, normalization produces a lexicographically sorted set of
`(trigger_dimension_key, required_dimension_key, required_value)` triples for every applicable direct and transitively
implied assignment. This result is independent of YAML mapping order and source-rule factoring.

**An existing v3 unit's normalized conditional implications never change.** _(from "Conditional semantics normalize per usage key")_
The source representation may evolve only when the normalized triple set for every old usage key is identical. Changing
the implication model or an old unit's normalized set requires a new wire contract.

**A mistaken published unit or conditional implication is repaired additively.** _(from "An existing v3 unit's runtime definition never changes", "An existing v3 unit's normalized conditional implications never change", "Incomplete old-client support does not require a new data version")_
V3 does not correct or remove an erroneous `price_key`, `per`, dimension assignment, or conditional implication in
place. It publishes a replacement usage key or other additive representation while leaving the old meaning intact; a
new endpoint version is needed only when no safe additive representation exists.

**Every wrapped runtime candidate is append-only relative to its compatibility registry.** _(from "An existing v3 unit's runtime definition never changes", "Existing usage-key order is stable and new units append", "A new v3 unit never becomes an ancestor or intermediate of an existing unit")_
Python and JavaScript compare with the active registry during preparation and immediately before activation. Go compares
with bundled units before constructing a calculator. A candidate that removes, redefines, reorders, or inserts an
ancestor of a known unit is rejected. Legacy provider arrays are exempt because they carry no units.

**Candidate preparation has no externally visible state change.**
A runtime validates the replacement registry and performs its baseline provider-data preparation before activation or
Go constructor return. Any failure detected at that stage leaves the Python or JavaScript pair unchanged and returns no
Go calculator.

**Runtime unit validation enforces every understood invariant in the v3 projection.** _(from "Unknown object members are ignorable v3 extensions")_
It validates the recognized wrapper and unit core, unsafe public keys, normalization, price and dimension identities,
`family`, family normalization, and joins for conflict-free understood units. Unknown members do not weaken validation
of recognized data.

**Runtime wire validation starts from a decoded JSON value.** _(from "Runtime unit validation enforces every understood invariant in the v3 projection")_
Python and Go decode bytes internally, while JavaScript normally receives an object after caller-owned JSON parsing.
Phase 2 validates the resulting value consistently and does not promise detection of duplicate source-text object member
names that a standard decoder has already collapsed.

**Wrapped provider data retains each runtime's existing validation timing.** _(from "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them", "The v3 provider member begins with the cutover v2 provider contract and evolves additively", "Unsupported structural variants skip only their containing capability")_
Wrapping provider data does not introduce an exhaustive provider scan. Python and JavaScript retain their existing
wire decoding and normalization, while registry membership, ancestor coverage, and join coverage remain deferred until
a selected price is calculated. Python moves extractor-destination checks to extraction; JavaScript retains its current
preparation warning and checks again during extraction. Go retains full validation during immutable calculator
construction.

**Unsupported additions do not make understood provider data invalid.** _(from "Wrapped provider data retains each runtime's existing validation timing", "New v3 features degrade locally on older clients")_
An unsupported extension follows the warning-and-omit path at the client's normal decoding or use boundary. Malformed
recognized data follows that client's existing error timing; an unused invalid model does not gain a new whole-update
failure mode in Python or JavaScript.

**Python and JavaScript activate providers and units through their existing global update boundaries.** _(from "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them", "Candidate preparation has no externally visible state change")_
The Python snapshot setter and JavaScript provider-data setter install the replacement registry and providers during the
same activation call. Existing operations continue reading process-global providers and the process-global registry;
Phase 2 adds no operation-scoped context or provider provenance mechanism.

**Runtime ingestion tests cover both accepted root shapes.** _(from "Every data-ingestion API shape-detects wrapped v3 objects and legacy provider arrays", "The v2 provider contract is pinned at the Phase 2 cutover")_
Each runtime exercises wrapped v3 objects and legacy provider arrays.

**Runtime atomicity tests cover preparation-time failures without state change.** _(from "Candidate preparation has no externally visible state change", "Wrapped provider data retains each runtime's existing validation timing")_
Coverage includes invalid wrappers and units, append-only failures, and the provider structures each runtime already
rejects during preparation. Use-time provider failures remain outside activation atomicity in Python and JavaScript.

**Forward-compatibility tests retain the understood projection.** _(from "New v3 features degrade locally on older clients", "Partial v3 support is explicit", "Unknown object members are ignorable v3 extensions", "Unsupported structural variants skip only their containing capability", "Behavior-changing extensions must be distinguishable from existing forms")_
Each runtime ignores added object members, warns and skips an unsupported extractor or price variant, and still activates
understood providers, models, extractors, units, and prices from the same payload.

**Runtime boundary tests pin decoded-value and integer rules.** _(from "V3 normalization factors fit every runtime exactly.", "Runtime wire validation starts from a decoded JSON value.")_
They accept `per` values 1 and 9,007,199,254,740,991, reject 0, non-integers, and larger integers, and demonstrate that
duplicate source-text members receive no cross-runtime guarantee beyond validation of the post-parse value.

---

**Changes — Build: the build owns v3 publication and compatibility enforcement.** _(from "Changes: Phase 2 is limited to versioned publication and paired runtime state", "Phase 2 publishes one full wrapped v3 payload")_
This subsection defines source validation, compatibility checks, frozen artifacts, publication, and package generation.

**Source-level validation remains the publication authority.** _(from "V3 unit definitions use the minimal runtime projection", "Conditional rules are monotone source-only implications")_
Before writing v3, the build validates unit key safety, identity uniqueness, family normalization, conditional
implications, exact interval closure, join-closedness, provider price coverage, and extractor destinations against the
complete `prices/units.yml` and provider source.

**The bootstrap check compares both runtime units and conditional implications from the exact target revision.** _(from "An existing v3 unit's runtime definition never changes", "Existing usage-key order is stable and new units append", "A new v3 unit never becomes an ancestor or intermediate of an existing unit", "An existing v3 unit's normalized conditional implications never change")_
For the initial v3 pull request, CI reads and validates `prices/units.yml` with `git show` from the pull request's exact
target-branch object, derives both the minimal runtime projection and normalized conditional implications, and compares
both with the candidate source.

**Bootstrap baseline derivation does not consult candidate files.** _(from "The bootstrap check compares both runtime units and conditional implications from the exact target revision")_
Every baseline input is read from the target object rather than the working tree.

**Later checks compare deployed v3 data and source semantics from the exact target revision.** _(from "The bootstrap check compares both runtime units and conditional implications from the exact target revision")_
They read `prices/new_data/v3/data.json`, `data.schema.json`, and `prices/units.yml` from the target object. Missing or
invalid baselines, forbidden unit or implication changes, new ancestors, incompatible stable-core schema changes, and
candidate data that fails the candidate schema all fail publication. Additive schema extensions are allowed.

**Compatibility checks report their full target object ID.** _(from "The bootstrap check compares both runtime units and conditional implications from the exact target revision", "Later checks compare deployed v3 data and source semantics from the exact target revision")_
CI output identifies the exact revision against which the candidate was authorized.

**Every compatibility baseline read uses the reported target object ID.** _(from "Compatibility checks report their full target object ID")_
No baseline component is read from another revision or an unpinned branch name.

**The bootstrap comparison persists no separate baseline artifact.** _(from "The bootstrap check compares both runtime units and conditional implications from the exact target revision", "Later checks compare deployed v3 data and source semantics from the exact target revision")_
After cutover, the deployed v3 files and source semantics become the later-check baseline.

**Merge-time policy enforces a fresh compatibility result.** _(from "Later checks compare deployed v3 data and source semantics from the exact target revision")_
The v3 compatibility job is a required check and `main` uses either strict up-to-date branch protection or a merge queue
that reruns it against the merge candidate. A green result for an older target revision cannot authorize merge after
`main` advances.

**The v3 cutover freezes the four v2 artifacts.**
Phase 2 records and pins the exact bytes of the full and slim v2 payload/schema pairs from the same target revision used
by bootstrap compatibility. This deliberately ends Phase 1 price updates rather than maintaining a lossy post-v2 unit
filter.

**The final slim v2 payload remains an exact projection.** _(from "The v3 cutover freezes the four v2 artifacts")_
It excludes free models; omits provider `pricing_urls`, `description`, and `price_comments`; omits model `name`,
`description`, and `price_comments`; and otherwise equals the frozen full v2 provider data.

**Normal builds stop writing v2 after cutover.** _(from "The v3 cutover freezes the four v2 artifacts")_
Publication writes the v3 contract, package generation reads it, and neither stage regenerates a v1 or v2 artifact.

**The initial `build-prices` cutover writes v3 data and schema.** _(from "Phase 2 publishes one full wrapped v3 payload", "The v3 schema evolves with the payload")_
It validates the authoring sources and bootstrap compatibility, regenerates `prices/providers/.schema.json`, then writes
`prices/new_data/v3/data.json` and the first `data.schema.json`. It also verifies the frozen v2 bytes rather than
deriving or rewriting them.

**Later `build-prices` runs write provider authoring schema, v3 schema, and v3 data.** _(from "The v3 schema evolves with the payload", "Later checks compare deployed v3 data and source semantics from the exact target revision")_
They compare the generated schema's stable core with the exact target revision, validate candidate data against the
generated schema, regenerate `prices/providers/.schema.json`, and replace both v3 `data.schema.json` and `data.json`.

**`package-data` reads and splits the validated v3 wrapper.** _(from "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them", "Phase 2 publishes one full wrapped v3 payload")_
It does not reconstruct the wrapper from separate provider and unit sources and does not write publication artifacts.

**Package generation splits the v3 pair for all three runtimes.** _(from "Python, JavaScript, and Go each consume the wrapped v3 contract", "Phase 2 publishes one full wrapped v3 payload")_
Python `data.py` and JavaScript `data.ts` contain providers while their unit modules contain units. Go embeds provider
JSON and generates unit definitions and constants. The outputs contain no updater or validation state.

**The default remote URL is v3 in every runtime.** _(from "Phase 2 publishes one full wrapped v3 payload")_
Python's default updater URL, JavaScript's `remoteDataUrl`, and Go's `RemoteDataURL` all point to
`prices/new_data/v3/data.json`. The common ingestion APIs still shape-detect a legacy array if a caller or endpoint
provides one.

**V2 cutover tests pin final artifact isolation.** _(from "The v3 cutover freezes the four v2 artifacts", "The final slim v2 payload remains an exact projection", "Normal builds stop writing v2 after cutover")_
They pin the final v2 bytes, verify the slim projection, and prove normal builds do not rewrite those artifacts.

**V3 publication tests pin the wrapper and compatible schema evolution.** _(from "Phase 2 publishes one full wrapped v3 payload", "The v3 schema evolves with the payload", "The stable v3 core never changes meaning")_
They validate generated v3 data against its schema, accept additive extensions, and reject removal or incompatible
redefinition of stable core fields.

**Compatibility tests pin target-bound unit evolution.** _(from "The bootstrap check compares both runtime units and conditional implications from the exact target revision", "Later checks compare deployed v3 data and source semantics from the exact target revision", "Compatibility checks report their full target object ID", "Every compatibility baseline read uses the reported target object ID")_
They exercise bootstrap, later-source, stale-target, target-object reporting, stable unit ordering, old-unit and
old-implication preservation, removal rejection, and new-ancestor rejection.

---

**Changes — Python: wrapped snapshots carry units to the existing activation boundary.** _(from "Python and JavaScript activate providers and units through their existing global update boundaries")_
This subsection defines Python decoding, snapshot ownership, customization, activation, and failure behavior.

**Python decoded-contract failures are `ValueError`.**
Invalid wrapper or unit data, a provider structure rejected by Python's existing decoder, or an append-only failure
raises `ValueError`. Registry membership and coverage checks retain their existing calculation-time behavior.

**Python decoded-contract errors identify the failing data.** _(from "Python decoded-contract failures are `ValueError`")_
The error includes a member path or provider/model context sufficient to locate the invalid input.

**Python activation rechecks only registry evolution.** _(from "Every wrapped runtime candidate is append-only relative to its compatibility registry", "Candidate preparation has no externally visible state change")_
Immediately before installing a fetched wrapped snapshot, `set_custom_snapshot(...)` repeats the append-only registry
comparison. It does not traverse or validate the snapshot's providers.

**A fetched Python v3 snapshot carries its candidate registry only for activation.** _(from "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them", "Python and JavaScript activate providers and units through their existing global update boundaries")_
The association is private activation data, not a snapshot-local calculation context. Before activation, snapshot
pricing and extraction use the process's active registry like every other Python operation. A provider-array snapshot
has no replacement registry.

**A caller-constructed Python snapshot changes providers only.** _(from "Provider-only inputs are an explicit exception to wrapped-pair activation", "A fetched Python v3 snapshot carries its candidate registry only for activation")_
Activating a `DataSnapshot` without a validated wrapped registry retains the active registry.

**Python provider customization remains lazy after fetch.** _(from "A fetched Python v3 snapshot carries its candidate registry only for activation", "Wrapped provider data retains each runtime's existing validation timing")_
The fetched snapshot remains mutable. A caller may add or replace custom prices, models, providers, and extractors before
activation. Activation rechecks only registry evolution and does not rescan the mutable provider graph; custom price and
extractor errors or unsupported names are discovered when the selected price is calculated or extractor is used.

**Background customization continues through `UpdatePrices.fetch()` overrides.** _(from "Python provider customization remains lazy after fetch")_
A subclass may call `super().fetch()`, mutate the returned snapshot, and return that same snapshot. Because the worker
calls the override for every refresh, those custom prices and extractors are reapplied to each download without a new
overlay API. Mutating one fetched snapshot outside that override remains temporary and may be replaced by the next
background refresh.

**Python background activation installs the fetched pair after `fetch()` returns.** _(from "A fetched Python v3 snapshot carries its candidate registry only for activation", "Python and JavaScript activate providers and units through their existing global update boundaries")_
The worker uses the same activation operation as `set_custom_snapshot(...)` after candidate preparation succeeds.

**Clearing Python state restores the complete bundled pair.** _(from "Python and JavaScript activate providers and units through their existing global update boundaries", "A fetched Python v3 snapshot carries its candidate registry only for activation")_
Passing `None` to `set_custom_snapshot(...)` restores bundled providers with bundled units. No fetched registry remains
active after an explicit clear or updater stop.

**Stopping Python cannot reinstall an in-flight fetched pair.** _(from "Python background activation installs the fetched pair after `fetch()` returns.", "Clearing Python state restores the complete bundled pair")_
`stop()` signals and joins the worker before restoring the bundled pair.

**Every Python operation uses the process's active registry.** _(from "Python and JavaScript activate providers and units through their existing global update boundaries", "A fetched Python v3 snapshot carries its candidate registry only for activation")_
`DataSnapshot` methods, bare provider/model methods, base `ModelPrice.calc_price(...)`, and standalone `Usage` operations
continue resolving the process-global registry through the existing registry accessor. No operation consults a
snapshot-local registry.

**Python custom extractors resolve destinations when used.** _(from "Python provider customization remains lazy after fetch", "Every Python operation uses the process's active registry")_
A `UsageExtractor` does not validate or permanently cache supported destinations during construction. Each extraction
checks mappings against the then-active registry, warns with `UserWarning` for unsupported destinations, omits those
mappings, and continues with supported siblings. An extractor added before activation can therefore use the fetched
snapshot's new units after activation.

**Python snapshot tests cover activation-only registry ownership and customization.** _(from "A fetched Python v3 snapshot carries its candidate registry only for activation", "A caller-constructed Python snapshot changes providers only", "Python provider customization remains lazy after fetch", "Background customization continues through `UpdatePrices.fetch()` overrides", "Python custom extractors resolve destinations when used", "Clearing Python state restores the complete bundled pair")_
Coverage includes pre-activation use of the active registry, custom prices and extractors added after fetch, repeated
subclassed background refreshes, activation, caller-constructed snapshots, and complete clearing.

**Python background tests cover paired activation and stopping.** _(from "Python background activation installs the fetched pair after `fetch()` returns.", "Stopping Python cannot reinstall an in-flight fetched pair.")_
Coverage includes worker activation, stop signaling, join ordering, and bundled-provider restoration.

**Python contract-error tests cover decoded and final registry failures.** _(from "Python decoded-contract failures are `ValueError`", "Python decoded-contract errors identify the failing data", "Python activation rechecks only registry evolution")_
They pin `ValueError` context and prove a failed final append-only check leaves active providers and units unchanged.

---

**Changes — JavaScript: provider-data updates activate providers and units together.** _(from "Python and JavaScript activate providers and units through their existing global update boundaries")_
This subsection defines JavaScript decoding, global activation, update ordering, and failure behavior.

**Synchronous JavaScript validation failures throw `Error` synchronously.**
A non-promise invalid wrapper or unit set, provider structure rejected by JavaScript's existing preparation path, or
append-only comparison throws from `setProviderData(...)` and leaves the active pair and current update promise
unchanged. New contract errors use the stable prefix `genai-prices: invalid data:` followed by path or provider/model
context. Selected-price validation retains its existing use-time behavior.

**Asynchronous JavaScript contract failures reject with `Error`.** _(from "Synchronous JavaScript validation failures throw `Error` synchronously.")_
An invalid resolved candidate rejects `waitForUpdate()`, emits the existing fire-and-forget warning, and leaves the
active pair unchanged. Contract validation creates `Error` with the synchronous prefix.

**JavaScript widens `setProviderData` with the wrapped shape.** _(from "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them")_
The accepted non-null value becomes `Provider[] | { units, providers }`, synchronously or through a promise. A provider
array changes providers only; a wrapped value can replace the pair after registry validation and baseline provider
preparation.

**JavaScript's promise ordering applies to complete pairs.** _(from "JavaScript widens `setProviderData` with the wrapped shape", "Python and JavaScript activate providers and units through their existing global update boundaries")_
An older pending wrapped or provider-only update cannot overwrite a newer non-null update.

**JavaScript operations use the process's active registry.** _(from "Python and JavaScript activate providers and units through their existing global update boundaries", "JavaScript widens `setProviderData` with the wrapped shape")_
Standard pricing and extraction continue resolving the process-global registry through the existing accessor. A
provider returned earlier or supplied directly has no separate registry provenance.

**JavaScript pair-ordering tests cover non-null attempts.** _(from "JavaScript's promise ordering applies to complete pairs")_
Coverage includes synchronous and promised candidates plus current and stale non-null attempts.

**JavaScript contract-validation tests cover error timing.** _(from "Synchronous JavaScript validation failures throw `Error` synchronously.", "Asynchronous JavaScript contract failures reject with `Error`.")_
They distinguish invalid direct candidates from invalid promised candidates and pin the contract-error prefix.

---

**Changes — Go: wrapped JSON constructs a new immutable calculator.** _(from "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them", "Python, JavaScript, and Go each consume the wrapped v3 contract")_
This subsection defines Go's open generated surface, immutable construction, caller-managed replacement, and failures.

**Generated Go unit identifiers must remain safe and unique.**
Publication rejects an invalid Go identifier, a Go keyword, or any collision between distinct usage keys or with an
existing Go package-level identifier.

**Go's open `UsageKey` type represents remote-only names.** _(from "Python, JavaScript, and Go each consume the wrapped v3 contract")_
A remotely added usage key remains usable as `UsageKey("name")` before a later package release generates its constant.

**Go validation failures wrap `ErrInvalidData`.**
`NewCalculatorFromJSON(...)` returns `nil` and an error satisfying `errors.Is(err, ErrInvalidData)` for an invalid
wrapper, units, providers, coverage, or append-only relation.

**Go accepts wrapped v3 through immutable construction.** _(from "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them", "Python, JavaScript, and Go each consume the wrapped v3 contract")_
`NewCalculatorFromJSON(...)` returns a calculator owning the validated wrapper registry and providers.

**Caller-managed Go updates replace the calculator only after construction succeeds.** _(from "Go accepts wrapped v3 through immutable construction", "Candidate preparation has no externally visible state change")_
A caller that automatically fetches `RemoteDataURL` constructs a new calculator, then replaces its own calculator
reference only after validation and construction complete.

**Go identifier validation tests cover generated-name safety.** _(from "Generated Go unit identifiers must remain safe and unique")_
They reject invalid identifiers, Go keywords, and collisions with generated or existing package-level names.

**Go wrapped-construction tests cover remote-only units.** _(from "Go accepts wrapped v3 through immutable construction", "Go's open `UsageKey` type represents remote-only names")_
They construct a calculator that extracts and prices a valid unit absent from bundled data.

**Go construction-failure tests cover caller-owned atomicity.** _(from "Caller-managed Go updates replace the calculator only after construction succeeds.", "Go validation failures wrap `ErrInvalidData`.")_
They pin `ErrInvalidData`, a `nil` failed result, and retention of the caller's prior calculator reference.

**Parity tests prove remotely added units.** _(from "Python, JavaScript, and Go each consume the wrapped v3 contract", "Go's open `UsageKey` type represents remote-only names.")_
One fixture adds a unit absent from bundled data plus provider prices and extraction mappings that use it. Python,
JavaScript, and Go extract and price it consistently, including use through Go's open `UsageKey` type.

---

**Scope exclusions: Phase 2 stops at the runtime-update boundary.** _(from "Changes: Phase 2 is limited to versioned publication and paired runtime state")_
The following exclusions keep unrelated persistence, customization, and optimization work out of this change.

**Arbitrary caller-defined unit semantics are unsupported.** _(from "Scope exclusions: Phase 2 stops at the runtime-update boundary")_
Custom wrapped inputs must satisfy the frozen v3 shape and append-only checks, but runtime acceptance is not a substitute
for source-only interval and conditional validation. Supported new unit semantics enter through this repository's
publisher.

**Exact interval-closure validation remains publisher-only.** _(from "V3 unit definitions use the minimal runtime projection", "Arbitrary caller-defined unit semantics are unsupported")_
The wire projection omits the conditional implications needed to decide which intermediate dimension sets are valid, so
runtimes do not claim to repeat that source check.

**Serialized outputs remain pure data.** _(from "Scope exclusions: Phase 2 stops at the runtime-update boundary")_
V3 and generated package files contain runtime-semantic units, providers, and prices only. Trust markers, schema
fingerprints, generations, locks, prepared validation results, and decomposition plans are not serialized.

**Concurrent mutable-client operations gain no new consistency guarantee.** _(from "Scope exclusions: Phase 2 stops at the runtime-update boundary")_
Phase 2 adds no locks, generations, operation-scoped registry context, provider provenance, or ordering promise among
concurrent Python or JavaScript reads and writes. Sequential activation remains the supported update model.

**A persistent custom-provider overlay is excluded.** _(from "Scope exclusions: Phase 2 stops at the runtime-update boundary", "Background customization continues through `UpdatePrices.fetch()` overrides")_
Phase 2 does not add a second provider store or automatically merge one-time custom mutations into later downloads.
Callers that need custom prices or extractors on every Python refresh reapply them in a `fetch()` override.

**Validation caches and decomposition caches are excluded.** _(from "Scope exclusions: Phase 2 stops at the runtime-update boundary")_
Provider/model lookup caches inside a snapshot or calculator remain permitted. New pricing, validation, or decomposition
caches require a separate specification.

**Fetched registry persistence is excluded.** _(from "Scope exclusions: Phase 2 stops at the runtime-update boundary")_
Process restart uses bundled data. Persisting and authenticating a fetched registry requires a separate specification.

---

**Unchanged Phase 1 behavior: only the requirements below are Phase 2 compatibility requirements.**
This final block is the complete preservation contract. Incidental Phase 1 lifecycle and API implementation details are
not undocumented compatibility requirements.

**Phase 1 remains supported without Phase 2.** _(from "Phase 2 ships as an independent change on top of the completed Phase 1 release.")_
The completed static-registry release remains supported without any Phase 2 code or artifact.

**Phase 2 inherits the root registry semantics and terminology.**
Except where this document explicitly changes a decision, the pricing, extraction, matching, validation, and warning
semantics in [the registry specification](../spec.md) remain requirements.

**Phase 2 does not change pricing semantics.** _(from "Phase 2 inherits the root registry semantics and terminology")_
The following nodes are the complete pricing and extraction rules intentionally preserved by this phase.

**Registered units retain their four-part identity.** _(from "Phase 2 does not change pricing semantics")_
A unit is identified by usage key, resolved price key, normalization factor, and dimensions including `family`.

**Dimension-subset relationships continue defining ancestors.** _(from "Phase 2 does not change pricing semantics")_
A unit is an ancestor when its complete dimensions mapping is a subset of another unit's dimensions.

**Conflict-free dimension unions continue defining joins.** _(from "Phase 2 does not change pricing semantics", "Conflict-free valid units remain valid under union")_
A valid union must also satisfy the source conditional implications defined earlier in this spec.

**Selected prices continue requiring ancestor and join coverage.** _(from "Dimension-subset relationships continue defining ancestors", "Conflict-free dimension unions continue defining joins")_
Every priced unit has the ancestors and joins required by its registered relationships.

**Only priced units remain exclusive usage buckets.** _(from "Phase 2 does not change pricing semantics")_
Unpriced registered relationships constrain validation but do not create a separately billed bucket.

**Unit cost remains usage multiplied by price and divided by normalization.** _(from "Registered units retain their four-part identity")_
All flat unit pricing uses `usage * price / normalization`.

**Ambiguous missing usage remains uninferred.** _(from "Dimension-subset relationships continue defining ancestors", "Conflict-free dimension unions continue defining joins")_
A missing value is not inferred when a positive related report makes that value ambiguous.

**Invalid recognized values, prices, and usage relationships remain errors.** _(from "Phase 2 does not change pricing semantics")_
Recognition continues to distinguish invalid supported data from unsupported names that follow the warning path below.

**Bundled calculation remains network-independent.**
Every release contains generated providers and matching units. Python and JavaScript use that pair until activation;
each Go calculator constructed from bundled data owns the pair permanently.

**Each runtime retains its Phase 1 lifecycle model.**
Python and JavaScript continue using mutable process state, while every Go `Calculator` remains immutable after
construction.

**Python `UpdatePrices.fetch()` remains side-effect-free.**
It returns `DataSnapshot | None`, raises on download or decode failure, and never changes process-global providers or
units. Callers decide separately whether to activate the returned snapshot with `set_custom_snapshot(...)`.

**The public Python `DataSnapshot` construction surface remains stable.**
`DataSnapshot(providers, from_auto_update)` remains valid, and instances retain public `providers`,
`from_auto_update`, and `timestamp` values plus the existing lookup, calculation, and extraction methods.

**Python custom-snapshot activation remains explicit.**
`set_custom_snapshot(snapshot)` activates a caller-selected snapshot. `set_custom_snapshot(None)` returns standard entry
points to bundled providers.

**Python's background updater remains singular.**
At most one background `UpdatePrices` instance is active. `start()` starts its worker, `wait()` reports or raises the
current attempt's outcome, and `stop()` joins the worker and restores bundled providers.

**JavaScript keeps one storage-factory update API.**
`updatePrices(factory)` supplies `onCalc`, `remoteDataUrl`, and `setProviderData`; `calcPrice(...)` remains the standard
calculation entry point; and `waitForUpdate()` returns the promise representing the current non-null update attempt.

**JavaScript `waitForUpdate()` remains provider-only.** _(from "JavaScript keeps one storage-factory update API")_
It resolves to the active provider array and exposes no second registry API.

**JavaScript's public extraction entry point remains `extractUsage(...)`.**
It continues to accept an explicit provider object and response data.

**JavaScript keeps its current non-null update ordering.**
A direct `null` is a no-op and does not supersede a pending attempt. Supplying a promise starts an update attempt and
supersedes older pending attempts immediately, even if it later resolves to `null`. A rejected current promise leaves
data unchanged, rejects `waitForUpdate()`, and warns fire-and-forget callers.

**Generated Go unit identifiers retain their deterministic transformation.**
The publisher applies the same `Usage`-prefixed transformation as `package_go_data`: underscore-separated parts are
title-cased, digit-leading parts are uppercased, and empty parts become `_`.

**Go keeps immutable calculator construction.**
`Calculate(PriceRequest) (PriceCalculation, error)`, `NewCalculator() (*Calculator, error)`, and
`NewCalculatorFromJSON([]byte) (*Calculator, error)` remain. JSON construction returns a new independent calculator or
`nil` plus an error; it never changes an existing calculator or package-global state.

**Go keeps both extraction entry points.** _(from "Go keeps immutable calculator construction")_
`ExtractUsage(ExtractRequest)` uses the bundled calculator, while `(*Calculator).ExtractUsage(ExtractRequest)` uses the
receiver's immutable provider/registry pair.

**Python keeps snapshot extraction.** _(from "The public Python `DataSnapshot` construction surface remains stable")_
`DataSnapshot.extract_usage(...)` remains the snapshot-scoped extraction entry point, and the module-level
`extract_usage(...)` continues to use the currently active snapshot.

**Python lookup methods retain their bare return types.** _(from "The public Python `DataSnapshot` construction surface remains stable")_
`DataSnapshot.find_provider(...)` and `find_provider_model(...)` continue returning `Provider` and `ModelInfo` objects;
Phase 2 adds no public provenance wrapper.

**Custom Python `ModelPrice` overrides retain their signature and registry ownership.**
An override of `ModelPrice.calc_price(self, usage)` keeps that signature and owns any registry lookups it initiates.

**Legacy arrays accept every representation admitted by the pinned v2 schema.** _(from "The v2 provider contract is pinned at the Phase 2 cutover", "The audited Phase 1 behavioral baseline is Git object `076f45bda74f18b21d7ccd9bbaf9f5c9332ab4fa`")_
Implementations continue decoding every structural field and value form admitted by that schema.

**Legacy arrays retain semantic validation beyond structural schema checks.** _(from "Legacy arrays accept every representation admitted by the pinned v2 schema")_
The schema is not an exhaustive statement of valid numeric values or cross-field relationships; each runtime continues
applying its baseline semantic checks.

**Legacy price-constraint shapes retain their meanings.** _(from "Legacy arrays accept every representation admitted by the pinned v2 schema")_
A `{start_date}` object remains a start-date constraint, while a `{start_time, end_time}` object remains a time-of-day
constraint.

**Legacy arrays retain each runtime's baseline structural tolerance.** _(from "Legacy arrays accept every representation admitted by the pinned v2 schema")_
Python and JavaScript perform their existing activation-time parsing and normalization, including failure for malformed
recognized structures they consume, but Phase 2 does not add exhaustive schema validation or rejection of extra object
members. Go retains its constructor-time decode and full validation, including its existing tolerance for extra JSON
object members. All three continue decoding every structural and representation form admitted by the pinned v2 schema,
then apply their baseline semantic checks at the times specified below.

**Legacy arrays retain each runtime's baseline provider-validation timing.** _(from "Provider-only inputs are an explicit exception to wrapped-pair activation", "Legacy arrays retain each runtime's baseline structural tolerance")_
Python retains its existing wire-value decoding and JavaScript retains its existing normalization; both defer unknown
price keys and ancestor/join coverage until a selected model price is calculated. Go validates every recognized model
price and coverage relationship in `NewCalculatorFromJSON`; unknown price keys remain tolerated and omitted from
pricing. Python's extractor-destination timing deliberately changes under "Python custom extractors resolve
destinations when used"; JavaScript and Go retain their existing extractor-warning timing.

**Unknown registry names retain baseline tolerance outside wrapped v3 candidates.** _(from "Phase 2 inherits the root registry semantics and terminology", "Legacy arrays retain each runtime's baseline provider-validation timing")_
In legacy arrays, detached providers, and caller usage, unsupported price keys, extractor destinations, and usage keys
produce the baseline deterministic warning or result-warning and are omitted from standard calculation or extraction.

**Python unsupported-name warnings remain `UserWarning` and preserve state.** _(from "Unknown registry names retain baseline tolerance outside wrapped v3 candidates")_
Emitting the deterministic warning does not activate or partially install candidate data.

**Python fetch preserves transport and JSON exceptions.**
Network and HTTP failures remain the corresponding `httpx2` exceptions, and malformed JSON remains
`json.JSONDecodeError`; Phase 2 does not wrap them as data-contract errors.

**Python background failures have one consumer.** _(from "Python's background updater remains singular")_
A background exception is stored, raised by the next `wait()` or `stop()`, and then cleared so the same exception is not
raised twice.

**JavaScript preserves caller-supplied promise rejection reasons.** _(from "JavaScript keeps its current non-null update ordering")_
A rejected input promise rejects `waitForUpdate()` with its original reason, including a non-`Error` reason, emits the
existing fire-and-forget warning, and leaves active state unchanged.

**JavaScript `null` remains a no-op.** _(from "JavaScript keeps its current non-null update ordering")_
Direct or promise-resolved `null` performs no validation and does not replace active data. Direct `null` does not
supersede a pending attempt; a supplied promise supersedes older pending attempts immediately, so a later `null`
resolution does not undo that supersession.

**A stale rejected JavaScript attempt rejects only its own promise.** _(from "JavaScript's promise ordering applies to complete pairs", "JavaScript preserves caller-supplied promise rejection reasons")_
The promise previously returned by `waitForUpdate()` for that attempt rejects with its original reason and emits the
fire-and-forget warning. It does not change active state, replace or reject the current `waitForUpdate()` promise, or
cancel the newer attempt.

**The existing v1 artifacts remain byte-frozen.**
The four root `prices/data*` payload and schema files remain the digest-pinned snapshots enforced by
`tests/test_frozen_v1_data.py` and receive no later provider, model, price, or schema update.

**The v2 URLs, array roots, schemas, and unit vocabulary remain compatible with every Phase 1 package.** _(from "The v3 cutover freezes the four v2 artifacts")_
`prices/new_data/v2/data.json` and `data_slim.json` remain provider arrays, their two schemas remain byte-for-byte
unchanged, and neither payload receives a new price key or extractor destination.

**Go generation tests preserve identifier spelling.** _(from "Generated Go unit identifiers retain their deterministic transformation")_
They pin representative underscores, digit-leading parts, and empty parts against the existing transformation.

**Legacy-array compatibility tests cover preserved v2 behavior.** _(from "Legacy arrays accept every representation admitted by the pinned v2 schema", "Legacy arrays retain semantic validation beyond structural schema checks", "Legacy price-constraint shapes retain their meanings", "Legacy arrays retain each runtime's baseline structural tolerance", "Legacy arrays retain each runtime's baseline provider-validation timing", "Unknown registry names retain baseline tolerance outside wrapped v3 candidates")_
Each runtime covers admitted representations, both constraint shapes, baseline semantic checks, structural tolerance,
validation timing, and unsupported-name behavior.

**Python compatibility tests cover preserved failure behavior.** _(from "Python unsupported-name warnings remain `UserWarning` and preserve state", "Python fetch preserves transport and JSON exceptions", "Python background failures have one consumer")_
They pin warning class and state, transport and malformed-JSON exception identity, and single-consumer background errors.

**JavaScript compatibility tests cover preserved update outcomes.** _(from "JavaScript `waitForUpdate()` remains provider-only", "JavaScript preserves caller-supplied promise rejection reasons", "JavaScript `null` remains a no-op", "A stale rejected JavaScript attempt rejects only its own promise")_
They cover provider-only results, caller rejection identity, direct and promised `null`, and stale rejection isolation.

**Frozen compatibility tests pin v1 and v2 bytes.** _(from "The existing v1 artifacts remain byte-frozen", "The v2 URLs, array roots, schemas, and unit vocabulary remain compatible with every Phase 1 package")_
They fail on any change to the four v1 or four final v2 artifacts.
