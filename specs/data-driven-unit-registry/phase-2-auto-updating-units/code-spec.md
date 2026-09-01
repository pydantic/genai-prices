# Code Spec: Phase 2 Auto-Updating Unit Definitions

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**

**Code architecture stays within prose scope.** _(implements "This prose spec is the complete Phase 2 source of truth.", "Code-level architecture is in [code-spec](code-spec.md).")_
This document defines files, data shapes, signatures, ownership, and call relationships only. The prose spec owns all
behavioral decisions, and implementation planning must derive from this skeleton.

**Implementation is based on the audited Phase 1 tree and preserves its shared pricing engine.** _(implements "Phase 2 ships as an independent change on top of the completed Phase 1 release.", "Phase 2 inherits the root registry semantics and terminology.", "The audited Phase 1 behavioral baseline is Git object `076f45bda74f18b21d7ccd9bbaf9f5c9332ab4fa`.", "Phase 2 does not change pricing semantics.", "Only the explicitly named Phase 1 behaviors below are Phase 2 compatibility requirements.", "Behavior we change is limited to versioned publication and paired runtime state.")_
The implementation branch audits changes since `076f45bda74f18b21d7ccd9bbaf9f5c9332ab4fa` before modifying runtime code.
Existing matching, constraint selection, tiering, decomposition, price arithmetic, extraction traversal, warning text, and
public request/result types remain in their current modules. Phase 2 adds wire decoding, registry evolution validation,
paired state ownership, and v3 publication around those engines.

**The v3 wire types are closed except for their documented dynamic mappings.** _(implements "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them.", "Phase 2 publishes one full wrapped v3 payload.", "V3 unit definitions use the minimal runtime projection.", "V3 normalization factors fit every runtime exactly.", "The v3 provider member uses the cutover v2 provider contract.", "The initial v3 schema is permanent.", "Runtime wire validation starts from a decoded JSON value.", "A v3 slim payload is excluded.")_
The build, schema, and three runtime decoders share these conceptual shapes without sharing generated executable code:

```text
RuntimeUnitData = {
    per: integer in [1, 9_007_199_254_740_991]
    price_key?: string
    dimensions: non-empty mapping[string, string] containing "family"
}

V3Payload = {
    units: ordered mapping[usage_key, RuntimeUnitData]
    providers: Provider[]
}
```

`RuntimeUnitData` is the serialized projection of one source unit; consumers resolve an omitted `price_key` to the usage
key. `V3Payload.units` preserves JSON member order as registry order. `V3Payload.providers` uses every field and value
representation admitted by the pinned v2 provider structure, while price-map keys and extractor destinations remain
dynamic strings checked against `units`. The wrapper and each unit reject additional members. There is no v3 slim type.

**Source validation exposes canonical runtime and implication projections.** _(implements "Conditional rules are monotone source-only implications.", "Every source unit conforms to all conditional implications that apply to it.", "Conflict-free valid units remain valid under union.", "Conditional semantics normalize per usage key.", "Source-level validation remains the publication authority.", "Exact interval-closure validation remains publisher-only.")_
Extend `prices/src/prices/export_validation.py` with these build-only aliases and functions:

```python
RuntimeUnitProjection = dict[str, dict[str, object]]
ImplicationTriple = tuple[str, str, str]
NormalizedImplications = dict[str, tuple[ImplicationTriple, ...]]

def runtime_unit_projection(raw_units: Mapping[str, Mapping[str, object]]) -> RuntimeUnitProjection
def normalize_conditional_implications(
    raw_units: Mapping[str, Mapping[str, object]],
) -> NormalizedImplications
def validate_runtime_unit_projection(raw_units: Mapping[str, Mapping[str, object]]) -> UnitRegistry
def validate_unit_evolution(
    previous_units: RuntimeUnitProjection,
    previous_implications: NormalizedImplications,
    candidate_units: Mapping[str, Mapping[str, object]],
) -> None
```

