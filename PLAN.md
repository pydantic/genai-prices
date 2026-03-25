# HuggingFace Extractor - Missing Default Flavor Fix

## Issue Reference

GitHub Issue #324, Gap #3: HuggingFace has no `default` flavor -- all 11 YAMLs only have `api_flavor: chat`.

## Problem Statement

All 11 HuggingFace provider YAML files define their sole extractor with `api_flavor: chat`. Since the `UsageExtractor.api_flavor` field defaults to `'default'` in both the YAML schema layer (`prices_types.py:152`) and the published Python package (`types.py:376`), any caller who invokes `extract_usage()` without explicitly passing `api_flavor='chat'` will receive a `ValueError`:

```
Unknown api_flavor 'default', allowed values: chat
```

This is the exact same error pattern tested and demonstrated for OpenAI in `tests/test_extract_usage.py:125-126`:

```python
with pytest.raises(ValueError, match=re.escape("Unknown api_flavor 'default', allowed values: chat, responses")):
    provider.extract_usage(response_data)
```

For OpenAI this is expected behavior because OpenAI has multiple distinct API shapes (chat, responses, embeddings) and callers must choose. But the HuggingFace providers each have exactly ONE extractor -- the `chat` flavor -- which means callers must always pass an explicit `api_flavor='chat'` even though there is no ambiguity. This is a usability problem.

## Current State Analysis

### All 11 HuggingFace YAMLs

Every HuggingFace provider YAML has this identical extractor block (only `api_flavor: chat`, no `default`):

| #   | File                           | Provider ID                | Extractor Flavors |
| --- | ------------------------------ | -------------------------- | ----------------- |
| 1   | `huggingface_cerebras.yml`     | `huggingface_cerebras`     | `chat` only       |
| 2   | `huggingface_fireworks-ai.yml` | `huggingface_fireworks-ai` | `chat` only       |
| 3   | `huggingface_groq.yml`         | `huggingface_groq`         | `chat` only       |
| 4   | `huggingface_hyperbolic.yml`   | `huggingface_hyperbolic`   | `chat` only       |
| 5   | `huggingface_nebius.yml`       | `huggingface_nebius`       | `chat` only       |
| 6   | `huggingface_novita.yml`       | `huggingface_novita`       | `chat` only       |
| 7   | `huggingface_nscale.yml`       | `huggingface_nscale`       | `chat` only       |
| 8   | `huggingface_ovhcloud.yml`     | `huggingface_ovhcloud`     | `chat` only       |
| 9   | `huggingface_publicai.yml`     | `huggingface_publicai`     | `chat` only       |
| 10  | `huggingface_sambanova.yml`    | `huggingface_sambanova`    | `chat` only       |
| 11  | `huggingface_together.yml`     | `huggingface_together`     | `chat` only       |

The extractor block in every file is identical:

```yaml
extractors:
  - api_flavor: chat
    root: usage
    model_path: model
    mappings:
      - path: prompt_tokens
        dest: input_tokens
        required: true
      - path: [prompt_tokens_details, cached_tokens]
        dest: cache_read_tokens
        required: false
      - path: [prompt_tokens_details, audio_tokens]
        dest: input_audio_tokens
        required: false
      - path: [completion_tokens_details, audio_tokens]
        dest: output_audio_tokens
        required: false
      - path: completion_tokens
        dest: output_tokens
        required: true
```

### How api_flavor Defaults to 'default'

There are three separate locations where the `'default'` default value is defined:

1. **YAML schema layer** (`prices/src/prices/prices_types.py:152`):

   ```python
   class UsageExtractor(_Model):
       api_flavor: str = 'default'
   ```

2. **Published Python package** (`packages/python/genai_prices/types.py:376`):

   ```python
   @dataclass
   class UsageExtractor:
       api_flavor: str = 'default'
   ```

