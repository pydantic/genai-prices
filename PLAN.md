# AWS Bedrock Default Extractor - Cache Token Mapping Fix

## Issue Reference

GitHub Issue: https://github.com/pydantic/genai-prices/issues/324 (Gap #1)
Upstream: https://github.com/pydantic/pydantic-ai/issues/4818 (migration of Bedrock model to `RequestUsage.extract()`)

## Problem Statement

The **default** usage extractor for AWS Bedrock (`aws.yml` lines 10-15) only maps `inputTokens` and `outputTokens` from the Converse API response. The AWS Bedrock Converse API also returns `cacheReadInputTokens` and `cacheWriteInputTokens` in its `TokenUsage` object, but these are silently dropped during extraction.

This means when a Bedrock Converse API response includes cache token usage, the extracted `Usage` object has `cache_read_tokens=None` and `cache_write_tokens=None`, causing:

1. **Data loss** -- cache token counts are discarded
2. **Incorrect cost calculation** -- models with `cache_read_mtok` pricing (e.g., all Amazon Nova models) cannot compute the cache discount, so all tokens are billed at the full `input_mtok` rate
3. **Blocks pydantic-ai migration** -- pydantic-ai issue #4818 cannot migrate the Bedrock model to `RequestUsage.extract()` without accurate cache token extraction

### Evidence from real API response (from issue #324)

```yaml
usage:
  inputTokens: 13
  outputTokens: 5
  cacheReadInputTokens: 1504
  cacheWriteInputTokens: 0
```

Current extraction result: `Usage(input_tokens=13, output_tokens=5)` -- cache fields are `None`.

Expected result: `Usage(input_tokens=1517, cache_read_tokens=1504, cache_write_tokens=0, output_tokens=5)` (if summing into `input_tokens`, which is the recommended approach -- see Key Decision Point below).

## Current State Analysis

### File: `prices/providers/aws.yml`

#### Default extractor (lines 10-15) -- THE PROBLEM

```yaml
extractors:
  - root: usage
    mappings:
      - path: inputTokens
        dest: input_tokens
      - path: outputTokens
        dest: output_tokens
```

This extractor has `api_flavor: default` (implicit). It only maps two fields. The `cacheReadInputTokens` and `cacheWriteInputTokens` fields from the API response are ignored.

#### Anthropic flavor extractor (lines 16-35) -- THE PATTERN TO FOLLOW

```yaml
- api_flavor: anthropic
  root: usage
  mappings:
    - path: input_tokens
      dest: input_tokens
      # when Anthropic quotes prices for input tokens, they included all input tokens
    - path: cache_creation_input_tokens
      dest: input_tokens
      required: false
    - path: cache_read_input_tokens
      dest: input_tokens
      required: false
    - path: cache_creation_input_tokens
      dest: cache_write_tokens
      required: false
    - path: cache_read_input_tokens
      dest: cache_read_tokens
      required: false
    - path: output_tokens
      dest: output_tokens
```

Key observation: the anthropic flavor maps cache tokens to **both** their dedicated fields (`cache_write_tokens`, `cache_read_tokens`) **AND** sums them into `input_tokens`. This dual-mapping is intentional and required by the `calc_price` function.

### File: `packages/python/genai_prices/types.py`

#### Usage dataclass (line 230)

```python
@dataclass
class Usage:
    input_tokens: int | None = None
    cache_write_tokens: int | None = None
    cache_read_tokens: int | None = None
    output_tokens: int | None = None
    input_audio_tokens: int | None = None
    cache_audio_read_tokens: int | None = None
    output_audio_tokens: int | None = None
```

#### UsageExtractor.extract() method (line 381)

When multiple mappings point to the same `dest`, the values are summed (line 406-407):

```python
current_value = getattr(usage, mapping.dest) or 0
setattr(usage, mapping.dest, current_value + value)
```

This is the mechanism that allows mapping both `inputTokens` and `cacheReadInputTokens` to `input_tokens` -- they accumulate.

#### ModelPrice.calc_price() method (lines 611-659)

The pricing calculation **requires** `input_tokens` to be the TOTAL of all input tokens (uncached + cache_read + cache_write). It then subtracts cache tokens to find the uncached portion:

```python
uncached_text_input_tokens = usage.input_tokens or 0
uncached_text_input_tokens -= uncached_audio_input_tokens
if cache_write_tokens := usage.cache_write_tokens:
    uncached_text_input_tokens -= cache_write_tokens
if cache_read_tokens := usage.cache_read_tokens:
    uncached_text_input_tokens -= cache_read_tokens

if uncached_text_input_tokens < 0:
    raise ValueError('Uncached text input tokens cannot be negative')
input_price += calc_mtok_price(self.input_mtok, uncached_text_input_tokens, total_input_tokens)
input_price += calc_mtok_price(self.cache_write_mtok, usage.cache_write_tokens, total_input_tokens)
```

