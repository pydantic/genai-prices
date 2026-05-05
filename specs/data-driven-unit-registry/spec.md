# Data-Driven Unit Registry

**The goal is to calculate prices as accurately as possible for a given request.**
This is the reason the system exists. Every phase of this work exists to improve pricing accuracy given the usage information and provider pricing information available at runtime.

**Correct pricing semantics beat algorithmic convenience.** _(from "The goal is to calculate prices as accurately as possible")_
The decomposition algorithm is an implementation detail, not a contract users need to understand. A provider's commercial pricing shape must be represented explicitly, even when that means defining intermediate units and repeating a numeric price. Returning a mathematically tidy result that misprices a provider's actual pricing model is not acceptable.

**Price data must be complete; usage data may be incomplete.** _(from "The goal is to calculate prices as accurately as possible")_
Price data is authored or published by us and can be validated before use. If a model prices cached tokens and audio tokens, it must also price cached-audio tokens; missing overlap prices are data bugs. Usage data comes from callers and provider APIs, so it can be partial. The runtime should use reported usage facts when they are enough to price accurately, and raise rather than guess when a required usage value is omitted.

**Every usage value must land in exactly one pricing bucket.** _(from "Price data must be complete; usage data may be incomplete")_
When a model prices overlapping units such as all input tokens and cached input tokens, each token count is assigned to one priced bucket. The system must not double-count or drop usage.

**Validation exists to protect pricing semantics.** _(from "Correct pricing semantics beat algorithmic convenience", "Price data must be complete; usage data may be incomplete")_
Validation rejects data that is incomplete, ambiguous, or impossible to price accurately. Hardcoded price fields used to reject typos such as `inptu_mtok` implicitly; registry-driven price keys must replace that safety net with explicit validation and go further. Registry interval closure, registry join-closedness, price ancestor coverage, and price join coverage are semantic completeness rules. They are not arbitrary requirements imposed to satisfy an algorithm. Rejecting bad data at build time, before a price is used, or during later trust-building activation is cheaper than debugging wrong prices at runtime.

**Units are data, not code.**
A pricing unit is defined once in data and propagated to every runtime. Adding a repo-defined unit should mean editing registry data, not adding Python fields, TypeScript interfaces, schema literals, extractor unions, and hand-maintained subtraction logic.

**Derive, don't duplicate.**
Field names, validation rules, containment relationships, price-key resolution, extractor destinations, and display metadata should be derived from the registry wherever practical. Usage inference is also registry-derived, but it is deferred to Phase 8 because it is orthogonal to proving data-driven units and introduces separate missing-data complexity.

**Backward compatibility is preserved unless clearly impractical.** _(from "Units are data, not code")_
Existing consumer patterns such as `model_price.input_mtok`, `usage.input_tokens`, custom `ModelPrice` subclasses, `calc_price(usage)`, `UpdatePrices.fetch()`, and `set_custom_snapshot(...)` remain supported. This constrains how the registry is introduced.

**Public API signatures remain stable.** _(from "Backward compatibility is preserved unless clearly impractical")_
`set_custom_snapshot(DataSnapshot | None)`, `UpdatePrices.fetch() -> DataSnapshot | None`, `calc_price(...)`, `DataSnapshot.calc(...)`, and `ModelInfo.calc_price(...)` keep their callable shape. `DataSnapshot` can gain an optional registry argument for internal/runtime staging, but existing callers who construct snapshots from provider lists continue to work. New price validation happens at build/export or one-model pricing boundaries before Phase 5, not by forcing callers into new function signatures. Phase 5 can add activation-time validation only as a behavior-preserving optimization that records runtime-private trust for later pricing calls.

**Manual custom pricing remains supported.** _(from "Backward compatibility is preserved unless clearly impractical")_
Python users can keep custom `ModelPrice` subclasses that override `calc_price()` and inspect arbitrary fields on the original usage object. Standard registry pricing may ignore unknown raw usage fields, but the orchestration path must pass the original usage object to custom pricing before the base method wraps it. Subclass-only custom fields remain custom override state unless their names are also registered price keys. Registry validation must not reject a field such as `sausage_price` merely because a custom override consumes it.

**No new generated handwritten modules.** _(from "Units are data, not code", "Derive, don't duplicate")_
Generated data stays in files that are already generated, such as Python `data.py`, JavaScript `data.ts`, `prices/data.json`, `prices/data_slim.json`, and generated schemas. Handwritten modules such as `types.py`, `decompose.py`, `data_snapshot.py`, `units.py`, and their JavaScript equivalents remain handwritten. Dynamic behavior comes from runtime registry lookups, not from generating source-code fields from the registry.

