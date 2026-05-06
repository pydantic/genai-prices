# Phase 1: Python Internal Registry Refactor

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 1 is the first implementation slice of the shared pricing goal.**
The root [Data-Driven Unit Registry](../spec.md) spec defines the overall model: calculate prices accurately, require complete price data, tolerate incomplete usage data, define units as data, and derive runtime behavior from a registry. Phase 1 proves that model in Python for today's public units while keeping the supported Python pricing and update entry points stable.

**The Phase 1 registry model has four runtime pieces.** _(from "Phase 1 is the first implementation slice of the shared pricing goal")_
First, raw registry data describes unit families, normalization factors, usage keys, price keys, and unit dimensions. Second, `UnitRegistry` parses that data into indexed `UnitFamily` and `UnitDef` objects. Third, `Usage` stores and exposes reported usage keys without inferring omitted ancestors or overlaps. Fourth, base `ModelPrice.calc_price()` resolves price keys through the registry and decomposes only the units priced by the current model.

**Phase 1 preserves supported entry points while changing unsafe internals.** _(from "The Phase 1 registry model has four runtime pieces")_
Python moves today's hardcoded usage and price semantics behind a data-shaped registry, registry-aware usage storage, registry-backed model prices, and generic decomposition. Existing pricing call signatures, permissive raw usage objects, provider data, and runtime update payload shape remain unchanged. This phase is allowed to tighten behavior when old behavior would hide incomplete price data or when preserving dataclass internals would block registry-shaped usage storage; those exceptions are specified below.

