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

**The runtime compatibility surface is deliberately minimal.**
Installed packages expose and carry only metadata required to identify units, read usage, validate selected prices, decompose quantities, and calculate costs. Build-time convenience does not justify adding fields to generated runtime data or runtime types: even nominally internal fields can constrain future representation changes once shipped.

**Backward compatibility is preserved unless it conflicts with accurate registry pricing.**
Existing calculation APIs, price and usage attributes, provider/model lookup, custom snapshots, Python custom pricing overrides, JavaScript plain objects, tiered prices, and request pricing remain supported. Fixed-field introspection and incomplete overlap fallbacks are not promises when they conflict with data-driven units or complete pricing.

**Unknown unit names are publication errors but runtime warnings.** _(from "Validation exists to protect pricing semantics", "Backward compatibility is preserved unless it conflicts with accurate registry pricing")_
The source registry defines usage names and validates their identity and structure, while the build rejects provider price keys and extractor destinations absent from that registry before repository data or generated packages are published. An installed runtime may instead encounter data authored for a different registry version or retained by consumer code across an upgrade. Direct standard `Usage` construction, base-model extraction, and base-model pricing therefore warn about names that the active registry cannot use, ignore those names for standard calculations, and continue with recognized data. Unknown extractor mappings are skipped entirely, including their source-path requirements. Generic raw-object normalization silently selects recognized attributes because unrelated object state is not presented as registry data, and Python custom-subclass state remains owned by the subclass rather than being diagnosed by base pricing. This tolerance may produce a partial price, which the warning makes explicit; it does not weaken runtime errors for invalid values attached to recognized names, incomplete ancestor or join prices among recognized units, missing required recognized usage, or contradictory recognized usage.

**The registry is a usage-keyed dimension graph.** _(from "Units are data, not handwritten runtime fields")_
Each unit has a usage key, a price key, a normalization factor, and dimensions including a required `family` value. `price_key` defaults to the usage key. Dimension containment defines ancestors; compatible dimension unions define joins and overlap.

**Dimension axes remain unit-local and general.** _(from "The registry is a usage-keyed dimension graph")_
Unit dimension mappings are the only declaration of dimension keys and values; there is no separate allowed-dimension schema. Families may represent tokens, requests, characters, duration, tool calls, or future reported quantities that use `usage * price / normalization`, provided their actual unit graph satisfies the shared structural rules.

**Usage values are finite non-negative quantities.** _(from "Dimension axes remain unit-local and general", "Correct pricing semantics beat algorithmic convenience")_
Every reportable unit accepts whole or fractional usage. The registry does not classify units as discrete or continuous: duration naturally requires fractions, and rejecting fractions for selected families is not needed for correct linear pricing or decomposition. Python stores recognized usage as `int | float | Decimal`, preserving each supplied built-in numeric kind, while JavaScript stores `number`. Accepted non-boolean Python `Integral` implementations normalize to built-in `int` for backward compatibility. Booleans, non-finite values, negative values, and other numeric objects are invalid recognized usage. Missing values remain distinct from explicit zero.

**Usage arithmetic preserves numeric domains with intuitive decimal sums.** _(from "Usage values are finite non-negative quantities", "Backward compatibility is preserved unless it conflicts with accurate registry pricing")_
Python integer-only usage arithmetic remains integer arithmetic. Other Python usage operations convert integers exactly, interpret floats through their shortest round-trippable decimal spellings, and use supplied Decimals directly in a private Decimal context independent of caller context. A result is Decimal if any operand was Decimal, otherwise float if any operand was float, otherwise int. Thus `0.1 + 0.2` produces the same stored float as literal `0.3`, while Decimal participation retains a Decimal result. This policy does not claim to recover decimal intent already lost before a float reaches the package. Decimal-bearing usage is intentionally not JSON-native. JavaScript retains ordinary number arithmetic and its existing rounding guardrails; cross-language fractional behavior requires numerical equivalence for JSON-origin values rather than identical runtime numeric types or binary intermediates.

**Build validation may use replaceable metadata for conditional dimensions.** _(from "Dimension axes remain unit-local and general", "Validation exists to protect pricing semantics", "The runtime compatibility surface is deliberately minimal")_
The source registry must give publication validation enough information to recognize subtype-specific axes. In particular, a candidate dimension set containing `cache_ttl` is structurally meaningful only with `token_type: cache_write`. The exact source representation and validation technique are build implementation details: `dimension_requirements` is an acceptable current mechanism, but the build may replace it with another approach without changing generated runtime data or package compatibility.

