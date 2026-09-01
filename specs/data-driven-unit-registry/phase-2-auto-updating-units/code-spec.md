# Code Spec: Phase 2 Auto-Updating Unit Definitions

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**

**Code architecture stays within prose scope.** _(implements "This prose spec is the complete Phase 2 source of truth.", "Code-level architecture is in [code-spec](code-spec.md).")_
This document defines files, data shapes, signatures, ownership, and call relationships only. The prose spec owns all
behavioral decisions, and implementation planning must derive from this skeleton.

**Implementation is based on the audited Phase 1 tree and preserves its shared pricing engine.** _(implements "Phase 2 ships as an independent change on top of the completed Phase 1 release.", "Phase 1 remains supported without Phase 2.", "Phase 2 inherits the root registry semantics and terminology.", "The audited Phase 1 behavioral baseline is Git object `076f45bda74f18b21d7ccd9bbaf9f5c9332ab4fa`.", "Phase 2 does not change pricing semantics.", "Registered units retain their four-part identity.", "Dimension-subset relationships continue defining ancestors.", "Conflict-free dimension unions continue defining joins.", "Selected prices continue requiring ancestor and join coverage.", "Only priced units remain exclusive usage buckets.", "Unit cost remains usage multiplied by price and divided by normalization.", "Ambiguous missing usage remains uninferred.", "Invalid recognized values, prices, and usage relationships remain errors.", "Each runtime retains its Phase 1 lifecycle model.", "Unchanged Phase 1 behavior: only the requirements below are Phase 2 compatibility requirements.", "Changes: Phase 2 is limited to versioned publication and paired runtime state.")_
The implementation branch audits changes since `076f45bda74f18b21d7ccd9bbaf9f5c9332ab4fa` before modifying runtime code.
Existing matching, constraint selection, tiering, decomposition, price arithmetic, extraction traversal, warning text, and
public request/result types remain in their current modules. Phase 2 adds wire decoding, registry evolution validation,
paired state ownership, and v3 publication around those engines.

**The v3 wire types expose a stable core and forward-compatible extensions.** _(implements "Changes — Shared contract and runtime behavior: every client consumes one versioned unit/provider pair.", "A wrapped v3 publication and activation always keep unit definitions with the provider fields that depend on them.", "New v3 features degrade locally on older clients.", "Partial v3 support is explicit.", "Incomplete old-client support does not require a new data version.", "Phase 2 publishes one full wrapped v3 payload.", "V3 unit definitions use the minimal runtime projection.", "V3 unit definitions have three stable core members.", "An omitted v3 `price_key` resolves to the usage key.", "V3 dimensions are a non-empty string mapping containing `family`.", "Source-only conditional metadata is omitted from v3 unit definitions.", "V3 normalization factors fit every runtime exactly.", "The v3 provider member begins with the cutover v2 provider contract and evolves additively.", "Unknown object members are ignorable v3 extensions.", "Unsupported structural variants skip only their containing capability.", "Behavior-changing extensions must be distinguishable from existing forms.", "The stable v3 core never changes meaning.", "The v3 schema evolves with the payload.", "Runtime compatibility is capability-based, not schema-version equality.", "Runtime wire validation starts from a decoded JSON value.")_
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

`RuntimeUnitData` is the stable serialized core of one source unit; consumers resolve an omitted `price_key` to the
usage key. `V3Payload.units` preserves JSON member order as registry order. `V3Payload.providers` initially uses every
field and value representation admitted by the pinned v2 provider structure, while price-map keys and extractor
destinations remain dynamic strings checked against `units`.

The publisher schema describes the current complete shape, but runtime decoders do not compare it with a bundled schema.
They validate recognized core members strictly, ignore unknown object members, and classify an unrecognized union or
tagged variant as an unsupported capability. That capability is removed at the smallest independently usable boundary
and produces the runtime's existing unsupported-feature warning with a member path and provider/model context. Sibling
units, prices, extractors, models, and providers remain in the candidate. A malformed value for a recognized construct
is instead a contract error. An object whose recognized discriminator or key signature selects no known form is
unsupported; a selected known form with malformed recognized fields is invalid even when it also has unknown members.
The schema generator also rejects a behavior-changing extension that would still validate as an older form after its
new fields were removed: such an extension must use a distinguishable variant or discriminator that an older decoder
can classify and skip. These rules let an older client keep consuming compatible model and price updates even when a
newer client can use more of the same payload.

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

**Go identifier validation is a named publication step.** _(implements "Generated Go unit identifiers retain their deterministic transformation.", "Generated Go unit identifiers must remain safe and unique.", "Go's open `UsageKey` type represents remote-only names.")_
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

