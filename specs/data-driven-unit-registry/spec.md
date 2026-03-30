# Data-Driven Unit Registry

**The goal is to calculate prices as accurately as possible for a given request.**
This is the reason the system exists. Every design decision traces back to this: maximize pricing accuracy given the information available.

**Price data must be complete; usage data may be incomplete.** _(from "The goal is to calculate prices as accurately as possible")_
These are two different kinds of information with different completeness guarantees. Price data is authored by us (in provider YAML files) — we control it and can enforce completeness. If a model prices cached tokens and audio tokens, it must also price cached-audio tokens; anything less is a data quality bug, not an acceptable approximation. Usage data comes from callers at runtime — they provide what they have (sometimes just `input_tokens` and `output_tokens` from OpenTelemetry). We give the best answer possible with incomplete usage, but we don't accept incomplete prices.

**Every usage value must land in exactly one pricing bucket.** _(from "Price data must be complete")_
When a model prices overlapping units (e.g., "all input tokens" and "cached input tokens"), the system assigns each token-count to exactly one bucket. No double-counting, no dropped tokens. This is a correctness invariant enforced by price data completeness — it's not something we approximate or hope for.

**Units are data, not code.**
A pricing unit — the thing you multiply usage by to get a cost — is defined once in a data file. That definition propagates to every language implementation. Adding a new unit requires editing a data file, nothing else. No Python class, no TypeScript interface, no schema update.

**Derive, don't duplicate.**
If information exists in one place, compute it elsewhere rather than copying it. Field names, validation rules, dimensional relationships — anything that can be derived from the registry should be derived, not restated in code.

**Backward compatibility is preserved unless clearly impractical.** _(from "Units are data, not code")_
Existing consumer code must continue to work. `model_price.input_mtok`, `usage.input_tokens`, `calc_price(usage)` — these patterns are the public API. This constrains how we implement data-driven units, not whether.

**Existing provider YAML files are mostly unchanged.** _(from "Backward compatibility", "Price data must be complete")_
Changes are justified only by genuine data gaps — e.g., a model that prices cached tokens and audio tokens but not cached-audio tokens fails a validation rule we're adding for good reason. No mass field renames, no restructuring for its own sake. This goes against "Price data must be complete" only in appearance — adding a missing cached-audio price IS making the data complete; it's not churn.

**Users can define custom units at runtime.** _(from "Units are data, not code")_
Without modifying the repository, without making a PR. Custom units are first-class: same mechanisms, same validation, same decomposition as built-in units. Users can add units to existing families or create entirely new families. Runtime-defined units are merged with built-in units and subject to the same validation — including ID uniqueness and dimension-set uniqueness within a family.

**Custom units arrive via DataSnapshot, the same path as custom prices.** _(from "Users can define custom units at runtime", "Unit definitions travel with prices")_
`DataSnapshot` already carries prices (as providers/models). Unit definitions belong there too — they travel together. The bundled snapshot gets its units from generated code; a custom snapshot includes additional or overridden families alongside its custom providers. Users construct `UnitFamily`/`UnitDef` objects (public classes) and include them in the snapshot. No separate registry API is needed — the entry point is the one that already exists for custom prices.

**The system is general across unit families.** _(from "Units are data, not code")_
Any unit with the structure `usage_value x price / normalization_factor` is expressible: tokens (per million), requests (per thousand), characters, duration, etc. Tokens are the first and most complex family (because of overlapping usage), but nothing in the system is token-specific. Future families require only a data file edit.

**A unit family groups units whose usage values can overlap.** _(from "The system is general")_
Each family has a normalization factor (`per: 1_000_000` for tokens). Within a family, a more-specific unit's usage is a subset of a less-specific one's (`cache_read_tokens` is a subset of `input_tokens`). Between families, there is no overlap — request counts don't interact with token counts.

**`requests_kcount` becomes a unit in a `requests` family.** _(from "The system is general", "A unit family groups units")_
The existing `requests_kcount` field is a hardcoded special case — a price per thousand requests. It belongs in the registry as a unit in a `requests` family with `per: 1_000`. The `requests` family has no dimensions — it's a single unit with no overlapping subtypes (no decomposition needed). The unit ID stays `requests_kcount` and the usage key is `requests`. This eliminates the last hardcoded pricing field from ModelPrice and makes request pricing subject to the same mechanisms as token pricing.

**Dimensions define unit specificity and overlap.** _(from "A unit family groups units")_
Each unit carries zero or more categorical dimension assignments: `{direction: input}`, `{direction: input, cache: read}`, `{direction: input, modality: audio, cache: read}`. More dimensions = more specific. The containment relationship — which units are ancestors/descendants of which — is determined by set inclusion on dimensions: if A's dimensions are a subset of B's, A is an ancestor of B. This structure is the basis for decomposition and for all validation rules.

