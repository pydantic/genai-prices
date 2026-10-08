---
emoji: '🏷️'
name: 'Price Check: Direct Providers'
description: 'Check sixteen official provider catalogs, propose verified price updates in a PR, and notify Slack.'
on:
  workflow_dispatch:
  schedule: daily
  permissions:
    pull-requests: read
  skip-if-match: 'is:pr is:open in:title "Update direct-provider prices"'
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
      - prices/providers/deepseek.yml
      - prices/providers/x_ai.yml
      - prices/providers/groq.yml
      - prices/providers/cerebras.yml
      - prices/providers/minimax.yml
      - prices/providers/moonshotai.yml
      - prices/providers/avian.yml
      - prices/providers/perplexity.yml
      - prices/providers/cohere.yml
      - prices/providers/voyageai.yml
      - prices/providers/cloudflare.yml
      - prices/providers/cursor.yml
      - prices/providers/arcee.yml
      - prices/providers/baseten.yml
      - prices/providers/github_copilot.yml
      - prices/providers/databricks.yml
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
timeout-minutes: 60
max-turns: 300
# Disable gh-aw's AI-credits guardrail: the Fireworks minimax model isn't in gh-aw's
# pricing catalog, so with the guardrail active the api-proxy rejects it (HTTP 400
# unknown_model_ai_credits). -1 makes the firewall drop maxAiCredits. Requires the
# compiler pinned to v0.82.2 (firewall 0.27.22); see AGENTIC_PRICE_CHECK.md.
max-ai-credits: -1
max-daily-ai-credits: -1
engine:
  id: claude
  # Claude Code pointed at Fireworks's Anthropic-compatible endpoint, matching
  # the pydantic/platform agentic fleet. The maintainer must add a
  # FIREWORKS_API_KEY repo secret (or swap this block for a direct
  # ANTHROPIC_API_KEY). gh-aw's preflight only checks the env var is non-empty.
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
    - api-docs.deepseek.com
    - docs.x.ai
    - console.groq.com
    - api.cerebras.ai
    - platform.minimax.io
    - platform.moonshot.ai
    - platform.kimi.ai
    - avian.io
    - docs.perplexity.ai
    - cohere.com
    - docs.voyageai.com
    - developers.cloudflare.com
    - cursor.com
    - docs.arcee.ai
    - docs.baseten.co
    - www.baseten.co
    - docs.github.com
    - www.databricks.com
    - docs.databricks.com
---

# Price Check: Direct Providers

Check every provider in `.github/agentic-price-check-providers.yml` against its official sources. Propose verified price
changes and new models in one PR titled `Update direct-provider prices`. Follow Steps 1-3, then the shared update steps.
Include incomplete findings in the PR body or the noop reason; do not edit unverified prices.

## Step 1 - read the manifest and recorded data

Run `cat .github/agentic-price-check-providers.yml` and then `cat` every provider file named by the manifest. The manifest's
`scope` limits model discovery and its `notes` define provider-specific mappings. Do not infer coverage outside that scope.

Read every model's canonical `id`, complete `match` expression, `deprecated` state, and every key under `prices:`. A match
expression can use `equals`, `starts_with`, `contains`, `regex`, or nested `or` rules. Read `prices/units.yml` when you need a
unit definition. Key suffixes are not interchangeable:

- `_mtok` is USD per 1,000,000 tokens.
- `_kcount` is USD per 1,000 events.
- `_mchars` is USD per 1,000,000 characters.
- `_hours` is USD per 3,600 seconds.
- `_gpixels` is USD per 1,000,000,000 pixels.
- `_kpages` is USD per 1,000 pages.

A price value can be a scalar or an object with `base` and `tiers`. Compare the base and every tier whose threshold appears in
the official source. A model's `prices:` can also be a list of records with constraints. For each distinct time, context, batch,
modality, or regional scope, compare only the last matching record whose complete constraint applies on the run date. Ignore
shadowed history, expired records, and future records when comparing current prices; preserve them unchanged.

## Step 2 - fetch every official source

Use `web-fetch` on every exact URL in the manifest. You may follow links on the same allowed official domains when a manifest
note requires a model detail page. Do not use search results, aggregators, cached snippets, or third-party pages.

A source is unreadable when it times out, errors, redirects to unrelated content, or omits the model IDs or numeric prices needed
for its stated purpose. Record an unreadable-source finding. Do not guess, reuse remembered prices, or treat the provider as clean.

## Step 3 - compare prices and catalogs

For every provider, perform all four checks:

1. **Price changes.** Match an official row to a YAML model only by its canonical ID, a satisfied `match` rule, or an
   unambiguous marketing name. Compare every official standard public-API price with the corresponding YAML field. Convert units
   and show the arithmetic. Do not compare free allowances, trials, subscriptions, dedicated capacity, Batch discounts, or
   enterprise quotes unless the manifest says to do so.
2. **New models.** List each in-scope, publicly available, numerically priced official model whose ID is not a canonical YAML ID
   and does not satisfy any YAML `match` expression. Do not list aliases as separate models.
3. **Potential removals.** List each non-deprecated YAML model that is absent from a readable, complete official catalog. Do not
   infer removal from a pricing page that does not claim to list the full catalog.
4. **Unchecked fields.** List every active YAML price field or tier that you could not map to an official value. A missing,
   ambiguous, or non-numeric official value is unchecked, not matching.

If a source is readable for prices but not a complete catalog, compare prices and unchecked fields but do not report new models
or potential removals from that source.
