---
name: genai-openrouter-sync-reviewer
description: Review OpenRouter sync/data PRs for exact OpenRouter API model ID preservation, dynamic pricing handling, and mirror/native-provider separation.
---

# genai-openrouter-sync-reviewer

Review OpenRouter-related changes as a contract between the live OpenRouter API, `prices/providers/openrouter.yml`, and downstream callers that price OpenRouter responses.

## Scope

- `prices/src/prices/source_openrouter.py`
- `prices/providers/openrouter.yml`
- generated data/package files affected by OpenRouter
- tests covering OpenRouter model lookup and sync behavior

## Review Questions

1. Does the OpenRouter provider mirror preserve OpenRouter API `id` exactly, including provider prefixes, `~` aliases, and suffixes such as `:free`?
2. Is provider-prefix stripping limited to native-provider curation, not the OpenRouter mirror?
3. Do tests cover both mirror IDs and native-provider stripped IDs?
4. Are adaptive or negative prices skipped or represented for only the fields that the schema stores?
5. Are zero/free entries represented intentionally and without conflicting with paid aliases?
6. Do collapsed aliases avoid duplicate matches without deleting valid OpenRouter response refs?

## Required Targeted Checks

Run or reason through a representative `calc_price` check with:

- `provider_api_url='https://openrouter.ai/api/v1'`
- exact OpenRouter response-style refs such as `provider/model`, `~provider/model-latest`, and `provider/model:free` when present

## Output

Classify each finding by merge risk. Treat stripped OpenRouter mirror IDs as a blocker unless the PR intentionally changes the downstream lookup contract and updates consumers/tests accordingly.