**Provider YAML churn is limited to real data gaps.** _(from "Backward compatibility is preserved unless clearly impractical", "Price data must be complete; usage data may be incomplete")_
The registry work should not rename or restructure existing provider YAML for its own sake. Provider data changes are justified when validation exposes a genuine completeness bug, such as a model pricing cached tokens and audio tokens but lacking the cached-audio overlap price. Adding an explicit repeated price to make a commercial fallback unambiguous is data correctness, not churn.

**Early runtime refactors preserve behavior before the shared contract changes.** _(from "Backward compatibility is preserved unless clearly impractical", "Units are data, not code")_
Python and JavaScript first move their current hardcoded pricing behavior behind internal registries without changing the public remote `data.json` / `data_slim.json` shape. Those early registries expose only the current public usage and price surface for the runtime being refactored. They make today's units registry-shaped internally, but they do not practically enable new repo-defined units for clients.

**The current-unit subset is a delivery exception, not a weaker model.** _(from "Early runtime refactors preserve behavior before the shared contract changes", "Validation exists to protect pricing semantics")_
Phases 1 and 2 may omit future structural join units because exposing those keys before the shared payload can carry them would be a behavior change. That exception is safe only because model-price validation rejects any priced compatible pair whose join is absent before decomposition runs. Full registry join-closedness starts when the complete shared registry is published in Phase 3.

**New repo-defined units become end-to-end only with the shared registry payload.** _(from "Early runtime refactors preserve behavior before the shared contract changes", "Units are data, not code")_
Before Phase 3, adding units to package-internal generated data would create half-support: one runtime might know a unit, but remote price updates and the other runtime would not. Review new built-in units with the Phase 3 wrapped payload change, where unit definitions and the prices that depend on them ship together.

**Usage inference is delayed until after the registry architecture is complete.** _(from "Price data must be complete; usage data may be incomplete", "Derive, don't duplicate")_
Inferring a missing ancestor or overlap from reported descendants is useful but not required to expand the unit set. Phases 1 through 7 therefore do not synthesize missing registered usage values from descendants. They store reported values, use explicit values for priced buckets and tier thresholds, treat safely absent priced descendants as zero, and raise when pricing would require guessing an omitted ancestor or overlap. Phase 8 adds demand-driven inference as a separate reviewable feature.

**The registry model is a data-defined unit graph used by every runtime.** _(from "Units are data, not code", "Derive, don't duplicate")_
A registry contains unit families. A family has a normalization factor such as `per: 1_000_000` and units whose usage values can overlap. A unit has a usage key, a price key, and dimension assignments. The runtime parses that raw data into indexed `UnitFamily` and `UnitDef` objects so pricing, validation, extraction, and display all use the same source of truth.

**Registry construction promotes raw data into indexed runtime objects.** _(from "The registry model is a data-defined unit graph used by every runtime")_
Raw family data stays as plain data until a runtime constructs the registry. Construction promotes usage-key dict keys into `UnitDef.usage_key`, defaults missing `price_key` to the usage key, fills family and unit back-references, and builds flat lookup indexes for usage keys, price keys, dimension sets, ancestors, and join lookup. Downstream validation and pricing use those indexes instead of rediscovering relationships by scanning every unit.
Runtime graph objects that contain back-references, such as unit-to-family links and family-to-unit maps, should use identity semantics rather than recursive value equality so they remain safe to reference, group, and hash by object identity when a language supports that distinction.

**The system is general across unit families.** _(from "The registry model is a data-defined unit graph used by every runtime")_
Any reported quantity with the shape `usage_value * price / normalization_factor` can be represented: tokens, requests, characters, duration, tool calls reported by an API, or future units. Tokens are the first complex family because their usage values overlap across direction, modality, and cache dimensions. The decomposition and validation model is not token-specific. Phase 8 can additionally infer some missing quantities from reported descendants, but that is not required for a unit to be represented or priced when its required usage values are explicit.

**A unit family is the boundary for overlap.** _(from "The system is general across unit families")_
Usage values can overlap only within the same family. Token counts do not overlap request counts. Price calculation resolves each stored price key to exactly one usage-keyed unit, groups priced units by family, decomposes each family independently, and then aggregates costs.