`runtime_unit_projection(...)` is the only build helper that strips source-only metadata for v3/package output and keeps
source order. `normalize_conditional_implications(...)` owns fixed-point expansion and canonical triples.
`validate_runtime_unit_projection(...)` enforces the invariants available from wire fields but deliberately does not
claim source interval validation. Existing `validate_units(...)` remains the richer authoring validator and calls both
projection helpers. `validate_unit_evolution(...)` compares existing unit definitions, existing relative order,
new-key append position, old normalized implications, and the no-new-ancestor rule.

**Go identifier validation is a named publication step.** _(implements "Generated Go unit identifiers use the existing deterministic transformation.", "Generated Go unit identifiers must remain safe and unique.", "Go's open `UsageKey` type represents remote-only names.")_
Add `prices/src/prices/go_identifiers.py` and move the existing transformation there with the validation boundaries:

```python
def go_usage_key_identifier(usage_key: str) -> str
def validate_go_usage_key_identifiers(usage_keys: Iterable[str]) -> None
def go_package_level_identifiers() -> frozenset[str]
```

`go_usage_key_identifier(...)` is the single transformation called by both validation and Go package generation.
`validate_go_usage_key_identifiers(...)` is called during source validation before any artifact write. It checks Go
syntax, keywords, transformed-name uniqueness, and collisions with the identifiers returned by
`go_package_level_identifiers()`. The latter reads the package declaration surface while excluding generated unit
constants being replaced. `build.py` and `package_data.py` import this leaf module, avoiding a build/package-generation
import cycle. Remote-only keys still need no generated constant to be passed as Go `UsageKey` strings.

**`build-prices` owns v3 publication and the mutable provider authoring schema.** _(implements "The initial `build-prices` cutover writes v3 data and schema.", "Later `build-prices` runs write provider authoring schema and v3 data.", "Normal builds stop writing v2 after cutover.", "Serialized outputs remain pure data.")_
Modify `prices/src/prices/build.py` around these signatures:

```python
def build() -> None
def v3_data_schema() -> dict[str, object]
def write_v3_data(providers: list[Provider], raw_units: Mapping[str, Mapping[str, object]]) -> None
```

`build()` continues reading provider YAML and `prices/units.yml`, calls the full source/export validators, regenerates
`prices/providers/.schema.json`, and calls `write_v3_data(...)`. At initial cutover, `v3_data_schema()` supplies the
checked-in `prices/new_data/v3/data.schema.json`; after that commit the build constructs the expected schema only to
compare it with the checked-in bytes and never rewrites it. `write_v3_data(...)` writes only
`prices/new_data/v3/data.json` inside the v3 directory and validates it against the frozen schema.
The build calls the frozen-v2 verifier below rather than writing those files. Existing v1 files remain outside every
build write path.

**Package generation consumes the published wrapper rather than rebuilding it.** _(implements "`package-data` reads and splits the validated v3 wrapper.", "Package generation splits the v3 pair for all three runtimes.", "Bundled calculation remains network-independent.", "Python, JavaScript, and Go each consume the wrapped v3 contract.")_
Modify `prices/src/prices/package_data.py` around these signatures:

```python
def package_data() -> None
def load_v3_payload(path: Path) -> tuple[list[JsonData], dict[str, dict[str, JsonData]]]
def package_python_data(provider_data: JsonData, units: Mapping[str, Mapping[str, JsonData]]) -> None
def package_ts_data(provider_data: JsonData, units: Mapping[str, Mapping[str, JsonData]]) -> None
def package_go_data(provider_data: JsonData, units: Mapping[str, Mapping[str, JsonData]]) -> None
```