**Decomposition uses dimensions, not hardcoded subtraction chains.** _(from "Dimensions define unit specificity", "Every usage value must land in exactly one pricing bucket")_
The current code subtracts specific unit values from general ones in a manually maintained order. The replacement: Mobius inversion on the containment poset defined by dimensions. The algorithm takes the set of priced units, computes each one's "leaf value" (exclusive portion of usage), and guarantees no double-counting. No code names specific units — the algorithm works from the dimension structure alone. See [algorithm](algorithm.md) for the formula and multi-way overlap handling.

**Only priced units participate in decomposition.** _(from "Decomposition uses dimensions")_
If a model doesn't price `input_audio_mtok`, audio tokens remain part of the `input_mtok` catch-all — they are not carved out. The decomposition is determined by the set of units that have prices for the current model, not the full registry. This is what makes partial pricing work: a model that only prices `input_mtok` and `output_mtok` still produces correct results.

**Decomposition operates within a family.** _(from "Decomposition uses dimensions", "A unit family groups units")_
Token decomposition does not affect request pricing. Each family's decomposition is independent — there is no cross-family overlap to resolve.

**Aggregate counts and costs are queryable by dimension filter.** _(from "Decomposition uses dimensions", "Dimensions define unit specificity")_
After decomposition, it must be possible to ask "how many tokens match this set of dimensions?" and get a correct answer — by summing the leaf values of all priced units whose dimensions are a superset of the filter. The same applies to costs: "what is the total cost for {direction: input}?" sums the leaf costs of all input-side units. Examples: all input tokens ({direction: input}), all cache read tokens ({cache: read}), all audio tokens ({modality: audio}) regardless of direction, all tokens (empty filter). A filter matching no priced units returns zero. This is the general mechanism behind things like TieredPrices, where the tier threshold is currently hardcoded to `input_tokens` but should be expressible as a dimension filter ({direction: input}).

**TieredPrices is not refactored in this change.** _(from "Aggregate counts and costs are queryable", "Backward compatibility")_
The existing TieredPrices mechanism (threshold-based pricing where crossing a tier applies that rate to all tokens) continues to work as-is. The aggregate query mechanism generalizes the concept but TieredPrices is not modified to use it — that's a separate future change.

**`input_price` and `output_price` are backward-compat accessors over dimension-filtered costs.** _(from "Aggregate counts and costs are queryable", "Backward compatibility")_
`calc_price` currently returns `{input_price, output_price, total_price}`. The input/output grouping is not hardcoded — it's a cost aggregate filtered by `{direction: input}` and `{direction: output}` respectively. These names are kept for backward compatibility as accessors over the general mechanism. Costs from families without a `direction` dimension (e.g., requests) appear only in `total_price`, not in `input_price` or `output_price`.

**Unspecified dimensions mean catch-all: the unit prices whatever isn't claimed by a more specific unit.** _(from "Dimensions define unit specificity", "Only priced units participate")_
`input_mtok` has no `modality` dimension — it's the catch-all for all input tokens not claimed by a modality-specific unit. The catch-all implicitly functions as the default modality. For text-primary models (most models), `input_mtok` IS the text price — no `input_text_mtok` needed. For image-primary models, the catch-all should be the image price: set `input_mtok` and `input_image_mtok` to the same value, and define `input_text_mtok` as the exception. See [examples](examples.md) for concrete pricing patterns.

**Ancestor coverage: pricing a unit requires pricing all its ancestors.** _(from "Price data must be complete", "Decomposition uses dimensions")_
If a model prices `cache_read_mtok` ({direction: input, cache: read}), it must also price `input_mtok` ({direction: input}). Without the ancestor, usage reported at the general level (just `input_tokens`, no breakdown) would have no price. This is a price data completeness requirement — validated, not assumed.

**Join coverage: pricing two overlapping units requires pricing their intersection.** _(from "Price data must be complete", "Decomposition uses dimensions")_
If a model prices both `cache_read_mtok` and `input_audio_mtok`, their join — the unit with the union of both dimension sets, `{direction: input, cache: read, modality: audio}` — must also be priced, if it exists in the registry. Without this, Mobius inversion double-counts tokens that belong to both parents. This is not a nice-to-have — it's a direct consequence of requiring accurate prices. Each token in one bucket, not two.

**The registry defines all dimension combinations symmetrically.** _(from "Join coverage")_
Every modality defines all four token slots (input, output, cache read, cache write) even where no provider currently uses them. Models simply don't define prices for unused units.

**Symmetric definitions ensure join coverage can always fire.** _(from "The registry defines all dimension combinations symmetrically", "Join coverage")_
Because all combinations exist, the join of any two priced units is guaranteed to exist in the registry. Join coverage validation never encounters a "join doesn't exist" gap.

