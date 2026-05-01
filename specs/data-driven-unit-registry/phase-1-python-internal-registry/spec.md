# Phase 1: Python Internal Registry Refactor

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 1 is the first implementation slice of the shared pricing goal.**
The root [Data-Driven Unit Registry](../spec.md) spec defines the overall model: calculate prices accurately, require complete price data, tolerate incomplete usage data, define units as data, and derive runtime behavior from a registry. Phase 1 proves that model in Python for today's public units without changing user-visible behavior.

**The Phase 1 registry model has four runtime pieces.** _(from "Phase 1 is the first implementation slice of the shared pricing goal")_
First, raw registry data describes unit families, normalization factors, usage keys, price keys, and unit dimensions. Second, `UnitRegistry` parses that data into indexed `UnitFamily` and `UnitDef` objects. Third, `Usage` reads reported usage keys and lazily infers missing values from the registry. Fourth, base `ModelPrice.calc_price()` resolves price keys through the registry and decomposes only the units priced by the current model.

**Phase 1 proves the Python registry model without changing public behavior.** _(from "The Phase 1 registry model has four runtime pieces")_
Python moves today's hardcoded usage and price semantics behind a data-shaped registry, registry-aware usage reads, registry-backed model prices, and generic decomposition. Existing Python caller behavior, provider data, and runtime update payload shape remain unchanged.

