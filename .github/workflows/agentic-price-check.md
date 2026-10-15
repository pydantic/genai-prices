---
emoji: '🏷️'
name: 'Price Check'
description: 'Check twenty-five provider records against official pricing sources, propose verified price updates in a PR, and notify Slack.'
on:
  workflow_dispatch:
  schedule:
    - cron: '0 6-18 * * 1-5'
      timezone: America/Los_Angeles
  permissions:
    pull-requests: read
if: ${{ vars.AGENTIC_WORKFLOWS_ENABLED == 'true' }}
runs-on: ubuntu-latest
permissions:
  contents: read
  pull-requests: read
concurrency:
  group: ${{ github.workflow }}
  cancel-in-progress: false
  queue: max
checkout:
  fetch-depth: 1
imports:
  - shared/price-check-engine.md
  - pydantic/pydantic-ai/src/pydantic_ai_harness/gh-aw/pydantic.md@main
  - shared/price-update.md
pre-agent-steps:
  - name: Install the gh-aw fetch transport
    run: |
      npm install --ignore-scripts --no-save --package-lock=false --no-audit --no-fund --prefix "$RUNNER_TEMP/gh-aw/price-check-fetch" undici@6.28.0
      echo "NODE_PATH=$RUNNER_TEMP/gh-aw/price-check-fetch/node_modules${NODE_PATH:+:$NODE_PATH}" >> "$GITHUB_ENV"
  - name: Install the price-check scope preflight
    run: |
      uv run python - <<'PY'
      import json
      import os
      import shlex
      import shutil
      import subprocess
      from pathlib import Path
      from ruamel.yaml import YAML

      directory = Path(os.environ['RUNNER_TEMP']) / 'gh-aw/price-check-scope'
      directory.mkdir()
      frontmatter = Path('.github/workflows/agentic-price-check.md').read_text().partition('\n---\n')[0].removeprefix('---\n')
      workflow = YAML(typ='safe').load(frontmatter)
      policy = directory / 'policy.json'
      policy.write_text(json.dumps({
          'base_sha': os.environ['GITHUB_SHA'],
          'allowed_files': workflow['safe-outputs']['create-pull-request']['allowed-files'],
          'helper_path': str(directory.parent / 'actions/manifest_file_helpers.cjs'),
      }))
      script = directory / 'check.cjs'
      shutil.copyfile('scripts/price_check_scope.cjs', script)
      hook = directory / 'pre-commit'
      hook.write_text('#!/bin/sh\nexec node ' + shlex.quote(str(script)) + ' ' + shlex.quote(str(policy)) + ' --staged\n')
      hook.chmod(0o755)
      subprocess.run(['git', 'config', 'core.hooksPath', str(directory)], check=True)
      with Path(os.environ['GITHUB_ENV']).open('a') as output:
          output.write(f'PRICE_CHECK_SCOPE_COMMAND=node {shlex.quote(str(script))} {shlex.quote(str(policy))}\n')
      PY
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
  threat-detection: false
  report-failure-as-issue: false
  report-incomplete:
    create-issue: false
  noop:
    report-as-issue: false
  create-pull-request:
    max: 1
    draft: false
    fallback-as-issue: false
    max-patch-size: 10240
    protected-files:
      policy: blocked
      exclude: [README.md]
    allowed-files:
      - prices/providers/openai.yml
      - prices/providers/openai_decisions.yml
      - prices/providers/anthropic.yml
      - prices/providers/google.yml
      - prices/providers/mistral.yml
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
      - prices/providers/typesafe.yml
      - prices/providers/zai.yml
      - prices/providers/meta.yml
      - prices/providers/modal.yml
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
timeout-minutes: 90
# Disable configurable credit budgets. AWF retains its fixed 10,000-credit cap;
# these API-equivalent rates support accounting and enforcement, not plan charges.
max-ai-credits: -1
max-daily-ai-credits: -1
models:
  # USD per million tokens, https://docs.z.ai/guides/overview/pricing (2026-10-15).
  default-ai-credits-pricing:
    input: 0.15
    cache_read: 0.03
    output: 0.50
  providers:
    anthropic:
      models:
        glm-5.3-flash:
          # The accounting overlay uses USD per token, including credit enforcement.
          cost:
            input: 0.00000015
            cache_read: 0.00000003
            output: 0.00000050
