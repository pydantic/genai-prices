# Phase 2: Auto-Updating Unit Definitions

**This prose spec is the complete Phase 2 source of truth.**
No code-level document may introduce Phase 2 behavior or expand its scope.

**The existing Phase 2 code spec must be rewritten before implementation.** _(from "This prose spec is the complete Phase 2 source of truth")_
Context: [code-spec.md](code-spec.md) predates the completed Phase 1 implementation and the Go package, so it is
supporting research rather than current implementation guidance.

**Phase 2 ships as an independent change on top of the completed Phase 1 release.**
Phase 1 remains a supported static-registry release without any Phase 2 code or artifact.

**A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them.**
A new price key or extractor destination becomes usable without another package release, and no wrapped update is
activated against an unrelated registry.

**Python, JavaScript, and Go each consume the wrapped v3 contract.**
Context: the build now generates and releases all three packages. Each runtime uses its existing lifecycle model:
mutable process state in Python and JavaScript, and immutable `Calculator` construction in Go.

**Phase 2 does not change pricing semantics.**
A unit is identified by usage key, resolved price key, normalization factor, and dimensions including `family`.
Dimension-subset relationships define ancestors; conflict-free dimension unions that satisfy the conditional rule below
define joins. Selected prices must include the ancestors and joins required by their priced units. Only priced units
become exclusive buckets, and each bucket costs `usage * price / normalization`. Missing usage is never inferred when a
positive related report makes the value ambiguous. Unknown runtime names warn and are omitted, while invalid recognized
values, incomplete recognized prices, and contradictory recognized usage remain errors.

**Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements.**
Incidental implementation details are not an undocumented compatibility contract.

**Bundled calculation remains network-independent.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
Every release contains generated providers and matching units. Python and JavaScript use that pair until activation;
each Go calculator constructed from bundled data owns the pair permanently.

**Python `UpdatePrices.fetch()` remains side-effect-free.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
It returns `DataSnapshot | None`, raises on download or decode failure, and never changes process-global providers or
units. Callers decide separately whether to activate the returned snapshot with `set_custom_snapshot(...)`.

**The public Python `DataSnapshot` construction surface remains stable.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
`DataSnapshot(providers, from_auto_update)` remains valid, and instances retain public `providers`,
`from_auto_update`, and `timestamp` values plus the existing lookup, calculation, and extraction methods.

**Python custom-snapshot activation remains explicit.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
`set_custom_snapshot(snapshot)` activates a caller-selected snapshot. `set_custom_snapshot(None)` returns standard entry
points to bundled providers.

**Python's background updater remains singular.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
At most one background `UpdatePrices` instance is active. `start()` starts its worker, `wait()` reports or raises the
current attempt's outcome, and `stop()` joins the worker and restores bundled providers.

**JavaScript keeps one storage-factory update API.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
`updatePrices(factory)` supplies `onCalc`, `remoteDataUrl`, and `setProviderData`; `calcPrice(...)` remains the standard
calculation entry point; and `waitForUpdate()` returns the promise representing the current non-null update attempt.

**JavaScript keeps its current non-null update ordering.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
A later non-null `setProviderData(...)` invocation supersedes an older pending promise. `null` means no update and does
not supersede a pending attempt. A rejected current promise leaves data unchanged, rejects `waitForUpdate()`, and warns
fire-and-forget callers.

**Go keeps immutable calculator construction.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
`Calculate(...)`, `NewCalculator()`, and `NewCalculatorFromJSON(...)` retain their names and result shapes.
`NewCalculatorFromJSON(...)` returns a new independent calculator or `nil` plus an error; it never changes an existing
calculator or package-global state.

**Every data-ingestion API shape-detects wrapped v3 objects and legacy provider arrays.**
Python `fetch()`, JavaScript `setProviderData`, and Go `NewCalculatorFromJSON` accept either form regardless of URL or
caller provenance. A provider array is decoded with the v2 provider contract and uses independently selected units: the
active registry in Python and JavaScript, and bundled units in Go.