3. **Public API** (`packages/python/genai_prices/__init__.py:78`):

   ```python
   def extract_usage(
       response_data: Any,
       *,
       provider_id: types.ProviderID | str | None = None,
       provider_api_url: str | None = None,
       api_flavor: str = 'default',
   ) -> types.ExtractedUsage:
   ```

4. **JS package** (`packages/js/src/extractUsage.ts:10`):
   ```typescript
   apiFlavor = apiFlavor ?? 'default'
   ```

### How Extractor Lookup Works (and Fails)

The lookup in the Python package (`packages/python/genai_prices/types.py:330-334`):

```python
try:
    extractor = next(e for e in self.extractors if e.api_flavor == api_flavor)
except StopIteration as e:
    fs = ', '.join(e.api_flavor for e in self.extractors)
    raise ValueError(f'Unknown api_flavor {api_flavor!r}, allowed values: {fs}') from e
```

The JS package has the equivalent (`packages/js/src/extractUsage.ts:16-19`):

```typescript
const extractor = provider.extractors.find((e) => e.api_flavor === apiFlavor)
if (!extractor) {
  const availableFlavors = provider.extractors.map((e) => e.api_flavor).join(', ')
  throw new Error(`Unknown apiFlavor '${apiFlavor}', allowed values: ${availableFlavors}`)
}
```

For a HuggingFace provider, calling `extract_usage(data, provider_id='huggingface_nebius')` without specifying `api_flavor='chat'` will fail because the generator in `next()` finds no extractor with `api_flavor == 'default'`.

### How the Auto-Generator Works

The file `prices/src/prices/source_huggingface.py` generates all 11 YAMLs. The critical section (lines 49-74):

```python
openai_extractors = ProviderYaml(providers_dir / 'openai.yml').provider.extractors
assert openai_extractors
[chat_extractor] = [e for e in openai_extractors if e.api_flavor == 'chat']

for provider in providers:
    # ...
    provider_info = Provider(
        id=provider_id,
        # ...
        extractors=[chat_extractor],
        # ...
    )
```

The generator reads the OpenAI provider's `chat` flavor extractor and directly reuses it. Because the OpenAI `chat` extractor has `api_flavor: chat` set explicitly (since OpenAI needs to distinguish between chat, responses, and embeddings), this `chat` flavor name is carried into all HuggingFace YAMLs.

The same pattern is used in `prices/src/prices/source_ovhcloud.py:74-76`, which produces `ovhcloud.yml` -- also with only `api_flavor: chat`.

### How Other Providers Handle Their Primary Flavor

| Provider           | File                | Primary Extractor `api_flavor` | Has `default`? | Has `chat`? | Other Flavors                                                |
| ------------------ | ------------------- | ------------------------------ | -------------- | ----------- | ------------------------------------------------------------ |
| Anthropic          | `anthropic.yml`     | (omitted = `default`)          | Yes (implicit) | Yes         | --                                                           |
| AWS Bedrock        | `aws.yml`           | (omitted = `default`)          | Yes (implicit) | No          | `anthropic`                                                  |
| Google             | `google.yml`        | (omitted = `default`)          | Yes (implicit) | Yes         | `anthropic`                                                  |
| Groq               | `groq.yml`          | (omitted = `default`)          | Yes (implicit) | No          | --                                                           |
| Mistral            | `mistral.yml`       | (omitted = `default`)          | Yes (implicit) | No          | --                                                           |
| Cohere             | `cohere.yml`        | (omitted = `default`)          | Yes (implicit) | No          | `embeddings`                                                 |
| X AI               | `x_ai.yml`          | `default` (explicit)           | Yes (explicit) | Yes         | --                                                           |
| Azure              | `azure.yml`         | --                             | No             | Yes         | `responses`, `embeddings`, `anthropic`, (implicit `default`) |
| OpenAI             | `openai.yml`        | --                             | No             | Yes         | `responses`, `embeddings`                                    |
| Cerebras           | `cerebras.yml`      | --                             | No             | `chat` only | --                                                           |
| DeepSeek           | `deepseek.yml`      | --                             | No             | `chat` only | --                                                           |
| Fireworks          | `fireworks.yml`     | --                             | No             | `chat` only | --                                                           |
| MoonshotAI         | `moonshotai.yml`    | --                             | No             | `chat` only | --                                                           |
| OVHcloud           | `ovhcloud.yml`      | --                             | No             | `chat` only | --                                                           |
| All 11 HuggingFace | `huggingface_*.yml` | --                             | No             | `chat` only | --                                                           |

