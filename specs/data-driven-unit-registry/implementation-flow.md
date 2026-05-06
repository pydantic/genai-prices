# Cross-Phase Implementation Flow

This file is supporting detail for the phase-local code specs. It does not replace them as the source of truth. Its purpose is to preserve the cross-phase call relationships, trust boundaries, global registry update flow, and provider activation flow so an implementer can see how the phase-local skeletons fit together.

## File Ownership By Phase

```text
Phase 1 creates:
  -> prices/units.yml
  -> packages/python/genai_prices/units.py
  -> packages/python/genai_prices/decompose.py
  -> packages/python/genai_prices/validation.py
  -> packages/python/genai_prices/data_units.py (generated)

Phase 1 modifies:
  -> packages/python/genai_prices/types.py
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
  -> packages/python/genai_prices/units.py
  -> packages/js/src/api.ts
  -> generated JSON outputs and JSON schemas under prices/

Phase 4 modifies:
  -> registry validation helpers
  -> provider YAML schema generation
  -> packages/python/genai_prices/types.py
  -> packages/python/genai_prices/_cli_impl.py

Phase 5 modifies:
  -> UnitRegistry / active registry validation identity state
  -> Python module-global validation caches
  -> JavaScript registry and validation cache helpers
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
  -> package_python_data(): emit providers + unit_families_data in separate generated Python modules
  -> package_ts_data(): emit data + unitFamiliesData in separate generated JavaScript modules
  -> generated runtime data is trusted because export validation succeeded first
```

Phase 1 and Phase 2 generate or embed language-native unit registry data for the current hardcoded unit subset while keeping `prices/data.json` and `prices/data_slim.json` as provider arrays. Phase 3 is the payload-shape break. Phase 4 derives provider YAML schema/autocomplete from registry price keys and reported usage keys. Phase 5 adds runtime-private validation caches and fingerprint checks while keeping generated data free of validation markers, fingerprints, and caches.

## Python Bundled Startup

```text
_get_registry()
  -> import unit_families_data from generated data_units.py
  -> UnitRegistry(unit_families_data)
  -> cache as the active global registry

get_snapshot()
  -> _bundled_snapshot()
       -> import providers from generated data.py
       -> DataSnapshot(providers=..., from_auto_update=False)
       -> do not validate every generated ModelPrice at import/startup
       -> do not precompute decomposition state
       -> do not require generated data.py or data_units.py to emit per-price validation markers
```

Generated package data is pure data. Runtime-private validation caches are created from loaded objects, not serialized into the generated files. The Python units-data module is separate so custom-provider code can borrow the default registry without importing the bundled provider list.

## Python Runtime Updates and Provider Activation

```text
UpdatePrices.fetch() after Phase 3 wrapped payloads
  -> parse wrapped JSON
  -> registry = UnitRegistry(parsed.unit_families)
  -> install registry as the active global registry
       -> clear Phase 5+ registry-keyed caches, if present
  -> parse providers
  -> return DataSnapshot(providers=..., from_auto_update=True)
       -> if provider parsing fails after registry install, keep the new registry
          and leave active providers unchanged

set_custom_snapshot(snapshot)
  -> if snapshot is None: clear custom snapshot
  -> in Phases 1-4: do not validate ModelPrice objects at activation time
  -> in Phases 1-4: candidate dynamic price keys, ancestor coverage, and join coverage are validated on use by ModelPrice.calc_price()
  -> validate extractor destinations when UsageExtractor objects are constructed, plus lifecycle boundaries that already own extractor validation for the current phase
  -> activate provider data as the active provider snapshot
```

Unit registry updates and provider snapshot activation are deliberately separate. Trusted remote unit families are global runtime state after structural registry validation succeeds. Provider activation is not a model-price validation boundary; standard base pricing validates the selected model price every time it calculates unless Phase 5 cache state safely covers that exact model price and active registry.

## Python Custom Price Flow

```text
snapshot = get_snapshot() or an inactive snapshot returned from fetch()
  -> use lookup helpers to find providers/models on that snapshot
  -> mutate relevant ModelPrice objects for registered price keys as needed
  -> if snapshot is inactive: set_custom_snapshot(snapshot)
       -> in Phases 1-4: activate without model-price validation
       -> activate on success
  -> if snapshot is already active:
       -> supported mutations have already updated the active snapshot
       -> in Phases 1-4: changed prices are validated by the next standard base calc before pricing
       -> in Phase 5+: changed key sets miss the validation cache and revalidate before pricing
```

Custom `ModelPrice` overrides receive the original usage object. The base `ModelPrice.calc_price()` wraps usage internally only for registry-driven pricing.

## Python Hot Path

```text
ModelInfo.calc_price(usage, provider, ...)
  -> model_price = self.get_prices(genai_request_timestamp)
  -> model_price.calc_price(usage)

ModelPrice.calc_price(usage)
  -> registry = _get_registry()
  -> validate this ModelPrice against registry
       -> in Phases 1-4: always run this one-model validation before pricing
       -> in Phase 5+: skip validation only when global cache covers this ModelPrice fingerprint and registry id
  -> smart_usage = Usage.from_raw(usage)
  -> resolve price keys to usage keys
  -> group priced units by family
  -> for each family:
       -> if requests, use fixed leaf value {"requests": 1}
       -> otherwise compute decomposition from explicit smart_usage values
       -> raise when a missing ancestor or overlap would need inference
  -> total_input_tokens = smart_usage.input_tokens only if a TieredPrices value is configured
       -> otherwise use a neutral threshold because non-tiered prices ignore it
       -> safe missing reads return zero; ambiguous missing reads raise
  -> for each priced usage-keyed unit:
       -> price = stored price at unit.price_key
       -> cost = calc_unit_price(price, leaf_count, total_input_tokens, family.per)
       -> aggregate by direction
  -> return input_price, output_price, total_price
```

Tier selection reads `input_tokens` through the normal usage-read path. If `input_tokens` is stored, the runtime uses it directly for tier selection without auditing descendant counts. If it is safely missing, the threshold is zero. If it is ambiguously missing, pricing raises rather than guessing a threshold.

## JavaScript Runtime Activation

```text
generated data.ts
  -> data bootstraps providerData
generated dataUnits.ts
  -> unitFamiliesData bootstraps units.ts
  -> do not validate every generated model price at module startup
  -> do not precompute decomposition state
  -> do not require generated data.ts or dataUnits.ts to emit per-price validation markers
  -> in Phase 5+: create module-private validation caches for the active global registry

runtime update
  -> parse wrapped JSON
  -> parsedFamilies = parseFamilies(parsed.unit_families)
  -> setUnitFamilies(parsedFamilies)
       -> clears Phase 5+ registry-keyed caches, if present
  -> parse provider data
  -> setProviderData(parsed.providers)
       -> treat parsed provider data as prevalidated for parsedFamilies without full price validation
  -> if family parsing fails:
       -> keep both active registry and providerData unchanged
  -> if provider parsing fails after setUnitFamilies:
       -> keep the new active registry and keep the previous providerData
```

Checked-in JavaScript examples that cache provider data must cache and restore the wrapped payload shape after Phase 3, not a bare provider array.
