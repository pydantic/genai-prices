# Phase 2: JavaScript Internal Registry Refactor

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 2 brings JavaScript to the same internal model as Phase 1 Python.**
JavaScript moves its current hardcoded pricing behavior behind a data-shaped registry, registry-normalized usage reads, validation helpers, and generic decomposition for the current public unit set only. It builds on Phase 1 and does not change Python behavior.

**The active JavaScript registry is limited to the current JavaScript unit surface.** _(from "Phase 2 brings JavaScript to the same internal model as Phase 1 Python")_
The registered usage and price keys match the current JavaScript behavior, including request-count pricing. Text, image, video, cache-by-modality units not already public, and other future units remain out of scope until Phase 3.

**The shared remote payload shape remains unchanged.** _(from "Phase 2 brings JavaScript to the same internal model as Phase 1 Python")_
JavaScript generated package data can embed unit families for startup, but runtime update URLs still return bare provider arrays in Phase 2. Wrapped `unit_families` payloads start in Phase 3 after both runtimes have registry-backed internals.

**JavaScript unit data stays separate from generated provider data.** _(from "The shared remote payload shape remains unchanged")_
JavaScript users can provide their own provider data without paying the import cost of the bundled generated providers. Phase 2 preserves that workflow by generating the small current-unit registry subset into a separate JavaScript package module from the provider-heavy generated `data.ts`. Code that only needs the default unit registry must import the units-data module, not the bundled provider list.

**JavaScript preserves its plain-object public usage contract.** _(from "Phase 2 brings JavaScript to the same internal model as Phase 1 Python")_
Callers continue passing plain objects. The runtime normalizes known externally reported usage keys into a plain object, ignores unknown extras, and does not materialize missing registered values. Reading a missing registered value returns zero when no positive related value makes that unsafe, and raises when positive reported related values mean answering would require inference. Contradictory usage can exist until a direct read or price calculation must interpret it.

**JavaScript behavior stays aligned with Python semantics.** _(from "JavaScript preserves its plain-object public usage contract")_
Direct reads of stored usage values are inert, safe missing reads return zero without materializing a value, missing values are not inferred in Phase 2, ambiguous missing reads raise, unpriced reported keys are ignored when explicit priced ancestors make them unnecessary, and request pricing uses the explicit one-request-per-usage-object rule in pricing code. Tier selection reads `input_tokens` through the same usage-read rules, matching Python's Phase 1 conservative rule.

**JavaScript validation mirrors Python's Phase 1 split.** _(from "Phase 2 brings JavaScript to the same internal model as Phase 1 Python")_
Registry parsing validates structural rules for the current subset. Price-level validation checks price keys, ancestor coverage, join coverage, and missing-join safety every time standard JavaScript pricing calculates against a model price. Runtime activation-time model-price validation, validation trust state, and decomposition caches remain deferred to Phase 5.

**Runtime updates stay atomic for provider data and registry state.** _(from "The shared remote payload shape remains unchanged", "JavaScript validation mirrors Python's Phase 1 split")_
Even though Phase 2 still consumes provider-array remote data, the active JavaScript registry and active provider data must not drift apart during startup or local staging. Failed parsing or structural validation leaves the current active state unchanged; model-price validation errors surface when pricing uses the affected model price.
