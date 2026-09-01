# Phase 2: Auto-Updating Unit Definitions

**This prose spec is the complete Phase 2 source of truth.**
No code-level document may introduce Phase 2 behavior or expand its scope.

**Code-level architecture is in [code-spec](code-spec.md).** _(from "This prose spec is the complete Phase 2 source of truth")_
The code spec derives file, type, signature, and call-boundary decisions from this document without adding product
behavior.

**Phase 2 ships as an independent change on top of the completed Phase 1 release.**
Phase 1 remains a supported static-registry release without any Phase 2 code or artifact.

**Phase 2 inherits the root registry semantics and terminology.**
Except where this document explicitly changes a decision, the pricing, extraction, matching, validation, and warning
semantics in [the registry specification](../spec.md) remain requirements. References below to explicitly named Phase 1
behaviors limit which Phase 1-specific lifecycle and API details are inherited; they do not narrow those shared root
semantics.

**The audited Phase 1 behavioral baseline is Git object `076f45bda74f18b21d7ccd9bbaf9f5c9332ab4fa`.** _(from "Phase 2 ships as an independent change on top of the completed Phase 1 release")_
The compatibility claims in this document refer to the Python, JavaScript, and Go implementations at that object.
Implementation starts by checking the Phase 2 branch's target object against this baseline and updating this prose spec
for any intentional intervening behavior change; an unreviewed implementation drift does not silently become contract.

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
Incidental Phase 1 lifecycle and API implementation details are not an undocumented compatibility contract.

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

**JavaScript's public extraction entry point remains `extractUsage(...)`.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
It continues to accept an explicit provider object and response data. Provider objects obtained through standard active
lookup are interpreted with the registry captured by that lookup operation; caller-supplied detached providers use the
active registry captured when extraction starts.

**JavaScript keeps its current non-null update ordering.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
A direct `null` is a no-op and does not supersede a pending attempt. Supplying a promise starts an update attempt and
supersedes older pending attempts immediately, even if it later resolves to `null`. A rejected current promise leaves
data unchanged, rejects `waitForUpdate()`, and warns fire-and-forget callers.

**Go keeps immutable calculator construction.** _(from "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements")_
`Calculate(PriceRequest) (PriceCalculation, error)`, `NewCalculator() (*Calculator, error)`, and
`NewCalculatorFromJSON([]byte) (*Calculator, error)` remain. JSON construction returns a new independent calculator or
`nil` plus an error; it never changes an existing calculator or package-global state.

**Go keeps both extraction entry points.** _(from "Go keeps immutable calculator construction")_
`ExtractUsage(ExtractRequest)` uses the bundled calculator, while `(*Calculator).ExtractUsage(ExtractRequest)` uses the
receiver's immutable provider/registry pair.

**Python keeps snapshot extraction.** _(from "The public Python `DataSnapshot` construction surface remains stable")_
`DataSnapshot.extract_usage(...)` remains the snapshot-scoped extraction entry point, and the module-level
`extract_usage(...)` continues to use the currently active snapshot.

**Every data-ingestion API shape-detects wrapped v3 objects and legacy provider arrays.**
Python `fetch()`, JavaScript `setProviderData`, and Go `NewCalculatorFromJSON` accept either form regardless of URL or
caller provenance. A provider array is decoded with the v2 provider contract and uses independently selected units: the
active registry in Python and JavaScript, and bundled units in Go. Go has no process-global active registry; each
immutable calculator owns the registry selected when it is constructed.

**Provider-only inputs are an explicit exception to wrapped-pair activation.** _(from "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them", "Every data-ingestion API shape-detects wrapped v3 objects and legacy provider arrays")_
They cannot introduce a unit definition and therefore never replace a registry. Their selected registry must still
validate recognized price keys and extractor destinations when those providers are used.

**The v2 provider contract is pinned at the Phase 2 cutover.**
The authoritative legacy-array shape is `prices/new_data/v2/data.schema.json` from the exact target-branch Git object
used by the initial v3 compatibility check. Implementations decode every structural field and representation form
admitted by that schema, subject to the baseline semantic validation rules below; the schema is not an exhaustive
statement of valid numeric values or cross-field relationships. A `{start_date}` price constraint becomes a start-date
constraint, and a `{start_time, end_time}` price constraint becomes a time-of-day constraint.