**Provider-only inputs are an explicit exception to wrapped-pair activation.** _(from "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them", "Every data-ingestion API shape-detects wrapped v3 objects and legacy provider arrays")_
They cannot introduce a unit definition and therefore never replace a registry. Their selected registry must still
validate recognized price keys and extractor destinations when those providers are used.

**The v2 provider contract is pinned at the Phase 2 cutover.**
The authoritative legacy-array shape is `prices/new_data/v2/data.schema.json` from the exact target-branch Git object
used by the initial v3 compatibility check. Implementations decode every structural field and value form admitted by
that schema; conditional price constraints normalize to the existing internal representations of start-date and
time-of-day constraints.

**The existing v1 artifacts remain byte-frozen.**
The four root `prices/data*` payload and schema files remain the digest-pinned snapshots enforced by
`tests/test_frozen_v1_data.py` and receive no later provider, model, price, or schema update.

**The v2 URLs, array roots, schemas, and unit vocabulary remain compatible with every Phase 1 package.**
`prices/new_data/v2/data.json` and `data_slim.json` remain provider arrays, their two schemas remain byte-for-byte
unchanged, and neither payload receives a new price key or extractor destination.

**Behavior we change is limited to versioned publication and paired runtime state.**
Phase 2 introduces the smallest new contract and lifecycle needed for wrapped unit/provider updates.

**Phase 2 publishes one full wrapped v3 payload.** _(from "Behavior we change is limited to versioned publication and paired runtime state", "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them")_
`prices/new_data/v3/data.json` has exactly two members: a usage-keyed `units` object and a `providers` array. The colocated
`prices/new_data/v3/data.schema.json` describes the complete wire shape.

**V3 unit definitions use the minimal runtime projection.**
Each unit contains exactly `per`, optional `price_key`, and `dimensions`. Omitted `price_key` means the usage key.
`dimensions` is a non-empty string-to-string object containing `family`. Source-only conditional metadata is not
serialized.

**V3 normalization factors fit every runtime exactly.** _(from "V3 unit definitions use the minimal runtime projection", "Python, JavaScript, and Go each consume the wrapped v3 contract")_
`per` is an integer from 1 through 9,007,199,254,740,991 inclusive. This is the largest bound below which every integer
is exactly representable by JavaScript and the Go runtime's `float64` normalization. The schema, publisher, and all
decoders enforce the same range.

**The v3 provider member uses the cutover v2 provider contract.**
It supports every provider field and value form in the v2 schema pinned above. Price maps and extractor destinations
remain dynamically keyed strings resolved against the adjacent units. A new structural provider field or value shape
requires a new versioned contract.

**The initial v3 schema is permanent.**
Later v3 payloads validate against the cutover `data.schema.json`, and that schema file remains byte-for-byte unchanged.
Provider and model entries and their admitted values may change within the frozen shape.

**An existing v3 unit's runtime definition never changes.** _(from "The initial v3 schema is permanent")_
A later publication cannot remove an existing usage key or change its resolved `price_key`, `per`, or complete
`dimensions` mapping.

**A new v3 unit never becomes an ancestor or intermediate of an existing unit.** _(from "Phase 2 does not change pricing semantics")_
Its dimensions cannot be a proper subset of an existing unit's dimensions. Ancestor and join relationships among old
units therefore remain stable when new descendants, intersections, or families are appended.

**Conditional validity uses monotone source-only implications.**
A rule may only say that the presence of one dimension key requires fixed companion key/value assignments. Every source
unit containing the trigger contains those assignments. The union of two conflict-free valid units is consequently
valid: the unit contributing the trigger also contributes its required companions. Changing this implication model
requires a new wire contract.

**An existing v3 unit's normalized conditional implications never change.** _(from "Conditional validity uses monotone source-only implications")_
The source representation may evolve, but publication reduces it to trigger-to-required-assignment semantics and
compares that normalized meaning for each old usage key.

