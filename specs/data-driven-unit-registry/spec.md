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
If information exists in one place, compute it elsewhere rather than copying it. This is the operating principle behind "units are data" but it's more general: field names, validation rules, dimensional relationships — anything that can be derived from the registry should be derived, not restated in code.

**Backward compatibility is preserved unless clearly impractical.** _(from "Units are data, not code")_
Existing consumer code must continue to work. `model_price.input_mtok`, `usage.input_tokens`, `calc_price(usage)` — these patterns are the public API. This constrains how we implement data-driven units, not whether.

**Existing provider YAML files are mostly unchanged.** _(from "Backward compatibility")_
Changes are justified only by genuine data gaps — e.g., a model that prices cached tokens and audio tokens but not cached-audio tokens fails a validation rule we're adding for good reason. No mass field renames, no restructuring for its own sake. This goes against "Price data must be complete" only in appearance — adding a missing cached-audio price IS making the data complete; it's not churn.

**Users can define custom units at runtime.** _(from "Units are data, not code")_
Without modifying the repository, without making a PR. Custom units are first-class: same mechanisms, same validation, same decomposition as built-in units.

**The system is general across unit families.** _(from "Units are data, not code")_
Any unit with the structure `usage_value x price / normalization_factor` is expressible: tokens (per million), requests (per thousand), characters, duration, etc. Tokens are the first and most complex family (because of overlapping usage), but nothing in the system is token-specific. Future families require only a data file edit.

**A unit family groups units whose usage values can overlap.** _(from "The system is general")_
Each family has a normalization factor (`per: 1_000_000` for tokens). Within a family, a more-specific unit's usage is a subset of a less-specific one's (`cache_read_tokens` is a subset of `input_tokens`). Between families, there is no overlap — request counts don't interact with token counts.

**Dimensions define unit specificity and overlap.** _(from "A unit family groups units")_
Each unit carries zero or more categorical dimension assignments: `{direction: input}`, `{direction: input, cache: read}`, `{direction: input, modality: audio, cache: read}`. More dimensions = more specific. The containment relationship — which units are ancestors/descendants of which — is determined by set inclusion on dimensions: if A's dimensions are a subset of B's, A is an ancestor of B. This structure is the basis for decomposition and for all validation rules.

**Decomposition uses dimensions, not hardcoded subtraction chains.** _(from "Dimensions define unit specificity", "Every usage value must land in exactly one pricing bucket")_
The current code subtracts specific unit values from general ones in a manually maintained order. The replacement: Mobius inversion on the containment poset defined by dimensions. The algorithm takes the set of priced units, computes each one's "leaf value" (exclusive portion of usage), and guarantees no double-counting. No code names specific units — the algorithm works from the dimension structure alone.

**Ancestor coverage: pricing a unit requires pricing all its ancestors.** _(from "Price data must be complete", "Decomposition uses dimensions")_
If a model prices `cache_read_mtok` ({direction: input, cache: read}), it must also price `input_mtok` ({direction: input}). Without the ancestor, usage reported at the general level (just `input_tokens`, no breakdown) would have no price. This is a price data completeness requirement — validated, not assumed.

**Join coverage: pricing two overlapping units requires pricing their intersection.** _(from "Price data must be complete", "Decomposition uses dimensions")_
If a model prices both `cache_read_mtok` and `input_audio_mtok`, their join — the unit with the union of both dimension sets, `{direction: input, cache: read, modality: audio}` — must also be priced, if it exists in the registry. Without this, Mobius inversion double-counts tokens that belong to both parents. This is not a nice-to-have — it's a direct consequence of requiring accurate prices. Each token in one bucket, not two.

**Unit definitions travel with prices, not just with the package.** _(from "Units are data, not code", "Users can define custom units at runtime")_
Currently, prices are in `data.json` which clients can auto-update at runtime (pulled on merge, before a package release). Unit definitions are in `units.json`, bundled into the Python/JS packages — only updated on package release. This means a new unit's prices could arrive before the client knows the unit exists. Unit definitions must be included in `data.json` (and `data_slim.json`) so they travel together with the prices that depend on them. When a client pulls fresh price data, it gets the units too.

