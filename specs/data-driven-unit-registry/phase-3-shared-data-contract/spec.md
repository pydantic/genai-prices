# Phase 3: Shared Data Contract and Base Dynamic Price Keys

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 3 makes repo-defined units an end-to-end feature.**
The shared generated payloads carry unit definitions with provider prices, both runtimes parse those wrapped payloads, and base runtime pricing can handle registered price keys that were not hardcoded before. This phase builds on the Python and JavaScript internal registry proofs from Phases 1 and 2.

**`data.json` and `data_slim.json` become wrapped top-level objects.** _(from "Phase 3 makes repo-defined units an end-to-end feature")_
Both payloads change from a bare provider list to `{"units": {...}, "providers": [...]}`. This is an intentional compatibility break for older released clients that fetch the main data URL and expect a provider array. The new wrapper is the extensibility point for future top-level fields.

This phase accepts the one-time remote-payload break rather than maintaining dual payloads, fallback wrapper detection for older clients, or a parallel versioned rollout URL. After the wrapper exists, future top-level metadata can be added without another bare-list-to-object break. `data_slim.json` undergoes the same structural change; slimming applies to provider descriptive data, while unit runtime fields remain available.

**Unit definitions travel with the prices that depend on them.** _(from "`data.json` and `data_slim.json` become wrapped top-level objects")_
Runtime auto-updates must not be able to deliver prices for units that the client does not know. The unit registry is therefore generated into `data.json` and `data_slim.json` alongside provider data, and into small language-native package modules separate from provider-heavy generated package data.

There is still no separate remote runtime unit file or update URL. Runtime package startup reads generated language-native provider data plus generated language-native unit data. Runtime auto-update reads the wrapped fetched payload, builds the fetched flat units into the one active global registry as trusted published data, and then parses or activates provider data separately. If provider parsing or activation fails after the candidate registry is installed, the runtime restores the previously active registry so old provider data is not left running against a failed update's unit definitions. Python `UpdatePrices.stop()` preserves its existing behavior of clearing the auto-updated provider snapshot; when it does that, it must also reset the active unit registry to the bundled units so bundled providers and bundled units are restored together.

**The complete repo-defined registry starts here.** _(from "Unit definitions travel with the prices that depend on them")_
`prices/units.yml` becomes the complete source for built-in repo-defined units, including the built-in token lattice needed by the shared pricing semantics. The source is a flat usage-keyed unit map. Every unit has `per`, a required `dimensions.family` value, and optional `price_key`. Full registry join-closedness is now a build/export validation rule rather than a current-subset exception.

**Family is a required ordinary dimension.** _(from "The complete repo-defined registry starts here")_
Every unit declares `dimensions.family`, and runtime registry logic treats it like any other dimension. Units from different families naturally do not overlap because their `family` dimension values conflict. Build/export validation rejects a unit missing `dimensions.family` and rejects different `per` values among units with the same family dimension value. Duplicating `per` on each unit is intentional in this experiment: the data carries the normalization at the same level as the priceable unit, while a tiny publication check recovers the invariant that one family-dimension value has one normalization factor.

**Dynamic public key names get lightweight build-time checks.** _(from "The complete repo-defined registry starts here")_
Usage keys become usage attributes and extractor destinations. Price keys become model-price attributes and provider YAML keys. Registry-defined keys must therefore be public and attribute-safe before they can travel in wrapped runtime payloads. Build/export validation rejects obvious unsafe public names such as names that are not JavaScript-compatible ASCII identifiers, private names, and JavaScript language keywords.

**Reserved-name validation is not semantic unit-name whitelisting.** _(from "Dynamic public key names get lightweight build-time checks")_
The denylist, if any, must stay tiny and generic. It must not hardcode commercial pricing concepts such as `input_tokens` or `input_mtok`, and it must not become a large cross-runtime collision system.

**Provider prices and extractor destinations validate against the same registry payload.** _(from "Unit definitions travel with the prices that depend on them")_
Build/export validation constructs the registry from `prices/units.yml`, validates unit publication rules, validates provider price keys, ancestor coverage, join coverage, and extractor destinations, then writes the wrapped payload. Fetched wrapped payload units and model prices are treated as prevalidated by the publisher.

The build/export validator is the publication trust boundary. It must be reusable outside the repo-specific build command so external payload producers can validate providers plus raw units before hosting data for `UpdatePrices(url=...)`. Client fetches should not re-run unit-only or price-level publication validation on every update. Unit-only publication validation is a Python build/export concern; there is no JavaScript/runtime `validateUnits` equivalent. Until Phase 5 adds runtime-private global validation caches, standard runtime pricing still validates the selected model price every time before calculating against it.

**Python base `ModelPrice` accepts registered non-hardcoded price keys.** _(from "Phase 3 makes repo-defined units an end-to-end feature")_
Base `ModelPrice` stores candidate dynamic price-key kwargs outside the legacy dataclass fields and accepts or rejects them when validation runs against the active global registry. A registered future key works on the base class without adding a new field. A misspelled key fails validation instead of disappearing.

**Dataclass subclass constructor support for undeclared dynamic price keys waits for Phase 4.** _(from "Python base `ModelPrice` accepts registered non-hardcoded price keys")_
Phase 3 promises non-hardcoded registered key support for base `ModelPrice`. Plain Python dataclass subclasses accepting undeclared dynamic price-key kwargs require additional constructor interception and are handled as compatibility polish in Phase 4.

**Runtime validation caching still waits for Phase 5.** _(from "Provider prices and extractor destinations validate against the same registry payload", "Python base `ModelPrice` accepts registered non-hardcoded price keys")_
Phase 3 repeats one-model validation before every standard base pricing calculation, including for dynamic price keys. It must not add model-price validation caches, generated validation markers, or decomposition caches.