`load_v3_payload(...)` validates and splits `prices/new_data/v3/data.json`. `package_data()` passes that exact pair to
all generators. Python `data.py`/`data_units.py`, JavaScript `data.ts`/`dataUnits.ts`, and Go
`internal/data/prices.json`/`data_units.go` remain separate pure-data outputs. Python and JavaScript unit generation
preserves wrapper order. Go generation additionally writes `bundledUnitOrder []UsageKey` beside `bundledUnits`, because a
Go map cannot represent publication order.

**Compatibility checking is an executable target-object comparison.** _(implements "An existing v3 unit's runtime definition never changes.", "Existing usage-key order is stable and new units append.", "A new v3 unit never becomes an ancestor or intermediate of an existing unit.", "An existing v3 unit's normalized conditional implications never change.", "A mistaken published unit or conditional implication requires a new contract.", "The bootstrap check compares both runtime units and conditional implications from the exact target revision.", "Later checks compare deployed v3 data and source semantics from the exact target revision.", "Merge-time policy enforces a fresh compatibility result.")_
Add `prices/src/prices/v3_compatibility.py` with this command boundary:

```python
def validate_v3_compatibility(target_oid: str) -> None
def main() -> None
```

`validate_v3_compatibility(...)` uses the supplied full Git object ID for every baseline read and emits that ID in CI
output. If the target lacks v3, it derives previous runtime units and normalized implications from the target's
`prices/units.yml`; otherwise it reads target v3 data/schema plus target source implications. It calls
`validate_unit_evolution(...)`, verifies schema bytes, and validates candidate data with the deployed schema. Missing or
invalid baselines fail. `main()` accepts the target object from CI and is the only command-line adapter.

Update `.github/workflows/ci.yml` so the current v2-schema guard becomes a `published-data-compatibility` pull-request
job. That job pins all four v2 artifacts, runs `v3_compatibility.py` with `github.event.pull_request.base.sha`, and joins
the required aggregate `check`. Repository settings keep that aggregate strict/up-to-date or run it through the merge
queue, so a result against an older target cannot authorize merge.

**The cutover fixtures pin all legacy publication bytes.** _(implements "The existing v1 artifacts remain byte-frozen.", "The v2 URLs, array roots, schemas, and unit vocabulary remain compatible with every Phase 1 package.", "The v3 cutover freezes the four v2 artifacts.", "The final slim v2 payload remains an exact projection.")_
Add `prices/src/prices/frozen_v2.py` with the shared cutover constants and verifier:

```python
V2_ARTIFACT_SHA256: Final[Mapping[str, str]]

def validate_frozen_v2_artifacts() -> None
```

`V2_ARTIFACT_SHA256` maps the four repository-relative v2 paths to literal cutover digests.
`validate_frozen_v2_artifacts()` checks those bytes and is called by `build()` before v3 output. The v1 digest test
remains unchanged. Add `tests/test_frozen_v2_data.py` to call the shared verifier and assert the documented slim
projection against the frozen full array. No runtime or generator receives a v2 write helper after cutover.

**All runtime payload decoders return a prepared pair or a provider-only candidate.** _(implements "Every data-ingestion API shape-detects wrapped v3 objects and legacy provider arrays.", "Provider-only inputs are an explicit exception to wrapped-pair activation.", "The v2 provider contract is pinned at the Phase 2 cutover.", "Legacy arrays retain each runtime's baseline structural tolerance.", "Legacy arrays retain each runtime's baseline registry-validation timing.", "Wrapped v3 candidates are validated eagerly in every runtime.", "Candidate preparation has no externally visible state change.", "Runtime unit validation enforces every invariant available in the v3 projection.", "Runtime provider validation uses the frozen v3 provider contract and candidate registry.", "Unknown registry names retain baseline tolerance outside wrapped v3 candidates.", "Arbitrary caller-defined unit semantics are unsupported.")_
Each language has a private decoded-candidate type with `providers` and optional replacement `registry`. Wrapper decoding
is structurally strict and eagerly validates all providers, recognized prices, coverage, and extractor destinations
against the adjacent registry. Legacy-array decoding preserves the baseline language-specific structural tolerance and
validation timing, selects the current/bundled registry independently, and cannot replace it. Candidate creation never
mutates active state or an existing Go calculator. Runtime acceptance does not stand in for source-only conditional or
interval validation.