**A mistaken published unit or conditional implication requires a new contract.** _(from "An existing v3 unit's runtime definition never changes", "An existing v3 unit's normalized conditional implications never change")_
V3 cannot correct or remove an erroneous `price_key`, `per`, dimension assignment, or conditional implication without
changing the meaning already released packages attach to the stable URL.

**Every wrapped runtime candidate is append-only relative to its compatibility registry.** _(from "An existing v3 unit's runtime definition never changes", "A new v3 unit never becomes an ancestor or intermediate of an existing unit")_
Python and JavaScript compare with the active registry during preparation and immediately before activation. Go compares
with bundled units before constructing a calculator. A candidate that removes, redefines, or inserts an ancestor of a
known unit is rejected. Legacy provider arrays are exempt because they carry no units.

**Source-level validation remains the publication authority.** _(from "Phase 2 does not change pricing semantics", "Conditional validity uses monotone source-only implications")_
Before writing v3, the build validates unit key safety, identity uniqueness, family normalization, conditional
implications, exact interval closure, join-closedness, provider price coverage, and extractor destinations against the
complete `prices/units.yml` and provider source.

**Generated Go unit identifiers are collision-free.** _(from "Python, JavaScript, and Go each consume the wrapped v3 contract", "Source-level validation remains the publication authority")_
The publisher applies the same `Usage`-prefixed identifier transformation as `package_go_data`: underscore-separated
parts are title-cased, digit-leading parts are uppercased, and empty parts become `_`. It rejects an invalid Go
identifier, a Go keyword, or any collision between distinct usage keys and existing or candidate generated identifiers.
Remote-only names remain usable through the open string type `UsageKey` before a package release generates a constant.

**The bootstrap check compares both runtime units and conditional implications from the exact target revision.** _(from "Every wrapped runtime candidate is append-only relative to its compatibility registry", "An existing v3 unit's normalized conditional implications never change")_
For the initial v3 pull request, CI reads and validates `prices/units.yml` with `git show` from the pull request's exact
target-branch object. It derives both the minimal runtime projection and normalized conditional implications without
consulting candidate files, then compares both with the candidate source and records the full target object ID.

**Later checks compare deployed v3 data and source semantics from the exact target revision.** _(from "The bootstrap check compares both runtime units and conditional implications from the exact target revision")_
They read `prices/new_data/v3/data.json`, `data.schema.json`, and `prices/units.yml` from the target object. Missing or
invalid baselines, forbidden unit or implication changes, new ancestors, changed schema bytes, and candidate data that
fails the deployed schema all fail publication.

**Merge-time policy enforces a fresh compatibility result.** _(from "Later checks compare deployed v3 data and source semantics from the exact target revision")_
The v3 compatibility job is a required check and `main` uses either strict up-to-date branch protection or a merge queue
that reruns it against the merge candidate. A green result for an older target revision cannot authorize merge after
`main` advances.

**Candidate preparation has no externally visible state change.**
A runtime constructs and validates the complete candidate before activation or Go constructor return. Any failure leaves
the Python or JavaScript pair unchanged and returns no Go calculator.

**Runtime unit validation enforces every invariant available in the v3 projection.** _(from "Candidate preparation has no externally visible state change", "Conditional validity uses monotone source-only implications")_
It rejects an invalid wrapper or unit shape, unsafe public keys, out-of-range normalization, duplicate price or dimension
identities, missing `family`, inconsistent family normalization, and missing joins for conflict-free units. JavaScript
validates the object it receives after host JSON parsing; it does not claim to recover duplicate member names already
discarded by that parser.

**Arbitrary caller-defined unit semantics are unsupported.**
Custom wrapped inputs must satisfy the frozen v3 shape and append-only checks, but runtime acceptance is not a substitute
for source-only interval and conditional validation. Supported new unit semantics enter through this repository's
publisher.

**Exact interval-closure validation remains publisher-only.** _(from "V3 unit definitions use the minimal runtime projection", "Arbitrary caller-defined unit semantics are unsupported")_
The wire projection omits the conditional implications needed to decide which intermediate dimension sets are valid, so
runtimes do not claim to repeat that source check.