**Built-in token categories are mutually exclusive.** _(from "Dimension axes remain unit-local and general", "Every priced usage value lands in exactly one bucket")_
The built-in token family uses `token_type` for mutually exclusive commercial categories including cache reads, cache writes, tool-use input, reasoning output, and citation output. Direction and modality remain independent dimensions. Cache writes additionally use `cache_ttl` for provider-reported write duration; `cache_ttl` requires `token_type: cache_write`, so cache durations do not intersect cache reads or tool-use input. Units declare only the directions in which a category is meaningful, so the registry does not require input reasoning or output tool-use counterparts. Omitting `token_type` is the catch-all for tokens not assigned to a more specific priced category.

**Registry construction promotes raw data into immutable indexes.** _(from "The registry is a usage-keyed dimension graph")_
`UnitRegistry` turns the runtime projection of unit data into `UnitDef` objects and indexes usage keys, price keys, dimension sets, ancestors, joins, reported keys, and registry order. Runtime code derives behavior from those indexes rather than generated code fields or build-only validation metadata.

**Registry identities and normalization are safe and unambiguous.** _(from "Validation exists to protect pricing semantics", "Registry construction promotes raw data into immutable indexes")_
Usage keys, price keys, and full dimension sets are globally unique. Public keys match `[A-Za-z][A-Za-z0-9_]*`, are neither Python nor JavaScript keywords, and are not any of the exact prototype hazards `__proto__`, `prototype`, or `constructor`. Every unit in one `family` dimension value uses the same normalization factor.

**Registry-aware pricing is dimension-driven.** _(from "The registry is a usage-keyed dimension graph", "Every priced usage value lands in exactly one bucket")_
Only units priced by the selected model become exclusive buckets. Each bucket's usage is multiplied by its price and divided by its unit normalization. Dimension filters aggregate input, output, and total costs. The detailed shared semantics are in [algorithm](algorithm.md) and [examples](examples.md).

**Unspecified dimensions are catch-alls.** _(from "Registry-aware pricing is dimension-driven")_
A priced ancestor receives the remainder not claimed by more-specific priced units. An unpriced reported descendant stays inside that ancestor when the necessary ancestor usage was explicitly reported; runtime code does not synthesize omitted parent totals.

**Catch-all rates follow the provider's unclassified remainder.** _(from "Unspecified dimensions are catch-alls", "Correct pricing semantics beat algorithmic convenience")_
Provider pricing data assigns an ancestor's rate from what remains unclassified in that provider's usage shape, not from the model's headline modality. When an aggregate output count contains mixed output and its detail array reports image tokens while omitting ordinary text, `output_mtok` carries the text rate and `output_image_mtok` carries the image rate. The unclassified remainder is then priced as text without fabricating an `output_text_tokens` report.

When an endpoint defines an aggregate count as entirely one modality, the ancestor may carry that modality's rate even when the extractor also reports the explicit modality descendant. An equal-rate descendant price remains redundant unless another priced descendant or join requires it. For example, an image endpoint whose `output_tokens` are defined as image tokens may use the image rate as `output_mtok`, report both `output_tokens` and `output_image_tokens`, and omit `output_image_mtok` when the rates would be equal.

**Ancestor and join coverage are required.** _(from "Validation exists to protect pricing semantics", "The registry is a usage-keyed dimension graph")_
Pricing a specific unit requires its registered ancestors. Pricing compatible incomparable units requires their registered intersection. Registry interval closure and join-closedness ensure the graph contains the structural units needed for these price rules.

**Structural closure has exact data-level definitions.** _(from "Ancestor and join coverage are required")_
For interval closure, if `A` is an ancestor of `B`, every valid dimension set made by adding a non-empty proper subset of `B.dimensions - A.dimensions` to `A.dimensions` exists as a unit. Build validation decides validity using the applicable conditional-dimension rule. For join-closedness, two units are compatible only when their dimension union has no conflicting assignments and satisfies the applicable conditional-dimension rules; the union of every compatible pair exists as a unit.

**Registry closure preserves future and custom pricing expressiveness.** _(from "Structural closure has exact data-level definitions", "Backward compatibility is preserved unless it conflicts with accurate registry pricing")_
Closure applies to registered units even when checked-in provider data does not currently price every unit. Every registered unit exposes a price key that publisher updates and standard custom `ModelPrice` instances may use. A registry that omitted a compatible intersection would advertise price keys that could not be priced together under standard decomposition because no join price key would exist. Publication therefore validates the complete registered graph, while selected-model validation separately requires prices for the ancestors and joins used by that model. Unpriced units do not become calculation buckets, so structural units that a selected model does not price do not add decomposition work.