**Legacy arrays retain each runtime's baseline structural tolerance.** _(from "The v2 provider contract is pinned at the Phase 2 cutover", "The audited Phase 1 behavioral baseline is Git object `076f45bda74f18b21d7ccd9bbaf9f5c9332ab4fa`")_
Python and JavaScript perform their existing activation-time parsing and normalization, including failure for malformed
recognized structures they consume, but Phase 2 does not add exhaustive schema validation or rejection of extra object
members. Go retains its constructor-time decode and full validation, including its existing tolerance for extra JSON
object members. All three continue decoding every structural and representation form admitted by the pinned v2 schema,
then apply their baseline semantic checks at the times specified below.

**Legacy arrays retain each runtime's baseline registry-validation timing.** _(from "Provider-only inputs are an explicit exception to wrapped-pair activation", "Legacy arrays retain each runtime's baseline structural tolerance")_
Python and JavaScript warn about unsupported extractor destinations while preparing the array, but defer unknown price
keys, invalid price values, and ancestor/join coverage checks until a selected model price is calculated. Go validates
every recognized model price and coverage relationship in `NewCalculatorFromJSON`; unknown price keys remain tolerated
and omitted from pricing, and unsupported extractor destinations remain warnings produced during extraction.

**Wrapped v3 candidates are validated eagerly in every runtime.** _(from "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them", "Legacy arrays retain each runtime's baseline registry-validation timing")_
Before Python or JavaScript activation or a Go constructor return, the entire decoded wrapper, every recognized provider
structure and price value, every registry relationship, all model price coverage, and all extractor destinations are
checked against the candidate registry. An official wrapper cannot contain an unknown registry name.

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
`per` is an integer from 1 through 9,007,199,254,740,991 inclusive: JavaScript's `Number.MAX_SAFE_INTEGER`, the largest
positive integer through which consecutive integer values have unique exact `Number` identities and safe integer
round-tripping. Go converts only values in this range to `float64`. The schema, publisher, and all decoders enforce the
same range.

**The v3 provider member uses the cutover v2 provider contract.** _(from "The v2 provider contract is pinned at the Phase 2 cutover", "Phase 2 publishes one full wrapped v3 payload")_
It supports every provider field and value form in the v2 schema pinned above. Price maps and extractor destinations
remain dynamically keyed strings resolved against the adjacent units. A new structural provider field or value shape
requires a new versioned contract.

**The initial v3 schema is permanent.**
Later v3 payloads validate against the cutover `data.schema.json`, and that schema file remains byte-for-byte unchanged.
Provider and model entries and their admitted values may change within the frozen shape.

**An existing v3 unit's runtime definition never changes.**
A later publication cannot remove an existing usage key or change its resolved `price_key`, `per`, or complete
`dimensions` mapping.

**Existing usage-key order is stable and new units append.** _(from "An existing v3 unit's runtime definition never changes")_
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

**A mistaken published unit or conditional implication requires a new contract.** _(from "An existing v3 unit's runtime definition never changes", "An existing v3 unit's normalized conditional implications never change")_
V3 cannot correct or remove an erroneous `price_key`, `per`, dimension assignment, or conditional implication without
changing the meaning already released packages attach to the stable URL.

**Every wrapped runtime candidate is append-only relative to its compatibility registry.** _(from "An existing v3 unit's runtime definition never changes", "A new v3 unit never becomes an ancestor or intermediate of an existing unit")_
Python and JavaScript compare with the active registry during preparation and immediately before activation. Go compares
with bundled units before constructing a calculator. A candidate that removes, redefines, or inserts an ancestor of a
known unit is rejected. Legacy provider arrays are exempt because they carry no units.

**Source-level validation remains the publication authority.** _(from "Phase 2 does not change pricing semantics", "Conditional rules are monotone source-only implications")_
Before writing v3, the build validates unit key safety, identity uniqueness, family normalization, conditional
implications, exact interval closure, join-closedness, provider price coverage, and extractor destinations against the
complete `prices/units.yml` and provider source.

**Generated Go unit identifiers use the existing deterministic transformation.**
The publisher applies the same `Usage`-prefixed transformation as `package_go_data`: underscore-separated parts are
title-cased, digit-leading parts are uppercased, and empty parts become `_`.

**Generated Go unit identifiers must remain safe and unique.** _(from "Generated Go unit identifiers use the existing deterministic transformation")_
Publication rejects an invalid Go identifier, a Go keyword, or any collision between distinct usage keys or with an
existing Go package-level identifier.

**Go's open `UsageKey` type represents remote-only names.** _(from "Generated Go unit identifiers use the existing deterministic transformation")_
A remotely added usage key remains usable as `UsageKey("name")` before a later package release generates its constant.

