---
emoji: '🏷️'
name: 'Price Check: Google & Mistral'
description: "Compare the recorded Google (Gemini) and Mistral model prices against each provider's official pricing page and file one rolling issue listing any discrepancies."
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
    title-prefix: '[price-check/google-mistral] '
    close-older-key: '[price-check/google-mistral]'
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
    - ai.google.dev
    - cloud.google.com
    - mistral.ai
    - docs.mistral.ai
---

# Price Check: Google & Mistral

Compare the model prices this repo records for **Google (Gemini)** and **Mistral**
against each provider's official pricing page, and file one issue listing every
price that differs. Do Google first, then Mistral: Steps 1-3 apply to each provider, and
Step 4 combines both into a single issue (built fresh each run, replacing the previous one).

## Step 1 — read the recorded prices

Run `cat prices/providers/google.yml` (then `mistral.yml`). Under `models:` each
entry has an `id`, a `match`, and a `prices:` block. Every number is **USD per
1,000,000 tokens**. The fields you check:

- `input_mtok` — standard **text** input price
- `output_mtok` — output price
- `cache_read_mtok` — cached input price (check only when the page lists one)
- `input_audio_mtok` — audio input price, on Gemini models that have it (compare it to the page's audio input rate, separately from text)
- `cache_audio_read_mtok` — cached **audio** input price, on Gemini models that have it (compare to the page's audio context-cache rate, check only when the page lists one)

Some Gemini entries are tiered by prompt size, e.g.
`input_mtok: {base: 1.25, tiers: [{start: 200000, price: 2.5}]}`. Use the `base`
value (the ≤200K-token rate) and set the tiers aside.

A model's `prices:` can also be a list of records, some wrapped in a `constraint:`
(e.g. `start_date`). Use the record that applies on the run date — the one whose
`start_date` is the most recent date on or before today (a record with no `constraint`
is the default).

Note each model's `id` and its `input_mtok` / `output_mtok` before you fetch.

## Step 2 — fetch the pricing page

`web-fetch` the exact URL for that provider (below). If the fetched content contains
no dollar figures at all, the page did not render for you — record that provider as
unread and move on; never fill in a number the page didn't give you.

### Google (Gemini)

- Page: <https://ai.google.dev/gemini-api/docs/pricing>
- Prices are the **paid tier**, per 1M tokens. Gemini often quotes a text/image/video
  input rate and a separate **audio** input rate — compare the text rate to
  `input_mtok` and the audio rate to `input_audio_mtok`. Where a rate is split by
  prompt size (e.g. Gemini 2.5 Pro is $1.25 up to 200K tokens and $2.50 above),
  compare the up-to-200K rate to the YAML `base`.

### Mistral

- Page: <https://mistral.ai/pricing/api>
- The API pricing table lists an input and output price per model, per 1M tokens.

## Step 3 — match models and compare

For each YAML model, find its row on the page by id or marketing name: YAML
`gemini-2.5-flash` is "Gemini 2.5 Flash"; YAML `gemini-2.5-pro` is "Gemini 2.5 Pro";
YAML `mistral-large` (name "Mistral Large"; `mistral-large-latest` is one of its match
aliases, not a separate model) is the page's "Mistral Large"; YAML `codestral` is
"Codestral". Match a row only when it identifies that exact record unambiguously — if a
name could be more than one YAML record (e.g. `mistral-large` vs `mistral-large-2512`),
skip it. When you find the row, compare each price field the page provides against the
YAML.

Put every price in USD per 1M tokens before comparing: "$3 / MTok" = `3`,
"$0.003 / 1K tokens" = `3`, "$3.00" = `3`.

Compare the standard on-demand rate. If the page also has Batch or provisioned
tables, read the standard one for the comparison and leave those alone.

Report each discrepancy under the model's canonical YAML `id`. A model where the matched
page rate differs from the YAML is a discrepancy to report. When a YAML model has no
matching row on the page, move to the next model.

## Step 4 — file the issue (or noop)

Collect every confirmed discrepancy from both providers first, then decide:

- **One or more discrepancies** — file **one** issue titled
  `Google/Mistral price discrepancies`, with a table, one row per differing field. If a
  provider's page was unreadable this run, still file the discrepancies you did confirm
  and add a line naming the unread page — never drop a real difference because the other
  page failed to load.

| Provider | Model (YAML id) | Field         | Recorded (YAML) | Official page | Page URL                                      |
| -------- | --------------- | ------------- | --------------- | ------------- | --------------------------------------------- |
| Google   | gemini-2.5-pro  | `output_mtok` | 10              | 12            | https://ai.google.dev/gemini-api/docs/pricing |

Where you converted units, show the arithmetic in that row. End the body with the date
you ran, e.g. "Checked 2026-07-22." A maintainer uses this to update the YAML `prices:`
and bump `prices_checked`.

- **Zero confirmed discrepancies** — call `safeoutputs noop` with a one-line reason,
  naming any page that would not load, e.g. "All Google + Mistral prices match" or
  "Mistral page returned no prices; all Google prices match".