**Built-in token symmetry is a data choice, not a validation law.**
The built-in token family defines input, output, cache-read, cache-write, cache-write TTL, tool-use, reasoning, citation, and supported modality patterns consistently where those concepts make sense, while omitting nonsensical direction/category combinations such as output cache reads. Token categories may overlap a modality, so the built-in graph includes their aggregate and supported text, audio, image, and video joins. Cache-write TTL units likewise include aggregate and modality intersections. Different `token_type` values are incompatible and do not require intersections with one another; the cache TTL requirement prevents subtype-specific TTL values from creating cross-category joins. Arbitrary future families need only satisfy the structural definitions for the units they actually define.

**Anthropic cache writes retain an aggregate fallback and expose TTL detail.** _(from "Unspecified dimensions are catch-alls", "Correct pricing semantics beat algorithmic convenience")_
`cache_write_tokens` remains the aggregate of cache-creation tokens and carries Anthropic's default five-minute write rate. Anthropic's `cache_creation.ephemeral_5m_input_tokens` and `cache_creation.ephemeral_1h_input_tokens` are also extracted to their TTL-specific descendants. Pricing the one-hour descendant at the published one-hour rate makes the aggregate remainder the five-minute bucket. If an older response omits the breakdown, the reported aggregate still receives the default five-minute rate rather than losing cache-write pricing.

**Usage remains explicit-only.** _(from "Price data must be complete while usage data may be incomplete")_
Stored values return directly. Safely missing registered values read as zero without becoming reported. Missing ancestors or overlaps raise when positive related reports would require inference. Contradictions remain inert until a read or selected price set must interpret them.

**Extractors validate each reported component before accumulation.** _(from "Usage values are finite non-negative quantities", "Validation exists to protect pricing semantics")_
Every recognized mapped number is validated before it is added to its destination. A negative or non-finite component cannot be hidden by a positive sibling mapping, and Python booleans cannot become integer counts through addition. Optional mappings may still probe absent or structurally incompatible paths according to their optional-path rules, but a present numeric value outside the valid domain is an error. Cross-field ancestor and overlap consistency remains lazy and demand-driven after extraction.

**Commercial price categories do not imply reported usage dimensions.** _(from "Usage remains explicit-only", "Correct pricing semantics beat algorithmic convenience")_
A provider saying that reasoning is billed at its text rate does not establish that the provider's reasoning count has text modality. Extractors record a reasoning/modality intersection only when the response contract reports or defines that intersection; pricing can still leave unclassified reasoning in a text-rate ancestor catch-all.

**Request pricing remains an explicit exception.** _(from "The registry is a usage-keyed dimension graph")_
Usage key `requests`, price key `requests_kcount`, `family: requests`, and `per: 1_000` represent one request supplied by pricing code. `requests` is not caller usage or an extractor destination.

**Web searches are reportable tool calls.** _(from "The registry is a usage-keyed dimension graph", "Correct pricing semantics beat algorithmic convenience")_
Usage key `web_searches`, price key `web_searches_kcount`, `family: tool_calls`, and `per: 1_000` represent provider-reported billable web searches. Extractors map a provider's documented search count to this unit. Because the unit has no input or output direction, its price contributes to total cost without being assigned to input or output cost.

**Tiered pricing behavior is preserved.** _(from "Correct pricing semantics beat algorithmic convenience")_
Existing threshold-based `TieredPrices` semantics and integer tier starts remain unchanged. A selected tiered price reads whole or fractional `input_tokens` through the same explicit-only usage rules and compares that quantity directly with the integer threshold.

**Manual custom Python pricing remains supported.** _(from "Backward compatibility is preserved unless it conflicts with accurate registry pricing")_
Custom `ModelPrice` subclasses may inspect their own state and the original usage object. Standard registry pricing considers registered price fields without consuming unrelated custom fields.

**Provider data changes stay limited to pricing requirements.** _(from "Backward compatibility is preserved unless it conflicts with accurate registry pricing", "Price data must be complete while usage data may be incomplete")_
Registry work does not rename or restructure provider YAML for its own sake. Provider-data changes repair real completeness or accuracy gaps, including an explicit repeated price when ancestor or join coverage requires one.