**The bootstrap check compares both runtime units and conditional implications from the exact target revision.** _(from "Every wrapped runtime candidate is append-only relative to its compatibility registry", "An existing v3 unit's normalized conditional implications never change")_
For the initial v3 pull request, CI reads and validates `prices/units.yml` with `git show` from the pull request's exact
target-branch object. It derives both the minimal runtime projection and normalized conditional implications without
consulting candidate files, then compares both with the candidate source. The job emits the full target object ID in its
check output and uses that same ID for every baseline `git show`; it need not persist a separate artifact after merge,
because the deployed v3 files become the later baseline.

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

**Runtime unit validation enforces every invariant available in the v3 projection.**
It rejects an invalid wrapper or unit shape, unsafe public keys, out-of-range normalization, duplicate price or dimension
identities, missing `family`, inconsistent family normalization, and missing joins for conflict-free units.

**Runtime wire validation starts from a decoded JSON value.** _(from "Runtime unit validation enforces every invariant available in the v3 projection")_
Python and Go decode bytes internally, while JavaScript normally receives an object after caller-owned JSON parsing.
Phase 2 validates the resulting value consistently and does not promise detection of duplicate source-text object member
names that a standard decoder has already collapsed.

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

**Unknown registry names retain baseline tolerance outside wrapped v3 candidates.** _(from "Phase 2 inherits the root registry semantics and terminology", "Legacy arrays retain each runtime's baseline registry-validation timing")_
In legacy arrays, detached providers, and caller usage, unsupported price keys, extractor destinations, and usage keys
produce the baseline deterministic warning or result-warning and are omitted from standard calculation or extraction.
Wrapped candidates instead reject a provider name absent from their adjacent registry, because such a pair is internally
inconsistent.

**Python fetch preserves transport and JSON exceptions.** _(from "Python `UpdatePrices.fetch()` remains side-effect-free")_
Network and HTTP failures remain the corresponding `httpx2` exceptions, and malformed JSON remains
`json.JSONDecodeError`; Phase 2 does not wrap them as data-contract errors.

**Python decoded-contract failures are `ValueError`.** _(from "Python fetch preserves transport and JSON exceptions", "Candidate preparation has no externally visible state change")_
Invalid wrapper, unit, provider, coverage, or append-only data raises `ValueError` with enough path or provider/model
context to identify the failing member. Deterministic unsupported-name warnings remain `UserWarning` and do not change
state.

**Python background failures have one consumer.** _(from "Python's background updater remains singular", "Python fetch preserves transport and JSON exceptions", "Python decoded-contract failures are `ValueError`")_
A background exception is stored, raised by the next `wait()` or `stop()`, and then cleared so the same exception is not
raised twice.

**Python activation races fail atomically.** _(from "Every wrapped runtime candidate is append-only relative to its compatibility registry", "Candidate preparation has no externally visible state change")_
Activation rechecks append-only compatibility and raises `ValueError` without changing state if the active registry
advanced incompatibly after preparation.

**Synchronous JavaScript validation failures throw `Error` synchronously.**
A non-promise invalid wrapper, unit set, provider set, coverage relation, or append-only comparison throws from
`setProviderData(...)` and leaves the active pair and current update promise unchanged. New contract errors use the
stable prefix `genai-prices: invalid data:` followed by path or provider/model context.

**Asynchronous JavaScript failures reject with `Error`.** _(from "Synchronous JavaScript validation failures throw `Error` synchronously.")_
A rejected input promise or invalid resolved candidate rejects `waitForUpdate()`, emits the existing fire-and-forget
warning, and leaves the active pair unchanged. Non-`Error` promise rejection reasons are preserved as current JavaScript
behavior; contract validation itself always creates `Error` with the synchronous prefix.

**JavaScript `null` remains a no-op.** _(from "JavaScript keeps its current non-null update ordering")_
Direct or promise-resolved `null` performs no validation and does not replace active data. Direct `null` does not
supersede a pending attempt; a supplied promise supersedes older pending attempts immediately, so a later `null`
resolution does not undo that supersession.

**Go validation failures wrap `ErrInvalidData`.** _(from "Go keeps immutable calculator construction", "Candidate preparation has no externally visible state change")_
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
Publication writes the v3 contract, package generation reads it, and neither stage regenerates a v1 or v2 artifact.

**The initial `build-prices` cutover writes v3 data and schema.** _(from "Phase 2 publishes one full wrapped v3 payload", "The initial v3 schema is permanent")_
It validates the authoring sources and bootstrap compatibility, regenerates `prices/providers/.schema.json`, then writes
`prices/new_data/v3/data.json` and the first `data.schema.json`. It also verifies the frozen v2 bytes rather than
deriving or rewriting them.

