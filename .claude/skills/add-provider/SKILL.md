---
name: add-provider
description: Add a new inference provider to genai-prices, including provider data, matching, usage extractors, update automation, cassettes, agentic checks, generated artifacts, and Python/JavaScript/Go parity tests. Use for a new provider, not a new model on an existing provider.
---

# Add a provider

Add the provider as a complete, maintainable integration. Read `AGENTS.md` before editing. Preserve unrelated worktree changes.

## Establish the supported scope

Use the provider's official pricing page and model catalog. Record the exact source URLs.

Read `prices/units.yml` before mapping prices. Include only billing units represented by the current published contract. Do not
add a unit to make a provider fit because that is a v3 contract change. Explain excluded model categories in the provider's
`price_comments`.

Decide whether the official source is a complete catalog or only a pricing page. This determines whether missing models can be
treated as potential removals.

## Author the provider YAML

Create `prices/providers/<provider>.yml`. Never edit generated artifacts directly.

Cover these fields when they apply:

- `id`, `name`, and official `pricing_urls`
- `api_pattern` for the provider's actual API hosts and paths
- `provider_match` for common provider identifiers
- `model_match` only when the provider owns an unambiguous model-ID namespace
- `fallback_model_providers` only when another provider's prices are intentionally inherited
- `price_comments` for free allowances, unsupported units, regional differences, or other calculation boundaries

For each supported model:

- use the exact API model ID as the canonical `id`
- add precise aliases without creating matches against sibling models
- map official rates to the correct units, such as `_mtok`, `_kcount`, or `_mchars`
- include cache, reasoning, modality, request, and tool rates when represented by the unit registry
- set `prices_checked` to the verification date
- preserve historical price changes with dated conditional prices instead of overwriting old rates
- mark officially deprecated models without inferring removal from an incomplete source

Keep models sorted by ID. Use names and context windows from official documentation when available.

## Add usage extraction

Inspect recorded or documented response bodies for every supported API flavor. Do not assume that an OpenAI-compatible endpoint
has the same response as the provider's native endpoint.

Add provider extractors for flavors that report usage. Extract the model when the response includes it. When the response omits
the model, return the usage with a nullable model so callers can provide the request model during price calculation. Map cached
tokens separately. Any extractor that maps `completion_tokens` must also map the provider's reasoning-token breakdown to
`output_reasoning_tokens`. Test each flavor through the public Python, JavaScript and Go extraction APIs.

If an API response does not report usage, leave that flavor unsupported and document the limitation instead of inventing a
mapping.

## Add an automatic price update

Every provider needs a way to update its prices automatically. Look for an official source a script can read without
credentials, in this order: a pricing API or `/v1/models` response with prices, a Markdown docs page (`.md`, `llms.txt`), then
JSON embedded in the official pricing page. Treat an HTML fallback served for a `.md` URL as unreadable.

Add `prices/src/prices/source_<provider>.py`, following `source_novita.py` (JSON) or `source_cloudflare.py` (Markdown):

- fetch with `httpx2` and parse prices as `Decimal`
- return `ModelInfo` entries from a public `parse_*` function and write them with `ProviderYaml.upsert_models`, which adds new
  models, appends changed rates as dated conditional prices, and keeps curated keys the source does not report
- emit only the keys the source reports, and parse tiers when the source has them instead of flattening them
- set a `MIN_MODEL_COUNT` so an empty or truncated response refuses to write
- fail loudly when the source is unreadable or changes shape

Expose `get_<provider>_prices` through `prices.__main__`. Add `<provider>-get` to `Makefile`, include it in `get-all-prices`,
and add `<provider>` to the `matrix.importer` list in `.github/workflows/update-prices.yml`, which runs every importer hourly
and keeps one rolling PR.

Pin tests that assert the provider's current rates to an explicit timestamp. Otherwise the first hourly rate change breaks CI
on the rolling PR.

Test the real HTTP boundary with `@pytest.mark.vcr`, recorded with `cassetter`. Record the official response, inspect the
cassette, commit it, and prove replay with:

```bash
uv run pytest tests/test_source_<provider>.py --record-mode=none
```

Use compact synthetic inputs only for pure parser and update-behavior tests. Do not replace the external request with a
hand-written HTTP mock.

A provider without an importer is the exception. If no source a script can read exists, list the URLs you checked in the PR
and rely on agentic monitoring alone.

## Add agentic monitoring

The weekly agentic check is the fallback for what an importer cannot see: announced future prices, promotions, and new units
or tiers. Add the provider to `.github/agentic-price-check-providers.yml` with its YAML path, exact official sources, supported
scope, and unit-mapping notes. Add every source domain to `network.allowed` in `.github/workflows/shared/price-check-network.md`
and the YAML path to `create-pull-request.allowed-files` in `.github/workflows/agentic-price-check.md`.

Update `.github/workflows/AGENTIC_PRICE_CHECK.md`. Compile the lock files with gh-aw `v0.91.1`, the version pinned in them. Never
hand-edit a lock file.

```bash
gh aw compile agentic-price-check agentic-model-price-check --no-check-update
```

The agentic workflow opens at most one PR of verified price updates per run.

## Verify every runtime

Add focused Python, JavaScript and Go tests for:

- provider selection by explicit provider ID
- provider selection by API URL and model namespace when supported
- representative input, cached-input, and output price calculation
- every usage extractor flavor
- aliases and context-sensitive matching that could collide

Put the Go tests in `packages/go/api_test.go`, which runs against the bundled provider data. Test updater parsing,
metadata preservation, write guards, and cassette replay in Python only: the updater lives in `prices/src/prices/`.

Run `make build` after every provider-data edit. This regenerates the v2 feed, package data, schemas, and provider inventory.
Never hand-edit those outputs or `tests/dataset/usages.json`.

Before handoff, run:

```bash
make all
git diff --check
```

Inspect the provider YAML, cassette, and generated diff. Confirm that frozen v1 files are unchanged. Follow `AGENTS.md` for the
commit, PR description, AI disclaimer, CI monitoring, and review resolution.