**`build-prices` owns v3 publication and both generated schemas.** _(implements "Changes — Build: the build owns v3 publication and compatibility enforcement.", "The initial `build-prices` cutover writes v3 data and schema.", "Later `build-prices` runs write provider authoring schema, v3 schema, and v3 data.", "Normal builds stop writing v2 after cutover.", "Serialized outputs remain pure data.")_
Modify `prices/src/prices/build.py` around these signatures:

```python
def build(compatibility_target_oid: str | None = None) -> None
def v3_data_schema() -> dict[str, object]
def write_v3_data(providers: list[Provider], raw_units: Mapping[str, Mapping[str, object]]) -> None
```

`build()` resolves `compatibility_target_oid` to one full Git object ID before preparing output; CI supplies the exact
pull-request target, while a local invocation without an argument resolves the current `HEAD` as its explicit baseline.
It reads provider YAML and `prices/units.yml`, prepares the complete in-memory schema/payload/source-semantics candidate,
and passes that candidate plus the pinned target ID to `validate_v3_compatibility(...)` below. Missing or invalid target
data and any bootstrap or later compatibility failure stop the build before the provider authoring schema or a
publication artifact is written. Only after that check succeeds does the build regenerate
`prices/providers/.schema.json` and call `write_v3_data(...)`.

At initial cutover, `v3_data_schema()` supplies the first checked-in `prices/new_data/v3/data.schema.json`. On every
later build it supplies the current candidate schema. The build checks that schema for compatible evolution, validates
the candidate payload against it, then writes both `data.schema.json` and `data.json`. The build calls the frozen-v2
verifier below rather than writing those files. Existing v1 files remain outside every build write path.

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
preserves wrapper order. Go generation additionally writes `bundledUnitOrder []UsageKey` beside `bundledUnits`, iterating
the wrapper's publication order without the existing sort, because a Go map cannot represent publication order.

**Compatibility checking is an executable target-object comparison.** _(implements "An existing v3 unit's runtime definition never changes.", "Existing usage-key order is stable and new units append.", "A new v3 unit never becomes an ancestor or intermediate of an existing unit.", "An existing v3 unit's normalized conditional implications never change.", "A mistaken published unit or conditional implication is repaired additively.", "The bootstrap check compares both runtime units and conditional implications from the exact target revision.", "Bootstrap baseline derivation does not consult candidate files.", "Later checks compare deployed v3 data and source semantics from the exact target revision.", "Compatibility checks report their full target object ID.", "Every compatibility baseline read uses the reported target object ID.", "The bootstrap comparison persists no separate baseline artifact.", "Merge-time policy enforces a fresh compatibility result.")_
Add `prices/src/prices/v3_compatibility.py` with this command boundary:

```python
def validate_v3_compatibility(
    target_oid: str,
    *,
    candidate_runtime_units: RuntimeUnitProjection,
    candidate_implications: NormalizedImplications,
    candidate_schema: JsonData,
    candidate_payload: JsonData,
) -> None
def validate_v3_schema_evolution(previous_schema: JsonData, candidate_schema: JsonData) -> None
def main() -> None
```

`validate_v3_compatibility(...)` is the build's pre-write compatibility dependency. It uses the supplied full Git object
ID for every baseline read and emits that ID in CI output. If the target lacks v3, it derives previous runtime units and
normalized implications from the target's `prices/units.yml`; otherwise it reads target v3 data/schema plus target
source implications. It compares the supplied in-memory candidate, calls `validate_unit_evolution(...)`, calls
`validate_v3_schema_evolution(...)`, and validates candidate data with the candidate schema. Missing or invalid
baselines fail. `main()` prepares the same candidate without writing, accepts the target object from CI, and is the
command-line adapter for the dedicated compatibility job.

`validate_v3_schema_evolution(...)` compares schemas in the restricted normal form emitted by this repository's schema
generator. It rejects removal or redefinition of an existing property, newly requiring a property in an existing object
shape, removal or narrowing of an admitted variant, replacement or narrowing of a recognized type, changed defaults,
removed enum values, and narrowed bounds. It allows new optional properties, new discriminator values that select a
skippable capability, and additional distinguishable variants. A generator-side projection test proves each new
behavior-changing variant is not accepted as an older form after its added fields are erased. Unknown-member tolerance
is a runtime rule, so a prior `additionalProperties: false` does not turn a newly documented optional property into a
breaking change. Semantic meaning that JSON Schema cannot express remains pinned by the prose contract and code review.

