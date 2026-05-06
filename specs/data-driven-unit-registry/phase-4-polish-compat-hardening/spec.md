# Phase 4: Polish and Compatibility Hardening

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 4 hardens the authoring and compatibility surfaces after the shared contract works.**
The registry model, wrapped payloads, public key-name safety, and base dynamic price-key support are already proven by Phases 1 through 3. Phase 4 makes the feature easier and safer to use without changing pricing semantics.

**Provider YAML authoring gets registry-derived autocomplete.** _(from "Phase 4 hardens the authoring and compatibility surfaces after the shared contract works")_
Generated provider YAML schemas derive allowed price keys and extractor destinations from the registry. This is editor support, not the source of truth. Build/export validation remains authoritative.

**Authoring names should remain pattern-matchable.** _(from "Provider YAML authoring gets registry-derived autocomplete")_
The built-in token registry should keep consistent names that authors can infer from nearby examples. Cached modality token names follow the existing `cache_{modality}_{op}` pattern, non-cached modality names follow `{direction}_{modality}`, price keys use `_mtok`, and usage keys use `_tokens`. Schema generation helps authors discover those names, but validation still comes from registry data rather than a handwritten naming convention table.
Phase 4 adds data regression tests for these built-in token naming conventions. Those tests protect repo-authored token data; they do not become runtime validation rules for arbitrary families.

**Python dataclass subclasses can accept undeclared registered dynamic price-key kwargs.** _(from "Phase 4 hardens the authoring and compatibility surfaces after the shared contract works")_
Base `ModelPrice` already accepts dynamic registered price keys in Phase 3. Phase 4 extends that compatibility to common `@dataclass` subclasses by intercepting undeclared candidate dynamic price-key kwargs before the generated dataclass constructor rejects them.

**CLI price presentation becomes registry-driven.** _(from "Phase 4 hardens the authoring and compatibility surfaces after the shared contract works")_
The CLI derives price labels and normalization display from unit metadata instead of hardcoded price-field maps. Existing output remains familiar for current units, and new registered units can appear without code changes.

**Phase 4 does not add runtime validation performance state.** _(from "Phase 4 hardens the authoring and compatibility surfaces after the shared contract works")_
Validation caches, price-key fingerprints, and decomposition caches still wait for Phase 5.
