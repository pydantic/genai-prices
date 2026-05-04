# Phase 5: Runtime Validation Performance Optimization

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 5 adds performance state after the data model is proven.**
Phases 1 through 4 prove the registry model, wrapped payload shape, validation behavior, public access patterns, and compatibility hardening. Phase 5 can optimize repeated runtime validation and decomposition work, but it must not change correctness semantics.

**Performance optimizations must be behavior-preserving.** _(from "Phase 5 adds performance state after the data model is proven")_
The accepted registry shape, price-key validation rules, extractor validation rules, usage inference semantics, decomposition semantics, generated payload shape, and public API behavior remain exactly as defined by Phases 1 through 4.

**Runtime validation trust is snapshot- and registry-specific.** _(from "Performance optimizations must be behavior-preserving")_
A model price can skip repeated validation only when the runtime can prove it is the same model price object, validated against the same registry validation identity, with the same effective price-key fingerprint.

**Phase 5 is the first activation-time model-price validation phase.** _(from "Runtime validation trust is snapshot- and registry-specific")_
Phases 1 through 4 validate model prices on use before every standard base pricing calculation. Phase 5 may move validation earlier for missing, custom, changed, runtime-authored, stale, or otherwise untrusted prices during snapshot activation, but only to record runtime-private trust that preserves the same accepted/rejected behavior as use-time validation.

**Supported mutation paths invalidate trust when effective price keys change.** _(from "Runtime validation trust is snapshot- and registry-specific")_
Adding or removing effective registered price keys makes prior validation stale. Setting a different value for an already-present key does not structurally require invalidation because ancestor and join coverage depend on keys, not values.

**JavaScript validation trust fails closed.** _(from "Runtime validation trust is snapshot- and registry-specific")_
JavaScript model prices are plain objects and arbitrary mutation cannot be intercepted. Every trust lookup must compare the current effective price-key fingerprint and revalidate on any mismatch.

**Generated outputs remain pure data.** _(from "Performance optimizations must be behavior-preserving")_
`data.json`, `data_slim.json`, Python `data.py`, and JavaScript `data.ts` contain unit families, providers, and raw price values only. They must not contain validation markers, trust flags, price-key fingerprints, decomposition coefficients, or cached plans.

**Decomposition caches are benchmark-gated.** _(from "Performance optimizations must be behavior-preserving")_
Cached decomposition coefficients or plans are allowed only if benchmarks show direct decomposition remains material after validation trust is in place. Any cache key must include the exact registry validation identity and the model's effective priced usage-key set.

**Usage registry-key lookups are a Phase 5 optimization target.** _(from "Performance optimizations must be behavior-preserving")_
Phase 1 keeps `Usage` construction, assignment, reads, and representation live against the active registry. Phase 5 should benchmark and, if useful, cache registry-derived reported usage key sets and registry-order reported key tuples by exact registry validation identity without changing `Usage` semantics.