**Python and JavaScript expose private constructors for untrusted runtime projections.** _(implements "Runtime unit validation enforces every invariant available in the v3 projection.", "Every wrapped runtime candidate is append-only relative to its compatibility registry.")_
Extend `packages/python/genai_prices/units.py` with:

```python
@classmethod
def UnitRegistry._from_untrusted(cls, raw_units: object) -> UnitRegistry

def _validate_unit_evolution(previous: UnitRegistry, candidate: UnitRegistry) -> None
```

`UnitRegistry._from_untrusted(...)` validates the wire projection before building immutable indexes;
`_validate_unit_evolution(...)` owns Python's definition/order/ancestor comparison. Existing `_get_registry()` delegates
to `data_snapshot._get_active_registry()` so detached public operations use current paired state.

Extend `packages/js/src/units.ts` with:

```typescript
export class UnitRegistry {
  static fromUntrusted(rawUnits: unknown): UnitRegistry
}

export function validateUnitEvolution(previous: UnitRegistry, candidate: UnitRegistry): void
```

`UnitRegistry.fromUntrusted(...)` validates then constructs the existing private indexes in source order.
`validateUnitEvolution(...)` owns JavaScript's equivalent append-only comparison. Both are package-internal surfaces even
though TypeScript exports them for module imports and focused tests.

**Python stores the process pair and snapshot-private registry in `data_snapshot.py`.** _(implements "The public Python `DataSnapshot` construction surface remains stable.", "Python custom-snapshot activation remains explicit.", "Python and JavaScript activate one paired state reference.", "A fetched Python v3 snapshot privately owns its candidate registry.", "A caller-constructed Python snapshot changes providers only.", "Clearing Python state intentionally keeps the latest registry.", "Python activation races fail atomically.")_
Modify `packages/python/genai_prices/data_snapshot.py` with these private shapes and boundaries:

```python
@dataclass(frozen=True)
class _RuntimeData:
    snapshot: DataSnapshot
    registry: UnitRegistry

@dataclass
class DataSnapshot:
    providers: list[Provider]
    from_auto_update: bool
    timestamp: datetime
    _registry: UnitRegistry | None  # init=False, repr=False, compare=False

    @classmethod
    def _from_wrapped(
        cls,
        providers: list[Provider],
        from_auto_update: bool,
        registry: UnitRegistry,
    ) -> DataSnapshot

def get_snapshot() -> DataSnapshot
def _get_runtime_data() -> _RuntimeData
def _get_active_registry() -> UnitRegistry
def set_custom_snapshot(snapshot: DataSnapshot | None) -> None

_runtime_data_lock: RLock
```

`_RuntimeData` is the single process-global reference replaced under `_runtime_data_lock`; readers copy the reference
once without retaining the lock. `DataSnapshot._registry` is populated only by `_from_wrapped(...)`, so the public two-argument constructor and
public fields stay unchanged. Existing provider/model lookup caches remain private snapshot-owned caches with their
current behavior. Snapshot `calc(...)` and `extract_usage(...)` use `_registry` when present; provider-array or
caller-created snapshots use the captured active registry. `set_custom_snapshot(...)` rechecks a wrapped candidate
against the active registry while holding the writer lock, then swaps one `_RuntimeData`. Passing a provider-only
snapshot retains the current registry; passing `None` combines bundled providers with that registry.

**Python payload decoding is side-effect-free and preserves exception classes.** _(implements "Python `UpdatePrices.fetch()` remains side-effect-free.", "Python fetch preserves transport and JSON exceptions.", "Python decoded-contract failures are `ValueError`.")_
Add `packages/python/genai_prices/provider_data.py` with:

```python
@dataclass(frozen=True)
class _DecodedProviderData:
    providers: list[Provider]
    registry: UnitRegistry | None

def _decode_provider_data(raw: object, compatibility_registry: UnitRegistry) -> _DecodedProviderData
def _decode_wrapped_provider_data(raw: Mapping[str, object], compatibility_registry: UnitRegistry) -> _DecodedProviderData
def _decode_legacy_provider_array(raw: list[object], registry: UnitRegistry) -> _DecodedProviderData
```

`_DecodedProviderData.registry` is `None` for a legacy array and the validated candidate for a wrapper.
`_decode_provider_data(...)` performs root shape detection and dispatch. `_decode_wrapped_provider_data(...)` owns strict
recursive wire checks, runtime-unit validation, append-only preparation, strict provider parsing, and eager coverage.
`_decode_legacy_provider_array(...)` delegates to the baseline `_providers_from_raw(...)` path and its warning/deferred
price validation behavior. Contract errors include a member path or provider/model context and raise `ValueError`.

`packages/python/genai_prices/update_prices.py::UpdatePrices.fetch()` keeps its existing signature. It performs the
existing `httpx2` request and `json.loads`, captures `_get_active_registry()`, calls `_decode_provider_data(...)`, and
returns an ordinary or `_from_wrapped(...)` snapshot without activation. Transport/HTTP exceptions and
`json.JSONDecodeError` propagate unchanged.

**Python operations receive one explicit applicable registry below their public boundary.** _(implements "Python keeps snapshot extraction.", "Python lookup results are detached from a snapshot's private registry.", "Python detached operations capture one applicable registry.")_
Add or extend these private call boundaries in `packages/python/genai_prices/types.py`:

```python
def Provider._extract_usage_with_registry(
    self,
    response_data: Any,
    api_flavor: str,
    registry: UnitRegistry,
) -> tuple[str | None, Usage]

def ModelInfo._calc_price_with_registry(
    self,
    usage: AbstractUsage,
    provider: Provider,
    registry: UnitRegistry,
    *,
    genai_request_timestamp: datetime,
    auto_update_timestamp: datetime | None,
) -> PriceCalculation

def ModelPrice._calc_price_with_registry(
    self,
    usage: AbstractUsage,
    registry: UnitRegistry,
) -> CalcPrice
```

Public `Provider.extract_usage(...)`, `ModelInfo.calc_price(...)`, base `ModelPrice.calc_price(...)`, and standalone
`Usage` operations capture `_get_active_registry()` once and delegate to registry-taking helpers. `DataSnapshot` methods
delegate with the snapshot-private registry when present. Lookup methods still return bare existing objects and attach no
provenance wrapper; calling those objects directly therefore follows the public active-registry path. A custom
`ModelPrice.calc_price(self, usage)` override keeps its existing signature and is not routed through the base private
helper.

**Python background activation keeps the existing updater lifecycle.** _(implements "Python's background updater remains singular.", "Python background activation installs the fetched pair after `fetch()` returns.", "Python background failures have one consumer.", "Stopping Python cannot reinstall an in-flight fetched pair.", "Unrelated Python manual writes have no new global ordering guarantee.")_
`UpdatePrices._update_prices()` remains the sole background activation caller: it calls side-effect-free `fetch()` and
then `set_custom_snapshot(...)`. `start()`, `wait()`, and the singleton guard retain their current roles. `stop()` signals
and joins the worker before calling `set_custom_snapshot(None)`, so that worker cannot reinstall a fetched pair after
restoration. The existing stored background-exception slot remains single-consumer for `wait()`/`stop()`. The
`data_snapshot.py` writer lock prevents a torn pair but deliberately adds no generation or ordering API among unrelated
manual writes.