**Key observation**: The issue description's claim that "every other provider family (Anthropic, AWS, Google, Groq, Mistral, Cohere) has its primary extractor implicitly or explicitly as `default`" is correct for the major established providers. However, HuggingFace is not alone in this problem -- `cerebras.yml`, `deepseek.yml`, `fireworks.yml`, `moonshotai.yml`, and `ovhcloud.yml` also have only `chat` with no `default`. These are all OpenAI-compatible API providers that copied the OpenAI chat extractor format.

### HuggingFace API Compatibility

The HuggingFace Inference API uses OpenAI-compatible chat completions format. The API endpoint is `https://router.huggingface.co/{provider}/v1/chat/completions` and returns the standard OpenAI response shape with `usage.prompt_tokens` and `usage.completion_tokens`. The extractor mappings in the YAMLs match this exactly -- they are literally the OpenAI `chat` extractor.

## Evidence Summary

1. **All 11 HuggingFace YAMLs**: Each one at line 17 contains `- api_flavor: chat` as the only extractor.

2. **Default value in prices_types.py line 152**: `api_flavor: str = 'default'`

3. **Default value in published package types.py line 376**: `api_flavor: str = 'default'`

4. **Default value in extract_usage() API, **init**.py line 78**: `api_flavor: str = 'default'`

5. **Lookup failure path in types.py lines 330-334**: `next()` raises `StopIteration`, caught and re-raised as `ValueError`.

6. **Auto-generator source_huggingface.py line 51**: `[chat_extractor] = [e for e in openai_extractors if e.api_flavor == 'chat']` -- explicitly picks the chat flavor from OpenAI.

7. **Test confirmation** (`tests/test_extract_usage.py:125-126`): The test for OpenAI proves that calling `extract_usage(data)` with default flavor raises `ValueError` when only `chat` is available.

8. **Non-HuggingFace providers with same issue**: `cerebras.yml`, `deepseek.yml`, `fireworks.yml`, `moonshotai.yml`, `ovhcloud.yml` all have the identical problem.

## Analysis of Options

### Option A: Remove `api_flavor: chat` so it becomes `default`

Change each YAML from:

```yaml
extractors:
  - api_flavor: chat
    root: usage
    ...
```

to:

```yaml
extractors:
  - root: usage
    ...
```

When `api_flavor` is omitted, the Pydantic model defaults to `'default'`, matching the caller's default.

**Pros:**

- Simplest change -- just remove one line per YAML
- Matches what Groq, Mistral, Cohere, AWS do (omit api_flavor, get default)
- Users can call `extract_usage(data, provider_id='huggingface_nebius')` without specifying flavor
- Since HuggingFace providers only have one API shape, there's no ambiguity

**Cons:**

- Breaking change for any callers who currently pass `api_flavor='chat'` explicitly -- they would get `ValueError: Unknown api_flavor 'chat', allowed values: default`
- The extractor IS the OpenAI chat format, so naming it `default` hides semantic information about what it is
- The `chat` label provides useful documentation that this is the OpenAI chat completions format
- Would NOT fix the auto-generator, so the next run of `source_huggingface.py` would revert the change

### Option B: Add a duplicate `default` flavor extractor alongside `chat`

Add a second extractor entry with `api_flavor: default` (or omitted) that has identical mappings:

```yaml
extractors:
  - api_flavor: chat
    root: usage
    ...
  - root: usage
    ...
```

**Pros:**

- No breaking change -- both `api_flavor='chat'` and `api_flavor='default'` work
- Preserves the semantic meaning of the `chat` label

