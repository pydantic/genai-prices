# Data-Driven Unit Registry

**The goal is to calculate prices as accurately as possible for a given request.**
Every release improves pricing accuracy given the usage information and provider pricing information available to that installed package.

**Correct pricing semantics beat algorithmic convenience.** _(from "The goal is to calculate prices as accurately as possible for a given request")_
A provider's commercial pricing shape must be represented explicitly, even when that requires intermediate units and repeated numeric prices. A tidy implementation that misprices a model is not acceptable.

**Price data must be complete while usage data may be incomplete.** _(from "The goal is to calculate prices as accurately as possible for a given request")_
Repo-authored prices can be validated before publication. Caller and provider usage may be partial, so runtime code uses reported facts when sufficient and raises rather than guessing when required usage is omitted.

**Every priced usage value lands in exactly one bucket.** _(from "Price data must be complete while usage data may be incomplete")_
When units overlap, decomposition must not double-count, drop, or arbitrarily assign usage.

**Validation exists to protect pricing semantics.** _(from "Correct pricing semantics beat algorithmic convenience", "Price data must be complete while usage data may be incomplete")_
Registry structure, price ancestor coverage, price join coverage, and extractor destinations are completeness rules. User-facing errors describe invalid keys, incomplete prices, missing required usage, or contradictory usage rather than internal decomposition machinery.

**Units are data, not handwritten runtime fields.**
A repo-defined unit is declared once and propagated to Python, JavaScript, authoring schemas, validation, extraction, pricing, and display without copying ordinary unit names into each handwritten module.

**The registry is a usage-keyed dimension graph.** _(from "Units are data, not handwritten runtime fields")_
Each unit has a usage key, a price key, a normalization factor, and dimensions including a required `family` value. `price_key` defaults to the usage key. Dimension containment defines ancestors; compatible dimension unions define joins and overlap.

**Registry construction promotes raw data into immutable indexes.** _(from "The registry is a usage-keyed dimension graph")_
`UnitRegistry` turns raw unit dictionaries into `UnitDef` objects and indexes usage keys, price keys, dimension sets, ancestors, joins, reported keys, and registry order. Runtime code derives behavior from those indexes rather than generated code fields.

**Registry-aware pricing is dimension-driven.** _(from "The registry is a usage-keyed dimension graph", "Every priced usage value lands in exactly one bucket")_
Only units priced by the selected model become exclusive buckets. Each bucket's usage is multiplied by its price and divided by its unit normalization. Dimension filters aggregate input, output, and total costs. The detailed shared semantics are in [algorithm](algorithm.md) and [examples](examples.md).

**Unspecified dimensions are catch-alls.** _(from "Registry-aware pricing is dimension-driven")_
A priced ancestor receives the remainder not claimed by more-specific priced units. An unpriced reported descendant stays inside that ancestor when the necessary ancestor usage was explicitly reported; runtime code does not synthesize omitted parent totals.

**Ancestor and join coverage are required.** _(from "Validation exists to protect pricing semantics", "The registry is a usage-keyed dimension graph")_
Pricing a specific unit requires its registered ancestors. Pricing compatible incomparable units requires their registered intersection. Registry interval closure and join-closedness ensure the graph contains the structural units needed for these price rules.

**Usage remains explicit-only.** _(from "Price data must be complete while usage data may be incomplete")_
Stored values return directly. Safely missing registered values read as zero without becoming reported. Missing ancestors or overlaps raise when positive related reports would require inference. Contradictions remain inert until a read or selected price set must interpret them.

**Request pricing remains an explicit exception.** _(from "The registry is a usage-keyed dimension graph")_
Usage key `requests`, price key `requests_kcount`, `family: requests`, and `per: 1_000` represent one request supplied by pricing code. `requests` is not caller usage or an extractor destination.

**Tiered pricing behavior is preserved.** _(from "Correct pricing semantics beat algorithmic convenience")_
Existing threshold-based `TieredPrices` semantics remain unchanged. A selected tiered price reads `input_tokens` through the same explicit-only usage rules.

**Backward compatibility is preserved unless it conflicts with accurate registry pricing.**
Existing calculation APIs, price and usage attributes, provider/model lookup, custom snapshots, Python custom pricing overrides, JavaScript plain objects, tiered prices, and request pricing remain supported. Fixed-field introspection and incomplete overlap fallbacks are not promises when they conflict with data-driven units or complete pricing.

**Manual custom Python pricing remains supported.** _(from "Backward compatibility is preserved unless it conflicts with accurate registry pricing")_
Custom `ModelPrice` subclasses may inspect their own state and the original usage object. Standard registry pricing considers registered price fields without consuming unrelated custom fields.

**Generated outputs contain data, not runtime state.** _(from "Units are data, not handwritten runtime fields")_
Generated provider modules, unit modules, JSON artifacts, and schemas may contain raw provider, unit, and price data. They do not contain validation markers, trust flags, fingerprints, cached plans, or generated pricing behavior.

**Remote contracts are versioned instead of repurposed.**
Every package version keeps fetching a payload shape and unit vocabulary it understands. A new contract uses a new URL rather than changing the artifact consumed by already released auto-updaters.

**The v1 provider artifacts remain unchanged by this work.** _(from "Remote contracts are versioned instead of repurposed")_
Existing `data.json` and `data_slim.json` consumers continue receiving their provider-array contract and original unit vocabulary. The registry release does not wrap or add new unit-related fields to those artifacts.

**Phase 1 delivers a releasable static registry through provider-array v2 data.** _(from "Remote contracts are versioned instead of repurposed", "Registry construction promotes raw data into immutable indexes")_
[Phase 1: Static Unit Registry Release](phase-1-static-unit-registry-release/spec.md) ([code spec](phase-1-static-unit-registry-release/code-spec.md)) consolidates the completed Python, JavaScript, shared-registry, and polish work. Installed packages construct one bundled registry, auto-update providers from same-shape `data_v2.json`, include new modality pricing, and remove obvious repeated hot-path scans without cache state.

**Phase 2 adds auto-updating unit definitions through wrapped v3 data.** _(from "Remote contracts are versioned instead of repurposed", "Phase 1 delivers a releasable static registry through provider-array v2 data")_
[Phase 2: Auto-Updating Unit Definitions](phase-2-auto-updating-units/spec.md) ([code spec](phase-2-auto-updating-units/code-spec.md)) is a future independent PR. It publishes `data_v3.json` with units and providers, activates them atomically, and preserves v1/v2 URLs. It is not required for the Phase 1 release.

**Runtime custom units remain deferred.** _(from "Phase 1 delivers a releasable static registry through provider-array v2 data", "Phase 2 adds auto-updating unit definitions through wrapped v3 data")_
Phase 1 supports repo-defined bundled units and Phase 2 supports publisher-defined remote units. Neither phase promises arbitrary caller-defined registry mutation as a public runtime feature.

**Validation and decomposition caches remain deferred.** _(from "Phase 1 delivers a releasable static registry through provider-array v2 data")_
Phase 1 removes repeated scans and allocations without cache lifecycle state. More elaborate validation or decomposition caches require new benchmark evidence and a separate specification; they are not an active numbered phase.

**Phase-local prose and code specs are the implementation source of truth.** _(from "Phase 1 delivers a releasable static registry through provider-array v2 data", "Phase 2 adds auto-updating unit definitions through wrapped v3 data")_
The root spec defines shared invariants and delivery boundaries. Each numbered phase's `spec.md` defines behavior, and its `code-spec.md` defines the corresponding architecture. Later requirements do not expand an earlier phase's release scope.
