# Phase 3: Core Registry and Shared Data Contract

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 3 makes repo-defined units work end to end.**
Python and JavaScript both price through a data-defined unit registry, generated and fetched payloads carry `units` with `providers`, and base runtime pricing accepts registered price keys that were not hardcoded before.

**The registry is the source of unit truth.** _(from "Phase 3 makes repo-defined units work end to end")_
`prices/units.yml` defines usage-keyed units with `per`, optional `price_key`, and required `dimensions.family`. Runtime `UnitRegistry` objects parse that data into indexed `UnitDef` objects for usage keys, price keys, dimension sets, ancestors, and joins. Handwritten runtime modules use lookups against those indexes rather than generated source-code fields.

**Python and JavaScript share the same pricing semantics.** _(from "The registry is the source of unit truth")_
Both runtimes resolve model price keys to usage-keyed units, validate the selected model's effective price-key set, decompose only priced units by dimension containment, price `requests_kcount` as one request per calculation, and aggregate costs into existing input/output/total result shapes.

**Usage remains explicit-only.** _(from "Python and JavaScript share the same pricing semantics")_
Runtime usage stores or reads reported values; it does not synthesize omitted ancestors, overlaps, or descendants. Stored values return directly, safely missing registered values read as zero without becoming reported, and missing reads or priced buckets raise when positive related usage would require guessing an omitted ancestor or overlap.

**Complete price data is required before pricing.** _(from "Python and JavaScript share the same pricing semantics", "Usage remains explicit-only")_
A model can price only registered price keys. Priced units must include required ancestors and required joins for compatible overlapping priced units. Missing overlap prices are rejected as incomplete price data rather than assigned to a fallback bucket.

**The shared payload is a wrapped object.** _(from "Phase 3 makes repo-defined units work end to end")_
`data.json` and `data_slim.json` use `{"units": {...}, "providers": [...]}`. Unit definitions travel with the provider prices that depend on them, and there is no separate runtime unit URL or standalone bundled `units.json`.

**The active runtime registry is global.** _(from "The shared payload is a wrapped object")_
Package startup builds the global registry from generated language-native unit data. Runtime updates build a candidate registry from fetched `units`, install it while the matching providers are parsed or activated, and restore the previous registry if provider activation fails. `DataSnapshot` remains provider data only.

**Publication validation is the trust boundary.** _(from "The shared payload is a wrapped object", "Complete price data is required before pricing")_
Build/export validation constructs the registry, validates unit structure, public key safety, provider price keys, ancestor coverage, join coverage, and extractor destinations before publishing payloads. Bundled and fetched runtime data are treated as trusted publisher output; standard pricing still validates the selected model price on use until Phase 5 adds cache-gated validation.

**Registered public keys must be safe runtime names.** _(from "Publication validation is the trust boundary")_
Usage keys become usage attributes and extractor destinations. Price keys become provider YAML keys and model-price attributes. Build/export validation rejects obvious unsafe public names across Python and JavaScript without hardcoding commercial unit concepts such as `input_tokens` or `input_mtok`.

**Python keeps compatibility while accepting dynamic price keys.** _(from "Phase 3 makes repo-defined units work end to end")_
Existing Python entry points and legacy `ModelPrice` fields keep their callable shape. Base `ModelPrice` stores candidate non-hardcoded price keys outside legacy dataclass fields, exposes them through normal price access paths, and accepts or rejects them during use-time validation against the active global registry. Custom overrides still receive the original usage object.

**JavaScript keeps plain-object usage and provider APIs.** _(from "Phase 3 makes repo-defined units work end to end")_
JavaScript callers continue passing plain usage objects. Registry-aware helpers read those objects directly for pricing, while extraction and returned usage objects normalize to externally reported registry usage keys. Runtime provider setters accept the wrapped payload and keep legacy bare provider arrays as compatibility input that leaves the active registry unchanged.

**Extractor destinations are externally reported usage keys.** _(from "The registry is the source of unit truth")_
Extractor mappings target usage keys that provider APIs can report. They do not target price keys, arbitrary strings, or pricing-only units such as `requests`. Extractor validation checks destinations before data becomes active, but extraction does not prove provider-reported usage values are mutually consistent.

**Runtime performance state waits for Phase 5.** _(from "Publication validation is the trust boundary")_
Phase 3 does not add validation markers, price-key fingerprints, generated trust flags, decomposition plans, or runtime validation caches. Generated outputs remain pure data, and repeated standard pricing validates the selected model price before calculating.
