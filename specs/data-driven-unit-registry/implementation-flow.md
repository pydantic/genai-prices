# Cross-Phase Implementation Flow

This file is supporting detail for the phase-local code specs. It does not replace them as the source of truth. Its purpose is to preserve the cross-phase call relationships, trust boundaries, and runtime activation flow so an implementer can see how the phase-local skeletons fit together.

## File Ownership By Phase

```text
Phase 1 creates:
  -> prices/units.yml
  -> packages/python/genai_prices/units.py
  -> packages/python/genai_prices/decompose.py
  -> packages/python/genai_prices/validation.py

Phase 1 modifies:
  -> packages/python/genai_prices/types.py
  -> packages/python/genai_prices/data_snapshot.py
  -> packages/python/genai_prices/data.py (generated)
  -> prices/src/prices/package_data.py

Phase 2 creates:
  -> packages/js/src/units.ts
  -> packages/js/src/usage.ts
  -> packages/js/src/decompose.ts
  -> packages/js/src/validation.ts

Phase 2 modifies:
  -> packages/js/src/types.ts
  -> packages/js/src/engine.ts
  -> packages/js/src/api.ts
  -> packages/js/src/extractUsage.ts
  -> packages/js/src/data.ts (generated)
  -> prices/src/prices/package_data.py

Phase 3 modifies:
  -> prices/src/prices/prices_types.py
  -> prices/src/prices/build.py
  -> prices/src/prices/package_data.py
  -> packages/python/genai_prices/update_prices.py
  -> packages/python/genai_prices/types.py
  -> packages/python/genai_prices/data_snapshot.py
  -> packages/js/src/api.ts
  -> generated JSON outputs and JSON schemas under prices/

Phase 4 modifies:
  -> registry validation helpers
  -> provider YAML schema generation
  -> packages/python/genai_prices/types.py
  -> packages/python/genai_prices/_cli_impl.py

Phase 5 modifies:
  -> UnitRegistry validation identity state
  -> Python DataSnapshot validation trust state
  -> Python ModelPrice trust invalidation paths
  -> JavaScript registry and validation trust helpers

Phase 6 modifies:
  -> UnitRegistry mutation APIs
  -> DataSnapshot unit-editing APIs
  -> Python/JavaScript validation trust compatibility
  -> JavaScript staged registry/provider activation helpers

Phase 7 modifies:
  -> Python DataSnapshot execution methods
  -> Python ModelInfo.calc_price identity guard
```

The lists are ownership guides, not permission boundaries. If an implementation discovers an additional touched file, update the relevant phase code spec before or alongside the implementation.

## Registry Construction

```text
prices/units.yml
  -> build.py loads raw family dict
  -> UnitRegistry(raw_families)
       -> create UnitFamily shells
       -> create UnitDef objects
       -> fill families / units / price_keys indexes
       -> fill family references on units
       -> fill dimension-set and ancestor indexes
       -> validate usage-key uniqueness
       -> validate price-key uniqueness
       -> validate dimension-set uniqueness within each family
       -> validate interval closure
       -> in Phase 3+: validate full join-closedness
       -> in Phase 4+: validate public dynamic key safety
```

Phases 1 and 2 intentionally construct a current-unit subset that may omit future join units, so full join-closedness is not enforced there. Price-level validation must reject any priced compatible pair whose join is absent before decomposition runs.

## Build-Time Validation and Packaging

```text
Phase 3 target:
build()
  -> load prices/units.yml
  -> registry = UnitRegistry(unit_families)
  -> load provider YAML files
  -> validate model price keys
  -> resolve price keys to usage keys
  -> validate ancestor coverage
  -> validate join coverage
  -> validate extractor destinations against externally reported usage keys
  -> write wrapped data.json and data_slim.json

package_data()
  -> read wrapped data.json
  -> package_python_data(): emit providers + unit_families_data
  -> package_ts_data(): emit data + unitFamiliesData
  -> generated runtime data is trusted because export validation succeeded first
```

Phase 1 and Phase 2 generate or embed language-native unit registry data for the current hardcoded unit subset while keeping `prices/data.json` and `prices/data_slim.json` as provider arrays. Phase 3 is the payload-shape break. Phase 4 derives provider YAML schema/autocomplete from registry price keys and reported usage keys. Phase 5 adds runtime-private trust and fingerprint checks while keeping generated data free of validation markers, fingerprints, and caches.

## Python Bundled Startup

