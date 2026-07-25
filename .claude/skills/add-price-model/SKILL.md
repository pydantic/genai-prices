---
name: add-price-model
description: >-
  Add a new LLM model (or provider) to genai-prices pricing data. Use when asked to add/update
  pricing for a model — e.g. "add grok 4.5", "add the new Claude", "update openai o5 prices". Covers
  sourcing prices, probing OpenRouter for undocumented dated snapshot IDs, editing the provider YAML,
  building, verifying resolution, and opening the PR.
---

# Add a model to genai-prices

Never edit `prices/data.json` / `prices/data_slim.json` by hand — they are generated. Edit the
provider YAML in `prices/providers/<provider>.yml`, then `make build-prices`.

## 0. Scope: every provider that hosts this model, not just the one you were named

A model rarely lives on one provider. The big vendors' flagships are resold across clouds and
aggregators, and each needs **its own YAML entry** — the same request "add the new Claude" means
`anthropic.yml` **and** `aws.yml` (Bedrock) **and** `google.yml` (Vertex) **and** `openrouter.yml`.
Adding only the direct-vendor entry is the most common miss (it's what happened for Opus 5 in #501,
requiring the follow-up #502). Before editing, list every provider that hosts the model and cover
them in one PR:

- **Direct vendor** — `anthropic.yml`, `openai.yml`, `google.yml` (Gemini), `x_ai.yml`, etc.
- **Aggregators/gateways** — `openrouter.yml` (usually day-one; often exposes `-fast`/`:beta` variants).
- **Cloud resellers** — `aws.yml` (Bedrock: `global.*` + `regional.*` split, regional ~+10%),
  `google.yml` (Vertex Claude entries live here too, separate from Gemini), Azure (`azure.yml` is
  Azure **OpenAI** only — Claude on Foundry is out of scope there; note it, don't force it).

Confirm hosting from each provider's docs/model list; don't assume. If a reseller genuinely hasn't
shipped it yet, that's the **only** reason to defer a provider — say which one and why in the PR, and
follow up when it lands (see "Provider rollout timing" below). "I was only asked about provider X" is
not a reason to skip the others.

## 1. Branch

Contribute via a branch on `origin` (this repo is `pydantic/genai-prices`, no fork). Always base off
freshly-fetched upstream:

```bash
git fetch origin && git checkout -b <slug> origin/main
```

## 2. Source the prices (cite everything)

Get input / cached-input / output per-Mtok and context window from the **provider's own docs first**
(authoritative). Vendor docs often omit the **cache-read** rate — cross-check OpenRouter's endpoint
API, which exposes it:

```
https://openrouter.ai/api/v1/models/<provider>/<model>/endpoints
```

`pricing.input_cache_read` is per-token — ×1,000,000 for the per-Mtok value. Record every number's
source; put them in the PR body.

## 3. Probe OpenRouter for the dated snapshot ID (do this every time)

Providers ship dated snapshot IDs (e.g. `grok-4.5-20260708`) that aren't in their docs. A real minimal
request returns the resolved dated ID in the response `model` field — capture it so the YAML `match`
covers future dated snapshots.

Key lives in `~/ai-coding-tools/.env` as `OPENROUTER_API_KEY`. Don't reference secret env vars in an
inline command (a hook blocks it and `env-run` rejects it) — put the request in a script that consumes
the var internally, then run it with `env-run`:

```bash
# scratchpad/or_probe.sh consumes $OPENROUTER_API_KEY internally
~/.claude/scripts/env-run ~/ai-coding-tools/.env -- bash scratchpad/or_probe.sh
```

```bash
curl -sS https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer ${OPENROUTER_API_KEY}" -H "Content-Type: application/json" \
  -d '{"model":"<provider>/<model>","messages":[{"role":"user","content":"hi"}],"max_tokens":5}' \
  | jq '{id, model, provider}'
```

The `model` field (e.g. `x-ai/grok-4.5-20260708`) reveals the snapshot. A `regex: '^<model>-\d{8}$'`
clause (plus a `<provider>/`-prefixed variant) makes it resolve without a separate entry.

## 4. Add the YAML entry

Match a sibling model's shape in `prices/providers/<provider>.yml` (ordering, `match`/`or` style,
fields). Include:

- `match.or`: bare id, `regex: '^<id>-\d{8}$'`, `<provider>/`-prefixed bare + dated, `-latest`
- `context_window`
- `prices_checked:` **today's date** (check the `currentDate` system reminder)
- `prices:` `input_mtok`, `cache_read_mtok` (omit if the provider has none), `output_mtok`

Add a `price_comments` field when a value needs explanation/reference.

**Migrate family-level `-latest` aliases when the new model is the current flagship.** Two kinds of
`-latest` alias coexist, and they behave differently:

- version-specific (`<id>-latest`, e.g. `grok-4.3-latest`) — always stays on its own entry.
- family-level / bare (`<provider>-latest`, e.g. `grok-latest`) — means "the current flagship" and
  should point at whichever model is newest/best right now.

When adding a new flagship, **move the family-level alias off the previous flagship onto the new
entry** (add it here, delete it there). First verify which model the vendor's alias actually resolves
to — check the provider docs and, if you can, hit the API and read the response `model` field — then
match that. Don't assume; the aliasing scheme is provider-specific (some vendors have no bare-family
alias at all).