**Cons:**

- Duplicates the entire extractor definition, violating DRY
- The duplicate flavor validator (`prices_types.py:66-77`) checks for duplicate `api_flavor` values -- this approach would NOT trigger it because the flavors are `'chat'` and `'default'` (different strings), but it still means maintaining two identical blocks
- Would need changes to `source_huggingface.py` to emit two extractors
- Doubles the size of the extractors section in each of 11 files

### Option C: Change the auto-generator to not emit api_flavor (making it `default`)

Modify `source_huggingface.py` to create a new extractor without `api_flavor: chat` rather than copying OpenAI's chat extractor directly. The generated YAMLs would then use the implicit `default` flavor.

**Pros:**

- Fixes the root cause -- the auto-generator is what introduces the wrong flavor name
- Future runs of `source_huggingface.py` produce correct output
- Clean solution -- one extractor per provider, with the implicit default flavor
- Consistent with how Groq, Mistral, Cohere handle single-extractor providers

**Cons:**

- Breaking change for callers who pass `api_flavor='chat'` explicitly
- Loses the semantic label indicating it's the OpenAI chat format

### Option D (Recommended): Change the auto-generator to emit `default` flavor AND also fix the broader issue

This is a hybrid of Option A and Option C. The auto-generator is the root cause, so fix it. But also consider that the same problem exists for `cerebras.yml`, `deepseek.yml`, `fireworks.yml`, `moonshotai.yml`, and `ovhcloud.yml` -- these are not auto-generated (except `ovhcloud.yml`) and should also be addressed.

For single-extractor providers that only have `api_flavor: chat`, the fix is to remove the explicit `api_flavor: chat` so the default kicks in. This aligns with the established convention used by Anthropic, AWS, Google, Groq, Mistral, and Cohere, where the primary extractor has no explicit `api_flavor` (defaulting to `'default'`).

For multi-extractor providers like OpenAI and Azure, `api_flavor: chat` remains correct because callers must choose between `chat`, `responses`, and `embeddings`.

## Recommended Approach

**Option C** is the recommended approach for this specific issue (HuggingFace only), with the understanding that the broader `chat`-only problem across other providers (Option D) could be addressed in a follow-up or the same PR.

The justification:

1. **Root cause fix**: The auto-generator (`source_huggingface.py`) is the source of truth for these files. Editing the YAMLs directly would be overwritten on the next generation run. The generator must be fixed.

2. **Consistency with established convention**: Providers with a single primary extractor (Anthropic, AWS, Google, Groq, Mistral, Cohere) omit `api_flavor`, letting it default to `'default'`. HuggingFace providers should follow suit.

3. **Minimal user impact**: The HuggingFace providers are relatively new additions and have only `chat` flavor. It is unlikely many callers are explicitly passing `api_flavor='chat'` for HuggingFace providers, especially since doing so requires knowing this non-obvious implementation detail.

4. **The `chat` flavor name is only meaningful when distinguishing from other flavors**: For OpenAI, `chat` vs `responses` vs `embeddings` is meaningful. For HuggingFace providers with a single API shape, the flavor name conveys no useful information to the caller.

## Proposed Fix

### 1. Modify `source_huggingface.py`

File: `prices/src/prices/source_huggingface.py`

Change lines 49-51 from:

```python
openai_extractors = ProviderYaml(providers_dir / 'openai.yml').provider.extractors
assert openai_extractors
[chat_extractor] = [e for e in openai_extractors if e.api_flavor == 'chat']
```

To create a new extractor with the default flavor (approach 1 -- construct directly):

```python
from prices.prices_types import UsageExtractor, UsageExtractorMapping

hf_extractor = UsageExtractor(
    root='usage',
    model_path='model',
    mappings=[
        UsageExtractorMapping(path='prompt_tokens', dest='input_tokens'),
        UsageExtractorMapping(path=['prompt_tokens_details', 'cached_tokens'], dest='cache_read_tokens', required=False),
        UsageExtractorMapping(path=['prompt_tokens_details', 'audio_tokens'], dest='input_audio_tokens', required=False),
        UsageExtractorMapping(path=['completion_tokens_details', 'audio_tokens'], dest='output_audio_tokens', required=False),
        UsageExtractorMapping(path='completion_tokens', dest='output_tokens'),
    ],
)
```