**The registry is a YAML file that defines all built-in units.** _(from "Units are data, not code", "Derive, don't duplicate")_
One file, checked into the repo. It defines families, their normalization factors, their dimension axes, and their units (each with an ID, a usage key, and dimension assignments). At build time, this file is compiled into `data.json` alongside prices. At runtime, the registry is loaded from the same data the client already has — no separate file needed.

**ModelPrice supports attribute access backed by registry data.** _(from "The registry is a YAML file", "Backward compatibility")_
ModelPrice is not a plain dict — that would break `model_price.input_mtok`. It's an object that supports attribute access, but the set of valid attributes comes from the registry. New units added to the registry are immediately accessible as attributes. Legacy names like `input_mtok` continue to work. Keeping typed property definitions for existing names is acceptable as a backward-compat shim — but it's a convenience for type checkers, not the source of truth. Future names need no code changes.

**Usage is accessed dynamically by key.** _(from "The registry is a YAML file", "Derive, don't duplicate")_
Each unit defines a `usage_key` — the attribute name to look up on the usage object (e.g., `input_tokens` for unit `input_mtok`). The engine uses `getattr`/Mapping access. No typed Protocol enumerates usage fields. Callers provide whatever they have; missing values are zero.

**Incomplete usage is handled gracefully, not rejected.** _(from "Price data must be complete; usage data may be incomplete", "Usage is accessed dynamically")_
A caller with only `{input_tokens: 1000, output_tokens: 500}` gets a valid price at catch-all rates. A caller with detailed breakdowns gets a more precise price. The system handles both — missing usage values default to zero (no carve-out), and the decomposition adapts to whatever units are priced. The accuracy limitation is accepted because it comes from the caller's data, not from ours.

**Validation replaces what hardcoded fields gave us implicitly, and adds more.** _(from "Units are data, not code", "Derive, don't duplicate")_
Hardcoded ModelPrice fields provided implicit validation: a typo like `inptu_mtok` would fail because the field doesn't exist. Moving to data-driven units means explicit validation must replace that safety net and go further. Validation is comprehensive — it's cheaper to reject bad data at build/construction time than to debug wrong prices at runtime.

**Price key validation: every key in a model's prices must be a registered unit ID.** _(from "Validation replaces what hardcoded fields gave us")_
If a provider YAML file has `prices: { inptu_mtok: 3 }`, the build fails. This replaces the implicit validation that hardcoded Pydantic/dataclass fields provided. Checked at build time (data pipeline) and at construction time (ModelPrice).

**Dimension validation: unit dimension keys and values must match their family's declarations.** _(from "Validation replaces what hardcoded fields gave us", "Dimensions define unit specificity")_
A unit in the `tokens` family can only use dimension keys declared for that family (`direction`, `modality`, `cache`), and only with declared values (`direction: input` is valid; `direction: sideways` is not). Checked when the registry is loaded.

**Unit uniqueness: no two units in a family may have identical dimension sets.** _(from "Validation replaces what hardcoded fields gave us", "Dimensions define unit specificity")_
Dimensions uniquely identify a unit's position in the containment poset. Two units with the same dimensions would be the same slot — that's a data error, not an edge case.

**Usage key uniqueness: no two units may share the same usage key.** _(from "Validation replaces what hardcoded fields gave us", "Usage is accessed dynamically")_
A usage key maps one-to-one to a unit. If two units read from the same usage field, decomposition can't distinguish their contributions.

**Ancestor coverage is validated.** _(from "Ancestor coverage: pricing a unit requires pricing all its ancestors", "Validation replaces what hardcoded fields gave us")_
At ModelPrice construction time, checked against the registry's dimension structure. Not deferred to calc_price.

**Join coverage is validated.** _(from "Join coverage: pricing two overlapping units requires pricing their intersection", "Validation replaces what hardcoded fields gave us")_
At ModelPrice construction time. For every pair of priced units, if their dimension-union corresponds to a unit in the registry, that unit must also be priced.

**Validation rules are expressed in terms of dimensions, not unit names.** _(from "Derive, don't duplicate", "Dimensions define unit specificity")_
All validation logic — ancestor coverage, join coverage, dimension validity, key matching — operates on the dimension structure from the registry. No validation code references `input_mtok` or any other specific unit by name.
