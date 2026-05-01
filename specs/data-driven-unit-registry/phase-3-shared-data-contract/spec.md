# Phase 3: Shared Data Contract and Base Dynamic Price Keys

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 3 makes repo-defined units an end-to-end feature.**
The shared generated payloads carry unit definitions with provider prices, both runtimes parse those wrapped payloads, and base runtime pricing can handle registered price keys that were not hardcoded before. This phase builds on the Python and JavaScript internal registry proofs from Phases 1 and 2.

**`data.json` and `data_slim.json` become wrapped top-level objects.** _(from "Phase 3 makes repo-defined units an end-to-end feature")_
Both payloads change from a bare provider list to `{"unit_families": {...}, "providers": [...]}`. This is an intentional compatibility break for older released clients that fetch the main data URL and expect a provider array. The new wrapper is the extensibility point for future top-level fields.

**Unit definitions travel with the prices that depend on them.** _(from "`data.json` and `data_slim.json` become wrapped top-level objects")_
Runtime auto-updates must not be able to deliver prices for units that the client does not know. The unit registry is therefore generated into `data.json`, `data_slim.json`, Python `data.py`, and JavaScript `data.ts` alongside provider data.

**The complete repo-defined registry starts here.** _(from "Unit definitions travel with the prices that depend on them")_
`prices/units.yml` becomes the complete source for built-in repo-defined units, including the built-in token lattice needed by the shared pricing semantics. Full registry join-closedness is now a structural validation rule rather than a current-subset exception.

**Provider prices and extractor destinations validate against the same registry payload.** _(from "Unit definitions travel with the prices that depend on them")_
Build/export validation constructs the registry from `prices/units.yml`, validates provider price keys, ancestor coverage, join coverage, and extractor destinations, then writes the wrapped payload. Fetched wrapped payloads are parsed and structurally checked at runtime, but their model prices are treated as prevalidated by the publisher.

**Python base `ModelPrice` accepts registered non-hardcoded price keys.** _(from "Phase 3 makes repo-defined units an end-to-end feature")_
Base `ModelPrice` stores candidate dynamic price-key kwargs outside the legacy dataclass fields and accepts or rejects them when validation has a registry context. A registered future key works on the base class without adding a new field. A misspelled key fails validation instead of disappearing.

**Dataclass subclass constructor support for undeclared dynamic price keys waits for Phase 4.** _(from "Python base `ModelPrice` accepts registered non-hardcoded price keys")_
Phase 3 promises non-hardcoded registered key support for base `ModelPrice`. Plain Python dataclass subclasses accepting undeclared dynamic price-key kwargs require additional constructor interception and are handled as compatibility polish in Phase 4.

**Runtime validation caching still waits for Phase 5.** _(from "Provider prices and extractor destinations validate against the same registry payload", "Python base `ModelPrice` accepts registered non-hardcoded price keys")_
Phase 3 can repeat one-model validation when defensive runtime checks are needed. It must not add validation trust contexts, price-key fingerprints, dirty sets, generated validation markers, or decomposition caches.