Or (approach 2 -- copy and override flavor, minimal diff):

```python
openai_extractors = ProviderYaml(providers_dir / 'openai.yml').provider.extractors
assert openai_extractors
[chat_extractor] = [e for e in openai_extractors if e.api_flavor == 'chat']
chat_extractor.api_flavor = 'default'
```

**Approach 2 is preferred** because it's a minimal change and maintains the existing pattern of deriving from OpenAI's extractor. The only difference is resetting the flavor to `'default'`.

However, since `UsageExtractor` in `prices_types.py` is a Pydantic model with `extra='forbid'`, mutating it directly might not work. Instead, use `model_copy`:

```python
openai_extractors = ProviderYaml(providers_dir / 'openai.yml').provider.extractors
assert openai_extractors
[chat_extractor] = [e for e in openai_extractors if e.api_flavor == 'chat']
hf_extractor = chat_extractor.model_copy(update={'api_flavor': 'default'})
```

Then on line 74, change:

```python
extractors=[chat_extractor],
```

to:

```python
extractors=[hf_extractor],
```

### 2. Regenerate all 11 HuggingFace YAMLs

After modifying `source_huggingface.py`, run `make huggingface-get` (or `python -m prices.source_huggingface`) to regenerate all 11 YAML files. They will automatically lose the `api_flavor: chat` line because `api_flavor='default'` is the default and gets excluded by `exclude_none=True` / default exclusion in `model_dump()`.

Wait -- `model_dump(exclude_none=True)` does NOT exclude default values, only `None` values. The `api_flavor='default'` would still be emitted as `api_flavor: default` in the YAML. Let me reconsider.

Actually, looking at the Pydantic `model_dump()` call on line 77:

```python
yaml_data = cast(ProviderYamlDict, provider_info.model_dump(mode='json', exclude_none=True, by_alias=True))
```

This uses `exclude_none=True`, not `exclude_defaults=True`. So `api_flavor: default` WOULD appear in the output YAML. This means the generated files would change from `api_flavor: chat` to `api_flavor: default`. That is functionally correct but aesthetically differs from providers like Anthropic/Groq/Mistral that omit the field entirely.

To make the output completely omit `api_flavor` when it equals `'default'` (matching the convention of other providers), the `get_provider_yaml_string()` function or the model_dump could use `exclude_defaults=True`. However, that may have side effects on other fields. A simpler approach: just let `api_flavor: default` appear in the YAML -- it's functionally equivalent to omitting it and makes the intent explicit.

### 3. Also fix `source_ovhcloud.py` (related but separate)

File: `prices/src/prices/source_ovhcloud.py`

Apply the same change at lines 74-76:

```python
openai_extractors = ProviderYaml(providers_dir / 'openai.yml').provider.extractors
assert openai_extractors
[chat_extractor] = [e for e in openai_extractors if e.api_flavor == 'chat']
hf_extractor = chat_extractor.model_copy(update={'api_flavor': 'default'})
```

And change line 96 to use `hf_extractor` (or `default_extractor`) instead of `chat_extractor`.

### 4. Consider manual fixes for non-auto-generated providers

The following non-auto-generated provider YAMLs also have a single `api_flavor: chat` with no `default`:

- `cerebras.yml`
- `deepseek.yml`
- `fireworks.yml`
- `moonshotai.yml`

These could be fixed by simply removing the `api_flavor: chat` line (the field defaults to `'default'`). This is a separate but related concern and could be done in the same PR or a follow-up.

### 5. Rebuild data files

Run `make build-prices` and `make package-data` to regenerate `data.json`, `data_slim.json`, and the package data.

## Testing Plan