**Unit definitions travel with prices, not just with the package.** _(from "Units are data, not code", "Users can define custom units at runtime")_
Currently, prices are in `data.json` which clients can auto-update at runtime (pulled on merge, before a package release). Unit definitions are in `units.json`, bundled into the Python/JS packages — only updated on package release. This means a new unit's prices could arrive before the client knows the unit exists. Unit definitions must be included in `data.json` (and `data_slim.json`) so they travel together with the prices that depend on them. When a client pulls fresh price data, it gets the units too.

**The registry is a YAML file that defines all built-in units.** _(from "Units are data, not code", "Derive, don't duplicate")_
One file, checked into the repo (`prices/units.yml`). It defines families, their normalization factors, their dimension axes, and their units (each with an ID, a usage key, and dimension assignments). The `tokens` family declares three dimension axes: `direction` (input, output), `modality` (text, audio, image, video), and `cache` (read, write). At build time, this file is compiled into `data.json` alongside prices. At runtime, the registry is loaded from the same data the client already has — no separate file needed.

**Naming optimizes for writability: people discover names by pattern-matching from existing ones.** _(from "Backward compatibility")_
Provider YAML files and usage objects are written frequently. People figure out names by looking at what's already there and extrapolating, not by memorizing a convention document. Consistency across unit names matters because inconsistency is how people get tripped up — seeing `cache_audio_read` and guessing `cache_image_read` must work (and it does, because the names are consistent). The convention for cached+modality units follows the pre-existing `cache_audio_read` pattern: `cache_{modality}_{op}`. For non-cached: `{direction}_{modality}`. Usage keys follow the same pattern with `_tokens` suffix.

**Generated JSON schemas provide editor autocomplete for provider YAML files.** _(from "Naming optimizes for writability", "The registry is a YAML file")_
The unit registry generates a JSON schema that provider YAML files reference (via the `yaml-language-server` directive). This gives autocomplete and validation in editors, reducing reliance on memorizing names. The schema is regenerated whenever the registry changes.

**ModelPrice supports attribute access backed by registry data.** _(from "The registry is a YAML file", "Backward compatibility")_
ModelPrice is not a plain dict — that would break `model_price.input_mtok`. It's an object that supports attribute access, but the set of valid attributes comes from the registry. New units added to the registry are immediately accessible as attributes. Legacy names like `input_mtok` continue to work. Keeping typed property definitions for existing names is acceptable as a backward-compat shim — but it's a convenience for type checkers, not the source of truth. Future names need no code changes.

**Usage is accessed dynamically by key.** _(from "The registry is a YAML file", "Derive, don't duplicate")_
Each unit defines a `usage_key` — the attribute name to look up on the usage object (e.g., `input_tokens` for unit `input_mtok`). The engine uses `getattr`/Mapping access. No typed Protocol enumerates usage fields. Callers provide whatever they have; missing values are zero.

**Usage key defaults to unit ID if not specified.** _(from "Usage is accessed dynamically")_
Unit IDs like `input_mtok` encode normalization (per-million). Usage values like `input_tokens` are raw counts. The `usage_key` field bridges the two — the system looks up `input_tokens` on the usage object and applies the `input_mtok` price with the family's `per: 1_000_000`. For the tokens family, every unit has an explicit `usage_key` because of this naming split. For families where the unit ID and usage key are the same (e.g., a future `tool_calls` family), the default avoids redundancy.

**Incomplete usage is handled gracefully, not rejected.** _(from "Price data must be complete; usage data may be incomplete", "Usage is accessed dynamically")_
A caller with only `{input_tokens: 1000, output_tokens: 500}` gets a valid price at catch-all rates. A caller with detailed breakdowns gets a more precise price. The system handles both — missing usage values default to zero (no carve-out), and the decomposition adapts to whatever units are priced. The accuracy limitation is accepted because it comes from the caller's data, not from ours. Conversely, if a caller provides a usage key (e.g., `input_video_tokens: 100`) for a model that doesn't price `input_video_mtok`, those tokens silently remain in the catch-all ancestor — the decomposition only considers priced units. Usage for a family with no priced units at all (e.g., `requests: 5` on a model with no request pricing) is silently ignored — there is nothing to decompose or price.

**Inconsistent usage is rejected.** _(from "Every usage value must land in exactly one pricing bucket", "Incomplete usage is handled gracefully")_
Incomplete and inconsistent are different. Missing `cache_read_tokens` means we assume zero cached tokens — that's fine. But `cache_read_tokens > input_tokens` is contradictory: a subset can't exceed its superset. Decomposition detects this as a negative leaf value and raises an error. This is the right behavior — silently producing a wrong price is worse than failing loudly.