post-steps:
  - name: Export price-check telemetry
    if: always()
    continue-on-error: true
    uses: actions/github-script@3a2844b7e9c422d3c10d287c895573f7108da1b3 # v9.0.0
    env:
      # Keep this credential scoped to the trusted step after the agent exits.
      OTEL_EXPORTER_OTLP_HEADERS: Authorization=${{ secrets.LOGFIRE_OTLP_AUTHORIZATION }}
    with:
      script: |
        const fs = require('node:fs');
        const path = require('node:path');
        const { createHash } = require('node:crypto');
        const { buildAttr, buildOTLPPayload, sendOTLPSpan } = require(
          path.join(process.env.RUNNER_TEMP, 'gh-aw/actions/send_otlp_span.cjs')
        );
        try {
          const readRecords = (file) => fs.readFileSync(file, 'utf8').split('\n').flatMap((line) => {
            try {
              const record = JSON.parse(line);
              return record && typeof record === 'object' && !Array.isArray(record) ? [record] : [];
            } catch { return []; }
          });
          const log = readRecords('/tmp/gh-aw/agent-session.jsonl');
          const usage = JSON.parse(fs.readFileSync('/tmp/gh-aw/agent_usage.json', 'utf8'));
          if (typeof usage.primary_model !== 'string' || !usage.primary_model) {
            throw new Error('No canonical primary model; telemetry is incomplete.');
          }
          const modelUsage = { [usage.primary_model]: {
            inputTokens: usage.input_tokens, cacheReadInputTokens: usage.cache_read_tokens,
            cacheCreationInputTokens: usage.cache_write_tokens, outputTokens: usage.output_tokens,
          } };
          const output = JSON.parse(fs.readFileSync('/tmp/gh-aw/agent_output.json', 'utf8'));
          const terminalEmitted = output.items?.some((item) => ['noop', 'create_pull_request'].includes(item.type)) === true;
          const succeeded = log.some((record) => record.type === 'session.result' && record.data?.status === 'success');
          const requests = [...new Map(readRecords(
            '/tmp/gh-aw/sandbox/firewall/logs/api-proxy-logs/otel.jsonl'
          ).map((record) => [record.spanId, record])).values()];
          if (!requests.length) throw new Error('No API request spans; telemetry is incomplete.');
          const identity = [process.env.GITHUB_REPOSITORY, process.env.GITHUB_RUN_ID, process.env.GITHUB_RUN_ATTEMPT].join(':');
          const digest = createHash('sha256').update(identity).digest('hex');
          const traceId = digest.slice(0, 32);
          const rootId = digest.slice(32, 48);
          const resourceAttributes = Object.entries({
            'gh-aw.repository': process.env.GITHUB_REPOSITORY,
            'gh-aw.run.id': process.env.GITHUB_RUN_ID,
            'github.run_attempt': process.env.GITHUB_RUN_ATTEMPT,
            'github.sha': process.env.GITHUB_SHA,
          }).map(([key, value]) => buildAttr(key, value));
          const startMs = Math.min(...requests.map((record) => record.startTimeMs));
          const endMs = Math.max(...requests.map((record) => record.endTimeMs));
          const payloads = [];
          const addSpan = (options) => payloads.push(buildOTLPPayload({
            traceId, serviceName: 'gh-aw.agentic-price-check', resourceAttributes, startMs, endMs, ...options,
          }));
          const toolCounts = {};
          for (const record of log) {
            const name = record.data?.toolName;
            if (record.type === 'tool.execution_start' && typeof name === 'string')
              toolCounts[name] = (toolCounts[name] ?? 0) + 1;
          }
          addSpan({ spanId: rootId, spanName: 'invoke_agent', statusCode: succeeded ? 1 : 2, attributes: [
            buildAttr('gen_ai.operation.name', 'invoke_agent'), buildAttr('gen_ai.agent.name', 'Price Check'),
            buildAttr('price_check.terminal_output_emitted', terminalEmitted),
            buildAttr('price_check.tool_counts', JSON.stringify(toolCounts)),
          ] });
          for (const [model, usage] of Object.entries(modelUsage)) {
            const counts = {
              uncached_input: usage.inputTokens, cached_input: usage.cacheReadInputTokens,
              cache_creation: usage.cacheCreationInputTokens, output: usage.outputTokens,
            };
            if (!Object.values(counts).every((value) => Number.isSafeInteger(value) && value >= 0)) {
              throw new Error('Invalid cumulative usage; telemetry is incomplete.');
            }
            addSpan({ spanId: createHash('sha256').update(identity + model).digest('hex').slice(0, 16),
              parentSpanId: rootId, spanName: 'price_check.usage', attributes: [
                buildAttr('gen_ai.request.model', model), buildAttr('price_check.usage.source', 'gh-aw.agent_usage'),
                ...Object.entries(counts).map(([key, value]) => buildAttr('price_check.usage.' + key, value)),
              ] });
          }
          for (const record of requests) addSpan({
            spanId: record.spanId, parentSpanId: rootId, spanName: record.name, kind: record.kind,
            startMs: record.startTimeMs, endMs: record.endTimeMs, statusCode: record.status?.code,
            attributes: Object.entries(record.attributes).map(([key, value]) => buildAttr(key, value)),
          });
          await sendOTLPSpan('https://logfire-eu.pydantic.info', {
            resourceSpans: payloads.flatMap((payload) => payload.resourceSpans),
          });
          if (fs.existsSync('/tmp/gh-aw/otlp-export-errors.jsonl')) throw new Error('Logfire export failed; inspect OTLP export errors.');
          fs.mkdirSync('/tmp/gh-aw/mcp-logs', { recursive: true });
          fs.writeFileSync('/tmp/gh-aw/mcp-logs/price-check-telemetry.json', JSON.stringify({
            run_id: process.env.GITHUB_RUN_ID, trace_id: traceId, exported_request_spans: requests.length,
            usage_source: 'gh-aw.agent_usage', model_usage: modelUsage, tool_counts: toolCounts,
            cost_is_client_estimate: true,
          }, null, 2));
          await core.summary.addRaw(`Logfire: exported ${requests.length} request spans and cumulative usage.\n`).write();
        } catch (error) {
          await core.summary.addRaw(`Logfire telemetry incomplete: ${error.message}\n`).write();
          throw error;
        }