### New Tests to Add

1. **Test HuggingFace extract_usage with default flavor** (`tests/test_extract_usage.py`):

   ```python
   def test_huggingface_default_flavor():
       """Test that HuggingFace providers work with default api_flavor."""
       provider = next(p for p in providers if p.id == 'huggingface_nebius')
       response_data = {
           'model': 'meta-llama/llama-3.3-70b-instruct',
           'usage': {
               'prompt_tokens': 100,
               'completion_tokens': 200,
           },
       }
       # Should work WITHOUT explicitly passing api_flavor='chat'
       model, usage = provider.extract_usage(response_data)
       assert model == 'meta-llama/llama-3.3-70b-instruct'
       assert usage == Usage(input_tokens=100, output_tokens=200)
   ```

2. **Test extract_usage via the public API**:

   ```python
   def test_huggingface_public_api():
       response_data = {
           'model': 'meta-llama/llama-3.3-70b-instruct',
           'usage': {'prompt_tokens': 100, 'completion_tokens': 200},
       }
       extracted = extract_usage(response_data, provider_id='huggingface_nebius')
       assert extracted.usage == Usage(input_tokens=100, output_tokens=200)
   ```

3. **Parametrized test for all HuggingFace providers** (ensure all 11 support default flavor):
   ```python
   @pytest.mark.parametrize('provider_id', [
       'huggingface_cerebras', 'huggingface_fireworks-ai', 'huggingface_groq',
       'huggingface_hyperbolic', 'huggingface_nebius', 'huggingface_novita',
       'huggingface_nscale', 'huggingface_ovhcloud', 'huggingface_publicai',
       'huggingface_sambanova', 'huggingface_together',
   ])
   def test_huggingface_providers_have_default_flavor(provider_id: str):
       provider = next(p for p in providers if p.id == provider_id)
       assert provider.extractors is not None
       flavors = [e.api_flavor for e in provider.extractors]
       assert 'default' in flavors
   ```

### Existing Tests to Verify

- `make test` -- ensure no regressions across the full test suite
- `make build-prices` -- ensure data files rebuild cleanly
- `make lint` and `make typecheck` -- ensure code quality

## Risk Assessment

### What Could Break

1. **Callers explicitly passing `api_flavor='chat'` for HuggingFace providers**: These calls would fail with `ValueError: Unknown api_flavor 'chat', allowed values: default`. However, since HuggingFace providers are relatively new and have only one flavor, it is unlikely callers have hard-coded `api_flavor='chat'` for them specifically.

2. **JS package consumers**: The same flavor change affects the JS package via `data.json`. Any JS callers passing `apiFlavor: 'chat'` for HuggingFace providers would break.

3. **Auto-generated data files**: The `data.json` and `data_slim.json` files would change (the `api_flavor` field for all HuggingFace extractors changes from `"chat"` to `"default"`). Consumers parsing these files directly would see the change.

4. **Re-running the generator**: If the `source_huggingface.py` fix is not included, re-running `make huggingface-get` would overwrite the YAML changes and revert to `api_flavor: chat`.

### Mitigation

- The fix to `source_huggingface.py` ensures that future regeneration produces correct output.
- The change is semantically correct -- HuggingFace providers have a single API shape and should use the default flavor.
- The broader codebase pattern (Anthropic, AWS, Google, Groq, Mistral) establishes that single-primary-extractor providers use `default`.

### Impact on Existing Users

- **Users NOT specifying api_flavor**: Currently broken, will be FIXED by this change.
- **Users specifying `api_flavor='chat'` for HuggingFace**: Currently working, will BREAK. This is a necessary trade-off to align with the codebase convention. Documentation should note this change.

### Alternative: Zero-breakage approach

If breaking `api_flavor='chat'` callers is unacceptable, Option B (adding a duplicate `default` extractor alongside `chat`) could be used instead. This doubles the extractor definitions but ensures both `'default'` and `'chat'` work. The auto-generator would need to emit two extractors per provider.
