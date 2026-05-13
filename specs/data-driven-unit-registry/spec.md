# Data-Driven Unit Registry

**The goal is to calculate prices as accurately as possible for a given request.**
This is the reason the system exists. Every phase improves pricing accuracy given the usage information and provider pricing information available at runtime.

**Correct pricing semantics beat algorithmic convenience.** _(from "The goal is to calculate prices as accurately as possible")_
The decomposition algorithm is an implementation detail. A provider's commercial pricing shape must be represented explicitly, even when that requires intermediate units and repeated numeric prices. A tidy result that misprices a provider's model is not acceptable.

**Price data must be complete; usage data may be incomplete.** _(from "The goal is to calculate prices as accurately as possible")_
Price data is authored or published by us and can be validated before use. Usage data comes from callers and provider APIs, so it can be partial. Runtime code should use reported facts when they are enough to price accurately and raise rather than guess when required usage is omitted.

**Every usage value must land in exactly one pricing bucket.** _(from "Price data must be complete; usage data may be incomplete")_
When a model prices overlapping units such as all input tokens and cached input tokens, each token count is assigned to one priced bucket. The system must not double-count or drop usage.

**Validation exists to protect pricing semantics.** _(from "Correct pricing semantics beat algorithmic convenience", "Price data must be complete; usage data may be incomplete")_
Validation rejects data that is incomplete, ambiguous, or impossible to price accurately. Registry structural closure, price ancestor coverage, and price join coverage are semantic completeness rules, not arbitrary algorithm requirements.

**Units are data, not code.**
A pricing unit is defined once in data and propagated to every runtime. Adding a repo-defined unit should mean editing registry data and prices, not adding handwritten Python fields, TypeScript unions, schema literals, extractor unions, and subtraction logic.

**Derive, don't duplicate.** _(from "Units are data, not code")_
Field names, validation rules, containment relationships, price-key resolution, extractor destinations, and display metadata should be derived from the registry wherever practical.

**Backward compatibility is preserved unless clearly impractical.** _(from "Units are data, not code")_
Existing consumer patterns such as `model_price.input_mtok`, `usage.input_tokens`, custom `ModelPrice` subclasses, `calc_price(usage)`, `UpdatePrices.fetch()`, and `set_custom_snapshot(...)` remain supported unless preserving an implementation detail would block registry-defined units.

**Public API signatures remain stable.** _(from "Backward compatibility is preserved unless clearly impractical")_
`set_custom_snapshot(DataSnapshot | None)`, `UpdatePrices.fetch() -> DataSnapshot | None`, `calc_price(...)`, `DataSnapshot.calc(...)`, and `ModelInfo.calc_price(...)` keep their callable shape. `DataSnapshot` remains a provider-data snapshot; the active unit registry is process-global runtime state.

**Manual custom pricing remains supported.** _(from "Backward compatibility is preserved unless clearly impractical")_
Python custom `ModelPrice` subclasses can keep overriding `calc_price()` and inspecting arbitrary fields on the original usage object. Registry validation must not reject subclass-only custom fields unless their names are also registered price keys.

**Do not generate behavior into handwritten modules.** _(from "Units are data, not code", "Derive, don't duplicate")_
Generated outputs may include provider data, generated schemas, and small generated units-data modules. Handwritten runtime modules remain handwritten and use runtime registry lookups instead of generated fields.

**Provider YAML churn is limited to real data gaps.** _(from "Backward compatibility is preserved unless clearly impractical", "Price data must be complete; usage data may be incomplete")_
The registry work should not rename or restructure provider YAML for its own sake. Provider data changes are justified when validation exposes a real completeness bug or when an explicit repeated price is needed to represent a commercial fallback unambiguously.

**The registry model is a data-defined unit graph used by every runtime.** _(from "Units are data, not code", "Derive, don't duplicate")_
A registry contains units keyed by usage key. Each unit has a price key, a normalization factor such as `per: 1_000_000`, and dimension assignments. The `family` dimension is required on every unit and participates in ordinary dimension comparisons.

**Registry construction promotes raw data into indexed runtime objects.** _(from "The registry model is a data-defined unit graph used by every runtime")_
Raw unit data stays plain data until a runtime constructs the registry. Construction promotes usage-key dict keys into `UnitDef.usage_key`, defaults missing `price_key` to the usage key, and builds lookup indexes for usage keys, price keys, dimension sets, ancestors, and joins.

**The system is general across dimensions.** _(from "The registry model is a data-defined unit graph used by every runtime")_
Any reported quantity with the shape `usage_value * price / normalization_factor` can be represented: tokens, requests, characters, duration, tool calls, or future units. Tokens are the first complex area because they overlap across direction, modality, and cache dimensions.

**Usage keys and price keys have different jobs.** _(from "The registry model is a data-defined unit graph used by every runtime")_
The usage key names the reported count, such as `input_tokens`. The price key names the model-price/provider-YAML field, such as `input_mtok`. `price_key` defaults to the usage key only when the names are the same.