**This is critical**: if `cache_read_tokens` is 1504 but `input_tokens` is only 13 (not summed), then `uncached_text_input_tokens` would be `13 - 1504 = -1491`, which would raise `ValueError('Uncached text input tokens cannot be negative')`.

### File: `prices/src/prices/prices_types.py`

The `UsageField` literal type (line 124) defines valid destination fields:

```python
UsageField = Literal[
    'input_tokens',
    'cache_write_tokens',
    'cache_read_tokens',
    'output_tokens',
    'input_audio_tokens',
    'cache_audio_read_tokens',
    'output_audio_tokens',
]
```

Both `cache_write_tokens` and `cache_read_tokens` are valid destinations.

## AWS API Documentation Evidence

Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_TokenUsage.html

The `TokenUsage` data type returned by the Bedrock Converse API contains:

| Field Name              | Type    | Required | Description                                                |
| ----------------------- | ------- | -------- | ---------------------------------------------------------- |
| `inputTokens`           | Integer | Yes      | Number of tokens sent in the request to the model (min: 0) |
| `outputTokens`          | Integer | Yes      | Number of tokens generated by the model (min: 0)           |
| `totalTokens`           | Integer | Yes      | Total of input + output tokens (min: 0)                    |
| `cacheReadInputTokens`  | Integer | No       | Number of input tokens read from cache (min: 0)            |
| `cacheWriteInputTokens` | Integer | No       | Number of input tokens written to cache (min: 0)           |
| `cacheDetails`          | Array   | No       | Detailed breakdown of cache writes by TTL                  |

The cache fields are **optional** (only present when caching is used), confirming that `required: false` is necessary in the extractor mappings.

### Relationship between `inputTokens` and cache fields

The AWS documentation does not explicitly state whether `inputTokens` includes or excludes cache tokens. However, the real API response from the issue provides strong evidence:

```yaml
inputTokens: 13
cacheReadInputTokens: 1504
```

Since `inputTokens` (13) is much smaller than `cacheReadInputTokens` (1504), **`inputTokens` clearly excludes cache tokens** on the Bedrock Converse API. This differs from Anthropic's native API where `input_tokens` is described as including "all input tokens."

The AWS Bedrock prompt caching documentation (https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html) states:

> "When using prompt caching, you're charged at a reduced rate for tokens read from cache. Depending on the model, tokens written to cache may be charged at a rate that is higher than that of uncached input tokens. Any tokens not read from or written to cache, are charged at the standard input token rate for that model."

This confirms three separate billing categories: uncached input tokens, cache read tokens, and cache write tokens.

## Test Dataset Evidence

### Existing test data (`tests/dataset/usages.json`)

The test dataset contains multiple AWS Bedrock Converse API responses with cache fields, but all have zero values:

```json
{
  "usage": {
    "cacheReadInputTokenCount": 0,
    "cacheReadInputTokens": 0,
    "cacheWriteInputTokenCount": 0,
    "cacheWriteInputTokens": 0,
    "inputTokens": 42,
    "outputTokens": 313,
    "totalTokens": 355
  }
}
```

These are currently extracted as `{"input_tokens": 42, "output_tokens": 313}` -- the cache fields are silently dropped. With zero values, the data loss is not observable in cost calculations, but it will become incorrect when non-zero cache values are present.

Note: the dataset also reveals `cacheReadInputTokenCount` and `cacheWriteInputTokenCount` fields (with "Count" suffix), but these are not documented in the TokenUsage API reference and appear to be duplicates or internal fields. The fix should only map the documented `cacheReadInputTokens` and `cacheWriteInputTokens` fields.

### Existing test (`tests/test_extract_usage.py`, line 242)

```python
def test_bedrock():
    provider = next(provider for provider in providers if provider.id == 'aws')
    response_data = {'usage': {'inputTokens': 406, 'outputTokens': 53}}
    usage = provider.extract_usage(response_data)
    assert usage == snapshot((None, Usage(input_tokens=406, output_tokens=53)))
```

This test only covers the no-caching case and passes with the current extractor. It does not test any response with cache fields.

## AWS Models with Cache Pricing

### Non-Anthropic models using the DEFAULT extractor that have `cache_read_mtok` pricing:

| Model                              | `input_mtok` | `cache_read_mtok` | `cache_write_mtok` |
| ---------------------------------- | ------------ | ----------------- | ------------------ |
| Amazon Nova Lite (`aws.yml:37`)    | $0.06        | $0.015            | (none)             |
| Amazon Nova Micro (`aws.yml:50`)   | $0.035       | $0.00875          | (none)             |
| Amazon Nova Premier (`aws.yml:65`) | $2.5         | $0.625            | (none)             |
| Amazon Nova Pro (`aws.yml:74`)     | $0.8         | $0.2              | (none)             |