**`requests_kcount` is an explicit one-request pricing exception.** _(from "The system is general across unit families")_
The existing request-count price is represented as usage key `requests`, price key `requests_kcount`, family `requests`, and `per: 1_000` so lookup, validation, display, and total-cost aggregation can see it. It is not caller-supplied usage, not an extractor destination, and not inferred from dimensions. Pricing supplies exactly one request for each `Usage` object passed to `calc_price`. This is the sole built-in exception to otherwise name-agnostic validation and extraction; it must not become a template for arbitrary synthetic usage sources or for hardcoding normal token unit names. Do not add generic registry fields such as `fixed_count`, `reported: false`, or source-kind metadata merely to model this existing request-count behavior.

**Usage keys and price keys have different jobs.** _(from "The registry model is a data-defined unit graph used by every runtime")_
The usage key names the reported count, such as `input_tokens`; after Phase 8 the same key can also name an inferred missing count. The price key names the model-price/provider-YAML field, such as `input_mtok`. `price_key` defaults to the usage key only when they are the same.

**Naming optimizes for writability.** _(from "Usage keys and price keys have different jobs", "Backward compatibility is preserved unless clearly impractical")_
Provider YAML files and usage objects are written by people who infer names from nearby examples. Consistency matters because authors will see `cache_audio_read_mtok` and expect `cache_image_read_mtok` to work. Token naming follows the existing patterns: cached modality units use `cache_{modality}_{op}`, non-cached modality units use `{direction}_{modality}`, token price keys use `_mtok`, and token usage keys use `_tokens`. These are authoring conventions for built-in token data, not validation code that hardcodes commercial unit names.
Repo tests must protect those built-in token naming conventions as data regressions. That test coverage is not runtime/export validation for arbitrary families or runtime custom units; production validation still derives accepted keys and relationships from the registry data itself.

**Dimensions define specificity and overlap.** _(from "The registry model is a data-defined unit graph used by every runtime")_
Dimension assignments such as `{direction: input}`, `{direction: input, cache: read}`, and `{direction: input, modality: audio, cache: read}` define containment. A unit is an ancestor of another unit when its dimensions are a subset of the other's dimensions. This structure replaces hardcoded token-specific subtraction chains.

**Dimension keys and values are unit-local.** _(from "Dimensions define specificity and overlap")_
Families do not separately declare allowed dimension keys or values. A unit with `{modality: video}` is how that family gains the `modality` axis and `video` value. This avoids a second declaration surface and keeps runtime custom units possible. The tradeoff is that a dimension typo can create a new axis or value; structural validation must then decide whether the resulting graph is usable. A stricter optional dimension schema can be added later if the typo protection becomes worth the extra authoring surface.

**Registry-aware pricing decomposes usage by dimensions.** _(from "Dimensions define specificity and overlap", "Every usage value must land in exactly one pricing bucket")_
For each model, only the units with prices participate in decomposition. The runtime groups priced units by family, computes each priced unit's exclusive usage value from the dimension graph, multiplies by the stored price and family normalization factor, and aggregates costs. The shared decomposition behavior is detailed in [algorithm](algorithm.md) and [examples](examples.md).

**Only priced units become buckets.** _(from "Registry-aware pricing decomposes usage by dimensions")_
If a model does not price `input_audio_tokens` and `input_tokens` was reported, reported audio tokens remain inside the nearest priced ancestor. Unpriced reported usage keys are ignored when explicit priced ancestors make them unnecessary. If a required priced ancestor or overlap is omitted, descendant-only reports do not become implicit parent totals before Phase 8; pricing raises rather than guessing.

**Unspecified dimensions are catch-alls.** _(from "Only priced units become buckets")_
`input_tokens` has `{direction: input}` but no `modality`, so it prices the remainder of all input tokens that are not claimed by more-specific priced units. For text-primary models, `input_mtok` is usually the text fallback and no `input_text_mtok` is needed. For an image-primary model, the catch-all can intentionally be the image rate by setting `input_mtok` and `input_image_mtok` to the same value and using `input_text_mtok` as the exception.

**Costs are aggregable by dimension filters.** _(from "Registry-aware pricing decomposes usage by dimensions")_
After decomposition, each priced unit has an exclusive usage value and a cost. Costs can be summed by dimension filters: `input_price` is the backward-compatible aggregate for units whose dimensions include `{direction: input}`, `output_price` is the analogous output aggregate, and `total_price` includes every priced family. Families without a `direction` dimension, including `requests`, contribute only to `total_price`.