Update `.github/workflows/ci.yml` so the current v2-schema guard becomes a `published-data-compatibility` pull-request
job. That job pins all four v2 artifacts, supplies `github.event.pull_request.base.sha` to the `build-prices` target (and
therefore its pre-write compatibility dependency), and joins the required aggregate `check`. The direct
`v3_compatibility.py` command remains available for focused CI tests and diagnostics against the same target.
Repository settings keep the aggregate strict/up-to-date or run it through the merge queue, so a result against an older
target cannot authorize merge.

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

**All runtime payload decoders return a prepared understood projection or a provider-only candidate.** _(implements "Every data-ingestion API shape-detects wrapped v3 objects and legacy provider arrays.", "Provider-only inputs are an explicit exception to wrapped-pair activation.", "Provider-only candidates use runtime-selected compatibility registries.", "The v2 provider contract is pinned at the Phase 2 cutover.", "Legacy arrays accept every representation admitted by the pinned v2 schema.", "Legacy arrays retain semantic validation beyond structural schema checks.", "Legacy price-constraint shapes retain their meanings.", "Legacy arrays retain each runtime's baseline structural tolerance.", "Legacy arrays retain each runtime's baseline registry-validation timing.", "Wrapped v3 candidates eagerly validate their understood projection in every runtime.", "Recognized malformed v3 data still fails atomically.", "Candidate preparation has no externally visible state change.", "Runtime unit validation enforces every understood invariant in the v3 projection.", "Runtime provider validation uses the understood v3 provider projection and candidate registry.", "Unknown registry names retain baseline tolerance outside wrapped v3 candidates.", "Arbitrary caller-defined unit semantics are unsupported.")_
Each language has a private decoded-candidate type with `providers` and optional replacement `registry`. Wrapper decoding
strictly validates the recognized core and eagerly validates every retained provider, price, coverage relationship, and
extractor destination against the adjacent registry. Unknown object members are ignored. Unsupported structural
variants produce a contextual upgrade warning and are omitted at the smallest independently usable boundary; they do
not discard understood siblings. Invalid data in a recognized construct rejects the entire candidate. Legacy-array
decoding preserves the baseline language-specific structural tolerance and validation timing, selects the
current/bundled registry independently, and cannot replace it. Candidate creation never mutates active state or an
existing Go calculator. Runtime acceptance does not stand in for source-only conditional or interval validation.

**Python and JavaScript expose private constructors for untrusted runtime projections.** _(implements "Runtime unit validation enforces every understood invariant in the v3 projection.", "Every wrapped runtime candidate is append-only relative to its compatibility registry.")_
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

**Python stores the process pair and snapshot-private registry in `data_snapshot.py`.** _(implements "Changes — Python: wrapped snapshots activate providers and units as one pair.", "The public Python `DataSnapshot` construction surface remains stable.", "Python custom-snapshot activation remains explicit.", "Python and JavaScript activate one paired state reference.", "A fetched Python v3 snapshot privately owns its candidate registry.", "A caller-constructed Python snapshot changes providers only.", "Clearing Python state intentionally keeps the latest registry.", "Python activation races fail atomically.")_
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
    timestamp: datetime = field(default_factory=datetime.now)
    _registry: UnitRegistry | None = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def _from_wrapped(
        cls,
        providers: list[Provider],
        from_auto_update: bool,
        registry: UnitRegistry,
    ) -> DataSnapshot

    def _calc_with_registry(
        self,
        usage: AbstractUsage,
        model_ref: str,
        provider_id: str | None,
        provider_api_url: str | None,
        genai_request_timestamp: datetime | None,
        registry: UnitRegistry,
    ) -> PriceCalculation

    def _extract_usage_with_registry(
        self,
        response_data: Any,
        provider_id: ProviderID | str | None,
        provider_api_url: str | None,
        api_flavor: str,
        registry: UnitRegistry,
    ) -> ExtractedUsage

def get_snapshot() -> DataSnapshot
def _get_runtime_data() -> _RuntimeData
def _get_active_registry() -> UnitRegistry
def set_custom_snapshot(snapshot: DataSnapshot | None) -> None

