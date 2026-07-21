# Phase 1: Static Unit Registry Release

**Phase 1 implementation follows the linked code-level architecture.**
Code-level architecture is in [code-spec](code-spec.md).

**Phase 1 preserves the shared registry and pricing invariants.**
The [root specification](../spec.md) remains authoritative for exact unit identity and normalization rules, dimension containment and closure, explicit-only usage, complete price coverage, decomposition, cost aggregation, request and tiered-price exceptions, compatibility, and generated-output purity. Phase 1 changes delivery and runtime lifecycle boundaries without weakening those semantics.

**Phase 1 must be independently shippable and releasable.**
It delivers meaningful pricing improvements without requiring runtime-updated unit definitions, cache machinery, or a breaking change to the existing auto-update artifact.

**Pricing accuracy is the Phase 1 product outcome.**
Repo-defined units, including image and other modality-specific token units, must work end to end in Python and JavaScript. The release includes the pricing-data corrections required by complete ancestor and overlap pricing.

**Phase 1 must avoid an unreasonable pricing hot-path regression.**
The registry may add structural work needed for correctness, but ordinary calculations should not repeatedly rediscover the same per-call facts. Phase 1 includes only a small stateless cleanup of the obvious repeated work.

**Phase 1 preserves supported consumer behavior unless accurate registry pricing makes that impossible.**
Existing calculation entry points, provider/model lookup, tiered prices, request pricing, permissive raw Python usage objects, JavaScript plain usage objects, custom Python `ModelPrice` overrides, custom provider snapshots, and familiar price/usage attribute access remain supported. Fixed dataclass introspection for `Usage` and incomplete fallback pricing for overlapping units are not preserved because they conflict with registry-shaped storage or accurate bucket assignment.

**Public pricing and snapshot APIs keep their callable shape.** _(from "Phase 1 preserves supported consumer behavior")_
`calc_price(...)`, JavaScript `calcPrice(...)`, `ModelPrice.calc_price(...)`, `ModelInfo.calc_price(...)`, `DataSnapshot.calc(...)`, `UpdatePrices.fetch()`, and `set_custom_snapshot(...)` remain recognizable entry points. `DataSnapshot` remains provider data only.

**Manual Python pricing extensions remain supported.** _(from "Phase 1 preserves supported consumer behavior")_
Custom `ModelPrice` subclasses may override `calc_price()` and inspect custom fields on the original usage object. Base registry validation does not treat subclass-only custom state as a price unless the bundled registry names that field as a price key.

**Units are repo-defined data used by handwritten runtime code.**
`prices/units.yml` defines usage-keyed units with a normalization factor, an optional distinct price key, and dimension assignments including a required `family` dimension. Generated language-native data carries those definitions into both packages; handwritten runtime modules derive behavior through `UnitRegistry` rather than generated fields or hardcoded unit-name branches.

**The Phase 1 registry is static for the lifetime of the installed package.** _(from "Phase 1 must be independently shippable and releasable", "Units are repo-defined data used by handwritten runtime code")_
Each runtime constructs one bundled `UnitRegistry` from `data_units.py` or `dataUnits.ts`. Provider updates and custom provider snapshots do not replace, mutate, reset, or carry a second registry. Supporting remotely updated unit definitions is Phase 2.

**`UnitRegistry` is immutable indexed metadata after construction.** _(from "The Phase 1 registry is static for the lifetime of the installed package")_
Construction promotes raw units into `UnitDef` objects and precomputes indexes for usage keys, price keys, dimension sets, ancestors, joins, all public keys, externally reported usage keys, and their registry order. Runtime code reads those indexes but does not mutate the registry or rebuild derived key collections on ordinary usage and pricing operations.

**Dimensions define containment, overlap, and cost aggregation.** _(from "Units are repo-defined data used by handwritten runtime code")_
A unit is an ancestor of another unit when its dimension assignments are a subset of the other's assignments. Compatible incomparable units overlap at the unit whose dimensions are their union. Only priced units become exclusive buckets; costs aggregate into input, output, and total results through dimension filters. The shared behavior is detailed in [algorithm](../algorithm.md) and [examples](../examples.md).

**Price data is complete while usage data may be incomplete.** _(from "Pricing accuracy is the Phase 1 product outcome", "Dimensions define containment, overlap, and cost aggregation")_
Model prices must use registered price keys and include required ancestor and join prices. Usage stores reported facts only, returns zero for safely absent registered values, and raises rather than inferring a missing ancestor or overlap when positive related reports make the value ambiguous.

**Every priced usage value lands in exactly one bucket.** _(from "Price data is complete while usage data may be incomplete")_
Dimension-driven decomposition must not double-count, drop, or guess the placement of usage. Contradictory reported values may remain inert until a requested read or selected price set requires interpreting them; impossible exclusive buckets then raise a user-facing data error.

**Repo-authored prices avoid redundant equal-rate descendants.** _(from "Price data is complete while usage data may be incomplete", "Every priced usage value lands in exactly one bucket")_
A model includes a child-unit price when its rate differs from the ancestor catch-all or when ancestor or join coverage requires the explicit child. It does not duplicate an equal-rate child merely to describe the model's modality. This is a checked-in pricing-data convention, not a runtime rejection rule for custom prices.