**The active registry is limited to the current Python unit surface.** _(from "Phase 1 proves the Python registry model without changing public behavior")_
The Phase 1 registry exposes only the usage keys and price keys Python already supports: `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `input_audio_tokens`, `cache_audio_read_tokens`, `output_audio_tokens`, their current `_mtok` price keys, plus the existing `requests` / `requests_kcount` request-pricing surface. Text, image, video, cache-by-modality units not already public, and other future units are not registered in this phase.

**The remote payload shape matters because prices update outside package releases.** _(from "Phase 1 proves the Python registry model without changing public behavior")_
The packages load generated language-native data at startup, but long-running clients can fetch `prices/data.json` or `prices/data_slim.json` to receive updated prices before a package release. If Phase 1 changed those remote files to include unit families, older released clients would break. Phase 1 therefore keeps both remote payloads as provider arrays and embeds only the current-unit registry subset into Python generated package data.

**Phase 1 adds no separate runtime unit artifact.** _(from "The remote payload shape matters because prices update outside package releases")_
The new source registry is `prices/units.yml`; generated Python package data embeds the current-unit subset beside providers. Phase 1 does not add a standalone bundled `units.json`, a new runtime URL, or generated source-code fields in handwritten modules. The registry data must travel either in existing generated package data or, in Phase 3, in the shared price payload itself.

**`UnitRegistry` owns Python's runtime unit graph.** _(from "The active registry is limited to the current Python unit surface")_
The registry parses raw unit data, validates slice-appropriate structural integrity, builds lookup indexes, and fills unit/family back-references. It is a public read/lookup type from `genai_prices.units`, but Phase 1 does not expose public methods for mutating an existing registry.

**Python uses one runtime model per unit concept.** _(from "`UnitRegistry` owns Python's runtime unit graph")_
`UnitDef` and `UnitFamily` are plain dataclasses populated by `UnitRegistry`. Python runtime code does not introduce separate Pydantic raw/parsed model layers for unit definitions. Raw registry data remains plain dictionaries until registry construction promotes usage-key dict keys into object fields, defaults missing `price_key` to the usage key, and fills back-references.

**Full registry join-closedness starts in Phase 3.** _(from "`UnitRegistry` owns Python's runtime unit graph", "The active registry is limited to the current Python unit surface")_
The current-unit subset intentionally omits future overlap units that would become new public keys. Phase 1 therefore validates uniqueness, dimension-set uniqueness, and interval closure for the subset, while price-level validation rejects any priced compatible pair whose join is absent from the active subset. Decomposition must never run for a priced set that depends on a missing overlap unit.

**Phase 1 preserves the complete-price/incomplete-usage contract.** _(from "Phase 1 is the first implementation slice of the shared pricing goal", "`UnitRegistry` owns Python's runtime unit graph")_
Provider/model prices must be complete for the units they price: registered price keys, required ancestors, and required joins are validated before registry-driven pricing. Runtime usage remains allowed to be partial or contradictory when first received; errors occur only when missing-value inference or price calculation must interpret data that cannot produce an accurate bucket.

**`Usage` becomes registry-aware and remains permissive for raw caller objects.** _(from "Phase 1 preserves the complete-price/incomplete-usage contract")_
Direct `Usage(...)` construction is strict for registered externally reported usage keys and rejects unknown keywords and non-reported pricing-only keys such as `requests`. `Usage.from_raw(obj)` reads known externally reported keys from mappings or objects and ignores extras, preserving the existing permissive raw-object contract. Missing values are inferred lazily from stored descendant values only when the requested value is uniquely determined; contradictory or underdetermined inference raises when interpreted, not when the object is constructed.

**`Usage` stores reported values only.** _(from "`Usage` becomes registry-aware and remains permissive for raw caller objects")_
Construction does not infer ancestors, normalize values, remember explicit-versus-inferred provenance, or reject contradictory registered values. `Usage.__add__`, equality, and representation operate on reported values; derived values are recomputed lazily on reads. This avoids bugs where inferred ancestors start behaving like caller-supplied data.

**Phase 1 does not make `Usage` immutable.** _(from "`Usage` becomes registry-aware and remains permissive for raw caller objects")_
Today's Python `Usage` is mutable, and immutability is unrelated to proving the registry pricing model. Phase 1 does not add custom registry-aware assignment semantics; registry-aware behavior lives behind reads and pricing.

**`ModelPrice` remains subclass-friendly and uses current legacy fields for storage.** _(from "Phase 1 proves the Python registry model without changing public behavior")_
Existing dataclass fields continue to store current price keys. Custom `@dataclass` subclasses with declared fields and custom `calc_price()` overrides continue to work, including overrides that inspect arbitrary fields on the original usage object. Phase 1 does not add base dynamic price-key constructor storage for future registered keys; that starts in Phase 3.

**`ModelPrice` construction does not validate against the registry.** _(from "`ModelPrice` remains subclass-friendly and uses current legacy fields for storage")_
No price-key lookup, ancestor coverage, or join coverage happens at `ModelPrice.__init__` time. Phase 1 can rely on existing dataclass fields to reject many current-field typos because no non-hardcoded price keys are enabled. Later dynamic keys are accepted as candidates in Phase 3 and validated when a snapshot registry context exists.

**Validation protects pricing semantics without runtime trust caching.** _(from "`UnitRegistry` owns Python's runtime unit graph", "`ModelPrice` remains subclass-friendly and uses current legacy fields for storage")_
Registry construction validates the unit structure. Price-level validation checks registered price keys, ancestor coverage, join coverage, and missing-join safety where needed. Runtime code repeats one-model validation before pricing when it needs a defensive check instead of carrying validation markers, price-key fingerprints, dirty sets, or decomposition caches. Those performance mechanisms belong to Phase 5.

**`calc_price` is a hot path and stays indexed.** _(from "Validation protects pricing semantics without runtime trust caching")_
Phase 1 should avoid full-snapshot validation, full-registry scans, or precomputed plan machinery in the normal request-pricing path. Runtime validation, when needed, is one-model validation over that model's priced key set. Price-key-to-usage-key and usage-key-to-unit lookups use flat registry indexes, and each `UnitDef` carries its family reference so normalization does not require another registry scan.

**`DataSnapshot` carries the Python registry but keeps current activation behavior.** _(from "The remote payload shape matters because prices update outside package releases", "Validation protects pricing semantics without runtime trust caching")_
The bundled snapshot is built with an explicit registry from generated package data. A constructed `DataSnapshot` can default to the current global snapshot's registry for backward compatibility. `set_custom_snapshot` validates only the custom, changed, or otherwise untrusted prices needed to avoid wrong registry-driven pricing and leaves the previous active snapshot in place if validation fails.

**Inactive snapshots are staging objects.** _(from "`DataSnapshot` carries the Python registry but keeps current activation behavior")_
Callers can fetch a snapshot, inspect providers and models, patch prices, and later activate it. Phase 1 does not try to make every inactive-snapshot execution path safe. Lookup-only helpers remain usable on inactive snapshots; explicit execution guards are Phase 7.

**Generated and fetched price feeds are trusted at the publication boundary.** _(from "`DataSnapshot` carries the Python registry but keeps current activation behavior")_
Generated bundled data is trusted because the build validated it. Fetched auto-update payloads remain trusted as prevalidated feeds once their payload shape and registry structure parse. Phase 1 does not bulk-revalidate every built-in or fetched model price during activation, and it does not serialize trust markers into generated data.

**The request-count unit is the only Phase 1 pricing-only unit special case.** _(from "The active registry is limited to the current Python unit surface")_
`requests` exists in the registry so `requests_kcount` participates in lookup, validation, display, and total-cost aggregation. It is not caller-supplied usage and not an extractor destination. Pricing code supplies one request per `Usage` object explicitly.

**Python errors describe user data problems, not decomposition internals.** _(from "`Usage` becomes registry-aware and remains permissive for raw caller objects", "Validation protects pricing semantics without runtime trust caching")_
Errors should talk about unknown keys, missing registered prices, contradictory usage, or values that cannot be inferred. They should not mention Mobius inversion, leaves, coefficients, posets, or internal dimension algorithms.
