---
emoji: '🏷️'
name: 'Price Check: Google & Mistral'
description: 'Check official Google and Mistral prices, propose verified updates in a PR, and notify Slack.'
on:
  workflow_dispatch:
  schedule: daily
  permissions:
    pull-requests: read
  skip-if-match: 'is:pr is:open in:title "Update Google and Mistral prices"'
if: ${{ vars.AGENTIC_WORKFLOWS_ENABLED == 'true' }}
runs-on: ubuntu-latest
permissions:
  contents: read
  pull-requests: read
concurrency:
  group: ${{ github.workflow }}
  cancel-in-progress: false
checkout:
  fetch-depth: 1
imports:
  - shared/price-update.md
tools:
  bash:
    - 'cat:*'
    - 'ls:*'
    - 'rg:*'
    - 'jq:*'
    - 'make:*'
    - 'npm:*'
    - 'uv:*'
  web-fetch:
safe-outputs:
  # Minimax is unpriced in gh-aw's separate detection guardrail.
  threat-detection: false
  report-failure-as-issue: false
  noop:
    report-as-issue: false
  create-pull-request:
    max: 1
    draft: false
    fallback-as-issue: false
    protected-files:
      policy: blocked
      exclude: [README.md]
    allowed-files:
      - prices/providers/google.yml
      - prices/providers/mistral.yml
      - prices/new_data/v2/data.json
      - prices/new_data/v2/data_slim.json
      - packages/python/genai_prices/data.py
      - packages/python/genai_prices/data_units.py
      - packages/js/src/data.ts
      - packages/js/src/dataUnits.ts
      - packages/go/internal/data/prices.json
      - packages/go/data_units.go
      - README.md
      - tests/test_price_calc.py
      - tests/test_price_regressions.py
      - tests/dataset/usages.json
      - packages/js/src/__tests__/**
      - packages/go/*_test.go
jobs:
  notify_slack:
    needs: [agent, safe_outputs]
    if: ${{ !cancelled() && needs.safe_outputs.outputs.created_pr_url != '' }}
    uses: ./.github/workflows/price-update-slack.yml
    with:
      pr-url: ${{ needs.safe_outputs.outputs.created_pr_url }}
    secrets:
      SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
timeout-minutes: 45
max-turns: 200
# Requires gh-aw v0.82.2; newer firewalls reject the unpriced Minimax model.
max-ai-credits: -1
max-daily-ai-credits: -1
engine:
  id: claude
  model: claude-sonnet-4-5
  api-target: api.fireworks.ai
  env:
    ANTHROPIC_BASE_URL: https://api.fireworks.ai/inference
    ANTHROPIC_API_KEY: ${{ secrets.FIREWORKS_API_KEY }}
    ANTHROPIC_MODEL: accounts/fireworks/models/minimax-m3
    ANTHROPIC_DEFAULT_OPUS_MODEL: accounts/fireworks/models/minimax-m3
    ANTHROPIC_DEFAULT_SONNET_MODEL: accounts/fireworks/models/minimax-m3
    ANTHROPIC_DEFAULT_HAIKU_MODEL: accounts/fireworks/models/minimax-m3
network:
  allowed:
    - defaults
    - api.fireworks.ai
    - ai.google.dev
    - cloud.google.com
    - mistral.ai
    - docs.mistral.ai
---

# Price Check: Google & Mistral

Check **Google (Gemini)** and **Mistral** against their official pricing pages. Propose verified price changes and new models
in one PR titled `Update Google and Mistral prices`. Follow Steps 1-3 for both providers, then the shared update steps.

## Step 1 - read the recorded data

Read `prices/providers/google.yml` and `prices/providers/mistral.yml`. Check every canonical model ID, `match` expression, and
active field or tier under `prices:`. Read `prices/units.yml` for the billing units. Price keys are not interchangeable:
`_mtok` is USD per 1,000,000 tokens, `_kcount` per 1,000 events, `_mchars` per 1,000,000 characters, `_hours` per 3,600 seconds,
`_gpixels` per 1,000,000,000 pixels, and `_kpages` per 1,000 pages. Show conversions in the PR body.

Check both the `base` and every published tier. For each distinct usage scope, resolve conditional price lists using the
last matching record whose complete constraint applies on the run date. Ignore shadowed history, expired records, and
future records when comparing current prices; preserve them unchanged. A field with no identifiable official counterpart
is unchecked, not matching.

## Step 2 - fetch the official sources

Use `web-fetch` on these exact URLs. You may follow model links on the allowed official domains to confirm an API ID or
price. Do not use aggregators, search snippets, or remembered prices. A page without the required IDs and numeric prices is
unreadable; record it and continue with the other provider.

### Google (Gemini)

- <https://ai.google.dev/gemini-api/docs/pricing>
- Compare the paid tier, in USD per 1M tokens. Map text input to `input_mtok` and audio input to `input_audio_mtok`.
- Compare cached text with `cache_read_mtok` and cached audio with `cache_audio_read_mtok`. Preserve separately quoted
  image, video, and image-output rates with their respective registry keys.
- Check both rates when pricing is split by prompt size. A `<= 200000` / `> 200000` split uses tier `start: 200000`; the
  engines apply a tier only above its `start` value.

### Mistral

- <https://mistral.ai/pricing/api>
- Map the standard API table's input and output columns, in USD per 1M tokens, to `input_mtok` and `output_mtok`.

## Step 3 - compare prices and discover models

Match each official row only to an unambiguous canonical ID, satisfied `match` expression, or marketing name. An alias such
as `mistral-large-latest` is not a separate model. If a marketing name could refer to multiple YAML records, skip it.
Compare standard public-API on-demand rates, not Batch or provisioned-capacity rates. Preserve existing special-rate records.

Identify publicly available, numerically priced models in the official source that neither have a canonical YAML ID nor
satisfy an existing match rule. Confirm the exact API ID before proposing an addition. Aliases are not new models. Do not
infer removals from absence on a pricing page. Record unmatched or ambiguous rows and unchecked fields as skipped findings.