**Tiered prices are preserved, not redesigned.** _(from "Backward compatibility is preserved unless clearly impractical")_
The existing `TieredPrices` mechanism remains threshold-based: once a threshold is selected, that tier applies to the relevant unit count as it does today. Before Phase 8, the threshold input is the explicitly reported `input_tokens` total. If a selected tiered price needs a non-zero count and `input_tokens` was not reported, price calculation raises instead of inferring or guessing a tier. Phase 8 can replace that conservative rule with registry-derived inference when the threshold is uniquely determined.

**Incomplete usage is interpreted conservatively before Phase 8.** _(from "Price data must be complete; usage data may be incomplete", "Usage inference is delayed until after the registry architecture is complete")_
Usage construction and extraction store what was reported. A direct read of a stored value returns that value without scanning other fields for contradictions. A missing registered usage value remains missing; it is not inferred from descendants until Phase 8. Pricing treats a missing priced unit as zero only when no positive reported descendant or required overlap makes that omission ambiguous. For example, `{input_tokens: 100, cache_read_tokens: 200}` can price a model that only has `input_mtok`, but must fail for a model that also prices `cache_read_mtok`.

**Raw usage objects remain permissive.** _(from "Backward compatibility is preserved unless clearly impractical")_
Callers can pass mappings, dataclasses, namespace objects, or other objects as usage. Runtime wrapping reads known externally reported usage keys and ignores unknown extras, preserving the existing permissive contract and allowing custom pricing overrides to inspect non-registry fields. Explicit Python `Usage(...)` construction is stricter and can reject unknown keywords; tightening raw-object typos is a separate API decision.

**Unit definitions must travel with prices.** _(from "Units are data, not code", "The registry model is a data-defined unit graph used by every runtime")_
Runtime clients can fetch updated price snapshots before the next package release. A fetched price payload must not contain prices for units the client cannot parse. The long-term data contract therefore carries unit families in the same snapshot as provider prices.

**There is one source registry and no standalone runtime units artifact.** _(from "Unit definitions must travel with prices")_
The checked-in source for built-in units is `prices/units.yml`. Runtime packages load generated language-native data at startup, and runtime auto-updates load unit families from the same fetched payload as providers after Phase 3. The design does not introduce a separate bundled `units.json` or another URL that could drift from prices.

**Validation rules are semantic preconditions.** _(from "Validation exists to protect pricing semantics")_
Validation is expressed in terms of registry dimensions and indexes, not ordinary unit names such as `input_tokens` or `input_mtok`. The explicit exception is the non-reported `requests` / `requests_kcount` pricing rule. Validation does not add economic sanity checks such as cache-read <= uncached, modality price ordering, or cache-write ordering; those may be useful later but are outside the unit-registry correctness rules.

**Validation is split by lifecycle boundary.** _(from "Validation rules are semantic preconditions", "Registry construction promotes raw data into indexed runtime objects")_
Registry construction validates structural unit rules. Build/export validation validates provider model prices and extractor destinations before publishing generated data. Runtime fetches structurally parse the registry but trust fetched model prices as prevalidated by the publisher. Before Phase 5, snapshot activation is not a model-price validation boundary: activating a snapshot installs the staged providers and registry, and standard base pricing validates the selected `ModelPrice` against the active registry every time before using it. Phase 5 may add activation-time validation for missing, stale, custom, changed, runtime-authored, or otherwise untrusted prices so repeated pricing can skip validation only when runtime-private trust proves it is safe.

**ModelPrice construction stays context-free.** _(from "Validation is split by lifecycle boundary", "Manual custom pricing remains supported")_
Constructing a `ModelPrice` does not validate price keys, ancestor coverage, or join coverage because construction often happens before the relevant snapshot registry is known. Candidate dynamic price keys are accepted into model-price storage and accepted or rejected later at build/export, at one-model validation immediately before pricing, or at Phase 5+ activation-time trust validation. Subclass-only custom fields remain custom override state unless the active registry also names them as price keys.

**Runtime model-price validation is use-time until Phase 5.** _(from "Validation is split by lifecycle boundary", "Provider YAML churn is limited to real data gaps")_
The official build validates generated bundled data before publication, and external payload producers are expected to validate before hosting runtime update payloads. Phases 1 through 4 do not maintain runtime trust state, so activation and fetch paths do not bulk-revalidate or selectively revalidate model prices. Standard base pricing validates the selected model price's effective key set against the active registry on every calculation. Phase 5 can replace repeated use-time validation with trust-gated validation, including activation-time validation for objects whose trust is missing or stale.

