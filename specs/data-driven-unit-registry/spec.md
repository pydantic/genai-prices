# Data-Driven Unit Registry

**The unit-registry work is seven numbered phases, not one phase with subphases.**
Each phase has its own prose spec and its own code spec. The prose spec states the behavioral target for that phase. The code spec states the implementation delta from the previous phase to that phase.

**Phase order is the review contract.** _(from "The unit-registry work is seven numbered phases")_
Each phase should be reviewable and shippable after the previous phase. Later phases can influence earlier APIs only where the earlier phase must preserve an extension point; they must not pull their implementation work forward.

**Phase-local code specs are the implementation source of truth.** _(from "The unit-registry work is seven numbered phases", "Phase order is the review contract")_
There is no top-level code spec. Use the phase-local prose spec plus the matching phase-local code spec. Phase 1 describes the implementation delta from the pre-registry baseline; Phases 2 through 7 describe only what must change after the previous phase is complete.

**Phase 1 proves the Python runtime model for the current unit surface.** _(from "Phase order is the review contract")_
[Phase 1: Python Internal Registry Refactor](phase-1-python-internal-registry/spec.md) ([code spec](phase-1-python-internal-registry/code-spec.md)) moves Python's existing hardcoded usage and price behavior behind a data-shaped `UnitRegistry`, registry-aware `Usage`, registry-backed `ModelPrice`, and generic decomposition for the current public unit set only. It preserves the current remote JSON shape and does not enable new repo-defined units.

**Phase 2 proves the JavaScript runtime model for the current unit surface.** _(from "Phase order is the review contract")_
[Phase 2: JavaScript Internal Registry Refactor](phase-2-javascript-internal-registry/spec.md) ([code spec](phase-2-javascript-internal-registry/code-spec.md)) gives JavaScript the same internal registry and decomposition model as Python while preserving current JavaScript behavior and the current remote JSON shape.

**Phase 3 publishes the shared registry data contract.** _(from "Phase order is the review contract")_
[Phase 3: Shared Data Contract and Base Dynamic Price Keys](phase-3-shared-data-contract/spec.md) ([code spec](phase-3-shared-data-contract/code-spec.md)) changes `data.json` and `data_slim.json` from bare provider arrays into wrapped payloads that carry both `unit_families` and `providers`. This is where new repo-defined units become an end-to-end feature, where full registry join-closedness starts, and where Python base `ModelPrice` accepts non-hardcoded registered price keys.

**Phase 4 hardens authoring and compatibility surfaces.** _(from "Phase order is the review contract")_
[Phase 4: Polish and Compatibility Hardening](phase-4-polish-compat-hardening/spec.md) ([code spec](phase-4-polish-compat-hardening/code-spec.md)) adds reserved-name validation, generated provider-YAML schema/autocomplete, registry-driven CLI price presentation, and Python dataclass-subclass dynamic price-key constructor support.

**Phase 5 adds runtime validation performance optimizations.** _(from "Phase order is the review contract")_
[Phase 5: Runtime Validation Performance Optimization](phase-5-runtime-validation-performance/spec.md) ([code spec](phase-5-runtime-validation-performance/code-spec.md)) adds validation trust contexts, price-key fingerprints, invalidation, and any benchmark-backed decomposition caches. These mechanisms improve repeated-runtime costs but must not change accepted data shapes, validation rules, decomposition semantics, generated payloads, or public API behavior.

**Phase 6 adds runtime custom units.** _(from "Phase order is the review contract")_
[Phase 6: Runtime Custom Units](phase-6-runtime-custom-units/spec.md) ([code spec](phase-6-runtime-custom-units/code-spec.md)) adds user-facing ways to add unit families or units to a staged `DataSnapshot` at runtime and activate the combined registry, price, and extractor changes atomically.

**Phase 7 adds global snapshot execution guardrails.** _(from "Phase order is the review contract")_
[Phase 7: Global Snapshot Semi-Enforcement](phase-7-global-snapshot-enforcement/spec.md) ([code spec](phase-7-global-snapshot-enforcement/code-spec.md)) turns the active-global-snapshot assumption into explicit execution guards without introducing a multi-snapshot execution architecture.

**Shared decomposition requirements live in [algorithm](algorithm.md) and [examples](examples.md).** _(from "Phase 1 proves the Python runtime model for the current unit surface", "Phase 2 proves the JavaScript runtime model for the current unit surface", "Phase 3 publishes the shared registry data contract")_
The shared algorithm and examples support the runtime phases. Phase-local specs state when those requirements become active for a language or payload shape.