```text
get_snapshot()
  -> _bundled_snapshot()
       -> import providers, unit_families_data from generated data.py
       -> UnitRegistry(unit_families_data)
       -> DataSnapshot(providers=..., unit_registry=..., from_auto_update=False)
       -> do not validate every generated ModelPrice at import/startup
       -> do not precompute decomposition state
       -> do not require generated data.py to emit per-price validation markers
       -> in Phase 5+: create runtime-private trusted-price context for this provider graph
```

Generated package data is pure data. Runtime-private validation trust is created from loaded objects, not serialized into the generated files.

## Python Snapshot Activation

```text
set_custom_snapshot(snapshot)
  -> if snapshot is None: clear custom snapshot
  -> validate the staged registry structure when needed
  -> validate only custom, changed, runtime-authored, stale, or otherwise untrusted ModelPrice objects
  -> validate candidate dynamic price keys against snapshot.unit_registry in Phase 3+
  -> validate ancestor and join coverage for changed/custom price-key sets
  -> validate extractor destinations against snapshot.unit_registry reported usage keys
  -> in Phase 5+: record runtime-private validation state in the snapshot trust context
  -> on success: activate snapshot as the active runtime snapshot
  -> on failure: raise and keep the previous active snapshot
```

Activation is the boundary where staged runtime objects become active runtime state. It must not bulk-revalidate unchanged trusted generated or fetched prices merely because one custom price changed.

## Python Custom Price Flow

```text
snapshot = get_snapshot() or an inactive snapshot returned from fetch()
  -> use lookup helpers to find providers/models on that snapshot
  -> mutate relevant ModelPrice objects for registered price keys as needed
       -> in Phase 5+: mutation invalidates trust-context state for changed key sets
  -> if snapshot is inactive: set_custom_snapshot(snapshot)
       -> validate only custom/changed/stale/untrusted ModelPrice objects required for the current phase
       -> do not revalidate unchanged trusted built-in prices just because one custom price changed
       -> activate on success
  -> if snapshot is already active:
       -> supported mutations have already updated the active snapshot
       -> changed prices are validated by the one-model calc fallback before pricing when needed
```

Custom `ModelPrice` overrides receive the original usage object. The base `ModelPrice.calc_price()` wraps usage internally only for registry-driven pricing.

## Python Hot Path

```text
ModelInfo.calc_price(usage, provider, ...)
  -> model_price = self.get_prices(genai_request_timestamp)
  -> model_price.calc_price(usage)

ModelPrice.calc_price(usage)
  -> registry = get_snapshot().unit_registry
  -> validate this ModelPrice against registry
       -> in Phase 5+: skip validation when active trust covers this ModelPrice fingerprint
  -> smart_usage = Usage.from_raw(usage)
  -> total_input_tokens = smart_usage.input_tokens only if any TieredPrices value needs a threshold
       -> otherwise use a neutral threshold because non-tiered prices ignore it
  -> resolve price keys to usage keys
  -> group priced units by family
  -> for each family:
       -> if requests, use fixed leaf value {"requests": 1}
       -> otherwise compute decomposition from smart_usage
  -> for each priced usage-keyed unit:
       -> price = stored price at unit.price_key
       -> cost = calc_unit_price(price, leaf_count, total_input_tokens, family.per)
       -> aggregate by direction
  -> return input_price, output_price, total_price
```

Tier selection uses the provided or inferable `input_tokens` total. If `input_tokens` is stored, the runtime uses it directly for tier selection without auditing descendant counts.

## JavaScript Runtime Activation

```text
generated data.ts
  -> unitFamiliesData bootstraps units.ts
  -> data bootstraps providerData
  -> do not validate every generated model price at module startup
  -> do not precompute decomposition state
  -> do not require generated data.ts to emit per-price validation markers
  -> in Phase 5+: create module-private trusted-price context for the active generated provider graph

runtime update
  -> parse wrapped JSON
  -> stagedFamilies = parseFamilies(parsed.unit_families)
  -> for fetched data-url update:
       -> treat parsed provider data as prevalidated for stagedFamilies without full price validation
  -> for user-provided staged data:
       -> validate only custom, changed, or otherwise untrusted model prices
  -> on success only:
       -> setUnitFamilies(stagedFamilies)
       -> setProviderData(parsed.providers)
  -> on failure:
       -> keep both active registry and providerData unchanged
```

Checked-in JavaScript examples that cache provider data must cache and restore the wrapped payload shape after Phase 3, not a bare provider array.