**Usage keys and price keys are globally unique.** _(from "Validation rules are semantic preconditions")_
A usage key identifies one unit across the entire registry, not just within one family. Usage keys are also raw registry unit keys, usage attributes, and extractor destinations for externally reported units. A price key maps one-to-one to a unit globally and becomes a provider-YAML key and model-price attribute. Duplicate usage keys or duplicate price keys would make extraction, dynamic access, and price-key resolution ambiguous.

**Unit dimension sets are unique within a family.** _(from "Validation rules are semantic preconditions")_
Two units in the same family cannot have identical dimension assignments. The dimension set is the unit's position in the containment graph; duplicate dimension sets describe the same pricing bucket and are a data error.

**Ancestor coverage is required.** _(from "Validation rules are semantic preconditions")_
Pricing a specific unit requires pricing its ancestors in the same family. If a model prices `cache_read_tokens`, it must also price `input_tokens`; otherwise usage reported only at the ancestor level would have no price. This is validated before registry-driven pricing, not guessed at runtime.

**Join coverage is required for overlapping priced units.** _(from "Validation rules are semantic preconditions")_
If a model prices two compatible overlapping units in the same family, it must price their intersection too. Pricing both `cache_read_tokens` and `input_audio_tokens` requires pricing `cache_audio_read_tokens`. Without the join price, usage that is both cached and audio would be double-counted or misallocated.

**Registry interval closure and join-closedness are distinct.** _(from "Validation rules are semantic preconditions")_
Interval closure says comparable units cannot skip structurally important intermediate dimension sets. Join-closedness says compatible overlapping units must have an explicit intersection unit in the registry. Price join coverage then says a model that prices overlapping parents must price that intersection. These rules are cumulative, not alternatives. They can require explicit intermediate units and repeated numeric prices so the data states the commercial fallback directly.

For interval closure, if unit `A` is an ancestor of unit `B`, every dimension set formed by adding a non-empty proper subset of `B.dimensions - A.dimensions` to `A.dimensions` must also exist as a unit in that family. For join-closedness, two units are compatible when they have no conflicting value for the same dimension key; their join is the union of both dimension sets and must exist in the complete registry.

**The built-in token registry is symmetric by data choice, not by validation law.** _(from "Registry interval closure and join-closedness are distinct")_
The complete built-in token family should define the valid input/output/cache-read/cache-write patterns consistently across token modalities where those concepts make sense, while excluding nonsensical combinations such as output cache reads. Future families and runtime custom additions do not need every dimension value to have the same shape; they only need to satisfy the structural rules for the units they actually define.

**Extractor destinations are externally reported usage keys.** _(from "Units are data, not code", "Derive, don't duplicate")_
Extractor mappings target usage keys that can be reported by provider APIs. They do not target price keys, arbitrary strings, or pricing-only units such as `requests`. Runtime extractor construction validates destinations against the relevant active or bundled registry instead of waiting for the first extraction call to fail. Extraction accumulates provider-reported counts by usage key and then hands those values to the registry-aware usage representation. Extraction does not certify that a provider's usage numbers are internally coherent; contradictions remain stored values until pricing, or Phase 8 inference, needs to interpret them.

**Errors describe data problems, not algorithms.** _(from "Validation exists to protect pricing semantics", "Incomplete usage is interpreted conservatively before Phase 8")_
User-facing errors should talk about unknown keys, missing registered prices, required ancestor/join prices, missing usage needed for pricing, or contradictory usage. They should not mention Mobius inversion, leaves, coefficients, posets, or internal dimension algorithms. When a more-specific count does not fit within a less-specific count, the message should explain that relationship in usage-key terms.

**The work is eight numbered phases, not one phase with subphases.** _(from "Backward compatibility is preserved unless clearly impractical", "Unit definitions must travel with prices", "Usage inference is delayed until after the registry architecture is complete")_
Each phase has its own prose spec and code spec. The prose spec states the behavioral target for that phase. The code spec states the implementation delta from the previous phase to that phase.

**Phase order is the review contract.** _(from "The work is eight numbered phases")_
Each phase should be reviewable and shippable after the previous phase. Later phases can influence earlier APIs only where the earlier phase must preserve an extension point; they must not pull their implementation work forward.

**Phase-local code specs are the implementation source of truth.** _(from "The work is eight numbered phases", "Phase order is the review contract")_
There is no top-level code spec. Use the phase-local prose spec plus the matching phase-local code spec. Phase 1 describes the implementation delta from the pre-registry baseline; Phases 2 through 8 describe only what must change after the previous phase is complete.

