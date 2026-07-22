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
  noop:
    report-as-issue: false
  create-issue:
    max: 1
    title-prefix: '[price-check/openai-anthropic] '
    close-older-key: '[price-check/openai-anthropic]'
    close-older-issues: true
    expires: 30d
timeout-minutes: 20
max-turns: 120
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
    - platform.openai.com
    - developers.openai.com
    - platform.claude.com
    - docs.claude.com
    - docs.anthropic.com
---

# Price Check: OpenAI & Anthropic

Compare the model prices this repo records for **OpenAI** and **Anthropic** against
each provider's official pricing page, and file one issue listing every price that
differs. Do OpenAI first, then Anthropic: Steps 1-3 apply to each provider, and Step 4
combines both into a single issue (built fresh each run, replacing the previous one).

## Step 1 — read the recorded prices

Run `cat prices/providers/openai.yml` (then `anthropic.yml`). Under `models:` each
entry looks like this:

```yaml
- id: gpt-4o
  match: { ... }
  prices:
    input_mtok: 2.5
    output_mtok: 10
    cache_read_mtok: 1.25
```

Every number in `prices:` is **USD per 1,000,000 tokens**. The fields you check:

- `input_mtok` — standard input price
- `output_mtok` — output price
- `cache_read_mtok` — cached / cache-hit input price (check only when the page lists a cache price)
- `cache_write_mtok` — cache-write price (check only when the page lists one)

A few entries are tiered, e.g. `input_mtok: {base: 3, tiers: [{start: 200000, price: 6}]}`.
Use the `base` value (here `3`) and set the tiers aside.

A model's `prices:` can also be a list of records, some wrapped in a `constraint:`
(e.g. `start_date`). Use the record that applies on the run date — the one whose
`start_date` is the most recent date on or before today (a record with no `constraint`
is the default) — and read that record's fields.

Note the `id` and `input_mtok` / `output_mtok` of every model so you know what to
look for on the page.

## Step 2 — fetch the pricing page

`web-fetch` the exact URL for that provider (below). Both are markdown pages with a
price table. If the fetched content contains no dollar figures at all, the page did
not render for you — record that provider as unread and move on; never fill in a
number the page didn't give you.

### OpenAI

- Page: <https://developers.openai.com/api/docs/pricing.md>
- This page lists each model as an array: `["gpt-4o", 2.5, 1.25, 10]`, meaning
  **[model id, input per 1M, cached input per 1M, output per 1M]**. So this row says
  `gpt-4o` is input $2.5, cached input $1.25, output $10 — compare those to
  `input_mtok`, `cache_read_mtok`, `output_mtok`.

### Anthropic

- Page: <https://platform.claude.com/docs/en/about-claude/pricing.md>
- Read the "Model pricing" table. Map its columns to the YAML fields:
  **Base Input Tokens** → `input_mtok`, **Output Tokens** → `output_mtok`,
  **5m Cache Writes** → `cache_write_mtok`, **Cache Hits & Refreshes** →
  `cache_read_mtok`. A cell like "$5 / MTok" means `5`.

## Step 3 — match models and compare

For each YAML model, find its row on the page by id or marketing name: YAML `gpt-4o`
is "gpt-4o"; YAML `gpt-4.1-mini` is "gpt-4.1-mini"; YAML `claude-3-5-sonnet` is
"Claude Sonnet 3.5"; YAML `claude-opus-4-8` is "Claude Opus 4.8". When you find the
row, compare each price field the page provides against the YAML.

Put every price in USD per 1M tokens before comparing: "$3 / MTok" = `3`,
"$0.003 / 1K tokens" = `3`, "$3.00" = `3`.

Compare the standard on-demand rate. If the page also has Batch, Flex, Priority,
fine-tuning, or Fast-mode tables, read the standard model-pricing table for the
comparison and leave those alone.

Match a page row to a YAML model only when its id or name identifies that exact record
unambiguously; if a row could be more than one record, skip it. Report each discrepancy
under the model's canonical YAML `id`. A model where the matched page rate differs from
the YAML is a discrepancy to report. When a YAML model has no matching row on the page,
move to the next model.

## Step 4 — file the issue (or noop)

Collect every confirmed discrepancy from both providers first, then decide:

- **One or more discrepancies** — file **one** issue titled
  `OpenAI/Anthropic price discrepancies`, with a table, one row per differing field. If
  a provider's page was unreadable this run, still file the discrepancies you did
  confirm and add a line naming the unread page — never drop a real difference because
  the other page failed to load.

| Provider | Model (YAML id) | Field         | Recorded (YAML) | Official page | Page URL                                          |
| -------- | --------------- | ------------- | --------------- | ------------- | ------------------------------------------------- |
| OpenAI   | gpt-4o          | `output_mtok` | 10              | 12            | https://developers.openai.com/api/docs/pricing.md |

Where you converted units, show the arithmetic in that row. End the body with the date
you ran, e.g. "Checked 2026-07-22." A maintainer uses this to update the YAML `prices:`
and bump `prices_checked`.

- **Zero confirmed discrepancies** — call `safeoutputs noop` with a one-line reason,
  naming any page that would not load, e.g. "All OpenAI + Anthropic prices match" or
  "All OpenAI prices match; Anthropic page returned no prices."
