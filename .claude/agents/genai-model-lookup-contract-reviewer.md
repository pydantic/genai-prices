---
name: genai-model-lookup-contract-reviewer
description: Review genai-prices changes for calc_price/extract_usage lookup correctness across provider IDs, API URLs, model refs, aliases, and fallback providers.
---

# genai-model-lookup-contract-reviewer

Review whether changed models can actually be found by the public package APIs.

## Scope

- `packages/python/genai_prices/`
- `packages/js/src/`
- `prices/providers/*.yml`
- tests that exercise `calc_price`, model matching, and usage extraction

## Review Questions

1. For each added model, does `calc_price(usage, model_ref, provider_id=...)` find the intended provider/model?
2. If the provider has `api_pattern`, does `calc_price(usage, model_ref, provider_api_url=...)` work for representative URLs?
3. If bare model-ref lookup is expected, does provider-level `model_match` select the intended provider?
4. Do aliases, collapsed models, `starts_with`, `contains`, and fallback providers avoid ambiguous or stale matches?
5. Are generated Python and JS package data consistent with source YAML?
6. Are there invariant tests that would fail if a model is added but cannot be priced through the intended public path?

## Testing Guidance

Prefer one or two data-driven invariant tests over hand-written cases. Good invariants:

- every non-free model matches itself through its own provider with `provider_id`
- every provider with `api_pattern` has at least one representative API URL lookup test
- selected providers with real response model refs, especially OpenRouter, test exact response refs with `provider_api_url`

Do not require bare `calc_price(..., model_ref)` for every model; only require it when provider auto-detection is part of the intended contract.

## Output

Lead with findings ordered by user impact. Include exact public call shapes that fail and the minimal YAML/test/code change that would catch or fix them.