**Naming optimizes for writability.** _(from "Usage keys and price keys have different jobs", "Backward compatibility is preserved unless clearly impractical")_
Built-in token names should remain inferable from nearby examples: cached modality units use `cache_{modality}_{op}`, non-cached modality units use `{direction}_{modality}`, token price keys use `_mtok`, and token usage keys use `_tokens`. These are repo data conventions, not runtime validation laws.

**Dimensions define specificity and overlap.** _(from "The registry model is a data-defined unit graph used by every runtime")_
Dimension assignments define containment. A unit is an ancestor of another unit when its dimensions are a subset of the other's dimensions. Units with conflicting dimension values, including conflicting `family` values, do not overlap.

**Dimension keys and values are unit-local.** _(from "Dimensions define specificity and overlap")_
There is no separate declaration of allowed dimension keys or values. Structural validation decides whether the resulting graph is usable. A stricter optional dimension schema can be added later if typo protection becomes worth the extra authoring surface.

**Registry-aware pricing decomposes usage by dimensions.** _(from "Dimensions define specificity and overlap", "Every usage value must land in exactly one pricing bucket")_
For each model, only units with prices participate in decomposition. The runtime computes each priced unit's exclusive usage value from the dimension graph, multiplies it by the stored price, divides by the unit's `per`, and aggregates costs. The shared behavior is detailed in [algorithm](algorithm.md) and [examples](examples.md).

**Only priced units become buckets.** _(from "Registry-aware pricing decomposes usage by dimensions")_
If a model does not price a more-specific reported unit, that reported value remains inside the nearest priced ancestor when an explicit ancestor is available. Descendant-only reports do not become implicit parent totals; pricing raises rather than guessing when a required priced ancestor or overlap is omitted.

**Unspecified dimensions are catch-alls.** _(from "Only priced units become buckets")_
`input_tokens` has `{family: tokens, direction: input}` but no `modality`, so it prices the remainder of all input tokens not claimed by more-specific priced units. Repeated numeric prices are allowed when a commercial fallback must be explicit.

**Costs are aggregable by dimension filters.** _(from "Registry-aware pricing decomposes usage by dimensions")_
After decomposition, each priced unit has an exclusive usage value and cost. `input_price` sums units whose dimensions include `{direction: input}`, `output_price` sums `{direction: output}`, and `total_price` includes every priced unit. Units without `direction`, including `requests`, contribute only to `total_price`.

**`requests_kcount` is an explicit one-request pricing exception.** _(from "The system is general across dimensions")_
The existing request-count price is represented as usage key `requests`, price key `requests_kcount`, `dimensions.family: requests`, and `per: 1_000`. It is not caller-supplied usage, not an extractor destination, and not a template for arbitrary synthetic usage sources.

**Tiered prices are preserved, not redesigned.** _(from "Backward compatibility is preserved unless clearly impractical")_
The existing `TieredPrices` mechanism remains threshold-based. The threshold input is `usage.input_tokens` read through the same missing-usage rules as ordinary access. Missing or ambiguous threshold reads follow the same explicit-only usage contract.

**Usage inference remains out of scope.** _(from "Price data must be complete; usage data may be incomplete", "Derive, don't duplicate")_
Runtime code does not synthesize missing registered usage values from descendants. It stores reported values, returns zero for safely absent reads, and raises when a direct read or pricing calculation would require guessing an omitted ancestor or overlap.

**Raw usage objects remain permissive.** _(from "Backward compatibility is preserved unless clearly impractical")_
Callers can pass existing supported raw usage objects. Runtime wrapping reads known externally reported usage attributes and ignores unknown extras so custom pricing overrides can still inspect non-registry fields on the original object.

**Unit definitions must travel with prices.** _(from "Units are data, not code", "The registry model is a data-defined unit graph used by every runtime")_
Runtime clients can fetch updated prices before the next package release. A fetched price payload must not contain prices for units the client cannot parse, so runtime price payloads carry unit definitions with provider prices.

**There is one source registry and no standalone runtime units artifact.** _(from "Unit definitions must travel with prices")_
The checked-in source for built-in units is `prices/units.yml`. Runtime packages load generated language-native unit data at startup, and runtime auto-updates load units from the same fetched payload as providers.

**There is one active runtime unit registry.** _(from "There is one source registry and no standalone runtime units artifact", "Public API signatures remain stable")_
Runtime code reads unit definitions from a process-global registry. Trusted remote update payloads can replace the global registry while the matching provider data is parsed or activated; failed provider parsing or activation restores the previous registry.

**Validation is split by lifecycle boundary.** _(from "Validation exists to protect pricing semantics", "Registry construction promotes raw data into indexed runtime objects")_
Build/export validation validates structural unit rules, provider model prices, and extractor destinations before publishing generated data. Runtime registry construction parses and indexes trusted unit data; it does not repeat publication-time unit validation for bundled or fetched payloads. Runtime fetches install trusted units, then parse provider data. Standard pricing validates the selected model price before use until Phase 5 adds safe runtime caches.

