# Google Gemini Extractor - toolUsePromptTokenCount Mapping Fix

## Issue Reference

GitHub Issue [#324](https://github.com/pydantic/genai-prices/issues/324) -- Gap #4: Google Gemini `toolUsePromptTokenCount` mapped to `output_tokens` incorrectly.

## Problem Statement

The Google default extractor in `google.yml` maps `toolUsePromptTokenCount` to `output_tokens`. This is semantically incorrect: Google's own protobuf definitions and documentation describe this field as representing tokens from **tool execution results that are fed back to the model as input**. The current mapping inflates `output_tokens` (and therefore computed output cost) whenever tool use is present, while underreporting `input_tokens`.

## Current State Analysis

### File: `prices/providers/google.yml` (lines 21-66)

The default extractor for Google is defined at the top of the file:

```yaml
extractors:
  - root: usageMetadata
    model_path: modelVersion
    mappings:
      - path: promptTokenCount
        dest: input_tokens
        required: false
      - path: cachedContentTokenCount
        dest: cache_read_tokens
        required: false
      # ... audio mappings omitted for brevity ...
      - path: candidatesTokenCount
        dest: output_tokens # line 59
        required: false
      - path: thoughtsTokenCount
        dest: output_tokens # line 62
        required: false
      - path: toolUsePromptTokenCount
        dest: output_tokens # line 65 -- THE BUG
        required: false
```

Lines 64-66 are the problematic mapping. `toolUsePromptTokenCount` is mapped to `output_tokens`, causing it to be summed with `candidatesTokenCount` and `thoughtsTokenCount`.

### How summing works

From `prices/src/prices/prices_types.py` (line 141-144) and `packages/python/genai_prices/types.py` (line 403-407):

> "If multiple mappings point to the same destination, the values are summed."

The extraction loop does:

```python
current_value = getattr(usage, mapping.dest) or 0
setattr(usage, mapping.dest, current_value + value)
```

So `output_tokens = candidatesTokenCount + thoughtsTokenCount + toolUsePromptTokenCount`, which is wrong.

## Evidence

### 1. Google Protobuf Definitions

**Gemini API (v1beta)** -- `google/ai/generativelanguage/v1beta/generative_service.proto`:

```protobuf
// Output only. Number of tokens present in tool-use prompt(s).
int32 tool_use_prompt_token_count = 8
    [(google.api.field_behavior) = OUTPUT_ONLY];

// Output only. List of modalities that were processed for tool-use request
// inputs.
repeated ModalityTokenCount tool_use_prompt_tokens_details = 9
    [(google.api.field_behavior) = OUTPUT_ONLY];
```

**Vertex AI (v1)** -- `google/cloud/aiplatform/v1/prediction_service.proto`:

```protobuf
// Output only. A detailed breakdown by modality of the token counts from the
// results of tool executions, which are provided back to the model as input.
repeated ModalityTokenCount tool_use_prompt_tokens_details = 12
    [(google.api.field_behavior) = OUTPUT_ONLY];
```

Key observations:

- The field name contains "Prompt" -- Google uses "prompt" to mean "input to the model."
- The Vertex AI proto explicitly says: **"token counts from the results of tool executions, which are provided back to the model as input."**
- The detail field is named `tool_use_prompt_tokens_details` where "prompt" = input context for the model.
- The Gemini API detail field description says: **"List of modalities that were processed for tool-use request inputs."**

### 2. Google Pricing Documentation on Code Execution

From https://ai.google.dev/gemini-api/docs/pricing:

> "Code execution is billed at the standard token rates for the selected model. Costs are determined solely by the tool's usage, no charges are accrued for the session runtime. The generated code and execution results are billed as **Output tokens** when created, and as **Input tokens** when the model uses them as part of its iterative reasoning process."

This confirms that tool execution results become **input tokens** when fed back into the model, which is exactly what `toolUsePromptTokenCount` represents: the token count of tool results provided back as input to the model.

### 3. Google Search Grounding

From https://ai.google.dev/gemini-api/docs/pricing:

> "Retrieved context (text or images) provided by Grounding with Google Search is not charged as input tokens."

From https://cloud.google.com/vertex-ai/generative-ai/pricing:

> "Input tokens provided by Grounding with Google Search or Web Grounding for Enterprise are not charged."

This means web search grounding results (a form of tool use) are explicitly stated as **not charged as input tokens** -- they appear to be free or billed through a separate per-query fee. This is an important nuance for the "map to input" vs "leave unmapped" decision.

### 4. Arithmetic Proof: totalTokenCount Decomposition

In **all 7 test cases** containing `toolUsePromptTokenCount`, the following identity holds:

```
totalTokenCount = promptTokenCount + candidatesTokenCount + thoughtsTokenCount + toolUsePromptTokenCount
```

| Test File                   | Model            | prompt | candidates | thoughts | toolUse | total | Match |
| --------------------------- | ---------------- | ------ | ---------- | -------- | ------- | ----- | ----- |
| server_tool_receive_history | gemini-2.0-flash | 54     | 141        | 0        | 161     | 356   | Yes   |
| web_search_tool (1)         | gemini-2.5-pro   | 17     | 201        | 213      | 119     | 550   | Yes   |
| web_search_tool (2)         | gemini-2.5-pro   | 209    | 206        | 131      | 286     | 832   | Yes   |
| web_search_tool_stream      | gemini-2.5-pro   | 249    | 240        | 301      | 319     | 1109  | Yes   |
| code_execution_tool (1)     | gemini-2.5-pro   | 15     | 177        | 483      | 675     | 1350  | Yes   |
| code_execution_tool (2)     | gemini-2.5-pro   | 39     | 58         | 540      | 637     | 1274  | Yes   |
| anthropic_server_tool       | gemini-2.0-flash | 13     | 35         | 0        | 31      | 79    | Yes   |

`toolUsePromptTokenCount` is counted **separately** from both `promptTokenCount` (user input) and `candidatesTokenCount` (model output). It is a third category of tokens.

### 5. Test Data Showing Cost Inflation

From `tests/dataset/usages.json` lines 2355-2399 (Entry 42):

```json
{
  "usageMetadata": {
    "promptTokenCount": 54,
    "candidatesTokenCount": 141,
    "toolUsePromptTokenCount": 161,
    "totalTokenCount": 356
  }
}
```

**Current extraction** (tool use mapped to output):

- `input_tokens = 54`
- `output_tokens = 302` (141 + 161)

**Correct extraction** (tool use mapped to input):

- `input_tokens = 215` (54 + 161)
- `output_tokens = 141`

Since output tokens are typically priced 2-10x higher than input tokens, the current mapping systematically **overcharges** users. For gemini-2.0-flash (input: $0.10/Mtok, output: $0.40/Mtok), this single request is costed at $0.000126 instead of the correct $0.000078 -- a 62% overestimate.

### 6. pydantic-ai Handling

In `pydantic_ai_slim/pydantic_ai/models/google.py`, the `_metadata_as_usage` function stores `tool_use_prompt_token_count` in a `details` dictionary under the key `'tool_use_prompt_tokens'`. It does **not** directly assign it to either `request_tokens` or `response_tokens`. Instead, it passes the raw response to `usage.RequestUsage.extract()`, which uses genai-prices extractors -- meaning pydantic-ai inherits whatever mapping genai-prices defines.

### 7. Git History

The mapping was introduced in commit `595693a` (PR [#200](https://github.com/pydantic/genai-prices/pull/200)):

```
commit 595693adedb6711c9966a3b4b09bb5843f75d0b1
Author: Alex Hall <alex.mojaki@gmail.com>
Date:   Mon Nov 17 23:26:18 2025 +0200

    Account for toolUsePromptTokenCount in google models (#200)
```

The commit added the mapping to `output_tokens`. The diff shows it was added alongside `candidatesTokenCount` and `thoughtsTokenCount`, both of which map to `output_tokens`. The likely reasoning was that `toolUsePromptTokenCount` appeared in the response alongside output-related fields, and the choice of `output_tokens` was made without consulting Google's proto documentation about the semantic meaning.

A follow-up commit `f0d332e` (PR [#203](https://github.com/pydantic/genai-prices/pull/203), "Fix extraction of google usage") fixed several other mappings in the same extractor but did not revisit the `toolUsePromptTokenCount` destination.

## Analysis of Options

### Option A: Map to `input_tokens` instead of `output_tokens`

**Proposed change:**

```yaml
- path: toolUsePromptTokenCount
  dest: input_tokens # changed from output_tokens
  required: false
```

**Pros:**

- Semantically correct per Google's proto documentation: "token counts from the results of tool executions, which are provided back to the model **as input**"
- The field name itself contains "Prompt" (Google's term for input)
- Matches how Google describes code execution billing: results are "Input tokens when the model uses them as part of its iterative reasoning process"
- Accurately reflects billing for code execution results and server tool results
- Gives the most accurate cost calculation for models where input/output rates differ

**Cons:**

- Google Search grounding results are explicitly "not charged as input tokens" per Google's pricing docs. If `toolUsePromptTokenCount` includes grounding tokens, mapping them to `input_tokens` would overcount input costs for search-grounded requests. However, the per-query fee ($14-35/1K queries) is separate from token billing, and the "not charged as input tokens" statement suggests these tokens should not be billed at all -- making `input_tokens` still closer to correct than `output_tokens`.
- Will change cost calculations for existing users, potentially lowering computed costs (since input is cheaper than output). This is a **correction**, not a regression.

### Option B: Remove the mapping entirely (leave unmapped)

**Proposed change:**

```yaml
# Remove lines 64-66 entirely
```

**Pros:**

- Conservative approach -- if unsure how Google bills these tokens, don't count them at all
- Avoids the grounding "not charged as input tokens" ambiguity
- Prevents overcharging on output side

**Cons:**

- `toolUsePromptTokenCount` tokens are real tokens that consume compute and are billed by Google. Ignoring them **underestimates** true cost.
- Code execution results are explicitly billed ("as Input tokens when the model uses them"). Dropping these tokens from the count means cost calculations will be too low.
- The tokens are significant: in test data, `toolUsePromptTokenCount` can be 50% or more of `totalTokenCount` (e.g., 675 out of 1350 for code execution).
- Tool use tokens are clearly part of `totalTokenCount`, so dropping them creates an inconsistency where `input_tokens + output_tokens < totalTokenCount`.

### Option C: Keep as `output_tokens` (status quo)

**Pros:**

- No change required
- No risk of breaking existing users' cost calculations

**Cons:**

- Directly contradicts Google's proto documentation ("provided back to the model **as input**")
- Inflates output costs, which are 2-10x more expensive than input
- Systematically overcharges users when tool use is present
- The field name contains "Prompt" which universally means input in Google's API nomenclature
- Every piece of evidence (proto comments, pricing docs, field naming) indicates this is wrong

## Recommended Approach

**Option A: Map `toolUsePromptTokenCount` to `input_tokens`.**

The evidence is overwhelming:

1. Google's own proto definition explicitly says these are tokens "from the results of tool executions, which are provided back to the model **as input**."
2. The field name `toolUsePromptTokenCount` contains "Prompt" -- Google's standard term for input.
3. The detail field `tool_use_prompt_tokens_details` is described as "modalities that were processed for tool-use **request inputs**."
4. Google's code execution pricing explicitly states results become "**Input tokens** when the model uses them as part of its iterative reasoning process."
5. The Vertex AI pricing page says grounding input tokens are "not charged" (i.e., zero cost), but mapping them to `input_tokens` at the standard rate is still closer to reality than mapping them to the much more expensive `output_tokens`.

The only risk is the grounding edge case, but even there, `input_tokens` is more accurate than `output_tokens`. For code execution and server tool use (the other tool types in the test data), `input_tokens` is unambiguously correct.

## Proposed Fix

### Change in `prices/providers/google.yml` (line 65)

**Before:**

```yaml
- path: toolUsePromptTokenCount
  dest: output_tokens
  required: false
```

**After:**

```yaml
- path: toolUsePromptTokenCount
  dest: input_tokens
  required: false
```

### Regenerate data files

After the YAML change, run:

```bash
make build-prices
make package-data
```

This will update `prices/data.json`, `prices/data_slim.json`, `packages/python/genai_prices/data.py`, and `packages/js/src/data.ts`.

### Update test expectations in `tests/dataset/usages.json`

All 7 test entries containing `toolUsePromptTokenCount` need their extracted usage updated. For each entry, `toolUsePromptTokenCount` must be moved from `output_tokens` to `input_tokens`.

Updated expected values:

| Test Case                                | Current input | Current output | New input | New output |
| ---------------------------------------- | ------------- | -------------- | --------- | ---------- |
| server_tool (gemini-2.0-flash)           | 54            | 302            | 215       | 141        |
| web_search (gemini-2.5-pro, 1)           | 17            | 533            | 136       | 414        |
| web_search (gemini-2.5-pro, 2)           | 209           | 623            | 495       | 337        |
| web_search_stream (gemini-2.5-pro)       | 249           | 860            | 568       | 541        |
| code_execution (gemini-2.5-pro, 1)       | 15            | 1335           | 690       | 660        |
| code_execution (gemini-2.5-pro, 2)       | 39            | 1235           | 676       | 598        |
| anthropic_server_tool (gemini-2.0-flash) | 13            | 66             | 44        | 35         |

The `input_price` and `output_price` fields in each extracted entry must also be recalculated based on the new token allocations and the respective model's per-token rates.

## Testing Plan

1. **Update test dataset**: Modify all 7 entries in `tests/dataset/usages.json` with corrected `input_tokens`, `output_tokens`, `input_price`, and `output_price` values.

2. **Run existing test suite**: `make test` -- ensures the extraction logic produces the updated expected values.

3. **Run linting and type checking**: `make lint && make typecheck` -- ensures no regressions.

4. **Run build**: `make build-prices && make package-data` -- regenerates all derived data files.

5. **Verify JS package**: The JS data file (`packages/js/src/data.ts`) is auto-generated from the YAML; verify it reflects the `input_tokens` destination after rebuild.

6. **Manual verification**: For at least one test case, manually compute cost using the model's pricing to confirm the new allocation produces a more accurate dollar amount.

## Risk Assessment

### What could break

- **Downstream cost calculations will change**: Any system using genai-prices to compute costs for Google Gemini requests with tool use will see **lower computed costs** (because tokens move from the more expensive output bucket to the cheaper input bucket). This is a **correction**, not a regression -- the previous values were inflated.

- **pydantic-ai impact**: pydantic-ai uses genai-prices extractors via `RequestUsage.extract()`. After this change, pydantic-ai's reported `request_tokens` (input) will increase and `response_tokens` (output) will decrease for tool-use requests. This is the correct behavior per Google's documentation.

- **No API contract breakage**: The `UsageField` type and extractor schema are unchanged. Only the destination of one mapping changes from one valid `UsageField` value to another.

### Impact magnitude

- **Only affects Google Gemini requests with active tool use** (code execution, web search/grounding, server tools). Standard text-only requests are unaffected.
- Cost reduction is proportional to the `toolUsePromptTokenCount` relative to total tokens. In test data, this ranges from 22% to 50% of total tokens, meaning cost overestimation of 30-100% for output in affected requests.
- The fix makes genai-prices consistent with Google's own billing semantics and documentation.
