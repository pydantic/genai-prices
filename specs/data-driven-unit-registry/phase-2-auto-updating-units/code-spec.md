# Code Spec: Phase 2 Auto-Updating Unit Definitions

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Baseline:** Phase 1 is merged and released with static bundled units and provider-array v2 updates.

**Phase 2 adds a versioned wrapped artifact without modifying v1 or v2.** _(implements "Existing v1 and v2 update contracts remain stable", "Phase 2 publishes wrapped `data_v3.json`")_
Extend the build to emit `prices/data_v3.json` and its own schema as:

```json
{
  "units": { "input_tokens": { "...": "..." } },
  "providers": [{ "...": "..." }]
}
```

The v3 unit object uses the same usage-keyed raw shape as `prices/units.yml`. Provider slimming or additional v3 variants are not required to prove runtime unit updates. Existing v1 and v2 files are not rewritten into this shape.

**V3 package generation remains split.** _(implements "Generated and fetched v3 outputs remain pure data")_
Bundled Python and JavaScript provider modules still contain providers, and their unit modules still contain units. Package generation may read the v3 wrapper and split it, but runtime source modules do not embed validation or cache state.

**Python fetch activates a candidate registry transactionally.** _(implements "Registry and provider activation is atomic", "The active v3 registry remains process-global and provider snapshots remain provider-only")_
Point v3-capable Python packages at `data_v3.json`. `UpdatePrices.fetch()` requires the wrapper, constructs a candidate `UnitRegistry`, makes it the parsing context for provider normalization and extractor validation, and returns a provider-only `DataSnapshot`. If any step fails, restore the previous active registry and leave active providers unchanged.

`UpdatePrices.stop()` clears fetched providers and restores the generated bundled registry. `set_custom_snapshot(...)` continues to replace provider data only and does not infer a registry from a snapshot.

**JavaScript provider activation accepts the v3 wrapper transactionally.** _(implements "Registry and provider activation is atomic")_
Point v3-capable JavaScript packages at `data_v3.json`. `setProviderData` handles `null`, a wrapped payload, or a promise resolving to either. It constructs a candidate `UnitRegistry`, validates provider extractor destinations against it, and activates registry plus providers together. Rejection or parse failure preserves previous state.

V3 package internals may retain provider-array setters for explicit local compatibility where already supported, but the official updater and examples use the v3 wrapper. A provider-only local update leaves the current active registry unchanged.

**Registry replacement is internal runtime state.** _(implements "The active v3 registry remains process-global and provider snapshots remain provider-only")_
Python and JavaScript expose private/internal accessors needed by pricing, usage, extraction, validation, update activation, restoration, and tests. They do not add package-root APIs for arbitrary registry mutation. Every constructed registry has stable identity for its lifetime, but Phase 2 does not add cache-specific validation tokens.

**V3 publication validation covers the complete wrapper.** _(implements "Published registry evolution must preserve existing unit meanings")_
Before writing v3, validate registry structure, public keys, provider price keys, ancestor and join coverage, and extractor destinations against the same unit object included in the payload. Runtime activation trusts publisher structure except for parsing and provider/extractor checks needed to avoid installing unusable state. Runtime code does not compare the fetched registry with historical releases.

**Tests exercise both runtime transactions and version isolation.** _(implements "Tests prove version isolation and atomic activation")_
Add Python and JavaScript integration tests for a new unit that is absent from bundled Phase 1-style data but present in a fetched v3 wrapper, plus rollback tests for malformed wrappers and invalid provider extraction. Assert v1 and v2 roots and URLs remain unchanged, updater stop restores bundled units/providers, `DataSnapshot` stays provider-only, and generated/fetched outputs contain no cache state.