**JavaScript types widen only the existing provider-data setter input.** _(implements "JavaScript keeps one storage-factory update API.", "JavaScript widens `setProviderData` with the wrapped shape.", "The default remote URL is v3 in every runtime.")_
Modify `packages/js/src/types.ts` and `packages/js/src/api.ts` with these shapes:

```typescript
export interface WrappedProviderData {
  units: RawUnitsDict
  providers: Provider[]
}

export type ProviderDataValue = null | Provider[] | WrappedProviderData
export type ProviderDataPayload = ProviderDataValue | Promise<ProviderDataValue>

export const REMOTE_DATA_JSON_URL: string
```

`WrappedProviderData` is the TypeScript-facing shape after runtime decoding, not a claim that a type assertion validates
input. `ProviderDataValue` and `ProviderDataPayload` remain the sole storage-factory setter types; no second public setter
is added. `REMOTE_DATA_JSON_URL` changes to `prices/new_data/v3/data.json` and still flows through
`StorageFactoryParams.remoteDataUrl`.

**JavaScript runtime state owns one pair and provider lookup provenance.** _(implements "Python and JavaScript activate one paired state reference.", "JavaScript's public extraction entry point remains `extractUsage(...)`.", "JavaScript operations capture one applicable registry.", "Validation caches and decomposition caches are excluded.")_
Add `packages/js/src/runtimeState.ts` with:

```typescript
export type RuntimeData = Readonly<{
  providers: readonly Provider[]
  registry: UnitRegistry
}>

export function getRuntimeData(): RuntimeData
export function getActiveRegistry(): UnitRegistry
export function activateRuntimeData(candidate: RuntimeData): void
export function rememberProviderRegistry(provider: Provider, registry: UnitRegistry): void
export function registryForProvider(provider: Provider): UnitRegistry | undefined
```

`RuntimeData` is the one module-level reference used by active reads and writes. `getRuntimeData()` is captured once by
standard pricing, lookup, and extraction entry points; `getActiveRegistry()` supports detached internal helpers.
`activateRuntimeData(...)` is private to the update API even though it is module-exported for package-internal imports.
`rememberProviderRegistry(...)` and `registryForProvider(...)` use a private `WeakMap` only to retain the registry of
providers returned by standard lookup; this is provenance, not a validation/decomposition cache and is never serialized.
Move bundled-registry construction here. `packages/js/src/units.ts` retains `UnitRegistry` and relationship helpers but
no mutable active-registry variable.

**JavaScript decoding separates strict wrappers from baseline legacy arrays.** _(implements "Wrapped v3 candidates are validated eagerly in every runtime.", "Legacy arrays retain each runtime's baseline structural tolerance.", "Legacy arrays retain each runtime's baseline registry-validation timing.", "Synchronous JavaScript validation failures throw `Error` synchronously.")_
Add `packages/js/src/providerData.ts` with:

```typescript
export type DecodedProviderData = Readonly<{
  providers: Provider[]
  registry?: UnitRegistry
}>

export function decodeProviderData(raw: unknown, compatibilityRegistry: UnitRegistry): DecodedProviderData
function decodeWrappedProviderData(
  raw: Record<string, unknown>,
  compatibilityRegistry: UnitRegistry,
): DecodedProviderData
function decodeLegacyProviderArray(raw: unknown[], registry: UnitRegistry): DecodedProviderData
```

`decodeProviderData(...)` shape-detects and dispatches. `decodeWrappedProviderData(...)` recursively checks the frozen
wire structure, builds and validates the candidate registry, performs append-only comparison, normalizes providers, and
eagerly validates recognized names, values, and coverage. `decodeLegacyProviderArray(...)` retains current normalization,
extra-member tolerance, unsupported-destination warning timing, and calculation-time price validation. New contract
errors are `Error` instances beginning `genai-prices: invalid data:` and include member/provider/model context.

