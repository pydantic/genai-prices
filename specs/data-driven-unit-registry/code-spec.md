# Code Spec: Data-Driven Unit Registry

**This indexes the phase-local code specs for [spec](spec.md).**

**Each phase code spec is a delta from the previous phase.**
Phase 1 describes the implementation delta from the pre-registry baseline. Phases 2 through 7 describe only what must change after the previous phase is complete.

**Phase code specs are the implementation source of truth.** _(from "Each phase code spec is a delta from the previous phase")_
Do not implement from this index alone. Use the phase-local prose spec plus the matching phase-local code spec:

- [Phase 1 code spec](phase-1-python-internal-registry/code-spec.md): Python internal registry refactor.
- [Phase 2 code spec](phase-2-javascript-internal-registry/code-spec.md): JavaScript internal registry refactor.
- [Phase 3 code spec](phase-3-shared-data-contract/code-spec.md): shared wrapped data contract and base dynamic price keys.
- [Phase 4 code spec](phase-4-polish-compat-hardening/code-spec.md): polish and compatibility hardening.
- [Phase 5 code spec](phase-5-runtime-validation-performance/code-spec.md): runtime validation performance optimization.
- [Phase 6 code spec](phase-6-runtime-custom-units/code-spec.md): runtime custom units.
- [Phase 7 code spec](phase-7-global-snapshot-enforcement/code-spec.md): global snapshot semi-enforcement.

**Shared supporting files remain at the root of this spec folder.** _(from "Phase code specs are the implementation source of truth")_
[algorithm](algorithm.md) defines the shared missing-value inference and decomposition behavior. [examples](examples.md) supplies worked pricing cases. Phase-local code specs reference those files when their phase activates the corresponding behavior.
