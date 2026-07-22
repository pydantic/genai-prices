---
emoji: '🏷️'
name: 'Price Check: OpenAI & Anthropic'
description: "Compare the recorded OpenAI and Anthropic model prices against each provider's official pricing page and file one rolling issue listing any discrepancies."
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
  threat-detection: false
  noop:
  create-issue:
    max: 1
    title-prefix: '[price-check/openai-anthropic] '
    close-older-key: '[price-check/openai-anthropic]'
    close-older-issues: true
    expires: 30d
timeout-minutes: 20
max-turns: 120
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
    - platform.openai.com
    - developers.openai.com
    - platform.claude.com
    - docs.claude.com
    - docs.anthropic.com
---

# Price Check: OpenAI & Anthropic

You verify that the model prices this repo records for **OpenAI** and
**Anthropic** still match each provider's **official** pricing page. Each run you
produce **one** issue listing every discrepancy you can confirm, or you call
`safeoutputs noop` when everything matches. That issue is replaced every run
(close-older), so it always reflects the current state — you never need to dedupe
against past issues.

A wrong discrepancy costs a maintainer real time chasing a phantom price change,
so **only report a discrepancy you can read directly and unambiguously off the
official page.** If a page will not load, or its prices are rendered in a way you
cannot read (some pages are JavaScript apps that `web-fetch` returns empty), say
so plainly and do **not** guess or infer a price. A clean noop with "could not
read <page>" is a good outcome.

## What to check, per provider

1. Read the recorded prices from the YAML with `cat`. Each entry under `models:`
   has an `id`, a `match`, and a `prices:` block of per-million-token USD rates:
   `input_mtok`, `output_mtok`, and sometimes `cache_read_mtok` /
   `cache_write_mtok`. Note each model's `prices_checked` date.
2. `web-fetch` the provider's official pricing page — the **exact URL below,
   nothing else**. Do not browse around the site.
3. For each model in the YAML, find the same model on the page and compare
   `input_mtok` and `output_mtok` (and the cache rates if the page lists them).
4. A discrepancy is: the page shows a clearly different number than the YAML for
   a model you can confidently match by name.

### OpenAI

- YAML: `prices/providers/openai.yml`
- Fetch: <https://platform.openai.com/docs/pricing>
- Fallback only if a model is absent above: <https://developers.openai.com/api/docs/pricing>

### Anthropic

- YAML: `prices/providers/anthropic.yml`
- Fetch: <https://platform.claude.com/docs/en/about-claude/pricing> (the "Model pricing" table). Compare against the **Base Input Tokens** and **Output Tokens** columns, and the cache columns if the YAML records them.
- Fallback only if a model is absent above: <https://docs.anthropic.com/en/docs/about-claude/models/overview>

## Matching models

Match by marketing name / API id (YAML `claude-3-5-sonnet` ↔ page "Claude Sonnet
3.5"; YAML `gpt-4o` ↔ page "gpt-4o"). If you cannot confidently identify which
page row is a given YAML model, **skip it** — do not force a match.

## Units — read carefully

- YAML `input_mtok: 3` means **$3.00 per 1M input tokens**.
- Pages may quote per-1K or per-1M tokens. Convert to USD per 1M before
  comparing: "$3 / MTok" and "$0.003 / 1K tokens" both equal `input_mtok: 3`.
  Show the conversion arithmetic in the issue whenever you did one.

## What NOT to flag

- The same value written differently ($3.00 vs $3).
- A model on the page that is not in the YAML (a "missing model" is out of scope
  for this agent — you only check prices already recorded).
- A YAML model you cannot find on the page (skip it).
- Batch / flex / priority / fine-tuning / cached-input promo tiers — compare only
  the standard on-demand input and output rates, unless the YAML explicitly
  records that tier.
- Any price you cannot read cleanly off the page.

## The issue

If you confirmed one or more discrepancies, file **one** issue. Title:
`OpenAI/Anthropic price discrepancies`. Body: a short table —

| Provider | Model (YAML id) | Field | Recorded (YAML) | Official page | Page URL |
| -------- | --------------- | ----- | --------------- | ------------- | -------- |

Add the exact page URL, and where you converted units show the arithmetic. Keep
it terse and factual: the maintainer will edit the YAML `prices:` and bump
`prices_checked`. End the body with the date you checked.

If every recorded price matches, or you could not confirm any discrepancy, call
`safeoutputs noop` with a one-line reason (e.g. "all OpenAI + Anthropic prices
match" or "anthropic.com/pricing rendered empty via web-fetch — could not read").
