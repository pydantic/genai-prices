# Cohere Extractor - billed_units vs tokens Source Decision

## Issue Reference

[pydantic/genai-prices#324](https://github.com/pydantic/genai-prices/issues/324) - Gap #2

## Problem Statement

The Cohere default extractor uses `root: [usage, billed_units]` to extract token counts, but pydantic-ai currently extracts from `usage.tokens`. These two sources return significantly different values for the same request, causing a mismatch when pydantic-ai migrates to use genai-prices' `RequestUsage.extract()`.

**Concrete example from test data** (`tests/dataset/usages.json:9968-9993`):

```json
{
  "body": {
    "file": "models/cassettes/test_cohere/test_cohere_model_instructions.yaml",
    "usage": {
      "billed_units": {
        "input_tokens": 13,
        "output_tokens": 61
      },
      "tokens": {
        "input_tokens": 542,
        "output_tokens": 63
      }
    }
  },
  "extracted": [
    {
      "extractors": [{ "api_flavor": "default", "provider_id": "cohere" }],
      "usage": { "input_tokens": 13, "output_tokens": 61 }
    }
  ]
}
```

genai-prices extracts `input_tokens=13` (from `billed_units`), while pydantic-ai reports `input_tokens=542` (from `tokens`). That is a **41x difference** in reported input tokens.

A second test case (`tests/dataset/usages.json:9997-10024`) shows an even more extreme ratio:

- `billed_units.input_tokens`: 1
- `tokens.input_tokens`: 496
- **496x difference**

## Current State Analysis

### Cohere extractor configuration (`prices/providers/cohere.yml:11-28`)

```yaml
extractors:
  # https://github.com/cohere-ai/cohere-python/blob/5.16.3/src/cohere/types/usage.py#L13
  # and https://github.com/cohere-ai/cohere-python/blob/5.16.3/src/cohere/types/usage_billed_units.py
  - root: [usage, billed_units]
    mappings:
      - path: input_tokens
        dest: input_tokens
      - path: output_tokens
        dest: output_tokens
  # https://github.com/cohere-ai/cohere-python/blob/v5.16.3/src/cohere/types/embed_by_type_response.py#L30
  # and https://github.com/cohere-ai/cohere-python/blob/v5.16.3/src/cohere/types/api_meta.py#L15
  # and https://github.com/cohere-ai/cohere-python/blob/v5.16.3/src/cohere/types/api_meta_billed_units.py
  - api_flavor: embeddings
    root: [meta, billed_units]
    mappings:
      - path: input_tokens
        dest: input_tokens
```

Key observations:

- The default flavor uses `root: [usage, billed_units]`
- The embeddings flavor also uses `billed_units` (via `[meta, billed_units]`)
- No extractor exists for `usage.tokens`
- Introduced in commit `a732789` ("Extract `Usage` from API responses (#116)") by Samuel Colvin

### How extractors are consumed (`packages/python/genai_prices/types.py:314-336`)

```python
def extract_usage(self, response_data: Any, *, api_flavor: str = 'default') -> tuple[str | None, Usage]:
    ...
    extractor = next(e for e in self.extractors if e.api_flavor == api_flavor)
    return extractor.extract(response_data)
```

The `api_flavor` defaults to `'default'`. Since Cohere's first extractor has no explicit `api_flavor`, it gets `'default'` (from `UsageExtractor.api_flavor` default at `types.py:376`).

### How `calc_price` uses extracted tokens (`packages/python/genai_prices/types.py:611-659`)

The `calc_price` method uses `usage.input_tokens` directly for cost calculation. For Cohere models (which have no cache pricing), the calculation is straightforward:

- `input_price = input_mtok * input_tokens / 1_000_000`
- `output_price = output_mtok * output_tokens / 1_000_000`

**This means the extracted token count directly determines the cost.** Using `billed_units` (13 tokens) vs `tokens` (542 tokens) produces a 41x cost difference.

## Evidence

### 1. Cohere API Documentation

From the [Cohere Chat API Reference](https://docs.cohere.com/reference/chat), the `Usage` response object contains:

| Sub-object     | Field             | Description                                                |
| -------------- | ----------------- | ---------------------------------------------------------- |
| `tokens`       | `input_tokens`    | "The number of tokens used as input to the model"          |
| `tokens`       | `output_tokens`   | "The number of tokens produced by the model"               |
| `billed_units` | `input_tokens`    | "The number of billed input tokens"                        |
| `billed_units` | `output_tokens`   | "The number of billed output tokens"                       |
| `billed_units` | `search_units`    | "The number of billed search units"                        |
| `billed_units` | `classifications` | "The number of billed classifications units"               |
| (top-level)    | `cached_tokens`   | "The number of prompt tokens that hit the inference cache" |

**Semantic difference**: `tokens` = actual processing counts; `billed_units` = what users are charged for.

The large discrepancy (13 vs 542 input tokens) likely comes from Cohere's system prompt / preamble tokens not being billed, or from internal RAG/tool tokens being included in processing but not billing.

### 2. Cohere Python SDK References

The YAML comments reference:

- [`cohere/types/usage.py#L13`](https://github.com/cohere-ai/cohere-python/blob/5.16.3/src/cohere/types/usage.py#L13) - The `Usage` class with `billed_units` and `tokens` fields
- [`cohere/types/usage_billed_units.py`](https://github.com/cohere-ai/cohere-python/blob/5.16.3/src/cohere/types/usage_billed_units.py) - The `UsageBilledUnits` class

### 3. Test Data Evidence

Four Cohere test cases exist in `tests/dataset/usages.json`:

| Test file                            | billed_units input | tokens input | Ratio |
| ------------------------------------ | ------------------ | ------------ | ----- |
| (no tokens field)                    | 431                | N/A          | N/A   |
| test_cohere_model_instructions       | 13                 | 542          | 41.7x |
| test_request_simple_success_with_vcr | 1                  | 496          | 496x  |
| (4th case)                           | 25                 | N/A          | N/A   |

Note: Two test cases don't have a `tokens` sub-object at all, suggesting it may not always be present.

### 4. Cohere Pricing Model

Cohere's pricing page lists prices per million tokens. The question is: which token count do they mean?

Given that `billed_units` is explicitly named as "billed" and the Cohere SDK/API separates it from raw token counts, Cohere's pricing is almost certainly based on `billed_units`, not `tokens`.

### 5. No Other Provider Has This Dual-Source Pattern

No other provider in genai-prices has a similar distinction between "billed tokens" and "actual tokens". Other providers (OpenAI, Anthropic, Google, etc.) report a single token count that serves both purposes.

## Analysis of Options

### Option A: Keep `billed_units` (Status Quo)

**Pros:**

- Correct for cost calculation: `billed_units` aligns with what Cohere charges, and genai-prices is fundamentally a cost-calculation library
- Already validated: existing test expectations use `billed_units` values
- Consistent with the intent of `prices_mtok` pricing data

**Cons:**

- Breaks pydantic-ai migration: pydantic-ai currently reports `tokens` (actual processing counts) and the migration to `RequestUsage.extract()` would silently change reported values
- Token counts from `billed_units` don't represent actual resource consumption

### Option B: Switch to `tokens`

**Pros:**

- Matches pydantic-ai's current behavior, making migration seamless
- Reports actual token consumption (useful for monitoring/debugging)

**Cons:**

- **Produces incorrect cost calculations**: Using `tokens.input_tokens=542` with Cohere's `input_mtok` pricing would overcharge by 41x, because Cohere prices against billed units, not raw tokens
- Contradicts the library's core purpose (accurate cost calculation)
- `tokens` sub-object may not always be present (2 of 4 test cases lack it)

### Option C: Support Both via Separate `api_flavor`s

**Pros:**

- Maximum flexibility: callers choose `'default'` for billing-accurate extraction or `'tokens'` for raw token counts
- No breaking change to existing behavior
- Allows pydantic-ai to use `api_flavor='tokens'` during migration

**Cons:**

- Adds complexity
- May be over-engineering for a single provider quirk
- The `tokens` flavor would still produce wrong costs when fed to `calc_price`

## Recommended Approach

**Option A: Keep `billed_units` as the default extractor (status quo for genai-prices).**

### Rationale

1. **genai-prices is a cost-calculation library.** The issue itself acknowledges: "For a cost-calculation library, `billed_units` is arguably the correct source." The `input_mtok` and `output_mtok` prices in `cohere.yml` correspond to Cohere's billing unit prices, not raw token prices.

2. **Using `tokens` would produce incorrect costs.** If we extract `tokens.input_tokens=542` but the Cohere pricing (`input_mtok: 2.5`) is based on billed units, the cost calculation would be wildly wrong.

3. **The gap is a pydantic-ai concern, not a genai-prices bug.** The pydantic-ai migration should pass `api_flavor` correctly or handle the Cohere discrepancy on its side.

### However: Add a `tokens` flavor for pydantic-ai compatibility

To unblock the pydantic-ai migration, we should **also** add a `tokens` flavor extractor that extracts from `usage.tokens`. This gives pydantic-ai the option to use `api_flavor='tokens'` when it needs raw token counts for usage tracking (separate from cost calculation).

## Proposed Fix

### Changes to `prices/providers/cohere.yml`

Add a new `tokens` flavor extractor after the existing default extractor:

```yaml
extractors:
  # https://github.com/cohere-ai/cohere-python/blob/5.16.3/src/cohere/types/usage.py#L13
  # and https://github.com/cohere-ai/cohere-python/blob/5.16.3/src/cohere/types/usage_billed_units.py
  - root: [usage, billed_units]
    mappings:
      - path: input_tokens
        dest: input_tokens
      - path: output_tokens
        dest: output_tokens
  # Extractor for raw token counts (not billing-adjusted)
  # usage.tokens reports actual model processing counts, while billed_units reports billing counts
  - api_flavor: tokens
    root: [usage, tokens]
    mappings:
      - path: input_tokens
        dest: input_tokens
      - path: output_tokens
        dest: output_tokens
  # https://github.com/cohere-ai/cohere-python/blob/v5.16.3/src/cohere/types/embed_by_type_response.py#L30
  # and https://github.com/cohere-ai/cohere-python/blob/v5.16.3/src/cohere/types/api_meta.py#L15
  # and https://github.com/cohere-ai/cohere-python/blob/v5.16.3/src/cohere/types/api_meta_billed_units.py
  - api_flavor: embeddings
    root: [meta, billed_units]
    mappings:
      - path: input_tokens
        dest: input_tokens
```

### Files affected

1. `prices/providers/cohere.yml` - Add `tokens` flavor extractor
2. `prices/data.json` - Regenerated (via `make build-prices`)
3. `prices/data_slim.json` - Regenerated
4. `packages/python/genai_prices/data.py` - Regenerated (via `make package-data`)
5. `packages/js/src/data.ts` - Regenerated
6. `tests/dataset/usages.json` - May need new test cases with `api_flavor: tokens`

### No changes needed to existing test expectations

The default flavor still extracts from `billed_units`, so existing test assertions remain correct.

## Key Decision Point

**Should the default flavor change from `billed_units` to `tokens`?**

**No.** The default should remain `billed_units` because:

- genai-prices' `calc_price()` multiplies extracted token counts by `input_mtok`/`output_mtok` prices
- Cohere's published prices correspond to billed units
- Changing the default would silently break cost calculations for all existing users

The pydantic-ai team can use `api_flavor='tokens'` if they need raw counts for display/monitoring purposes.

## Testing Plan

1. **Existing tests pass unchanged** - The default extractor behavior doesn't change
2. **Add test cases for `tokens` flavor** - Add entries to `tests/dataset/usages.json` with `api_flavor: tokens` and expected values from `usage.tokens`
3. **Verify cost calculation** - Ensure `calc_price` with default-extracted values produces correct costs against Cohere's published pricing

## Risk Assessment

**Low risk.**

- **No breaking change**: The default flavor is unchanged
- **Additive only**: The `tokens` flavor is a new addition
- **`tokens` sub-object may not always be present**: Some API responses (e.g., older API versions, embedding responses) may lack `usage.tokens`. The `tokens` flavor would fail on these. This is acceptable since it's an opt-in flavor.
- **Cohere API evolution**: Cohere may change their response schema in future API versions. The existing SDK references in comments help track this.