**Runtime provider validation uses the frozen v3 provider contract and candidate registry.** _(from "Candidate preparation has no externally visible state change")_
Dynamic price keys and extractor destinations are resolved against the candidate. Every recognized model price in a
wrapped candidate has complete ancestor and join coverage before activation or Go constructor return.

**Unknown provider names retain runtime tolerance.** _(from "Phase 2 does not change pricing semantics", "Runtime provider validation uses the frozen v3 provider contract and candidate registry")_
Unsupported price keys and extractor destinations produce deterministic warnings and are omitted from standard
calculation or extraction. Official v3 publication may not emit a name absent from its adjacent registry.

**Python failures remain exceptions.**
Download, wrapper, unit, provider, coverage, and append-only failures make `UpdatePrices.fetch()` raise. A background
failure is stored and raised by the next `wait()` or `stop()` according to the existing single-consumption behavior.
Activation rechecks append-only compatibility and raises `ValueError` without changing state if the active registry
advanced incompatibly after fetch.

**Synchronous JavaScript validation failures throw synchronously.**
A non-promise invalid wrapper, unit set, provider set, coverage relation, or append-only comparison throws from
`setProviderData(...)` and leaves the active pair and current update promise unchanged.

**Asynchronous JavaScript validation failures reject the update promise.**
A rejected input promise or invalid resolved candidate rejects `waitForUpdate()`, emits the existing fire-and-forget
warning, and leaves the active pair unchanged. `null` performs no validation and no state change.

**Go validation failures wrap `ErrInvalidData`.**
`NewCalculatorFromJSON(...)` returns `nil` and an error satisfying `errors.Is(err, ErrInvalidData)` for an invalid
wrapper, units, providers, coverage, or append-only relation.

**The v3 cutover freezes the four v2 artifacts.**
Phase 2 records and pins the exact bytes of the full and slim v2 payload/schema pairs from the same target revision used
by bootstrap compatibility. This deliberately ends Phase 1 price updates rather than maintaining a lossy post-v2 unit
filter.

**The final slim v2 payload remains an exact projection.** _(from "The v3 cutover freezes the four v2 artifacts")_
It excludes free models; omits provider `pricing_urls`, `description`, and `price_comments`; omits model `name`,
`description`, and `price_comments`; and otherwise equals the frozen full v2 provider data.

**Normal builds stop writing v2 after cutover.** _(from "The v3 cutover freezes the four v2 artifacts")_
Build and package generation read the v3 wrapper and never regenerate any v1 or v2 artifact.

**Package generation splits the v3 pair for all three runtimes.** _(from "Python, JavaScript, and Go each consume the wrapped v3 contract", "Phase 2 publishes one full wrapped v3 payload")_
Python `data.py` and JavaScript `data.ts` contain providers while their unit modules contain units. Go embeds provider
JSON and generates unit definitions and constants. The outputs contain no updater or validation state.

**The default remote URL is v3 in every runtime.**
Python's default updater URL, JavaScript's `remoteDataUrl`, and Go's `RemoteDataURL` all point to
`prices/new_data/v3/data.json`. The common ingestion APIs still shape-detect a legacy array if a caller or endpoint
provides one.

**Python and JavaScript activate one paired state reference.** _(from "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them", "Candidate preparation has no externally visible state change")_
After final validation, activation replaces one process-global reference containing registry and providers. Standard
pricing, matching, and extraction capture that reference once per operation.

**A fetched Python v3 snapshot privately owns its candidate registry.** _(from "Python `UpdatePrices.fetch()` remains side-effect-free", "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them")_
Its calculation and extraction methods use that registry before activation. The association does not add a public
constructor parameter or field. A provider-array snapshot has no replacement registry and uses the active one.

**Python background activation installs the fetched pair after `fetch()` returns.** _(from "Python's background updater remains singular", "A fetched Python v3 snapshot privately owns its candidate registry", "Python and JavaScript activate one paired state reference")_
The worker uses the same activation operation as `set_custom_snapshot(...)`; `fetch()` itself remains side-effect-free.