_runtime_data: _RuntimeData
_runtime_data_lock = RLock()
```

`_RuntimeData` is the single process-global reference replaced under `_runtime_data_lock`; readers copy the reference
once without retaining the lock. `DataSnapshot._registry` is populated only by `_from_wrapped(...)`, so the public two-argument constructor and
public fields stay unchanged. Existing provider/model lookup caches remain private snapshot-owned caches with their
current behavior. Public snapshot `calc(...)` and `extract_usage(...)` capture `_registry` when present or the active
registry once, then delegate to the registry-explicit methods above. Module-level `calc_price(...)` and
`extract_usage(...)` instead capture `_get_runtime_data()` once and call the corresponding private snapshot method with
both members of that pair, so a concurrent activation cannot combine an older snapshot with a newer registry.
`set_custom_snapshot(...)` rechecks a wrapped candidate against the active registry while holding the writer lock, then
swaps one `_RuntimeData`. Passing a provider-only snapshot retains the current registry; passing `None` combines bundled
providers with that registry.

**Python payload decoding is side-effect-free and preserves exception classes.** _(implements "Python `UpdatePrices.fetch()` remains side-effect-free.", "Python fetch preserves transport and JSON exceptions.", "Python decoded-contract failures are `ValueError`.", "Python decoded-contract errors identify the failing data.", "Python unsupported-name warnings remain `UserWarning` and preserve state.", "Partial v3 support is explicit.", "Unknown object members are ignorable v3 extensions.", "Unsupported structural variants skip only their containing capability.", "Recognized malformed v3 data still fails atomically.")_
Add `packages/python/genai_prices/provider_data.py` with:

```python
@dataclass(frozen=True)
class _DecodedProviderData:
    providers: list[Provider]
    registry: UnitRegistry | None
    compatibility_warnings: tuple[str, ...]

def _decode_provider_data(raw: object, compatibility_registry: UnitRegistry) -> _DecodedProviderData
def _decode_wrapped_provider_data(raw: Mapping[str, object], compatibility_registry: UnitRegistry) -> _DecodedProviderData
def _decode_legacy_provider_array(raw: list[object], registry: UnitRegistry) -> _DecodedProviderData
```

`_DecodedProviderData.registry` is `None` for a legacy array and the validated candidate for a wrapper.
`_decode_provider_data(...)` performs root shape detection and dispatch. `_decode_wrapped_provider_data(...)` validates
recognized core fields recursively, ignores unknown object members, and omits unsupported variants at the narrowest
usable boundary while accumulating deterministic contextual upgrade warnings. It then performs runtime-unit validation,
append-only preparation, provider normalization, and eager validation of the retained projection.
`_decode_legacy_provider_array(...)` delegates to the baseline `_providers_from_raw(...)` path and its warning/deferred
price validation behavior. Invalid values for recognized constructs include a member path or provider/model context and
raise `ValueError`; unsupported additions do not use that error path.

`packages/python/genai_prices/update_prices.py::UpdatePrices.fetch()` keeps its existing signature. It performs the
existing `httpx2` request and `json.loads`, captures `_get_active_registry()`, calls `_decode_provider_data(...)`, and
returns an ordinary or `_from_wrapped(...)` snapshot without activation. After successful preparation it emits each
candidate compatibility warning as `UserWarning`; warning emission does not activate or otherwise alter runtime state.
Transport/HTTP exceptions and `json.JSONDecodeError` propagate unchanged.

**Python operations receive one explicit applicable registry below their public boundary.** _(implements "Python keeps snapshot extraction.", "Python lookup methods retain their bare return types.", "Custom Python `ModelPrice` overrides retain their signature and registry ownership.", "Python lookup results are detached from a snapshot's private registry.", "Python detached operations capture one applicable registry.")_
Add or extend these private call boundaries in `packages/python/genai_prices/types.py`:

```python
def Provider._extract_usage_with_registry(
    self,
    response_data: Any,
    api_flavor: str,
    registry: UnitRegistry,
) -> tuple[str | None, Usage]

def UsageExtractor._extract_with_registry(
    self,
    response_data: Any,
    registry: UnitRegistry,
) -> tuple[str | None, Usage]

@classmethod
def Usage._from_values_with_registry(
    cls,
    values: Mapping[str, UsageValue | None],
    registry: UnitRegistry,
) -> Usage

@classmethod
def Usage._from_raw_with_registry(cls, obj: object, registry: UnitRegistry) -> Usage

def Usage._reported_values_with_registry(self, registry: UnitRegistry) -> dict[str, UsageValue]
def Usage._infer_missing_value_with_registry(self, usage_key: str, registry: UnitRegistry) -> UsageValue

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