**Later `build-prices` runs write provider authoring schema and v3 data.** _(from "The initial v3 schema is permanent", "Later checks compare deployed v3 data and source semantics from the exact target revision")_
They read the existing v3 schema, verify its bytes against the exact target revision, validate candidate data against it,
regenerate `prices/providers/.schema.json` from the current unit source, and replace `data.json`. Inside
`prices/new_data/v3/`, `data.json` is the only rewritten artifact after cutover; v3 schema generation is a check, not a
write path.

**`package-data` reads and splits the validated v3 wrapper.** _(from "Normal builds stop writing v2 after cutover")_
It does not reconstruct the wrapper from separate provider and unit sources and does not write publication artifacts.

**Package generation splits the v3 pair for all three runtimes.** _(from "Python, JavaScript, and Go each consume the wrapped v3 contract", "Phase 2 publishes one full wrapped v3 payload")_
Python `data.py` and JavaScript `data.ts` contain providers while their unit modules contain units. Go embeds provider
JSON and generates unit definitions and constants. The outputs contain no updater or validation state.

**The default remote URL is v3 in every runtime.** _(from "Phase 2 publishes one full wrapped v3 payload")_
Python's default updater URL, JavaScript's `remoteDataUrl`, and Go's `RemoteDataURL` all point to
`prices/new_data/v3/data.json`. The common ingestion APIs still shape-detect a legacy array if a caller or endpoint
provides one.

**Python and JavaScript activate one paired state reference.** _(from "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them", "Candidate preparation has no externally visible state change")_
After final validation, activation replaces one process-global reference containing registry and providers. Standard
pricing, matching, and extraction capture that reference once per operation.

**A fetched Python v3 snapshot privately owns its candidate registry.** _(from "Python `UpdatePrices.fetch()` remains side-effect-free", "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them")_
Its calculation and extraction methods use that registry before activation. The association does not add a public
constructor parameter or field. A provider-array snapshot has no replacement registry and uses the active one.

**Python lookup results are detached from a snapshot's private registry.** _(from "A fetched Python v3 snapshot privately owns its candidate registry", "The public Python `DataSnapshot` construction surface remains stable")_
`DataSnapshot.find_provider(...)` and `find_provider_model(...)` keep returning the existing bare `Provider` and
`ModelInfo` objects. Calling their methods directly uses the active registry, so a fetched-only unit is usable through
snapshot `calc(...)` and `extract_usage(...)` before activation but not through a detached lookup result until that
snapshot has been activated. Phase 2 adds no public wrapper object merely to carry lookup provenance.

**Python background activation installs the fetched pair after `fetch()` returns.** _(from "Python's background updater remains singular", "A fetched Python v3 snapshot privately owns its candidate registry", "Python and JavaScript activate one paired state reference")_
The worker uses the same activation operation as `set_custom_snapshot(...)`; `fetch()` itself remains side-effect-free.

**A caller-constructed Python snapshot changes providers only.** _(from "Python custom-snapshot activation remains explicit", "Provider-only inputs are an explicit exception to wrapped-pair activation")_
Activating a `DataSnapshot` without a validated wrapped registry retains the active registry.

**Clearing Python state intentionally keeps the latest registry.** _(from "Provider-only inputs are an explicit exception to wrapped-pair activation", "Every wrapped runtime candidate is append-only relative to its compatibility registry")_
Bundled providers are restored against the active append-only superset so detached objects using fetched units remain
usable. Process restart restores the fully bundled pair.

**Stopping Python cannot reinstall an in-flight fetched pair.** _(from "Python's background updater remains singular", "Clearing Python state intentionally keeps the latest registry")_
`stop()` signals and joins the worker before restoring bundled providers.

**Unrelated Python manual writes have no new global ordering guarantee.** _(from "Stopping Python cannot reinstall an in-flight fetched pair")_
State replacement is serialized, but Phase 2 adds no process-wide generation protocol or ordering promise among
unrelated `set_custom_snapshot(...)` calls.

**JavaScript widens `setProviderData` with the wrapped shape.** _(from "JavaScript keeps one storage-factory update API", "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them")_
The accepted non-null value becomes `Provider[] | { units, providers }`, synchronously or through a promise. A provider
array changes providers only; a wrapped value can replace the pair after complete validation.

**JavaScript's promise ordering applies to complete pairs.** _(from "JavaScript keeps its current non-null update ordering", "JavaScript widens `setProviderData` with the wrapped shape")_
An older pending wrapped or provider-only update cannot overwrite a newer non-null update. `waitForUpdate()` continues
resolving to the active provider array rather than exposing a second registry API.

