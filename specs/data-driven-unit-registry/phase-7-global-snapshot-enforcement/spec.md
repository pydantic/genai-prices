# Phase 7: Global Snapshot Semi-Enforcement

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 7 turns the active-global-snapshot assumption into guardrails.**
Phases 1 through 6 rely on one active global `DataSnapshot` for registry-aware execution. Phase 7 rejects the most obvious non-global execution paths so pricing, extraction, validation trust, and runtime custom units share a clear execution context.

**This is semi-enforcement, not multi-snapshot architecture.** _(from "Phase 7 turns the active-global-snapshot assumption into guardrails")_
The goal is to stop accidental execution against stale or inactive snapshot objects, not to make multiple snapshots safely executable at the same time. Supporting concurrent executable snapshots would require explicit context/provenance design across pricing, extraction, usage inference, validation trust, decomposition caches, and runtime custom units. That is out of scope here.

**Only execution paths are blocked.** _(from "This is semi-enforcement, not multi-snapshot architecture")_
Lookup and staging workflows still work on inactive snapshots. A caller can fetch a snapshot, inspect providers/models, patch model prices or units, and then activate it with `set_custom_snapshot(snapshot)`. Guardrails apply only when a method would calculate prices or extract usage through a snapshot that is not the active global snapshot.

**`DataSnapshot.calc` and `DataSnapshot.extract_usage` require the active snapshot.** _(from "Only execution paths are blocked")_
Calling these methods on a non-active snapshot raises a user-facing error. The message should explain that registry-aware pricing/extraction uses the active global snapshot and that callers should activate the snapshot first or use the top-level API.

**Escaped model pricing is rejected when identity can prove it is inactive.** _(from "Only execution paths are blocked")_
`ModelInfo.calc_price()` has no snapshot parameter, so it cannot independently support safe non-global execution. If the provider/model pair being priced can be shown not to belong to the current active snapshot, pricing raises instead of silently using the active registry with an escaped inactive model.

**Pure lookups remain allowed on inactive snapshots.** _(from "Only execution paths are blocked")_
`find_provider`, `find_provider_model`, and similar lookup-only helpers do not use registry-aware pricing or extraction and remain valid on inactive snapshots. This preserves the customization workflow where callers fetch data, inspect and patch it, and activate it later.