**JavaScript promise identity remains the update-ordering mechanism.** _(implements "JavaScript keeps its current non-null update ordering.", "Asynchronous JavaScript failures reject with `Error`.", "JavaScript `null` remains a no-op.", "JavaScript's promise ordering applies to complete pairs.", "A stale rejected JavaScript attempt rejects only its own promise.")_
Keep the existing private `setProviderData(data: ProviderDataPayload): void` and public
`waitForUpdate(): Promise<Provider[]>` in `packages/js/src/api.ts`. Direct `null` returns before changing the current
promise. A supplied promise becomes the current promise immediately; its resolved non-null value calls
`decodeProviderData(...)` and may activate only while promise identity is still current. A `null` resolution keeps data
unchanged, resolves that attempt to the active provider array, and does not restore the superseded promise. A stale
fulfillment cannot activate. A stale rejection rejects its own previously returned promise and reaches the existing
warning sink without replacing active data or the current wait promise. Synchronous values decode and activate before
`setProviderData(...)` returns, so validation throws synchronously and leaves the earlier pair/promise intact.

**JavaScript pricing, lookup, and extraction pass a captured registry.** _(implements "JavaScript's public extraction entry point remains `extractUsage(...)`.", "JavaScript operations capture one applicable registry.")_
`packages/js/src/api.ts::calcPrice(...)` and `findProvider(...)` capture one `RuntimeData`; the former passes its registry
through engine, validation, usage, and decomposition helpers, while the latter records provider provenance before
return. `packages/js/src/extractUsage.ts::extractUsage(...)` keeps its public signature and selects
`registryForProvider(provider) ?? getActiveRegistry()` once. Direct helpers in `engine.ts`, `usage.ts`, and
`validation.ts` keep optional-registry entry points but resolve the default once and pass it through nested calls.

**Go decodes both roots into a new immutable calculator.** _(implements "Go keeps immutable calculator construction.", "Go keeps both extraction entry points.", "Go accepts wrapped v3 through immutable construction.", "Go validation failures wrap `ErrInvalidData`.", "The default remote URL is v3 in every runtime.")_
Modify `packages/go/types.go`, `calculator.go`, and `units.go` with these private shapes and signatures:

```go
type wireUnitDef struct {
    PriceKey  string
    Per       uint64
    Dimensions map[string]string
}

type orderedWireUnits struct {
    Order  []UsageKey
    Values map[UsageKey]wireUnitDef
}

type wireProvider struct {
    ID                     string
    Name                   string
    PricingURLs            []string
    APIPattern             string
    Description            *string
    PriceComments          *string
    ModelMatch             *matchLogic
    ProviderMatch          *matchLogic
    Extractors             []usageExtractor
    FallbackModelProviders []string
    Models                 []wireModel
}

type wireModel struct {
    ID            string
    Name          *string
    Description   *string
    Match         matchLogic
    ContextWindow *int64
    PriceComments *string
    Prices        modelPrices
    Deprecated    *bool
}

type wrappedProviderData struct {
    Units     orderedWireUnits
    Providers json.RawMessage
}

func (value wireProvider) runtimeProvider() provider
func decodeCalculatorData(data []byte) (*Calculator, error)
func decodeWrappedCalculatorData(data []byte) (*Calculator, error)
func decodeLegacyCalculatorData(data []byte) (*Calculator, error)
func newUnitRegistry(units map[UsageKey]unitDef, order []UsageKey) *unitRegistry
func newUntrustedUnitRegistry(units orderedWireUnits) (*unitRegistry, error)
func validateUnitEvolution(previous *unitRegistry, candidate *unitRegistry) error
```