These are the models **directly affected** by this bug. They use the default extractor and have cache_read_mtok pricing, but cache tokens are never extracted, so the cache discount is never applied.

Note: Nova models have `cache_read_mtok` but no `cache_write_mtok`. This means cache writes for Nova are billed at the standard `input_mtok` rate. The extractor should still map `cacheWriteInputTokens` to `cache_write_tokens` for completeness, even though there is no separate pricing for writes on these models -- the `calc_price` method handles `None` cache_write_mtok gracefully.

### Anthropic models using the ANTHROPIC flavor extractor (not affected by this bug):

All Anthropic models on Bedrock (Claude 3.5 Haiku, Claude 3.5/3.7 Sonnet, Claude 4/4.5/4.6 Opus/Sonnet, etc.) have both `cache_read_mtok` and `cache_write_mtok` pricing and use the `anthropic` flavor extractor, which already correctly maps cache tokens.

## Key Decision Point: Should cache tokens sum into `input_tokens`?

**Recommendation: YES -- cache tokens MUST be summed into `input_tokens`.**

### Evidence requiring summation

1. **`calc_price()` requires it** (decisive): The `ModelPrice.calc_price()` method (types.py lines 627-636) computes uncached input tokens as:

   ```
   uncached_text_input_tokens = input_tokens - cache_write_tokens - cache_read_tokens
   ```

   If `input_tokens` does not include cache tokens, this subtraction produces a negative number and raises `ValueError('Uncached text input tokens cannot be negative')`. This would crash on any response with non-zero cache tokens.

