# Phase 4: Polish and Compatibility Hardening

**Code-level architecture is in [code-spec](code-spec.md).**

**Phase 4 hardens the authoring and compatibility surfaces after the core works.**
The registry model, wrapped payloads, public key-name safety, and base dynamic price-key support are already proven by Phase 3. Phase 4 makes the feature easier and safer to use without changing pricing semantics.

**Provider YAML authoring gets registry-derived autocomplete.** _(from "Phase 4 hardens the authoring and compatibility surfaces after the core works")_
Generated provider YAML schemas derive allowed price keys and extractor destinations from the registry. This is editor support, not the source of truth. Build/export validation remains authoritative.

**Authoring names should remain pattern-matchable.** _(from "Provider YAML authoring gets registry-derived autocomplete")_
The built-in token registry should keep consistent names that authors can infer from nearby examples. Cached modality token names follow the existing `cache_{modality}_{op}` pattern, non-cached modality names follow `{direction}_{modality}`, price keys use `_mtok`, and usage keys use `_tokens`. Schema generation helps authors discover those names, but validation still comes from registry data rather than a handwritten naming convention table.
Phase 4 adds data regression tests for these built-in token naming conventions. Those tests protect repo-authored token data; they do not become runtime validation rules for arbitrary family dimension values.

**Python `ModelPrice` uses one direct runtime storage model.** _(from "Phase 4 hardens the authoring and compatibility surfaces after the core works")_
Base `ModelPrice` accepts dynamic price-key kwargs and stores them as normal public instance attributes. It should not preserve legacy price keys as declared dataclass fields, and it should not introduce a hidden `_extra_prices` side store. Custom `ModelPrice` subclasses can keep overriding `calc_price()` and owning their own custom fields, but Phase 4 does not require generated dataclass subclass constructors to accept undeclared dynamic price-key kwargs.

**Old and new price keys use the same runtime surface.** _(from "Python `ModelPrice` uses one direct runtime storage model")_
Legacy price keys such as `input_mtok` remain accepted as constructor kwargs and readable attributes, but they should not stay as special declared dataclass fields. Registry-defined old and new keys should behave the same for construction, attribute access, validation, calculation, string formatting, and CLI display. Dataclass introspection and constructor-signature IDE hints are allowed to lose the legacy price-key list because newly registered keys could not be represented there anyway.

**Runtime provider parsing is an internal normalization step.** _(from "Python `ModelPrice` uses one direct runtime storage model")_
The runtime package does not need to preserve `providers_schema` as a public parsing contract. `UpdatePrices.fetch()` and package-data generation may normalize raw provider payloads internally by converting price mappings into runtime `ModelPrice` objects before validating the surrounding provider dataclasses.

**CLI price presentation becomes registry-driven.** _(from "Phase 4 hardens the authoring and compatibility surfaces after the core works")_
The CLI derives price labels and normalization display from unit metadata instead of hardcoded price-field maps. Existing output remains familiar for current units, and new registered units can appear without code changes.

**Phase 4 does not add runtime validation performance state.** _(from "Phase 4 hardens the authoring and compatibility surfaces after the core works")_
Validation caches, price-key fingerprints, and decomposition caches still wait for Phase 5.