## 5. Build + verify resolution

Use `make build`, not just `make build-prices`. The installed `genai_prices` package (and the JS
package) read their **bundled** data (`packages/python/genai_prices/data.py`, `packages/js/src/data.ts`)
— NOT `prices/data.json`. `make build-prices` only writes `prices/data.json`, so a `calc_price` check
run after it verifies **stale** package data and can silently show the wrong result. `make build` runs
`build-prices` + `package-data` + `inject-providers`.

```bash
make build    # build-prices + package-data + inject-providers
```

Confirm the base id, the dated snapshot, the provider-prefixed dated id, and any `-latest` alias you
touched all resolve to the intended entry (include the previous flagship to prove its version-specific
`-latest` didn't move):

```bash
uv run python -c "
from genai_prices import calc_price, Usage
u = Usage(input_tokens=1000, output_tokens=1000)
for m in ['<id>', '<id>-<YYYYMMDD>', '<provider>/<id>-<YYYYMMDD>', '<provider>-latest', '<prev-id>-latest']:
    r = calc_price(u, m, provider_id='<provider_id>')
    print(m, '->', r.model.id, r.model.prices.input_mtok, r.model.prices.output_mtok)
"
```

## 6. Commit, push, PR

Pre-commit hooks regenerate more than the JSON — **README.md**, **packages/js/src/data.ts**, and
**packages/python/genai_prices/data.py**. The first `git commit` will abort after the hooks rewrite
these; re-stage the regenerated files and commit again.

Stage files explicitly — **never `git add -A`** (it leaks local/scratch files):

```bash
git add prices/providers/<provider>.yml prices/data.json prices/data_slim.json \
        README.md packages/js/src/data.ts packages/python/genai_prices/data.py
git commit -m "Add <Provider> <Model> pricing"   # re-run once if hooks rewrite files
git push -u origin <slug>
gh pr create --base main --title "Add <Provider> <Model> pricing" --body "..."
```

Never force-push. PR body: pricing table, sources (provider docs + OpenRouter for cache rate), and
scope notes (e.g. single variant / no cache-write / any `-latest` alias you moved, each with its
one-line reason).

After pushing, don't go idle — poll until CI is green and every reviewer comment (cubic included) is
addressed or dismissed (see `AGENTS.md`). Unresolved review threads mean the PR isn't mergeable.

## Provider rollout timing

This is the escape hatch for step 0, not a reason to default to a single-provider PR. Cover every
provider that already hosts the model in the same PR. OpenRouter usually lists new models day-one.
Only when a reseller (Bedrock / Vertex) genuinely hasn't shipped yet do you defer _that_ provider —
name it in the PR body and follow up in a later PR once it lands, rather than blocking the rest.