def _compute_registry_priced_counts(
    resolved_prices: Sequence[tuple[UnitDef, Decimal | TieredPrices]],
    usage: Usage,
    registry: UnitRegistry,
) -> dict[str, UsageValue]
```

`Provider._extract_usage_with_registry(...)` selects an extractor, and
`UsageExtractor._extract_with_registry(...)` constructs its result through `Usage._from_values_with_registry(...)`, so a
fetched-only destination survives snapshot extraction before activation. `Usage._from_raw_with_registry(...)`,
`_reported_values_with_registry(...)`, and `_infer_missing_value_with_registry(...)` are the registry-explicit paths used
by base pricing, decomposition, and snapshot calculation; the `Usage` object itself does not retain a registry.
`ModelPrice._calc_price_with_registry(...)` passes its registry to `_compute_registry_priced_counts(...)`, which passes it
to the decomposition boundary below.

Public `Provider.extract_usage(...)`, `ModelInfo.calc_price(...)`, base `ModelPrice.calc_price(...)`, and standalone
`Usage` operations capture `_get_active_registry()` once and delegate to registry-taking helpers. `DataSnapshot` methods
delegate with the snapshot-private registry when present. Lookup methods still return bare existing objects and attach no
provenance wrapper; calling those objects directly therefore follows the public active-registry path. A custom
`ModelPrice.calc_price(self, usage)` override keeps its existing signature and is not routed through the base private
helper.

Modify `packages/python/genai_prices/decompose.py` around these signatures:

```python
def compute_leaf_values(
    priced_usage_keys: set[str],
    usage: Usage,
    units_by_usage_key: Mapping[str, UnitDef],
    registry: UnitRegistry,
) -> dict[str, UsageValue]

def _usage_value(usage: Usage, usage_key: str, registry: UnitRegistry) -> UsageValue
```

`_usage_value(...)` reads an explicitly reported value or calls `Usage._infer_missing_value_with_registry(...)`; it does
not use `getattr(...)` or any active-registry fallback. `compute_leaf_values(...)` passes the same registry through all
value and error-message reads. Its standard pricing caller is `_compute_registry_priced_counts(...)`, which receives that
registry from `ModelPrice._calc_price_with_registry(...)`.

**Python background activation keeps the existing updater lifecycle.** _(implements "Python's background updater remains singular.", "Python background activation installs the fetched pair after `fetch()` returns.", "Python background failures have one consumer.", "Stopping Python cannot reinstall an in-flight fetched pair.", "Unrelated Python manual writes have no new global ordering guarantee.")_
`UpdatePrices._update_prices()` remains the sole background activation caller: it calls side-effect-free `fetch()` and
then `set_custom_snapshot(...)`. `start()`, `wait()`, and the singleton guard retain their current roles. `stop()` signals
and joins the worker before calling `set_custom_snapshot(None)`, so that worker cannot reinstall a fetched pair after
restoration. The existing stored background-exception slot remains single-consumer for `wait()`/`stop()`. The
first failure fills an empty slot; later producer successes or failures do not clear or replace an unconsumed exception.
The next `wait()` or `stop()` raises and clears that slot. The `data_snapshot.py` writer lock prevents a torn pair but
deliberately adds no generation or ordering API among unrelated manual writes.

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

**JavaScript runtime state owns one pair and provider lookup provenance.** _(implements "Changes — JavaScript: provider-data updates activate complete pairs.", "Python and JavaScript activate one paired state reference.", "JavaScript's public extraction entry point remains `extractUsage(...)`.", "JavaScript operations capture one applicable registry.", "Validation caches and decomposition caches are excluded.")_
Add `packages/js/src/runtimeState.ts` with:

```typescript
export type RuntimeData = Readonly<{
  providers: Provider[]
  registry: UnitRegistry
}>

export function getRuntimeData(): RuntimeData
export function getActiveRegistry(): UnitRegistry
export function activateRuntimeData(providers: Provider[], replacementRegistry?: UnitRegistry): void
export function rememberProviderRegistry(provider: Provider, registry: UnitRegistry): void
export function registryForProvider(provider: Provider): UnitRegistry | undefined
```

`RuntimeData` is the one module-level reference used by active reads and writes. `getRuntimeData()` is captured once by
standard pricing, lookup, and extraction entry points; `getActiveRegistry()` supports detached internal helpers.
The outer `Readonly` prevents reassignment while retaining the existing mutable-array type returned by
`waitForUpdate()`. `activateRuntimeData(...)` is private to the update API even though it is module-exported for
package-internal imports. For a wrapped candidate it calls
`validateUnitEvolution(getRuntimeData().registry, replacementRegistry)` immediately before replacing the one state
reference; a failed race leaves that reference unchanged. Without `replacementRegistry`, it installs the providers with
the current registry captured inside this function, so a provider-only update retains the latest registry.
`rememberProviderRegistry(...)` and `registryForProvider(...)` use a private `WeakMap` only to retain the registry of
providers returned by standard lookup; this is provenance, not a validation/decomposition cache and is never serialized.
Move bundled-registry construction here. `packages/js/src/units.ts` retains `UnitRegistry` and relationship helpers but
no mutable active-registry variable.

**JavaScript decoding separates forward-compatible wrappers from baseline legacy arrays.** _(implements "Wrapped v3 candidates eagerly validate their understood projection in every runtime.", "Recognized malformed v3 data still fails atomically.", "Partial v3 support is explicit.", "Unknown object members are ignorable v3 extensions.", "Unsupported structural variants skip only their containing capability.", "Legacy arrays retain each runtime's baseline structural tolerance.", "Legacy arrays retain each runtime's baseline registry-validation timing.", "Synchronous JavaScript validation failures throw `Error` synchronously.")_
Add `packages/js/src/providerData.ts` with:

```typescript
export type DecodedProviderData = Readonly<{
  providers: Provider[]
  registry?: UnitRegistry
  compatibilityWarnings: string[]
}>