engine:
  model: anthropic/glm-5.3-flash
sandbox:
  agent:
    token-steering: false
network:
  allowed:
    - defaults
    - api.z.ai
    - platform.openai.com
    - developers.openai.com
    - platform.claude.com
    - docs.claude.com
    - docs.anthropic.com
    - ai.google.dev
    - cloud.google.com
    - docs.cloud.google.com
    - mistral.ai
    - docs.mistral.ai
    - api-docs.deepseek.com
    - docs.z.ai
    - dev.meta.ai
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
    - docs.typesafe.ai
    - developers.cloudflare.com
    - cursor.com
    - docs.arcee.ai
    - docs.baseten.co
    - www.baseten.co
    - docs.github.com
    - www.databricks.com
    - modal.com
    - docs.databricks.com
---

# Price Check

Check every provider in `.github/agentic-price-check-providers.yml` against its official sources. Propose verified price
changes and new models in one PR titled `Update provider prices`. Read the manifest once, then work provider by provider:
complete Steps 1-3a for one provider before moving to the next, recording findings as you go. After every provider is covered,
follow the shared Steps 4-5. Complete the evidence check in Step 3a before editing any existing rate.
Include incomplete findings in the PR body or the noop reason; do not edit unverified prices.

Keep every changed file within this workflow's `create-pull-request.allowed-files` list.
Defer a candidate if its required regression updates need a file outside that list.
Run `$PRICE_CHECK_SCOPE_COMMAND` before validation and before committing. Restore and defer candidates that fail this preflight.

## Step 1 - read the manifest and recorded data

Run `cat .github/agentic-price-check-providers.yml` once. For each provider, `cat` its provider file and read all models
before checking that provider's official sources. The manifest's `scope` limits model discovery and its `notes` define
provider-specific mappings. Do not infer coverage outside that scope.

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

For the current provider, use `web-fetch` on every exact URL in the manifest. Reuse each fetched response for all in-scope
models it covers; do not fetch or reread a readable page again per model. Fetch a distinct official URL once when needed.
You may follow links on the same allowed official domains to confirm an exact API ID or an in-scope price. Respect the
manifest's mapping notes. Do not use search results, aggregators, cached snippets, or third-party pages. Retry a failed
fetch, or fetch a specific official follow-up only for a field the first response leaves unresolved.

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
   infer removal from a pricing page that does not claim to list the full catalog. Keep removal claims specific to the provider
   and exact model IDs in the source. A reseller's catalog omission does not establish discontinuation by the model's creator.
   Do not extend a family's discontinuation notice to separately listed variants or later generations.
4. **Unchecked fields.** List every active YAML price field or tier that you could not map to an official value. A missing,
   ambiguous, or non-numeric official value is unchecked, not matching.

If a source is readable for prices but not a complete catalog, compare prices and unchecked fields but do not report potential
removals from it. You may propose new models when the official source identifies their exact API IDs and in-scope prices.

## Step 3a - establish evidence before editing an existing rate

A different price on today's official page proves the current rate. It does not prove when the rate changed or that the
recorded price was wrong. Classify every proposed change to an existing model before editing its YAML:

1. **Rate change with a verified effective date.** Record the provider's effective date and the official source URL that
   establishes it. Preserve every existing price record and add the dated update using the shared Step 4 scope rules.
2. **Correction with evidence of an original error.** Record the official evidence that the old value was already wrong when
   recorded. Only this case permits an in-place correction. Today's rate alone is not that evidence.
3. **Unverified timing or correction.** Leave the entire model entry unchanged, including `prices_checked`. Put the exact
   model ID, recorded and proposed rates, source URL, and missing evidence in the PR's skipped-findings section. Continue with
   independently verified new models or changes. Call noop if no safe changes remain.

Do not use the run date, `prices_checked`, a page's update date, a search crawl date, or a model's launch date as a substitute
for a published rate-change date. If the available sources disagree about timing or rates, skip the change.

For example, if YAML records $0.0805 per million input tokens and today's page lists $0.14 without a change date or proof
of an original error, retain $0.0805 and report $0.14 as deferred. Do not overwrite it or invent a dated entry.

For every dated update, add public-API regression assertions in Python, JavaScript, and Go for a request immediately before
the effective date and a request on that date. Assert the original and new costs, including each affected cache or output
rate. Updating only the current-price assertions does not verify historical pricing.

Before submitting the PR, inspect `git diff` and check every changed existing rate against its classification above. The PR
body must include effective-date evidence for each dated update and original-error evidence for each in-place correction.
Restore and defer any change missing that evidence, then rebuild and rerun the checks. Passing tests do not supply missing
pricing evidence.
