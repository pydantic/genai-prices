# Phase 8: Usage Inference

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 8 adds missing-usage inference after the registry architecture is complete.**
Phases 1 through 7 make units data-driven, validate price completeness, publish unit definitions with prices, add runtime custom units, optimize validation, and enforce the active-snapshot execution context. They deliberately avoid inferring missing usage values because expanding the unit set does not require that feature. Phase 8 is the separate phase that investigates and implements inference now that the registry model is stable.

**Inference is demand-driven, not construction-time normalization.** _(from "Phase 8 adds missing-usage inference after the registry architecture is complete")_
Usage construction and extraction still store only reported values. They do not fill ancestors, compute overlaps, normalize the usage object, or reject contradictory registered values up front. Inference happens only when a missing registered value is read or when pricing needs a missing priced bucket or tier threshold.

**Reported values remain authoritative.** _(from "Inference is demand-driven, not construction-time normalization")_
If a usage value was reported, a direct read returns that stored value without auditing descendants. Equality, addition, representation, serialization helpers, and diagnostics continue to distinguish reported values from inferred values. Inferred values are not cached as if they had been supplied by the caller.

**Missing values are inferred only when uniquely determined.** _(from "Inference is demand-driven, not construction-time normalization")_
For a missing requested unit, the runtime may use reported descendants in the same family to determine the requested total. It returns an inferred value only when all valid interpretations of the reported descendant data produce the same total. If there is no relevant descendant data, the missing value remains zero for pricing/read purposes. If descendant data is contradictory or leaves more than one possible total, the read or pricing calculation raises a user-facing usage error.

**Inference is registry-derived for all unit families.** _(from "Missing values are inferred only when uniquely determined")_
The runtime derives containment, overlap, and disjointness from registry dimensions and relationship indexes. It must not hardcode token names such as `input_tokens`, `cache_read_tokens`, or `cache_audio_read_tokens`. Runtime custom units added in Phase 6 participate in the same inference behavior after activation.

**Pricing may use inference where earlier phases raised.** _(from "Missing values are inferred only when uniquely determined", "Reported values remain authoritative")_
Before Phase 8, pricing raises when a missing ancestor, missing overlap, or tier threshold read would require guessing. Phase 8 replaces those conservative failures with inferred values when the registry and reported usage uniquely determine them. Pricing still raises when the missing value is contradictory or underdetermined.

**Tier thresholds use the same inference rule.** _(from "Pricing may use inference where earlier phases raised")_
The `TieredPrices` threshold remains the `input_tokens` total. If `input_tokens` was reported, tier selection uses it directly and does not audit descendants. If it was safely omitted, earlier phases use zero and Phase 8 keeps that result. If related reported usage makes the omitted threshold ambiguous, Phase 8 may infer it from reported descendants only when the total is uniquely determined; otherwise price calculation raises instead of selecting a guessed tier.

**Inference errors describe usage facts, not solving machinery.** _(from "Missing values are inferred only when uniquely determined")_
User-facing errors should name the missing usage key and the reported keys that made it contradictory or underdetermined. They must not mention linear algebra, ranks, atoms, Mobius inversion, leaves, coefficients, posets, or other implementation details.