**The active registry is limited to the current Python unit surface.** _(from "Phase 1 preserves supported entry points while changing unsafe internals")_
The Phase 1 registry exposes only the usage keys and price keys Python already supports: `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `input_audio_tokens`, `cache_audio_read_tokens`, `output_audio_tokens`, their current `_mtok` price keys, plus the existing `requests` / `requests_kcount` request-pricing surface. Text, image, video, cache-by-modality units not already public, and other future units are not registered in this phase.

**The remote payload shape matters because prices update outside package releases.** _(from "Phase 1 preserves supported entry points while changing unsafe internals")_
The packages load generated language-native data at startup, but long-running clients can fetch `prices/data.json` or `prices/data_slim.json` to receive updated prices before a package release. If Phase 1 changed those remote files to include unit families, older released clients would break. Phase 1 therefore keeps both remote payloads as provider arrays and embeds only the current-unit registry subset into Python generated package data.

**Python unit data stays separate from generated provider data.** _(from "The remote payload shape matters because prices update outside package releases", "Phase 1 preserves supported entry points while changing unsafe internals")_
Python users can provide their own provider data without paying the import cost of the bundled generated providers. Phase 1 preserves that workflow by generating the small current-unit registry subset into a separate Python package module from the provider-heavy generated `data.py`. Code that only needs the default unit registry must import the units-data module, not the bundled provider list.

**Phase 1 adds no separate runtime unit artifact.** _(from "The remote payload shape matters because prices update outside package releases")_
The new source registry is `prices/units.yml`; generated Python package data embeds the current-unit subset in a small generated units-data module. Phase 1 does not add a standalone bundled `units.json`, a new runtime URL, or generated source-code fields in handwritten modules. The registry data must travel either in existing generated package data or, in Phase 3, in the shared price payload itself.

**`UnitRegistry` owns Python's runtime unit graph.** _(from "The active registry is limited to the current Python unit surface")_
The registry parses raw unit data, validates slice-appropriate structural integrity, builds lookup indexes, and fills unit/family back-references. It is a public read/lookup type from `genai_prices.units`, but Phase 1 does not expose public methods for mutating an existing registry.

**Python uses one runtime model per unit concept.** _(from "`UnitRegistry` owns Python's runtime unit graph")_
`UnitDef` and `UnitFamily` are identity dataclasses populated by `UnitRegistry`, using `@dataclass(eq=False)` so family/unit back-references do not create recursive value equality and family objects can be used as identity grouping keys. Python runtime code does not introduce separate Pydantic raw/parsed model layers for unit definitions. Raw registry data remains plain dictionaries until registry construction promotes usage-key dict keys into object fields, defaults missing `price_key` to the usage key, and fills back-references.

**Full registry join-closedness starts in Phase 3.** _(from "`UnitRegistry` owns Python's runtime unit graph", "The active registry is limited to the current Python unit surface")_
The current-unit subset intentionally omits future overlap units that would become new public keys. Phase 1 therefore validates uniqueness, dimension-set uniqueness, and interval closure for the subset, while price-level validation rejects any priced compatible pair whose join is absent from the active subset. Decomposition must never run for a priced set that depends on a missing overlap unit.

**Phase 1 preserves the complete-price/incomplete-usage contract.** _(from "Phase 1 is the first implementation slice of the shared pricing goal", "`UnitRegistry` owns Python's runtime unit graph")_
Provider/model prices must be complete for the units they price: registered price keys, required ancestors, and required joins are validated before registry-driven pricing. Runtime usage remains allowed to be partial or contradictory when first received. Phase 1 does not infer omitted usage values; errors occur only when a direct read or price calculation must interpret data that cannot produce an accurate value or bucket without guessing.

**Complete-price validation intentionally supersedes old fallback overlap pricing.** _(from "Phase 1 preserves the complete-price/incomplete-usage contract", "Phase 1 preserves supported entry points while changing unsafe internals")_
Before registry validation, a manual `ModelPrice` that priced `cache_read_mtok` and `input_audio_mtok` without `cache_audio_read_mtok` could price cached-audio tokens by falling them into one parent bucket. Phase 1 rejects that price set instead. This goes against the broad behavior-preservation goal, but it follows from the complete-price contract: overlapping priced units require an explicit registered join price so usage cannot be double-counted, dropped, or silently assigned to a fallback bucket that the provider data did not state.

**`Usage` becomes registry-aware and remains permissive for raw caller objects.** _(from "Phase 1 preserves the complete-price/incomplete-usage contract")_
Direct `Usage(...)` construction is strict for registered externally reported usage keys and rejects unknown keywords and non-reported pricing-only keys such as `requests`. `Usage.from_raw(obj)` reads known externally reported attributes from dataclasses, namespace objects, and other attribute objects while ignoring extras, preserving the existing permissive raw-object contract. It does not read usage values from mappings such as plain dictionaries because those were not supported by Python `calc_price` before Phase 1. Missing registered values stay missing in Phase 1; descendant reports do not synthesize ancestor totals. Directly reading a missing registered value raises when positive reported related values mean answering would require inferring an omitted ancestor or overlap, and otherwise returns zero without storing that zero.

**`Usage` stores reported values only.** _(from "`Usage` becomes registry-aware and remains permissive for raw caller objects")_
Construction does not infer ancestors, normalize values, remember explicit-versus-derived provenance, or reject contradictory registered values. `Usage.__add__`, equality, and representation operate on reported values; representation orders those values by registry unit order rather than preserving the old dataclass field order. Unambiguous missing registered values read as zero rather than derived values; that read-time zero is not stored and does not make the key reported. Ambiguous missing reads raise instead of computing derived values. This avoids bugs where computed ancestors start behaving like caller-supplied data.

**`Usage` no longer preserves dataclass-introspection compatibility.** _(from "`Usage` stores reported values only", "Phase 1 preserves supported entry points while changing unsafe internals")_
Prior `Usage` was a dataclass, so `dataclasses.is_dataclass(usage)` and `dataclasses.asdict(usage)` worked. Phase 1 intentionally drops that implementation detail: registry-shaped usage needs a normal class that stores only reported values without fixed dataclass fields. Construction, attribute reads, equality, representation, addition, and raw-object wrapping remain supported; dataclass introspection over fixed fields is not a compatibility promise in this phase.

**Phase 1 keeps `Usage` mutable but does not make assignment a new extension point.** _(from "`Usage` no longer preserves dataclass-introspection compatibility")_
Today's Python `Usage` is mutable, and immutability is unrelated to proving the registry pricing model. Assignment to a registered externally reported usage key may update the stored reported value to preserve ordinary field-mutation workflows. That does not make assignment a way to create dynamic usage keys; the active registry still decides which names are reported usage values, and registry-aware behavior lives behind reads and pricing.

**`ModelPrice` remains subclass-friendly and uses current legacy fields for storage.** _(from "Phase 1 preserves supported entry points while changing unsafe internals")_
Existing dataclass fields continue to store current price keys. Custom `@dataclass` subclasses with declared fields and custom `calc_price()` overrides continue to work, including overrides that inspect arbitrary fields on the original usage object. Phase 1 does not add base dynamic price-key constructor storage for future registered keys; that starts in Phase 3.

**`ModelPrice` construction does not validate against the registry.** _(from "`ModelPrice` remains subclass-friendly and uses current legacy fields for storage")_
No price-key lookup, ancestor coverage, or join coverage happens at `ModelPrice.__init__` time. Phase 1 can rely on existing dataclass fields to reject many current-field typos because no non-hardcoded price keys are enabled. Later dynamic keys are accepted as candidates in Phase 3 and validated when a snapshot registry context exists.

**Validation protects pricing semantics without runtime trust caching.** _(from "`UnitRegistry` owns Python's runtime unit graph", "`ModelPrice` remains subclass-friendly and uses current legacy fields for storage")_
Registry construction validates the unit structure. Price-level validation checks registered price keys, ancestor coverage, join coverage, and missing-join safety where needed. Ancestor and join validation receive the active `UnitRegistry` plus the family being checked so they can use registry relationship indexes directly instead of duplicating scans. Runtime code always repeats one-model validation immediately before base `ModelPrice.calc_price()` uses a price. Phase 1 does not carry validation markers, price-key fingerprints, dirty sets, or decomposition caches; those performance mechanisms belong to Phase 5.

**`calc_price` is a hot path and stays indexed.** _(from "Validation protects pricing semantics without runtime trust caching")_
Phase 1 should avoid full-snapshot validation, full-registry scans, or precomputed plan machinery in the normal request-pricing path. Runtime validation is one-model validation over the selected model's priced key set, performed every time standard base pricing calculates against that model price. Price-key-to-usage-key and usage-key-to-unit lookups use flat registry indexes, and each `UnitDef` carries its family reference so normalization does not require another registry scan.

**`DataSnapshot` carries the Python registry but keeps current activation behavior.** _(from "The remote payload shape matters because prices update outside package releases", "Validation protects pricing semantics without runtime trust caching")_
The bundled snapshot is built with an explicit registry from generated package data. A constructed `DataSnapshot` can default to the current global snapshot's registry for backward compatibility. `set_custom_snapshot` does not validate model prices in Phase 1; it installs the staged snapshot, and any price-key, ancestor, join, or missing-join error is raised when standard base pricing first calculates against the affected `ModelPrice`.

**Inactive snapshots are staging objects.** _(from "`DataSnapshot` carries the Python registry but keeps current activation behavior")_
Callers can fetch a snapshot, inspect providers and models, patch prices, and later activate it. Phase 1 does not try to make every inactive-snapshot execution path safe. Lookup-only helpers remain usable on inactive snapshots; explicit execution guards are Phase 7.

**Generated and fetched price feeds are trusted at the publication boundary.** _(from "`DataSnapshot` carries the Python registry but keeps current activation behavior")_
Generated bundled data is trusted because the build validated it. Fetched auto-update payloads remain trusted as prevalidated feeds once their payload shape and registry structure parse. Phase 1 does not bulk-revalidate or selectively revalidate model prices during activation, and it does not serialize trust markers into generated data. Use-time validation is deliberately repeated until Phase 5 adds runtime-private trust.

**The request-count unit is the only Phase 1 pricing-only unit special case.** _(from "The active registry is limited to the current Python unit surface")_
`requests` exists in the registry so `requests_kcount` participates in lookup, validation, display, and total-cost aggregation. It is not caller-supplied usage and not an extractor destination. Pricing code supplies one request per `Usage` object explicitly.

**`UsageExtractor` construction validates destination keys.** _(from "`Usage` becomes registry-aware and remains permissive for raw caller objects", "The request-count unit is the only Phase 1 pricing-only unit special case")_
Constructing a runtime `UsageExtractor` validates every mapping destination against the active registry's externally reported usage keys, rejecting price keys, arbitrary strings, and pricing-only `requests` before any response data is extracted. Generated bundled provider data validates its extractor destinations against the bundled units-data module while `data.py` is importing, so this construction-time check does not force the generated provider list into code paths that only need the default unit registry.

**Python errors describe user data problems, not decomposition internals.** _(from "`Usage` becomes registry-aware and remains permissive for raw caller objects", "Validation protects pricing semantics without runtime trust caching")_
Errors should talk about unknown keys, missing registered prices, missing usage required for reads or pricing, or contradictory usage. They should not mention Mobius inversion, leaves, coefficients, posets, or internal dimension algorithms.