**`requests_kcount` remains an explicit one-request pricing exception.** _(from "Units are repo-defined data used by handwritten runtime code")_
The registry represents usage key `requests`, price key `requests_kcount`, `per: 1_000`, and `family: requests`, but callers and extractors do not report it. Pricing supplies one request per calculation and includes its cost only in the total.

**Build/export validation is the authoritative publication boundary.** _(from "Price data is complete while usage data may be incomplete", "`UnitRegistry` is immutable indexed metadata after construction")_
Publication validates registry structure, public key safety, unique usage/price/dimension identities, interval closure, join-closedness, provider price-key and coverage rules, and extractor destinations before generated artifacts are written. Runtime registry construction trusts generated package unit data and indexes it without repeating publication validation.

**Model prices are still validated on use.** _(from "Build/export validation is the authoritative publication boundary", "Manual Python pricing extensions remain supported")_
Construction can precede or bypass publication validation for custom objects, so standard base pricing validates the selected model price against the bundled registry before decomposition. Phase 1 does not attach trust flags or validation markers to generated data.

**Python `Usage` stores reported registry values directly.** _(from "Price data is complete while usage data may be incomplete", "Public pricing and snapshot APIs keep their callable shape")_
Direct construction accepts externally reported bundled-registry keys and rejects unknown or pricing-only keys. `Usage.from_raw(...)` reads known attributes from dataclasses, namespace objects, and other attribute objects while ignoring extras; it does not add plain-mapping input compatibility. The original object remains available to custom overrides. Assigning a registered key stores its value or removes it when assigned `None`; nonregistered names remain ordinary attributes. Equality, addition, representation, and missing reads consider only bundled-registry reported values.

**Python `ModelPrice` uses direct public attribute storage.** _(from "Manual Python pricing extensions remain supported", "Model prices are still validated on use")_
Base `ModelPrice` is a plain class whose construction accepts candidate dynamic price-key keyword arguments and stores them as ordinary attributes. It has no declared dataclass price fields, metaclass or Pydantic core-schema customization, or hidden `_extra_prices` store. Registered old and new keys share construction, reads, validation, calculation, string display, and CLI behavior; an absent registered price key reads as `None`, and ordinary assignment and deletion need no custom hooks. Custom subclasses may own custom state and override pricing, but generated dataclass subclass constructors are not required to accept undeclared dynamic price-key keyword arguments.

**Runtime provider parsing is an internal normalization step.** _(from "Python `ModelPrice` uses direct public attribute storage")_
The runtime provider schema is not a supported public parsing contract. Package generation and auto-update recursively normalize raw price mappings, validate each as `dict[str, Decimal | TieredPrices | None]`, construct `ModelPrice`, and then validate the surrounding provider dataclasses with arbitrary runtime model-price instances allowed.

**JavaScript retains plain usage and model-price objects.** _(from "Public pricing and snapshot APIs keep their callable shape", "Model prices are still validated on use")_
Registry-aware helpers read caller objects directly for pricing, while extractor output normalization retains externally reported bundled-registry usage keys. Open record types admit repo-defined keys, and runtime validation rejects unsupported direct/custom price keys before standard pricing.

**Extractor destinations are externally reported bundled-registry usage keys.** _(from "`UnitRegistry` is immutable indexed metadata after construction", "Python `Usage` stores reported registry values directly")_
Provider mappings may target reportable usage keys, including new modality keys, but not price keys, arbitrary names, or pricing-only `requests`. Build validation is authoritative; runtime provider activation checks destinations against the same static registry before replacing active provider data. Extraction accumulates reported counts but does not certify that a provider's related usage values are mutually consistent; contradictions remain subject to the explicit-only read and pricing rules.

**Python extractor construction keeps its public compatibility boundary.** _(from "Phase 1 preserves supported consumer behavior", "Extractor destinations are externally reported bundled-registry usage keys")_
`UsageExtractorMapping.dest` remains `str`, and direct `UsageExtractor` construction validates every mapping destination against the bundled registry.

**Provider YAML authoring derives allowed keys from the registry.** _(from "Build/export validation is the authoritative publication boundary")_
Generated editor schemas expose registry price keys and extractor destinations for autocomplete while build/export validation remains authoritative. Repo-data regression tests require built-in token usage keys to end in `_tokens`, token price keys to end in `_mtok`, non-cached modality names to follow `{direction}_{modality}`, and cached modality names to follow `cache_{modality}_{op}`. These are authoring conventions, not runtime laws for arbitrary future families.

**CLI price presentation is registry-driven.** _(from "Python `ModelPrice` uses direct public attribute storage", "Units are repo-defined data used by handwritten runtime code")_
CLI field discovery, labels, normalization display, and value formatting use stored price keys plus unit metadata. A repo-defined unit appears without a new hardcoded CLI branch.

