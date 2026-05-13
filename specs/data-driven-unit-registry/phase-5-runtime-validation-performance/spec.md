# Phase 5: Runtime Validation Performance Optimization

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 5 adds benchmark-backed performance state after the data model is proven.**
Phases 1 through 4 prove the registry model, wrapped payload shape, validation behavior, public access patterns, and compatibility hardening. Phase 5 may optimize repeated runtime validation and decomposition work, but it must not change correctness semantics.

**Performance optimizations must be behavior-preserving.** _(from "Phase 5 adds benchmark-backed performance state after the data model is proven")_
The accepted registry shape, price-key validation rules, extractor validation rules, explicit-only missing-usage rules, decomposition semantics, generated payload shape, and public API behavior remain exactly as defined by Phases 1 through 4.

**Validation caching is global-registry-specific.** _(from "Performance optimizations must be behavior-preserving")_
A model price can skip repeated validation only when the runtime can prove it is the same model price object, validated against the same active global registry identity, with the same effective price-key fingerprint. Replacing the active global registry invalidates validation caches.

**Provider activation is not a bulk model-price validation boundary.** _(from "Validation caching is global-registry-specific")_
Phases 1 through 4 validate model prices on use before every standard base pricing calculation. Phase 5 should preserve that lifecycle and cache successful one-model validation results on the hot path. It does not need to bulk-validate provider snapshots during `set_custom_snapshot(...)`.

**Fingerprint checks fail closed.** _(from "Validation caching is global-registry-specific")_
Adding or removing effective registered price keys makes prior validation stale. Setting a different value for an already-present key does not structurally require invalidation because ancestor and join coverage depend on keys, not values. Python and JavaScript should both compare the current effective price-key fingerprint before using a cached validation result.

**Generated outputs remain pure data.** _(from "Performance optimizations must be behavior-preserving")_
`data.json`, `data_slim.json`, Python `data.py`, Python `data_units.py`, JavaScript `data.ts`, and JavaScript `dataUnits.ts` contain unit families, providers, and raw price values only. They must not contain validation markers, trust flags, price-key fingerprints, decomposition coefficients, or cached plans.

**Decomposition caches are benchmark-gated.** _(from "Performance optimizations must be behavior-preserving")_
Cached decomposition coefficients or plans are allowed only if benchmarks show direct decomposition remains material after validation caching is in place. Any cache key must include the exact active global registry identity and the model's effective priced usage-key set.

**Usage registry-key lookups are a Phase 5 optimization target.** _(from "Performance optimizations must be behavior-preserving")_
Phase 1 keeps `Usage` construction, assignment, reads, and representation live against the active global registry. Phase 5 should benchmark and, if useful, cache registry-derived reported usage key sets and registry-order reported key tuples by exact active global registry identity without changing `Usage` semantics.