export function decodeProviderData(raw: unknown, compatibilityRegistry: UnitRegistry): DecodedProviderData
function decodeWrappedProviderData(
  raw: Record<string, unknown>,
  compatibilityRegistry: UnitRegistry,
): DecodedProviderData
function decodeLegacyProviderArray(raw: unknown[], registry: UnitRegistry): DecodedProviderData
```

`decodeProviderData(...)` shape-detects and dispatches. `decodeWrappedProviderData(...)` recursively validates recognized
core fields, ignores unknown object members, and omits unsupported variants at the narrowest usable boundary while
accumulating deterministic contextual upgrade warnings. It then builds and validates the candidate registry, performs
append-only comparison, normalizes providers, and eagerly validates the retained names, values, and coverage.
`decodeLegacyProviderArray(...)` retains current normalization, extra-member tolerance, unsupported-destination warning
timing, and calculation-time price validation. Invalid recognized constructs are `Error` instances beginning
`genai-prices: invalid data:` and include member/provider/model context; unsupported additions do not use that path.
Private JavaScript wire types keep extractor `api_flavor`, `model_path`, and mapping `required` optional until a shared
wire-to-runtime normalizer supplies the v2 defaults `"default"`, `"model"`, and `true`. Both wrapped and legacy-array
decoders use that normalizer; recognized wrapper fields are validated before defaulting, while the legacy path keeps its
baseline tolerance for additional members.

**JavaScript promise identity remains the update-ordering mechanism.** _(implements "JavaScript keeps its current non-null update ordering.", "JavaScript `waitForUpdate()` remains provider-only.", "Asynchronous JavaScript contract failures reject with `Error`.", "JavaScript preserves caller-supplied promise rejection reasons.", "JavaScript `null` remains a no-op.", "JavaScript's promise ordering applies to complete pairs.", "A stale rejected JavaScript attempt rejects only its own promise.")_
Keep these boundaries and the current-attempt identity in `packages/js/src/api.ts`:

```typescript
let currentUpdate: Promise<Provider[]>