2. **Consistency with all other providers**: The Anthropic native extractor, the AWS anthropic flavor extractor, and the Google anthropic flavor extractor all sum cache tokens into `input_tokens`. The OpenAI chat extractor maps `prompt_tokens` (which already includes cached tokens per OpenAI's API design) to `input_tokens`. This is a universal pattern in the codebase.

3. **Correct cost calculation**: For Amazon Nova Lite with 13 uncached + 1504 cache read tokens:
   - With summation: `input_tokens=1517, cache_read_tokens=1504` => uncached = 13, cost = `13 * $0.06/M + 1504 * $0.015/M = $0.00000078 + $0.00002256 = $0.00002334`
   - Without summation: `input_tokens=13, cache_read_tokens=1504` => uncached = `13 - 1504 = -1491` => **CRASH**

### Why Bedrock differs from Anthropic's native API

On Anthropic's native API, `input_tokens` already includes all input tokens (cached + uncached). The anthropic flavor extractor sums `cache_creation_input_tokens` and `cache_read_input_tokens` into `input_tokens` because they are subsets already counted in the reported `input_tokens`.

On the Bedrock Converse API, `inputTokens` appears to be ONLY the uncached tokens (evidenced by `inputTokens: 13` with `cacheReadInputTokens: 1504`). So the summation here is additive rather than redundant -- it is essential to reconstruct the total.

**Either way, the result is the same**: `input_tokens` in the `Usage` object must equal the total of all input tokens.

## Proposed Fix

### YAML change to `prices/providers/aws.yml`

Replace lines 10-15:

```yaml
- root: usage
  mappings:
    - path: inputTokens
      dest: input_tokens
    - path: outputTokens
      dest: output_tokens
```

With:

```yaml
- root: usage
  mappings:
    - path: inputTokens
      dest: input_tokens
    - path: cacheReadInputTokens
      dest: input_tokens
      required: false
    - path: cacheWriteInputTokens
      dest: input_tokens
      required: false
    - path: cacheReadInputTokens
      dest: cache_read_tokens
      required: false
    - path: cacheWriteInputTokens
      dest: cache_write_tokens
      required: false
    - path: outputTokens
      dest: output_tokens
```

### Explanation of each added mapping

1. `cacheReadInputTokens -> input_tokens (required: false)`: Sums cache read tokens into total input_tokens for correct `calc_price()` computation. Optional because caching is not always used.

2. `cacheWriteInputTokens -> input_tokens (required: false)`: Sums cache write tokens into total input_tokens. Optional for same reason.

3. `cacheReadInputTokens -> cache_read_tokens (required: false)`: Maps to the dedicated cache_read_tokens field so `calc_price()` can apply the `cache_read_mtok` discount rate.

4. `cacheWriteInputTokens -> cache_write_tokens (required: false)`: Maps to the dedicated cache_write_tokens field so `calc_price()` can apply the `cache_write_mtok` rate (when a model defines it).

This pattern exactly mirrors the anthropic flavor extractor (lines 16-35) but uses camelCase field names matching the Bedrock Converse API response format.

## Testing Plan

### 1. Update existing test (`tests/test_extract_usage.py`)

Add a new test case for Bedrock with cache tokens:

```python
def test_bedrock_with_cache():
    provider = next(provider for provider in providers if provider.id == 'aws')
    response_data = {
        'usage': {
            'inputTokens': 13,
            'outputTokens': 5,
            'cacheReadInputTokens': 1504,
            'cacheWriteInputTokens': 0,
            'totalTokens': 18,
        }
    }
    model, usage = provider.extract_usage(response_data)
    assert model is None  # Bedrock Converse API doesn't return model in response
    assert usage == Usage(
        input_tokens=13 + 1504,  # inputTokens + cacheReadInputTokens + cacheWriteInputTokens
        cache_read_tokens=1504,
        cache_write_tokens=0,
        output_tokens=5,
    )
```

### 2. Add cache write test case

```python
def test_bedrock_with_cache_write():
    provider = next(provider for provider in providers if provider.id == 'aws')
    response_data = {
        'usage': {
            'inputTokens': 100,
            'outputTokens': 50,
            'cacheReadInputTokens': 0,
            'cacheWriteInputTokens': 500,
            'totalTokens': 150,
        }
    }
    model, usage = provider.extract_usage(response_data)
    assert usage == Usage(
        input_tokens=600,  # 100 + 0 + 500
        cache_read_tokens=0,
        cache_write_tokens=500,
        output_tokens=50,
    )
```

### 3. Add cost calculation test for a Nova model with cache

```python
def test_bedrock_nova_cache_pricing():
    """Verify cache discount is correctly applied for Nova Lite."""
    provider = next(provider for provider in providers if provider.id == 'aws')
    response_data = {
        'usage': {
            'inputTokens': 13,
            'outputTokens': 5,
            'cacheReadInputTokens': 1504,
            'cacheWriteInputTokens': 0,
        }
    }
    extracted = extract_usage(response_data, provider_id='aws')
    # Manually find Nova Lite model for pricing
    price = calc_price(extracted.usage, 'amazon.nova-lite-v1:0')
    # Verify cache discount is applied (cache_read_mtok=0.015 vs input_mtok=0.06)
    assert price.total_price is not None
```

### 4. Verify existing test still passes

The existing `test_bedrock` test (no cache fields in response) must continue to pass unchanged, since the new mappings are `required: false`.

### 5. Update test dataset (`tests/dataset/usages.json`)

The existing test dataset entries for AWS Bedrock that contain `cacheReadInputTokens: 0` and `cacheWriteInputTokens: 0` should have their expected extraction results updated to include `cache_read_tokens: 0` and `cache_write_tokens: 0`, and `input_tokens` should remain unchanged (since 0 is added).

### 6. Run full test suite

```bash
make test
make build-prices  # Rebuild data.json since aws.yml changed
make lint
make typecheck
```

## Risk Assessment

### Low risk

- **Backward compatible for responses without cache fields**: The new mappings use `required: false`, so responses that do not include `cacheReadInputTokens` or `cacheWriteInputTokens` will continue to work exactly as before. The existing `test_bedrock` test case validates this.

- **Zero-value cache fields produce equivalent results**: For responses where cache fields are 0 (like all current test data), `input_tokens` gets `+0` added, `cache_read_tokens` becomes `0` instead of `None`, and `cache_write_tokens` becomes `0` instead of `None`. These produce identical cost calculations.

- **Pattern is proven**: The exact same dual-mapping pattern is already used by the anthropic flavor extractor in the same file, the Anthropic provider, and the Google provider's anthropic flavor. No novel logic is introduced.

### Moderate risk

- **Test dataset update**: The `usages.json` file's expected extraction results for AWS entries will need updating. Entries with `cacheReadInputTokens: 0` will now extract `cache_read_tokens: 0` (previously omitted). If the dataset validation is strict about expected output matching, this could cause test failures that need to be addressed.

- **Assumption about `inputTokens` semantics**: The fix assumes `inputTokens` in the Bedrock response is the count of UNCACHED input tokens (so cache tokens must be added to get the total). This is supported by the evidence (`inputTokens: 13` with `cacheReadInputTokens: 1504`), but if AWS changes this semantics or it varies by model, cache tokens could be double-counted. This risk is mitigated by the fact that the same approach works for the anthropic flavor extractor on the same API.

### What could break

1. Nothing in existing functionality -- all new mappings are `required: false`.
2. If someone was relying on `cache_read_tokens` being `None` for Bedrock responses (unlikely since it was a bug).
3. The `usages.json` dataset test assertions may need updating for entries that now produce `cache_read_tokens: 0` and `cache_write_tokens: 0` instead of those fields being absent.