**Validation replaces what hardcoded fields gave us implicitly, and adds more.** _(from "Units are data, not code", "Derive, don't duplicate")_
Hardcoded ModelPrice fields provided implicit validation: a typo like `inptu_mtok` would fail because the field doesn't exist. Moving to data-driven units means explicit validation must replace that safety net and go further. Validation is comprehensive — it's cheaper to reject bad data at build/construction time than to debug wrong prices at runtime.

**Expensive validation happens once at definition time, not on every load.** _(from "Validation replaces what hardcoded fields gave us", "Unit definitions travel with prices")_
The repo contains thousands of model prices. Structural validation — ancestor coverage, join coverage, dimension consistency — is expensive (O(n^2) for join coverage over priced units). This validation runs in the build pipeline when prices are defined. The build pipeline produces multiple outputs — `data.json`/`data_slim.json` for runtime updates, and generated code like `data.py` (Python) that embeds the same data as language-native structures. All of these outputs are pre-validated. The distinction is not about file format (JSON vs Python) — it's about provenance: data that came through the build pipeline is trusted; data constructed at runtime by users is validated on the spot. Expensive validation only runs for runtime-defined prices (custom units, programmatic ModelPrice construction).

**Unit definitions are generated into language-native code alongside prices.** _(from "Unit definitions travel with prices", "Expensive validation happens once at definition time")_
Each language package has a generated file that embeds all price data as language-native structures — `data.py` for Python, the equivalent for JavaScript. This is what loads at startup, not `data.json`. The `data.json` file exists for runtime auto-updates (refreshing prices in a long-running process). All of these must contain unit definitions. The build pipeline generates unit definitions into the language-native files as code, and into `data.json` as data. When `data.json` is fetched at runtime to update prices, the unit definitions it carries are also loaded — but since they too came through the build pipeline, they're trusted.

**Price key validation: every key in a model's prices must be a registered unit ID.** _(from "Validation replaces what hardcoded fields gave us")_
If a provider YAML file has `prices: { inptu_mtok: 3 }`, the build fails. This replaces the implicit validation that hardcoded Pydantic/dataclass fields provided. Checked at build time (data pipeline) and at construction time (ModelPrice).

**Dimension validation: unit dimension keys and values must match their family's declarations.** _(from "Validation replaces what hardcoded fields gave us", "Dimensions define unit specificity")_
A unit in the `tokens` family can only use dimension keys declared for that family (`direction`, `modality`, `cache`), and only with declared values (`direction: input` is valid; `direction: sideways` is not). Checked when the registry is loaded.

**Unit IDs are globally unique across all families.** _(from "Validation replaces what hardcoded fields gave us", "ModelPrice supports attribute access")_
A unit ID identifies a single unit in the entire registry, not just within its family. ModelPrice uses unit IDs as attribute names — if two families could share a unit ID, attribute access would be ambiguous.

**Unit uniqueness: no two units in a family may have identical dimension sets.** _(from "Validation replaces what hardcoded fields gave us", "Dimensions define unit specificity")_
Dimensions uniquely identify a unit's position in the containment poset. Two units with the same dimensions would be the same slot — that's a data error, not an edge case.

**Usage key uniqueness: no two units may share the same usage key.** _(from "Validation replaces what hardcoded fields gave us", "Usage is accessed dynamically")_
A usage key maps one-to-one to a unit. If two units read from the same usage field, decomposition can't distinguish their contributions.

**Ancestor coverage is validated.** _(from "Ancestor coverage: pricing a unit requires pricing all its ancestors", "Expensive validation happens once at definition time")_
Checked in the build pipeline for repo-defined prices, and at construction time for runtime-defined prices. Not deferred to calc_price.

**Join coverage is validated.** _(from "Join coverage: pricing two overlapping units requires pricing their intersection", "Expensive validation happens once at definition time")_
For every pair of priced units, if their dimension-union corresponds to a unit in the registry, that unit must also be priced. Checked in the build pipeline for repo-defined prices, and at construction time for runtime-defined prices.

**Price sanity checks warn on violations of common economic inequalities.** _(from "The goal is to calculate prices as accurately as possible", "Validation replaces what hardcoded fields gave us")_
Some pricing relationships hold across nearly all models: cache reads are cheaper than uncached input, cache writes are more expensive, text is the cheapest modality. These aren't hard constraints — a model might legitimately break them — but violations are worth flagging as warnings during the build pipeline. They catch data entry mistakes ("did you swap cache_read and cache_write prices?") without blocking unusual-but-correct pricing. The inequalities should be expressible in terms of dimensions (e.g., "within the same direction and modality, cache=read ≤ uncached ≤ cache=write") rather than listing specific unit pairs.

**Validation rules are expressed in terms of dimensions, not unit names.** _(from "Derive, don't duplicate", "Dimensions define unit specificity")_
All validation logic — ancestor coverage, join coverage, dimension validity, key matching — operates on the dimension structure from the registry. No validation code references `input_mtok` or any other specific unit by name.