**Phase 1 preserves the existing CLI surface.** _(from "Phase 1 preserves supported consumer behavior", "CLI price presentation is registry-driven")_
CLI flag names and option semantics supported at target-main commit `ba8093719f296a3672ff4b2fc848a122e92a049c` remain unchanged. Output for that baseline's legacy unit vocabulary remains familiar while registry-defined fields extend it.

**The existing v1 JSON artifacts are pinned in Phase 1.** _(from "Phase 1 must be independently shippable and releasable", "Phase 1 preserves supported consumer behavior")_
This branch restores the four files below to their exact blobs at target-main commit `ba8093719f296a3672ff4b2fc848a122e92a049c`; the hashes make the baseline reproducible even if branch names move. Existing package versions continue using the existing `data.json` URL and provider-array contract without seeing new unit keys, extractor destinations, or a wrapped root.

- `prices/data.json`: SHA-256 `1941f414dc96f4a73dc78a4a5de3f8fdff76140e3edcf586f5b6408ec4c3cc79`
- `prices/data_slim.json`: SHA-256 `6e74a8b8ff87a006da329262a339e47c8d5df28829e07c76cafdbe2af9df0333`
- `prices/data.schema.json`: SHA-256 `af9ebea4214da05756b6a95f7befe33b0e73ac9e218eada6b7800ab8915744fb`
- `prices/data_slim.schema.json`: SHA-256 `6356b78d316f9ffb2a20e79c635620ae87ead977be8e989f28383fb840ba3ba9`

**Phase 1 publishes provider-array `data_v2.json`.** _(from "The existing v1 JSON artifacts are pinned in Phase 1", "Pricing accuracy is the Phase 1 product outcome")_
The v2 artifact keeps the same top-level provider-array shape as v1 but may contain prices and extractor destinations for every unit bundled with Phase 1. Its schema is published separately as `data_v2.schema.json`; it does not contain unit definitions or runtime performance state.

**Phase 1 auto-updaters use only `data_v2.json`.** _(from "Phase 1 publishes provider-array `data_v2.json`", "The Phase 1 registry is static for the lifetime of the installed package")_
New Python and JavaScript packages fetch provider arrays from the v2 URL and activate only provider data. The bundled registry remains unchanged on successful updates, failed updates, updater shutdown, and custom snapshot activation.

**The v2 unit vocabulary is frozen.** _(from "Phase 1 auto-updaters use only `data_v2.json`")_
Ordinary provider, model, and price-value updates may continue within the unit and extractor vocabulary understood by Phase 1 packages. New unit definitions, price keys, or extractor destination keys wait for the versioned Phase 2 payload rather than appearing later at the v2 URL and breaking an already released v2 parser.

**Generated package providers and units have separate inputs.** _(from "Phase 1 publishes provider-array `data_v2.json`", "The Phase 1 registry is static for the lifetime of the installed package")_
Package generation reads providers from the v2 provider array and generates unit modules from the checked-in unit source. Generated `data.py` / `data.ts` contain providers, while `data_units.py` / `dataUnits.ts` contain raw unit definitions. None contains cache state, trust markers, fingerprints, or generated behavior.

**Phase 1 removes repeated structural work from the pricing hot path.** _(from "Phase 1 must avoid an unreasonable pricing hot-path regression", "Model prices are still validated on use")_
The registry refactor must not repeatedly scan the whole bundled registry to rediscover the same current model-price facts. This is a stateless cleanup, not a cache: each calculation derives its effective non-null price entries and corresponding units once, validates that structure, and reuses it for decomposition, tier detection, normalization, and aggregation.

**JavaScript model validation materializes key and unit collections once.** _(from "Phase 1 removes repeated structural work from the pricing hot path")_
Composed validation helpers may remain independently callable, but standard `calcPrice(...)` does not repeatedly validate, copy, and resolve the same iterable while checking keys, ancestors, and joins.

**Tests prove the complete releasable contract.** _(from "Phase 1 must be independently shippable and releasable")_
Coverage includes registry construction and publication validation; duplicate usage, price, and dimension identities; exact interval and join closure; public-name rejection; Python/JavaScript pricing parity; new modality and image-token prices; explicit-only and contradictory usage behavior; dynamic and misspelled price keys; custom Python pricing; flat and tiered raw-provider normalization; extractor destinations; built-in naming conventions; authoring schemas; CLI display of legacy and new registered prices; generated provider/unit separation and purity; unchanged v1 artifacts; provider-array v2 generation; no eager model-price validation during provider activation; v2 auto-update without registry replacement; rollback of failed provider activation; and alignment with the shared examples.

**Phase 1 deliberately excludes runtime-updated units and performance caches.** _(from "Phase 1 must be independently shippable and releasable", "The Phase 1 registry is static for the lifetime of the installed package", "Phase 1 removes repeated structural work from the pricing hot path")_
It does not ship wrapped provider/unit payloads, active-registry replacement, registry rollback, runtime custom units, validation identities, weak-reference caches, price-key fingerprints stored as state, decomposition plans, or decomposition caches. These exclusions keep the release smaller without blocking Phase 2's versioned unit-update contract.