function setProviderData(data: ProviderDataPayload): void
export function waitForUpdate(): Promise<Provider[]>
```

`setProviderData(...)` owns current-attempt identity and connects synchronous or promised input to
`decodeProviderData(...)`, `activateRuntimeData(...)`, and the existing asynchronous warning sink.
For a successfully activated current attempt, it sends `compatibilityWarnings` to that sink after activation; warnings
from a stale attempt do not describe active state and are not emitted.
`waitForUpdate()` exposes only the promise owned by that boundary. The cited prose defines the exact direct-null,
promise-null, current/stale fulfillment, current/stale rejection, synchronous-error, and active-state outcomes; no
second generation counter or registry promise is introduced.

**JavaScript pricing, lookup, and extraction pass a captured registry.** _(implements "JavaScript's public extraction entry point remains `extractUsage(...)`.", "JavaScript operations capture one applicable registry.")_
`packages/js/src/api.ts::calcPrice(...)` and `findProvider(...)` capture one `RuntimeData`; both record the captured
registry for every active provider they expose (including `PriceCalculation.provider`), and `calcPrice(...)` passes the
same registry through engine, validation, usage, and decomposition helpers. `packages/js/src/extractUsage.ts::extractUsage(...)` keeps its public signature and selects
`registryForProvider(provider) ?? getActiveRegistry()` once. Direct helpers in `engine.ts`, `usage.ts`, and
`validation.ts` keep optional-registry entry points but resolve the default once and pass it through nested calls.

**Go decodes both roots into a new immutable calculator.** _(implements "Changes — Go: wrapped JSON constructs a new immutable calculator.", "Go keeps immutable calculator construction.", "Go keeps both extraction entry points.", "Go accepts wrapped v3 through immutable construction.", "Caller-managed Go updates replace the calculator only after construction succeeds.", "Go validation failures wrap `ErrInvalidData`.", "The default remote URL is v3 in every runtime.", "Partial v3 support is explicit.", "Unknown object members are ignorable v3 extensions.", "Unsupported structural variants skip only their containing capability.", "Recognized malformed v3 data still fails atomically.")_
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
    CompatibilityWarnings []string
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
    Extractors             []wireUsageExtractor
    FallbackModelProviders []string
    Models                 []wireModel
}

type wireModel struct {
    ID            string
    Name          *string
    Description   *string
    Match         matchLogic
    ContextWindow json.RawMessage
    PriceComments *string
    Prices        modelPrices
    Deprecated    *bool
}

type wireUsageExtractor struct {
    Root      extractPath
    Mappings  []wireUsageExtractorMapping
    APIFLavor json.RawMessage
    ModelPath json.RawMessage
}

type wireUsageExtractorMapping struct {
    Path     extractPath
    Dest     UsageKey
    Required json.RawMessage
}

type wrappedProviderData struct {
    Units     orderedWireUnits
    Providers json.RawMessage
}

type decodedProviders struct {
    Values                []provider
    CompatibilityWarnings []string
}

func decodeWrappedProviders(data json.RawMessage, registry *unitRegistry) (decodedProviders, error)
func (value wireProvider) runtimeProvider(registry *unitRegistry) (provider, []string, error)
func (value wireUsageExtractor) runtimeExtractor() (usageExtractor, bool, []string, error)
func decodeCalculatorData(data []byte) (*Calculator, error)
func decodeWrappedCalculatorData(data []byte) (*Calculator, error)
func decodeLegacyCalculatorData(data []byte) (*Calculator, error)
func newUnitRegistry(units map[UsageKey]unitDef, order []UsageKey) *unitRegistry
func newUntrustedUnitRegistry(units orderedWireUnits) (*unitRegistry, error)
func validateUnitEvolution(previous *unitRegistry, candidate *unitRegistry) error
```

`wireUnitDef` preserves the JSON integer until the safe range is checked, then runtime `unitDef.per` remains `float64`
for existing arithmetic. `orderedWireUnits` owns decoded member order and post-parse mapping values; its decoder makes no
cross-runtime duplicate-source-member promise, ignores unknown unit members, and records contextual compatibility
warnings. `wireProvider` and `wireModel` mirror every cutover-v2 core field: identifiers, matching, extractors, fallbacks,
and prices feed runtime structures, while the named metadata fields are validated then discarded by
`runtimeProvider()`. `ContextWindow` remains raw because the core contract admits integers wider than Go runtime integer
types and the field is not used for calculation. `wireUsageExtractor` and
`wireUsageExtractorMapping` retain presence-sensitive raw values for the three defaulted fields;
`runtimeExtractor()` applies `api_flavor = "default"`, `model_path = "model"`, and `required = true` only when the
corresponding member is omitted.

`wrappedProviderData` retains provider JSON for `decodeWrappedProviders(...)`. That decoder walks recognized core fields,
ignores unknown object members, and omits an unsupported structural variant at the smallest usable boundary while
recording a contextual upgrade warning. A wrong type, missing requirement, or invalid value in a recognized construct
remains an error. The legacy decoder uses the same wire-to-runtime default normalization while preserving its baseline
tolerance and validation timing.

`decodeCalculatorData(...)` shape-detects the root. The wrapped path constructs and validates a candidate registry,
compares it with bundled units/order, converts the understood provider projection, and eagerly runs
`Calculator.validate()` over everything retained. The legacy path preserves the current extra-member tolerance and
bundled registry selection. Every returned calculator owns its providers, registry, and immutable compatibility-warning
slice; existing calculators and package-global bundled state never change. Only recognized-invalid decode/validation
errors are wrapped with `ErrInvalidData` by `NewCalculatorFromJSON(...)`; unsupported extensions return a calculator.

`NewCalculator()`, package `Calculate(...)`, package `ExtractUsage(...)`, and the two receiver methods retain their
signatures and ownership: package functions use `bundledCalculator`; receiver methods use only that calculator's pair.
The receiver methods append the calculator's compatibility warnings to the existing `PriceCalculation.Warnings` or
`ExtractedUsage.Warnings`, so Go exposes partial support through its existing result-warning channel without logging or
global state.
`RemoteDataURL` changes to the v3 URL. A caller-managed automatic updater fetches that URL, passes the bytes to
`NewCalculatorFromJSON(...)`, and replaces its own calculator reference only after construction succeeds. Runtime-only
usage keys remain ordinary `UsageKey` values.

