# Code Spec: Phase 4 Polish and Compatibility Hardening

**This implements the prose spec in [spec](spec.md), which is the primary source of truth.**
**Previous phase:** [Phase 3 Shared Data Contract and Base Dynamic Price Keys](../phase-3-shared-data-contract/code-spec.md).

**Phase 4 adds polish without changing accepted pricing semantics.** _(implements "Phase 4 hardens the authoring and compatibility surfaces after the shared contract works")_
Modify existing registry, schema, CLI, and Python `ModelPrice` code. Do not change the wrapped payload shape, decomposition behavior, price validation rules, or public API signatures established by Phase 3.

**Add cross-language public-key safety validation.** _(implements "Dynamic public key names are validated for both runtimes", "Reserved-name validation is not semantic unit-name whitelisting")_
Add a validation helper equivalent to:

```python
def validate_public_registry_key_names(registry: UnitRegistry) -> None:
    """Reject usage/price keys that are unsafe dynamic attributes in Python or JS."""
```

Run it during build/export validation and custom snapshot activation after structural registry construction. Reject invalid identifier-like names, names beginning with `_`, dunder names, Python keywords when exposed as Python attributes, JavaScript prototype/object names such as `__proto__`, `prototype`, and `constructor`, and names already owned by `Usage` or `ModelPrice` public or internal surfaces. Derive class-owned names from the runtime classes where practical and keep the shared denylist small.

**Generate provider YAML schemas from the registry.** _(implements "Provider YAML authoring gets registry-derived autocomplete")_
Update schema generation so provider YAML price keys come from `registry.price_keys` and extractor destinations come from externally reported usage keys. The generated schema should improve autocomplete and inline feedback, but build/export validation remains the authoritative check. Schema generation must not hardcode ordinary unit names; the explicit `requests` pricing-only exclusion is allowed where needed.

Keep the authoring schema aligned with the built-in naming patterns in the registry, but do not move those patterns into validation code. The schema is regenerated from the registry when units change. It may expose autocomplete for names such as `cache_audio_read_mtok` and `cache_image_read_mtok` because those are registry price keys, not because the schema generator knows token modality concepts.

**Add Python dataclass-subclass dynamic price-key constructor support.** _(implements "Python dataclass subclasses can accept undeclared registered dynamic price-key kwargs")_
Introduce constructor interception around `ModelPrice` subclasses, for example with `ModelPriceMeta`, so undeclared candidate dynamic price-key kwargs are split before a generated dataclass subclass `__init__` receives them. The normal subclass constructor receives declared subclass fields. Captured dynamic price keys are stored in base `_extra_prices` and validated later against the active or staged registry.

Preserve existing behavior for declared custom subclass fields such as `sausage_price`: they remain subclass-owned custom state unless the registry also declares them as price keys.

**Make CLI price display registry-driven.** _(implements "CLI price presentation becomes registry-driven")_
Update `_cli_impl.py` so price-field collection iterates each `ModelPrice` object's effective stored price keys, labels derive from unit metadata and family normalization, and formatting does not depend on a hardcoded dataclass-field list. Existing CLI flags and output for current units should remain compatible.

**Tests cover hardening boundaries.** _(implements "Phase 4 hardens the authoring and compatibility surfaces after the shared contract works")_
Add tests for reserved-name rejection in both Python and JavaScript-relevant cases, generated provider schema price-key and extractor-destination suggestions, dataclass subclass constructor handling for undeclared dynamic price keys plus declared custom fields, and CLI display of both legacy and newly registered price keys.
