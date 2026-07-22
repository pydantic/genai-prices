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

Compare the model prices this repo records for **OpenAI** and **Anthropic**
against each provider's official pricing page, and file one issue listing the
differences. The issue is replaced each run, so report the current state.

For each provider:

1. Read the recorded prices: `cat prices/providers/<file>.yml`. Each model has an
   `id`, a `match`, and a `prices:` block of USD-per-million-token rates:
   `input_mtok`, `output_mtok`, and sometimes `cache_read_mtok` /
   `cache_write_mtok`.
2. `web-fetch` the provider's pricing page (the exact URL below).
3. Match each YAML model to its row on the page by API id / name (YAML `gpt-4o` ↔
   "gpt-4o"; YAML `claude-3-5-sonnet` ↔ "Claude Sonnet 3.5"), then compare
   `input_mtok` and `output_mtok`, plus the cache rates when both sides list them.
4. Convert every page price to USD per 1M tokens before comparing: "$3 / MTok" and
   "$0.003 / 1K" both equal `input_mtok: 3`. Use the standard on-demand rate; for a
   model with tiered / batch / flex pricing, use the standard tier unless the YAML
   records the tier.
5. Report a model when the page's rate differs from the YAML, using only prices you
   can read directly off the page. Match a YAML model to its page row where you can;
   where you can't, move on.

### OpenAI

- YAML: `prices/providers/openai.yml`
- Page: <https://developers.openai.com/api/docs/pricing.md>

### Anthropic

- YAML: `prices/providers/anthropic.yml`
- Page: <https://platform.claude.com/docs/en/about-claude/pricing.md> — the
  "Model pricing" table (Base Input Tokens and Output Tokens columns, plus the
  cache columns).

## The issue

File one issue titled `OpenAI/Anthropic price discrepancies` with a table:

| Provider | Model (YAML id) | Field | Recorded (YAML) | Official page | Page URL |
| -------- | --------------- | ----- | --------------- | ------------- | -------- |

Show the unit conversion where you did one, and end with the date you checked. If
every price matches, or a page returned no readable prices, call `safeoutputs noop`
with a one-line reason.