Add `order []UsageKey` to the existing `unitRegistry`; trusted bundled construction receives `bundledUnitOrder`, while
`newUntrustedUnitRegistry(...)` validates and retains decoded wrapper order.

**Runtime append-only validation is projection-only in all languages.** _(implements "Every wrapped runtime candidate is append-only relative to its compatibility registry.", "Runtime unit validation enforces every understood invariant in the v3 projection.", "Exact interval-closure validation remains publisher-only.")_
Python `UnitRegistry._from_untrusted(...)` plus `_validate_unit_evolution(...)`, JavaScript
`UnitRegistry.fromUntrusted(...)` plus `validateUnitEvolution(...)`, and Go `newUntrustedUnitRegistry(...)` plus
`validateUnitEvolution(...)` enforce the same wire-available rules: public key safety, exact shapes, safe normalization,
family consistency, unique usage/price/dimension identities, join availability, old definition/order preservation,
appended new keys, and no new ancestor of an old unit. They do not accept conditional metadata and do not implement
exact interval closure. Go compares wrappers with bundled units; Python and JavaScript compare during preparation and
again against active state immediately before activation.

**Runtime tests are organized by contract boundary, not by implementation helper.** _(implements "V2 cutover tests pin final artifact isolation.", "V3 publication tests pin the wrapper and compatible schema evolution.", "Compatibility tests pin target-bound unit evolution.", "Go identifier validation tests cover generated-name safety.", "Runtime ingestion tests cover both accepted root shapes.", "Runtime atomicity tests reject invalid candidates without state change.", "Forward-compatibility tests retain the understood projection.", "Python snapshot tests cover paired state behavior.", "Python background tests cover paired activation and stopping.", "Python contract-error tests cover decoded failures and activation races.", "Python operation-capture tests prevent mixed-registry reads.", "JavaScript pair-ordering tests cover non-null attempts.", "JavaScript contract-validation tests cover error timing.", "JavaScript operation-capture tests prevent mixed-registry reads.", "Go wrapped-construction tests cover remote-only units.", "Go construction-failure tests cover caller-owned atomicity.", "Runtime boundary tests pin decoded-value and integer rules.", "Parity tests prove remotely added units.", "Go generation tests preserve identifier spelling.", "Legacy-array compatibility tests cover preserved v2 behavior.", "Python compatibility tests cover preserved failure behavior.", "JavaScript compatibility tests cover preserved update outcomes.", "Frozen compatibility tests pin v1 and v2 bytes.")_
Extend `tests/test_pipeline_build.py`, add `tests/test_frozen_v2_data.py`, and add
`tests/test_v3_compatibility.py` for publication, schema, order, implications, identifier, bootstrap/later-target,
stale-target, slim projection, and artifact-freeze coverage. Extend Python updater/provider-array/lifecycle/unit tests,
JavaScript provider activation/integration/unit tests, and Go API/parity tests for both roots, language-specific legacy
timing, error surfaces, atomicity, safe-integer boundaries, post-parse duplicate-member policy, Python lookup provenance,
stop/join, JavaScript null/stale rejection, and operation capture. Add one shared wrapped fixture whose new unit, price,
and extractor destination are absent from bundled data; all three runtimes extract and price it, including Go use through
an ungenerated `UsageKey` literal. Add forward-compatible fixtures with safely ignorable unknown members and
distinguishable unsupported extractor,
match, constraint, and price variants; each client warns through its existing channel, skips only the unsupported
capability, and retains understood siblings. Separate fixtures prove malformed recognized constructs remain atomic
errors. Schema-evolution tests accept optional properties and added distinguishable variants while rejecting
stable-core changes and ambiguous behavior-changing additions.

**Phase 2 adds no persistence, mutation API, cache, or serialized control state.** _(implements "Scope exclusions: Phase 2 stops at the runtime-update boundary.", "Serialized outputs remain pure data.", "Validation caches and decomposition caches are excluded.", "Fetched registry persistence is excluded.", "Arbitrary caller-defined unit semantics are unsupported.")_
Do not add disk storage for fetched registries, public registry setters, custom-unit mutation methods, validation or
decomposition caches, generations, trust markers, schema fingerprints, locks in generated data, or new provider
feature fields as part of this Phase 2 implementation. Process restart uses the bundled pair. Any future addition in
those categories starts in a prose spec; a new endpoint is required only when the stable v3 core cannot evolve
compatibly.