**A stale rejected JavaScript attempt rejects only its own promise.** _(from "JavaScript's promise ordering applies to complete pairs", "Asynchronous JavaScript failures reject with `Error`.")_
The promise previously returned by `waitForUpdate()` for that attempt rejects with its original reason and emits the
fire-and-forget warning. It does not change active state, replace or reject the current `waitForUpdate()` promise, or
cancel the newer attempt.

**Go accepts wrapped v3 through immutable construction.** _(from "Go keeps immutable calculator construction", "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them")_
`NewCalculatorFromJSON(...)` returns a calculator owning the validated wrapper registry and providers. New remote usage
names remain expressible through `UsageKey` even before a package release generates a constant. A caller that
automatically fetches `RemoteDataURL` installs updated units and providers by constructing a new calculator and replacing
its own calculator reference only after construction succeeds; the package does not mutate an existing calculator or
process-global state.

**Python detached operations capture one applicable registry.** _(from "Python and JavaScript activate one paired state reference", "A fetched Python v3 snapshot privately owns its candidate registry")_
`DataSnapshot` methods use their private registry when present. Base `ModelInfo.calc_price(...)`, base
`ModelPrice.calc_price(...)`, and standalone `Usage` operations otherwise capture the active registry once at entry.
Custom `ModelPrice.calc_price(self, usage)` overrides keep that signature and own any registry lookups they initiate.

**JavaScript operations capture one applicable registry.** _(from "Python and JavaScript activate one paired state reference", "JavaScript's public extraction entry point remains `extractUsage(...)`.")_
Standard entry points pass the registry captured with active providers through matching, extraction, and pricing. Direct
helpers without an explicit registry capture the active registry once at entry.

**Serialized outputs remain pure data.**
V3 and generated package files contain runtime-semantic units, providers, and prices only. Trust markers, schema
fingerprints, generations, locks, prepared validation results, and decomposition plans are not serialized.

**Publication tests prove version isolation.** _(from "The existing v1 artifacts remain byte-frozen", "The v3 cutover freezes the four v2 artifacts", "Later checks compare deployed v3 data and source semantics from the exact target revision")_
They pin v1 and final v2 bytes, verify the slim projection, validate v3 against its frozen schema, and exercise bootstrap,
later-source, stale-target, target-object reporting, Go-identifier transformation/collision, stable unit ordering, old-unit,
old-implication, removal, and new-ancestor rejection.

**Runtime tests prove failure atomicity and preserved lifecycle behavior.** _(from "Candidate preparation has no externally visible state change", "Every data-ingestion API shape-detects wrapped v3 objects and legacy provider arrays")_
They cover both input shapes; all v2-admitted structural fields and representation forms, including both constraint
shapes, together with baseline rejection of invalid numeric values and cross-field relationships; each runtime's legacy
structural tolerance and validation timing; Python fetch, activation, lookup provenance, clearing, stop/join,
manual-write exclusion, and exact exception behavior; JavaScript synchronous, asynchronous, null, current and stale
rejection, promise identity, direct-null no-op, and promise-resolved-null supersession; Go `ErrInvalidData`; append-only
activation; invalid units, providers, and coverage; and one-state-per-operation capture.

**Runtime boundary tests pin decoded-value and integer rules.** _(from "V3 normalization factors fit every runtime exactly.", "Runtime wire validation starts from a decoded JSON value.")_
They accept `per` values 1 and 9,007,199,254,740,991, reject 0, non-integers, and larger integers, and demonstrate that
duplicate source-text members receive no cross-runtime guarantee beyond validation of the post-parse value.

**Parity tests prove remotely added units.** _(from "Python, JavaScript, and Go each consume the wrapped v3 contract", "Go's open `UsageKey` type represents remote-only names.")_
One fixture adds a unit absent from bundled data plus provider prices and extraction mappings that use it. Python,
JavaScript, and Go extract and price it consistently, including use through Go's open `UsageKey` type.

**A v3 slim payload is excluded.**
Phase 2 publishes the one full payload used by automatic updates. A smaller v3 projection requires separate product and
compatibility requirements.

**Validation caches and decomposition caches are excluded.**
Provider/model lookup caches inside a snapshot or calculator remain permitted. New pricing, validation, or decomposition
caches require a separate specification.

**Fetched registry persistence is excluded.**
Process restart uses bundled data. Persisting and authenticating a fetched registry requires a separate specification.
