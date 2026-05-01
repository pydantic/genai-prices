# Data-Driven Unit Registry

**The goal is to calculate prices as accurately as possible for a given request.**
This is the reason the system exists. Every phase of this work exists to improve pricing accuracy given the usage information and provider pricing information available at runtime.

**Correct pricing semantics beat algorithmic convenience.** _(from "The goal is to calculate prices as accurately as possible")_
The decomposition algorithm is an implementation detail, not a contract users need to understand. A provider's commercial pricing shape must be represented explicitly, even when that means defining intermediate units and repeating a numeric price. Returning a mathematically tidy result that misprices a provider's actual pricing model is not acceptable.

**Price data must be complete; usage data may be incomplete.** _(from "The goal is to calculate prices as accurately as possible")_
Price data is authored or published by us and can be validated before use. If a model prices cached tokens and audio tokens, it must also price cached-audio tokens; missing overlap prices are data bugs. Usage data comes from callers and provider APIs, so it can be partial. The runtime should use whatever usage facts it has and infer only values that are uniquely determined.

**Every usage value must land in exactly one pricing bucket.** _(from "Price data must be complete; usage data may be incomplete")_
When a model prices overlapping units such as all input tokens and cached input tokens, each token count is assigned to one priced bucket. The system must not double-count or drop usage.

**Validation exists to protect pricing semantics.** _(from "Correct pricing semantics beat algorithmic convenience", "Price data must be complete; usage data may be incomplete")_
Validation rejects data that is incomplete, ambiguous, or impossible to price accurately. Registry interval closure, registry join-closedness, price ancestor coverage, and price join coverage are semantic completeness rules. They are not arbitrary requirements imposed to satisfy an algorithm.

**Units are data, not code.**
A pricing unit is defined once in data and propagated to every runtime. Adding a repo-defined unit should mean editing registry data, not adding Python fields, TypeScript interfaces, schema literals, extractor unions, and hand-maintained subtraction logic.

**Derive, don't duplicate.**
Field names, validation rules, containment relationships, usage inference, price-key resolution, extractor destinations, and display metadata should be derived from the registry wherever practical.

**Backward compatibility is preserved unless clearly impractical.** _(from "Units are data, not code")_
Existing consumer patterns such as `model_price.input_mtok`, `usage.input_tokens`, custom `ModelPrice` subclasses, `calc_price(usage)`, `UpdatePrices.fetch()`, and `set_custom_snapshot(...)` remain supported. This constrains how the registry is introduced.

**The registry model is a data-defined unit graph used by every runtime.** _(from "Units are data, not code", "Derive, don't duplicate")_
A registry contains unit families. A family has a normalization factor such as `per: 1_000_000` and units whose usage values can overlap. A unit has a usage key, a price key, and dimension assignments. The runtime parses that raw data into indexed `UnitFamily` and `UnitDef` objects so pricing, validation, extraction, and display all use the same source of truth.

**Usage keys and price keys have different jobs.** _(from "The registry model is a data-defined unit graph used by every runtime")_
The usage key names the reported or inferred count, such as `input_tokens`. The price key names the model-price/provider-YAML field, such as `input_mtok`. `price_key` defaults to the usage key only when they are the same.

**Dimensions define specificity and overlap.** _(from "The registry model is a data-defined unit graph used by every runtime")_
Dimension assignments such as `{direction: input}`, `{direction: input, cache: read}`, and `{direction: input, modality: audio, cache: read}` define containment. A unit is an ancestor of another unit when its dimensions are a subset of the other's dimensions. This structure replaces hardcoded token-specific subtraction chains.

**Registry-aware pricing decomposes usage by dimensions.** _(from "Dimensions define specificity and overlap", "Every usage value must land in exactly one pricing bucket")_
For each model, only the units with prices participate in decomposition. The runtime groups priced units by family, computes each priced unit's exclusive usage value from the dimension graph, multiplies by the stored price and family normalization factor, and aggregates costs. The shared inference and decomposition behavior is detailed in [algorithm](algorithm.md) and [examples](examples.md).

**Unit definitions must travel with prices.** _(from "Units are data, not code", "The registry model is a data-defined unit graph used by every runtime")_
Runtime clients can fetch updated price snapshots before the next package release. A fetched price payload must not contain prices for units the client cannot parse. The long-term data contract therefore carries unit families in the same snapshot as provider prices.

**The work is seven numbered phases, not one phase with subphases.** _(from "Backward compatibility is preserved unless clearly impractical", "Unit definitions must travel with prices")_
Each phase has its own prose spec and code spec. The prose spec states the behavioral target for that phase. The code spec states the implementation delta from the previous phase to that phase.

**Phase order is the review contract.** _(from "The work is seven numbered phases")_
Each phase should be reviewable and shippable after the previous phase. Later phases can influence earlier APIs only where the earlier phase must preserve an extension point; they must not pull their implementation work forward.

**Phase-local code specs are the implementation source of truth.** _(from "The work is seven numbered phases", "Phase order is the review contract")_
There is no top-level code spec. Use the phase-local prose spec plus the matching phase-local code spec. Phase 1 describes the implementation delta from the pre-registry baseline; Phases 2 through 7 describe only what must change after the previous phase is complete.

**Phase 1 proves the Python runtime model for the current unit surface.** _(from "Phase order is the review contract", "The registry model is a data-defined unit graph used by every runtime")_
[Phase 1: Python Internal Registry Refactor](phase-1-python-internal-registry/spec.md) ([code spec](phase-1-python-internal-registry/code-spec.md)) moves Python's existing hardcoded usage and price behavior behind a data-shaped `UnitRegistry`, registry-aware `Usage`, registry-backed `ModelPrice`, and generic decomposition for the current public unit set only. It preserves the current remote JSON shape and does not enable new repo-defined units.

**Phase 2 proves the JavaScript runtime model for the current unit surface.** _(from "Phase order is the review contract", "The registry model is a data-defined unit graph used by every runtime")_
[Phase 2: JavaScript Internal Registry Refactor](phase-2-javascript-internal-registry/spec.md) ([code spec](phase-2-javascript-internal-registry/code-spec.md)) gives JavaScript the same internal registry and decomposition model as Python while preserving current JavaScript behavior and the current remote JSON shape.

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