`wireUnitDef` preserves the JSON integer until the safe range is checked, then runtime `unitDef.per` remains `float64`
for existing arithmetic. `orderedWireUnits` owns decoded member order and post-parse mapping values; its decoder makes no
cross-runtime duplicate-source-member promise. `wireProvider` and `wireModel` mirror every frozen v2 field: identifiers,
matching, extractors, fallbacks, and prices feed runtime structures, while the named metadata fields are validated then
discarded by `runtimeProvider()`. `wrappedProviderData` retains provider JSON until strict wire decoding. This separation
lets wrapped decoding reject unknown fields without rejecting admitted metadata.
`decodeCalculatorData(...)` shape-detects the root. The wrapped path uses strict field decoding, constructs/validates a
candidate registry, compares it with bundled units/order, strictly decodes all providers, and eagerly runs
`Calculator.validate()`. The legacy path preserves the current extra-member tolerance and bundled registry selection.
Every returned calculator owns its providers and registry; existing calculators and package-global bundled state never
change. All decode/validation errors are wrapped with `ErrInvalidData` by `NewCalculatorFromJSON(...)`.

`NewCalculator()`, package `Calculate(...)`, package `ExtractUsage(...)`, and the two receiver methods retain their
signatures and ownership: package functions use `bundledCalculator`; receiver methods use only that calculator's pair.
`RemoteDataURL` changes to the v3 URL. Runtime-only usage keys remain ordinary `UsageKey` values.

Add `order []UsageKey` to the existing `unitRegistry`; trusted bundled construction receives `bundledUnitOrder`, while
`newUntrustedUnitRegistry(...)` validates and retains decoded wrapper order.

**Runtime append-only validation is projection-only in all languages.** _(implements "Every wrapped runtime candidate is append-only relative to its compatibility registry.", "Runtime unit validation enforces every invariant available in the v3 projection.", "Exact interval-closure validation remains publisher-only.")_
Python `UnitRegistry._from_untrusted(...)` plus `_validate_unit_evolution(...)`, JavaScript
`UnitRegistry.fromUntrusted(...)` plus `validateUnitEvolution(...)`, and Go `newUntrustedUnitRegistry(...)` plus
`validateUnitEvolution(...)` enforce the same wire-available rules: public key safety, exact shapes, safe normalization,
family consistency, unique usage/price/dimension identities, join availability, old definition/order preservation,
appended new keys, and no new ancestor of an old unit. They do not accept conditional metadata and do not implement
exact interval closure. Go compares wrappers with bundled units; Python and JavaScript compare during preparation and
again against active state immediately before activation.

**Runtime tests are organized by contract boundary, not by implementation helper.** _(implements "Publication tests prove version isolation.", "Runtime tests prove failure atomicity and preserved lifecycle behavior.", "Runtime boundary tests pin decoded-value and integer rules.", "Parity tests prove remotely added units.")_
Extend `tests/test_pipeline_build.py`, add `tests/test_frozen_v2_data.py`, and add
`tests/test_v3_compatibility.py` for publication, schema, order, implications, identifier, bootstrap/later-target,
stale-target, slim projection, and artifact-freeze coverage. Extend Python updater/provider-array/lifecycle/unit tests,
JavaScript provider activation/integration/unit tests, and Go API/parity tests for both roots, language-specific legacy
timing, error surfaces, atomicity, safe-integer boundaries, post-parse duplicate-member policy, Python lookup provenance,
stop/join, JavaScript null/stale rejection, and operation capture. Add one shared wrapped fixture whose new unit, price,
and extractor destination are absent from bundled data; all three runtimes extract and price it, including Go use through
an ungenerated `UsageKey` literal.

**Phase 2 adds no persistence, mutation API, cache, or serialized control state.** _(implements "Serialized outputs remain pure data.", "Validation caches and decomposition caches are excluded.", "Fetched registry persistence is excluded.", "Arbitrary caller-defined unit semantics are unsupported.")_
Do not add disk storage for fetched registries, public registry setters, custom-unit mutation methods, validation or
decomposition caches, generations, trust markers, schema fingerprints, locks in generated data, a v3 slim artifact, or
new provider structural fields. Process restart uses the bundled pair. Any future addition in those categories starts in
the prose spec and a new compatible contract where required.