**A caller-constructed Python snapshot changes providers only.** _(from "Python custom-snapshot activation remains explicit", "Provider-only inputs are an explicit exception to wrapped-pair activation")_
Activating a `DataSnapshot` without a validated wrapped registry retains the active registry.

**Clearing Python state intentionally keeps the latest registry.** _(from "Provider-only inputs are an explicit exception to wrapped-pair activation", "Every wrapped runtime candidate is append-only relative to its compatibility registry")_
Bundled providers are restored against the active append-only superset so detached objects using fetched units remain
usable. Process restart restores the fully bundled pair.

**Stopping Python cannot reinstall an in-flight fetched pair.** _(from "Python's background updater remains singular", "Clearing Python state intentionally keeps the latest registry")_
`stop()` signals and joins the worker before restoring bundled providers. State replacement is serialized, but Phase 2
adds no process-wide generation protocol or ordering promise among unrelated manual snapshot writes.

**JavaScript widens `setProviderData` with the wrapped shape.** _(from "JavaScript keeps one storage-factory update API")_
The accepted non-null value becomes `Provider[] | { units, providers }`, synchronously or through a promise. A provider
array changes providers only; a wrapped value can replace the pair after complete validation.

**JavaScript's promise ordering applies to complete pairs.** _(from "JavaScript keeps its current non-null update ordering", "JavaScript widens `setProviderData` with the wrapped shape")_
An older pending wrapped or provider-only update cannot overwrite a newer non-null update. `waitForUpdate()` continues
resolving to the active provider array rather than exposing a second registry API.

**Go accepts wrapped v3 through immutable construction.** _(from "Go keeps immutable calculator construction", "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them")_
`NewCalculatorFromJSON(...)` returns a calculator owning the validated wrapper registry and providers. New remote usage
names remain expressible through `UsageKey` even before a package release generates a constant.

**Python detached operations capture one applicable registry.**
`DataSnapshot` methods use their private registry when present. Base `ModelInfo.calc_price(...)`, base
`ModelPrice.calc_price(...)`, and standalone `Usage` operations otherwise capture the active registry once at entry.
Custom `ModelPrice.calc_price(self, usage)` overrides keep that signature and own any registry lookups they initiate.

**JavaScript operations capture one applicable registry.**
Standard entry points pass the registry captured with active providers through matching, extraction, and pricing. Direct
helpers without an explicit registry capture the active registry once at entry.

**Serialized outputs remain pure data.**
V3 and generated package files contain runtime-semantic units, providers, and prices only. Trust markers, schema
fingerprints, generations, locks, prepared validation results, and decomposition plans are not serialized.

**Publication tests prove version isolation.**
They pin v1 and final v2 bytes, verify the slim projection, validate v3 against its frozen schema, and exercise bootstrap,
later-source, stale-target, Go-identifier, old-unit, old-implication, removal, and new-ancestor rejection.

**Runtime tests prove failure atomicity and preserved lifecycle behavior.**
They cover both input shapes; Python fetch, activation, clearing, stop, and exception behavior; JavaScript synchronous,
asynchronous, null, rejection, and stale-promise behavior; Go `ErrInvalidData`; append-only activation; invalid units,
providers, and coverage; and one-state-per-operation capture.

**Parity tests prove remotely added units.**
One fixture adds a unit absent from bundled data plus provider prices and extraction mappings that use it. Python,
JavaScript, and Go extract and price it consistently, including use through Go's open `UsageKey` type.

**A v3 slim payload is excluded.**
Phase 2 publishes the one full payload used by automatic updates. A smaller v3 projection requires separate product and
compatibility requirements.

**Validation caches and decomposition caches are excluded.**
Phase 2 retains only existing provider lookup caches. New pricing caches require a separate specification.

**Fetched registry persistence is excluded.**
Process restart uses bundled data. Persisting and authenticating a fetched registry requires a separate specification.
