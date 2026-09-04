---
emoji: '🏷️'
name: 'Price Check: Direct Providers'
description: 'Check fifteen direct provider catalogs for changed prices, new models, removed models, and unreadable sources.'
on:
  workflow_dispatch:
  schedule: weekly on monday
if: ${{ vars.AGENTIC_WORKFLOWS_ENABLED == 'true' }}
runs-on: ubuntu-latest
permissions:
  contents: read
  issues: read
concurrency:
  group: ${{ github.workflow }}
  cancel-in-progress: true
checkout:
  fetch-depth: 1
tools:
  bash:
    - 'cat:*'
    - 'ls:*'
    - 'rg:*'
  web-fetch:
safe-outputs:
  # Disabled: the detection sub-agent runs its own minimax call through a separate
  # credit guardrail that can't be satisfied for a BYOK model (a positive cap rejects
  # the unpriced minimax with HTTP 400; -1 is rejected as "maxAiCredits must be > 0").
  # With minimax it can never produce a verdict, so it stamped a false "threat detected
  # / could not be parsed" banner on every issue. Re-enable if the engine moves to a
  # model gh-aw prices.
  threat-detection: false
  noop:
    report-as-issue: false
  create-issue:
    max: 1
    title-prefix: '[price-check/direct-providers] '
    close-older-key: '[price-check/direct-providers]'
    close-older-issues: true
    expires: 30d
timeout-minutes: 30
max-turns: 200
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
---

# Price Check: Direct Providers

Check every provider in `.github/agentic-price-check-providers.yml` against its official sources. File one rolling issue with
every actionable or incomplete finding from the run. Do not edit the repository.

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
the official source. A model's `prices:` can also be a list of records with constraints. Compare every record that can apply on
the run date, including separate time, context, batch, modality, or regional rates when the official source exposes them. Ignore
records that ended before the run date or start in the future.

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

## Step 4 - file one issue or noop

If any price change, new model, potential removal, unchecked field, or unreadable source exists, create one issue titled
`Direct-provider price check findings`. Include only non-empty sections from this list:

- `Price discrepancies`: Provider, YAML model ID, field or tier, recorded value, official value, source URL.
- `New models`: Provider, official model ID, official prices, source URL.
- `Potential removals`: Provider, YAML model ID, source URL.
- `Unchecked fields`: Provider, YAML model ID, field or tier, reason, source URL.
- `Unreadable sources`: Provider, source URL, failure.

Use tables and one row per finding. End with `Checked YYYY-MM-DD.` using the run date.

Call `safeoutputs noop` only when all manifest providers and sources were read successfully, every active price field and tier was
checked, every recorded value matched, and catalog comparison found no new or potentially removed models. State that all fourteen
direct providers match.
