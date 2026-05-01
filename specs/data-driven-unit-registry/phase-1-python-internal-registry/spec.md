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

**`UnitRegistry` owns Python's runtime unit graph.** _(from "The active registry is limited to the current Python unit surface")_
The registry parses raw unit data, validates slice-appropriate structural integrity, builds lookup indexes, and fills unit/family back-references. It is a public read/lookup type from `genai_prices.units`, but Phase 1 does not expose public methods for mutating an existing registry.

**Full registry join-closedness starts in Phase 3.** _(from "`UnitRegistry` owns Python's runtime unit graph", "The active registry is limited to the current Python unit surface")_
The current-unit subset intentionally omits future overlap units that would become new public keys. Phase 1 therefore validates uniqueness, dimension-set uniqueness, and interval closure for the subset, while price-level validation rejects any priced compatible pair whose join is absent from the active subset. Decomposition must never run for a priced set that depends on a missing overlap unit.

**Phase 1 preserves the complete-price/incomplete-usage contract.** _(from "Phase 1 is the first implementation slice of the shared pricing goal", "`UnitRegistry` owns Python's runtime unit graph")_
Provider/model prices must be complete for the units they price: registered price keys, required ancestors, and required joins are validated before registry-driven pricing. Runtime usage remains allowed to be partial or contradictory when first received; errors occur only when missing-value inference or price calculation must interpret data that cannot produce an accurate bucket.

**`Usage` becomes registry-aware and remains permissive for raw caller objects.** _(from "Phase 1 preserves the complete-price/incomplete-usage contract")_
Direct `Usage(...)` construction is strict for registered externally reported usage keys and rejects unknown keywords and non-reported pricing-only keys such as `requests`. `Usage.from_raw(obj)` reads known externally reported keys from mappings or objects and ignores extras, preserving the existing permissive raw-object contract. Missing values are inferred lazily from stored descendant values only when the requested value is uniquely determined; contradictory or underdetermined inference raises when interpreted, not when the object is constructed.

**Phase 1 does not make `Usage` immutable.** _(from "`Usage` becomes registry-aware and remains permissive for raw caller objects")_
Today's Python `Usage` is mutable, and immutability is unrelated to proving the registry pricing model. Phase 1 does not add custom registry-aware assignment semantics; registry-aware behavior lives behind reads and pricing.

**`ModelPrice` remains subclass-friendly and uses current legacy fields for storage.** _(from "Phase 1 proves the Python registry model without changing public behavior")_
Existing dataclass fields continue to store current price keys. Custom `@dataclass` subclasses with declared fields and custom `calc_price()` overrides continue to work, including overrides that inspect arbitrary fields on the original usage object. Phase 1 does not add base dynamic price-key constructor storage for future registered keys; that starts in Phase 3.

**Validation protects pricing semantics without runtime trust caching.** _(from "`UnitRegistry` owns Python's runtime unit graph", "`ModelPrice` remains subclass-friendly and uses current legacy fields for storage")_
Registry construction validates the unit structure. Price-level validation checks registered price keys, ancestor coverage, join coverage, and missing-join safety where needed. Runtime code repeats one-model validation before pricing when it needs a defensive check instead of carrying validation markers, price-key fingerprints, dirty sets, or decomposition caches. Those performance mechanisms belong to Phase 5.

**`DataSnapshot` carries the Python registry but keeps current activation behavior.** _(from "The remote payload shape matters because prices update outside package releases", "Validation protects pricing semantics without runtime trust caching")_
The bundled snapshot is built with an explicit registry from generated package data. A constructed `DataSnapshot` can default to the current global snapshot's registry for backward compatibility. `set_custom_snapshot` validates only the custom, changed, or otherwise untrusted prices needed to avoid wrong registry-driven pricing and leaves the previous active snapshot in place if validation fails.

**The request-count unit is the only Phase 1 pricing-only unit special case.** _(from "The active registry is limited to the current Python unit surface")_
`requests` exists in the registry so `requests_kcount` participates in lookup, validation, display, and total-cost aggregation. It is not caller-supplied usage and not an extractor destination. Pricing code supplies one request per `Usage` object explicitly.

**Python errors describe user data problems, not decomposition internals.** _(from "`Usage` becomes registry-aware and remains permissive for raw caller objects", "Validation protects pricing semantics without runtime trust caching")_
Errors should talk about unknown keys, missing registered prices, contradictory usage, or values that cannot be inferred. They should not mention Mobius inversion, leaves, coefficients, posets, or internal dimension algorithms.
