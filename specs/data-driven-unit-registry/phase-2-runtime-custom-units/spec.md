# Phase 2: Runtime Custom Units

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 1 remains the source of truth for the base registry.**
Phase 2 builds on the repo-defined unit registry in [../spec](../spec.md). It does not replace `prices/units.yml`, generated package data, wrapped `data.json`, generic decomposition, or registry-backed `Usage`/`ModelPrice` behavior. It adds a user-facing way to define additional units at runtime.

**Users can define custom units at runtime.** _(from "Phase 1 remains the source of truth for the base registry")_
Without modifying the repository and without making a PR, callers can add units to existing unit families or create entirely new unit families. Custom units are first-class after activation: they use the same validation, usage inference, price-key resolution, and decomposition machinery as repo-defined units.

**Runtime custom units reuse the Phase 1 raw unit shape.** _(from "Users can define custom units at runtime")_
The raw data shape stays `family_id -> family data -> units -> usage_key -> unit data`. Unit dimensions remain unit-local; adding a unit with a new dimension key or value is how an existing family gains that axis or value. There is no separate declaration surface for dimension keys or values.

**Runtime unit and price patches happen through `DataSnapshot`.** _(from "Users can define custom units at runtime")_
The public workflow should be "edit the snapshot, then activate it if needed." Callers should not need to manually deep-copy the current registry, providers, models, or prices before making a small patch. The implementation may copy internally to provide validation rollback, but that is not user-visible ceremony.

**Registry mutations commit only structurally valid states.** _(from "Runtime unit and price patches happen through `DataSnapshot`")_
Registry mutations validate usage key uniqueness, price key uniqueness, dimension-set uniqueness, interval closure, and join-closedness before the mutation becomes visible. There is no externally visible invalid intermediate registry: mutation either commits a valid registry state or fails and leaves the registry unchanged.

**Existing-family unit edits are batch operations.** _(from "Registry mutations commit only structurally valid states", "Runtime custom units reuse the Phase 1 raw unit shape")_
The registry exposes one batch operation that accepts one or more unit definitions for a single existing family, applies them to a candidate family, validates the complete candidate registry, and commits only if the final state is valid. Passing a one-unit batch handles the simple case. Passing a larger batch handles units that are only valid together under interval closure or join-closedness.

The batch operation does not invent or require a shape. It does not auto-generate units for every dimension value, require a new modality to match existing modalities, add prices, validate model prices, update extractors, or activate a `DataSnapshot`. It only edits unit definitions. After editing units, callers add matching provider/model price changes to the same snapshot.

**Runtime unit patches use the same batch boundary in every language.** _(from "Existing-family unit edits are batch operations")_
The concrete method name can be language-idiomatic, but the operation shape is the same: pass a batch of unit definitions for one existing family and validate once after the batch is staged. Python might accept a mapping keyed by usage key, while JavaScript might accept an array of objects with `usageKey`; either representation is the same operation.

**Snapshot activation validates custom units, prices, and extractors together.** _(from "Runtime unit and price patches happen through `DataSnapshot`")_
Before activation, a snapshot can contain custom units, custom prices, and extractor configs whose references have not yet been accepted together. `set_custom_snapshot(snapshot)` validates the staged registry structure first, then validates changed or untrusted model prices and extractor destinations against that same registry. If any validation fails, the previous active snapshot remains in place.

**Custom extractor destinations can target runtime units after the unit exists in the same snapshot.** _(from "Snapshot activation validates custom units, prices, and extractors together")_
Extractor destinations remain registered usage keys. A runtime-authored extractor can target a runtime custom unit only after that unit has been added to the snapshot being activated.

**Pure additive unit additions preserve trusted unchanged prices.** _(from "Snapshot activation validates custom units, prices, and extractors together")_
Adding units without deleting or changing existing unit definitions must not force revalidation of every trusted built-in or official price. Unchanged trusted prices remain trusted when the units and price-key mappings they reference still exist with the same meaning. Destructive changes can make affected prices stale, but even then validation should happen for changed/untrusted prices during activation and for one trusted price only if it is later used.

**Multiple executable snapshots remain out of scope.** _(from "Phase 1 remains the source of truth for the base registry")_
Phase 2 adds runtime custom units inside the same one-active-snapshot execution model chosen in Phase 1. Supporting multiple concurrently executable snapshots would require a separate context/provenance design and is not part of this phase.