**Cross-phase call relationships remain documented as supporting detail.** _(from "Phase-local code specs are the implementation source of truth")_
The phase-local code specs are still authoritative, but an implementing agent also needs to see how build validation, packaging, bundled startup, snapshot activation, custom price patching, pricing hot paths, and JavaScript runtime update activation connect across phase boundaries. [implementation-flow](implementation-flow.md) records that connective detail without reintroducing a top-level code spec.

**Phase 1 proves the Python runtime model for the current unit surface.** _(from "Phase order is the review contract", "The registry model is a data-defined unit graph used by every runtime")_
[Phase 1: Python Internal Registry Refactor](phase-1-python-internal-registry/spec.md) ([code spec](phase-1-python-internal-registry/code-spec.md)) moves Python's existing hardcoded usage and price behavior behind a data-shaped `UnitRegistry`, registry-aware `Usage`, registry-backed `ModelPrice`, and generic decomposition for the current public unit set only. It preserves the current remote JSON shape, does not enable new repo-defined units, and does not infer missing usage values from descendants.

**Phase 2 proves the JavaScript runtime model for the current unit surface.** _(from "Phase order is the review contract", "The registry model is a data-defined unit graph used by every runtime")_
[Phase 2: JavaScript Internal Registry Refactor](phase-2-javascript-internal-registry/spec.md) ([code spec](phase-2-javascript-internal-registry/code-spec.md)) gives JavaScript the same internal registry and decomposition model as Python while preserving current JavaScript behavior, the current remote JSON shape, and the no-inference missing-usage rule.

**Phase 3 publishes the shared registry data contract.** _(from "Phase order is the review contract", "Unit definitions must travel with prices")_
[Phase 3: Shared Data Contract and Base Dynamic Price Keys](phase-3-shared-data-contract/spec.md) ([code spec](phase-3-shared-data-contract/code-spec.md)) changes `data.json` and `data_slim.json` from bare provider arrays into wrapped payloads that carry both `unit_families` and `providers`. This is where new repo-defined units become an end-to-end feature, where full registry join-closedness starts, and where Python base `ModelPrice` accepts non-hardcoded registered price keys.

**Phase 4 hardens authoring and compatibility surfaces.** _(from "Phase order is the review contract", "Backward compatibility is preserved unless clearly impractical")_
[Phase 4: Polish and Compatibility Hardening](phase-4-polish-compat-hardening/spec.md) ([code spec](phase-4-polish-compat-hardening/code-spec.md)) adds reserved-name validation, generated provider-YAML schema/autocomplete, registry-driven CLI price presentation, and Python dataclass-subclass dynamic price-key constructor support.

**Phase 5 adds runtime validation performance optimizations.** _(from "Phase order is the review contract", "Validation exists to protect pricing semantics")_
[Phase 5: Runtime Validation Performance Optimization](phase-5-runtime-validation-performance/spec.md) ([code spec](phase-5-runtime-validation-performance/code-spec.md)) adds validation trust contexts, price-key fingerprints, invalidation, and any benchmark-backed decomposition caches. These mechanisms improve repeated-runtime costs but must not change accepted data shapes, validation rules, decomposition semantics, generated payloads, or public API behavior.

**Phase 6 adds runtime custom units.** _(from "Phase order is the review contract", "Units are data, not code")_
[Phase 6: Runtime Custom Units](phase-6-runtime-custom-units/spec.md) ([code spec](phase-6-runtime-custom-units/code-spec.md)) adds user-facing ways to add unit families or units to a staged `DataSnapshot` at runtime and activate the combined registry, price, and extractor changes atomically.

**Phase 7 adds global snapshot execution guardrails.** _(from "Phase order is the review contract", "Backward compatibility is preserved unless clearly impractical")_
[Phase 7: Global Snapshot Semi-Enforcement](phase-7-global-snapshot-enforcement/spec.md) ([code spec](phase-7-global-snapshot-enforcement/code-spec.md)) turns the active-global-snapshot assumption into explicit execution guards without introducing a multi-snapshot execution architecture.

**Phase 8 adds demand-driven usage inference.** _(from "Phase order is the review contract", "Usage inference is delayed until after the registry architecture is complete")_
[Phase 8: Usage Inference](phase-8-usage-inference/spec.md) ([code spec](phase-8-usage-inference/code-spec.md)) replaces the conservative missing-usage rule with registry-derived inference for missing values that are uniquely determined by reported descendants. It keeps reported values as the source of truth and raises when a missing value is contradictory or underdetermined.