**Generated runtime outputs contain only runtime-semantic data.** _(from "Units are data, not handwritten runtime fields", "The runtime compatibility surface is deliberately minimal")_
Generated package unit modules contain only usage identity, price identity, normalization, and dimensions. They omit `dimension_requirements` and any future source-only closure hints, authoring annotations, validation markers, trust flags, fingerprints, or build intermediates. Generated provider modules and runtime JSON artifacts likewise contain provider and price data needed by installed packages, not generated pricing behavior or build-validation machinery. Build-side schemas and diagnostics may retain richer metadata because they are replaceable authoring infrastructure rather than installed runtime contracts.

**Remote contracts are versioned instead of repurposed.**
Every package version keeps fetching a payload shape and unit vocabulary it understands. A new contract uses a new URL rather than changing the artifact consumed by already released auto-updaters.

**New remote contract versions use versioned directories.** _(from "Remote contracts are versioned instead of repurposed")_
Version 2 publishes under `prices/new_data/v2/`, version 3 under `prices/new_data/v3/`, and later contracts follow the same `prices/new_data/v<version>/` layout. Each directory uses stable artifact names such as `data.json`, `data.schema.json`, `data_slim.json`, and `data_slim.schema.json`, so adding a contract version does not keep expanding the flat `prices/` directory.

**The v1 provider artifacts retain their released-client compatibility contract.** _(from "Remote contracts are versioned instead of repurposed")_
Existing `data.json` and `data_slim.json` consumers continue receiving provider arrays at the same URLs using the v1 structure and vocabulary. The compatibility oracle for both payloads is `prices/data.schema.json` at target-main commit `ba8093719f296a3672ff4b2fc848a122e92a049c`, which describes the common provider-array input accepted by v1 package decoders. Each maintained payload must validate against that baseline schema. Exact byte identity is not part of this contract, so compatible provider, model, and pricing data may change. The current schema artifacts are not updater inputs and may evolve independently; they do not justify publishing v1 data that fails the baseline oracle.

**Phase 1 delivers a releasable static registry through full and slim provider-array v2 data.** _(from "New remote contract versions use versioned directories", "Registry construction promotes raw data into immutable indexes")_
[Phase 1: Static Unit Registry Release](phase-1-static-unit-registry-release/spec.md) ([code spec](phase-1-static-unit-registry-release/code-spec.md)) consolidates the completed Python, JavaScript, shared-registry, and polish work. Installed packages construct one bundled registry, auto-update providers from full same-shape `prices/new_data/v2/data.json`, include new modality pricing, and remove obvious repeated hot-path scans without cache state. Phase 1 also publishes a compatible slim projection for consumers that choose the smaller artifact.

**Phase 2 adds auto-updating unit definitions through wrapped v3 data.** _(from "Remote contracts are versioned instead of repurposed", "Phase 1 delivers a releasable static registry through full and slim provider-array v2 data")_
[Phase 2: Auto-Updating Unit Definitions](phase-2-auto-updating-units/spec.md) ([code spec](phase-2-auto-updating-units/code-spec.md)) is a future independent PR. It publishes `prices/new_data/v3/data.json` with units and providers, activates them atomically, and preserves v1/v2 URLs. It is not required for the Phase 1 release.

**Runtime custom units remain deferred.** _(from "Phase 1 delivers a releasable static registry through full and slim provider-array v2 data", "Phase 2 adds auto-updating unit definitions through wrapped v3 data")_
Phase 1 supports repo-defined bundled units and Phase 2 supports publisher-defined remote units. Neither phase promises arbitrary caller-defined registry mutation as a public runtime feature.

**Validation and decomposition caches remain deferred.** _(from "Phase 1 delivers a releasable static registry through full and slim provider-array v2 data")_
Phase 1 removes repeated scans and allocations without cache lifecycle state. More elaborate validation or decomposition caches require a separate specification; they are not an active numbered phase.

**Phase prose specs are the implementation source of truth.** _(from "Phase 1 delivers a releasable static registry through full and slim provider-array v2 data", "Phase 2 adds auto-updating unit definitions through wrapped v3 data")_
The root spec defines shared invariants and delivery boundaries, while each numbered phase's `spec.md` contains that phase's complete requirements. A phase's `code-spec.md` is supporting implementation detail: it traces details to prose requirements but cannot introduce a requirement or expand release scope. Later requirements likewise do not expand an earlier phase's release scope.
