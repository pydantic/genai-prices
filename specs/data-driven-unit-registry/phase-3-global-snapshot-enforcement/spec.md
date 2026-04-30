# Phase 3: Global Snapshot Semi-Enforcement

**Code-level architecture is in [code-spec](code-spec.md).**

**This phase turns the active-global-snapshot assumption into guardrails.**
Phase 1 assumes ordinary registry-aware execution uses the active global `DataSnapshot`, but it does not need to block other usage patterns. This phase adds small checks that reject the most obvious non-global execution paths so future registry work has a clearer execution context.

**Phase numbering is bookkeeping, not a required implementation order.** _(from "This phase turns the active-global-snapshot assumption into guardrails")_
This phase can be implemented before, after, or between other phases if it makes implementation smoother. It is separated from Phase 1 because it is not required for the repo-defined unit registry to work for the normal active-snapshot path.

**This is semi-enforcement, not multi-snapshot architecture.** _(from "This phase turns the active-global-snapshot assumption into guardrails")_
The goal is to stop accidental execution against stale or inactive snapshot objects, not to make multiple snapshots safely executable at the same time. Supporting concurrent executable snapshots would require explicit context/provenance design across pricing, extraction, usage inference, validation markers, and decomposition caches. That is out of scope here.

**Only execution paths are blocked.** _(from "This is semi-enforcement, not multi-snapshot architecture")_
Lookup and staging workflows still work on inactive snapshots. A caller can fetch a snapshot, inspect providers/models, patch model prices, and then activate it with `set_custom_snapshot(snapshot)`. The guardrails apply only when a method would calculate prices or extract usage through a snapshot that is not the active global snapshot.

**`DataSnapshot.calc` and `DataSnapshot.extract_usage` require the active snapshot.** _(from "Only execution paths are blocked")_
Calling these methods on a non-active snapshot raises a user-facing error. The message should explain that registry-aware pricing/extraction uses the active global snapshot and that callers should activate the snapshot first or use the top-level API.

**Escaped model pricing is rejected when identity can prove it is inactive.** _(from "Only execution paths are blocked")_
`ModelInfo.calc_price()` has no snapshot parameter, so it cannot independently support safe non-global execution. If the provider/model pair being priced can be shown not to belong to the current active snapshot, pricing raises instead of silently using the active registry with an escaped inactive model.

**Pure lookups remain allowed on inactive snapshots.** _(from "Only execution paths are blocked")_
`find_provider`, `find_provider_model`, and similar lookup-only helpers do not use registry-aware pricing or extraction and remain valid on inactive snapshots. This preserves the existing customization workflow where callers fetch data, find a model, patch it, and return or activate the snapshot later.
