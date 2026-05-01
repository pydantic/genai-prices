# Phase 4: Polish and Compatibility Hardening

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 4 hardens the authoring and compatibility surfaces after the shared contract works.**
The registry model, wrapped payloads, and base dynamic price-key support are already proven by Phases 1 through 3. Phase 4 makes the feature easier and safer to use without changing pricing semantics.

**Provider YAML authoring gets registry-derived autocomplete.** _(from "Phase 4 hardens the authoring and compatibility surfaces after the shared contract works")_
Generated provider YAML schemas derive allowed price keys and extractor destinations from the registry. This is editor support, not the source of truth. Build/export validation remains authoritative.

**Dynamic public key names are validated for both runtimes.** _(from "Phase 4 hardens the authoring and compatibility surfaces after the shared contract works")_
Usage keys become usage attributes and extractor destinations. Price keys become model-price attributes and provider YAML keys. Registry-defined keys must therefore be public, attribute-safe, and free of collisions with Python or JavaScript runtime behavior. The validation rejects private or dunder-like names, language keywords where relevant, prototype-like names, and names already owned by `Usage` or `ModelPrice`.

**Reserved-name validation is not semantic unit-name whitelisting.** _(from "Dynamic public key names are validated for both runtimes")_
The denylist can mention runtime method/property names and a small shared cross-language reserved set, but it must not hardcode commercial pricing concepts such as `input_tokens` or `input_mtok`.

**Python dataclass subclasses can accept undeclared registered dynamic price-key kwargs.** _(from "Phase 4 hardens the authoring and compatibility surfaces after the shared contract works")_
Base `ModelPrice` already accepts dynamic registered price keys in Phase 3. Phase 4 extends that compatibility to common `@dataclass` subclasses by intercepting undeclared candidate dynamic price-key kwargs before the generated dataclass constructor rejects them.

**CLI price presentation becomes registry-driven.** _(from "Phase 4 hardens the authoring and compatibility surfaces after the shared contract works")_
The CLI derives price labels and normalization display from unit metadata instead of hardcoded price-field maps. Existing output remains familiar for current units, and new registered units can appear without code changes.

**Phase 4 does not add runtime validation performance state.** _(from "Phase 4 hardens the authoring and compatibility surfaces after the shared contract works")_
Validation trust contexts, price-key fingerprints, dirty sets, and decomposition caches still wait for Phase 5.