**ModelPrice construction stays context-free.** _(from "Validation is split by lifecycle boundary", "Manual custom pricing remains supported")_
Constructing a `ModelPrice` does not validate price keys, ancestor coverage, or join coverage because construction can happen before the relevant global registry is installed. Candidate dynamic price keys are accepted into model-price storage and accepted or rejected later at build/export or one-model validation time.

**Usage keys and price keys are globally unique public runtime names.** _(from "Validation exists to protect pricing semantics")_
A usage key identifies one unit across the registry and can become a usage attribute or extractor destination. A price key maps one-to-one to a unit and can become a provider YAML key or model-price attribute. Build/export validation rejects ambiguous, duplicate, private, or unsafe public names.

**Unit dimension sets are globally unique.** _(from "Validation exists to protect pricing semantics")_
Two units cannot have identical full dimension assignments. The required `family` dimension is part of that full dimension set.

**Ancestor coverage is required.** _(from "Validation exists to protect pricing semantics")_
Pricing a specific unit requires pricing its registered ancestors. If a model prices `cache_read_tokens`, it must also price `input_tokens`.

**Join coverage is required for overlapping priced units.** _(from "Validation exists to protect pricing semantics")_
If a model prices two compatible overlapping units, it must price their intersection too. Pricing both `cache_read_tokens` and `input_audio_tokens` requires pricing `cache_audio_read_tokens`.

**Registry interval closure and join-closedness are distinct.** _(from "Validation exists to protect pricing semantics")_
Interval closure says comparable units cannot skip structurally important intermediate dimension sets. Join-closedness says compatible overlapping units must have an explicit intersection unit in the registry. Price join coverage then says a model that prices overlapping parents must price that intersection.

For interval closure, if unit `A` is an ancestor of unit `B`, every dimension set formed by adding a non-empty proper subset of `B.dimensions - A.dimensions` to `A.dimensions` must also exist as a unit. For join-closedness, two units are compatible when they have no conflicting value for the same dimension key; their join is the union of both dimension sets and must exist in the complete registry.

**The built-in token registry is symmetric by data choice, not by validation law.** _(from "Registry interval closure and join-closedness are distinct")_
The complete built-in token family dimension value should define the valid input/output/cache-read/cache-write patterns consistently across token modalities where those concepts make sense, while excluding nonsensical combinations such as output cache reads. Future family dimension values do not need every dimension value to have the same shape; they only need to satisfy the structural rules for the units they actually define.

**Extractor destinations are externally reported usage keys.** _(from "Units are data, not code", "Derive, don't duplicate")_
Extractor mappings target usage keys that can be reported by provider APIs. They do not target price keys, arbitrary strings, or pricing-only units such as `requests`.

**Errors describe data problems, not algorithms.** _(from "Validation exists to protect pricing semantics", "Usage inference remains out of scope")_
User-facing errors should talk about unknown keys, missing registered prices, required ancestor or join prices, missing usage needed for a read or pricing, or contradictory usage. They should not mention internal decomposition machinery.

**The work now has three active numbered phases.** _(from "Backward compatibility is preserved unless clearly impractical", "Unit definitions must travel with prices")_
Historical Phases 1 through 3 have been consolidated into current Phase 3. Old Phases 1 and 2 were implementation slices toward the completed core, and old Phase 3's shared payload work is now part of the same core phase.

**Phase order is the review contract.** _(from "The work now has three active numbered phases")_
Each active phase should be reviewable and shippable after the previous phase. Later phases can influence earlier APIs only where an earlier phase must preserve an extension point; they must not pull their implementation work forward.

**Phase-local code specs are the implementation source of truth.** _(from "The work now has three active numbered phases", "Phase order is the review contract")_
There is no top-level code spec. Use the phase-local prose spec plus the matching phase-local code spec.

**Phase 3 is the consolidated core registry and shared contract.** _(from "Phase order is the review contract")_
[Phase 3: Core Registry and Shared Data Contract](phase-3-shared-data-contract/spec.md) ([code spec](phase-3-shared-data-contract/code-spec.md)) covers Python registry-backed pricing, JavaScript registry-backed pricing, wrapped `units` plus `providers` payloads, dynamic registered price keys, and use-time validation before Phase 5.

**Phase 4 hardens authoring and compatibility surfaces.** _(from "Phase order is the review contract")_
[Phase 4: Polish and Compatibility Hardening](phase-4-polish-compat-hardening/spec.md) ([code spec](phase-4-polish-compat-hardening/code-spec.md)) adds generated provider-YAML schema/autocomplete, registry-driven CLI price presentation, and Python dataclass-subclass dynamic price-key constructor support.

**Phase 5 adds runtime validation performance optimizations.** _(from "Phase order is the review contract")_
[Phase 5: Runtime Validation Performance Optimization](phase-5-runtime-validation-performance/spec.md) ([code spec](phase-5-runtime-validation-performance/code-spec.md)) adds benchmark-backed global validation caches and any benchmark-backed decomposition caches without changing accepted data shapes, validation rules, decomposition semantics, generated payloads, or public API behavior.
