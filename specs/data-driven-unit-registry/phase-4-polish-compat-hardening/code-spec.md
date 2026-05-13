# Code Spec: Phase 4 Polish and Compatibility Hardening

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Previous phase:** [Phase 3 Shared Data Contract and Base Dynamic Price Keys](../phase-3-shared-data-contract/code-spec.md).

**Phase 4 adds polish without changing accepted pricing semantics.** _(implements "Phase 4 hardens the authoring and compatibility surfaces after the shared contract works")_
Modify existing schema, CLI, and Python `ModelPrice` code. Do not change the wrapped payload shape, decomposition behavior, public key-name safety validation, price validation rules, or public API signatures established by Phase 3.

**Generate provider YAML schemas from the registry.** _(implements "Provider YAML authoring gets registry-derived autocomplete")_
Update schema generation so provider YAML price keys come from `registry.price_keys` and extractor destinations come from externally reported usage keys. The generated schema should improve autocomplete and inline feedback, but build/export validation remains the authoritative check. Schema generation must not hardcode ordinary unit names; the explicit `requests` pricing-only exclusion is allowed where needed.

Keep the authoring schema aligned with the built-in naming patterns in the registry, but do not move those patterns into validation code. The schema is regenerated from the registry when units change. It may expose autocomplete for names such as `cache_audio_read_mtok` and `cache_image_read_mtok` because those are registry price keys, not because the schema generator knows token modality concepts.

Add repo data regression tests that walk units whose `dimensions.family` value is `tokens` in `prices/units.yml` and assert that token usage keys, price keys, non-cached modality names, and cached modality names follow the documented built-in conventions. Keep these tests scoped to repo-authored built-in token data; production registry validation must not enforce token-specific semantic naming rules for arbitrary family dimension values.

**Add Python dataclass-subclass dynamic price-key constructor support.** _(implements "Python dataclass subclasses can accept undeclared registered dynamic price-key kwargs")_
Introduce constructor interception around `ModelPrice` subclasses, for example with `ModelPriceMeta`, so undeclared candidate dynamic price-key kwargs are split before a generated dataclass subclass `__init__` receives them. The normal subclass constructor receives declared subclass fields. Captured dynamic price keys are stored in base `_extra_prices` and validated later against the active global registry.

Preserve existing behavior for declared custom subclass fields such as `sausage_price`: they remain subclass-owned custom state unless the registry also declares them as price keys.

**Make CLI price display registry-driven.** _(implements "CLI price presentation becomes registry-driven")_
Update `_cli_impl.py` so price-field collection iterates each `ModelPrice` object's effective stored price keys, labels derive from unit metadata and family normalization, and formatting does not depend on a hardcoded dataclass-field list. Existing CLI flags and output for current units should remain compatible.

Concretely:

- `_collect_model_price_fields()` iterates stored/effective price keys from each `ModelPrice` instead of `dataclasses.fields(ModelPrice)`.
- `_price_field_label()` derives labels from `UnitDef.dimensions` and `UnitDef.per` instead of a hardcoded field-name map.
- `_format_model_price_value()` and `_format_model_prices()` iterate registry-backed price keys and format values generically.

The CLI may keep compatibility aliases and familiar labels for existing units, but new registered units must appear without adding new hardcoded price-field branches.

**Tests cover hardening boundaries.** _(implements "Phase 4 hardens the authoring and compatibility surfaces after the shared contract works")_
Add tests for built-in token naming convention regressions, generated provider schema price-key and extractor-destination suggestions, dataclass subclass constructor handling for undeclared dynamic price keys plus declared custom fields, and CLI display of both legacy and newly registered price keys.
