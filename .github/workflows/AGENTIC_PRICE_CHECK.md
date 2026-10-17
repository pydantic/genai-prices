# Agentic price-update workflow

```bash
gh secret set ZAI_API_KEY
gh secret set LOGFIRE_OTLP_AUTHORIZATION
gh variable set PRICE_UPDATE_APP_CLIENT_ID --body Iv23libntR0K6oyQrZWX
gh secret set PRICE_UPDATE_APP_PRIVATE_KEY < /path/to/genai-prices-automation.private-key.pem
gh secret set SLACK_WEBHOOK_URL
gh variable set AGENTIC_WORKFLOWS_ENABLED --body true
gh workflow run agentic-price-check.lock.yml
```

This [gh-aw](https://github.com/github/gh-aw) workflow schedules a check of all twenty-five covered provider records
each Monday at 06:00 UTC and supports manual dispatch. The same invocation also revisits pending requested-model rollouts from Genie Pricer. See the [gh-aw schedule syntax] and
[GitHub Actions schedule syntax]. The workflow combines
verified new models and rate changes into one ready-for-review PR titled `Update provider prices`. Scheduled runs target
`main`. Manual dispatch uses `main` unless you select a branch with `--ref`.
A separate job sends that PR's link to Slack. Runs with no verified changes send no notification. You can read skipped
findings in the PR body and noop reasons in the workflow run's summary.
Runs remain serial, with up to 100 pending runs in the concurrency group; GitHub cancels additional runs once the queue is
full. See [GitHub Actions concurrency].

One manual [workflow run 38748564180](https://github.com/pydantic/genai-prices/actions/runs/38748564180) on
`codex/price-check-coverage-runtime` on 2026-10-15 took 89m30s. Its telemetry recorded 1,004 model API
request spans, including 620 HTTP 429 responses and two HTTP 502 responses, alongside 34 research-task launches and a peak
of 17 active tasks. Price Check uses `Coder(sub_agents=False)` to keep research in one execution context.
This historical measurement describes one Claude Code run and does not predict CLAI 2 runtime.

See [performance measurements and implementation plan](AGENTIC_PRICE_CHECK_PERFORMANCE.md) for historical measurements,
current-engine accounting, and exact-source coverage. Historical Claude runs are not a baseline for the current engine.

## Configuration

| Variable or secret             | Purpose                                                                                             |
| ------------------------------ | --------------------------------------------------------------------------------------------------- |
| `AGENTIC_WORKFLOWS_ENABLED`    | Set this repository variable to `true` to enable the checks.                                        |
| `ZAI_API_KEY`                  | Repository secret held by the API proxy for GLM-5.3-Flash through Z.ai's Anthropic-compatible API.  |
| `PRICE_UPDATE_APP_CLIENT_ID`   | Repository variable containing the GenAI Prices Automation App's client ID: `Iv23libntR0K6oyQrZWX`. |
| `PRICE_UPDATE_APP_PRIVATE_KEY` | Repository secret containing the App's complete PEM private key.                                    |
| `SLACK_WEBHOOK_URL`            | Slack incoming-webhook URL for the channel that should receive price-update PR links.               |
| `LOGFIRE_OTLP_AUTHORIZATION`   | Repository secret containing the complete `Bearer …` authorization value for Logfire.               |

You choose the Slack channel when you create the incoming webhook. Store its URL as a secret, never in a workflow or prompt.
The notification job uses the `price-updates` GitHub environment. You can restrict that environment to your default branch
and store the webhook secret there instead of at repository scope. The job fails if the secret is missing or Slack rejects
the request. It does not undo a successfully created PR.

The workflow imports the public [Pydantic AI engine] and runs CLAI 2 with harness version `0.56.0`.
`engine.model: anthropic/glm-5.3-flash` selects the Anthropic Messages protocol. The engine removes the
`anthropic/` routing prefix before sending the model ID upstream. gh-aw configures the API proxy to forward
`/v1/messages` to `https://api.z.ai/api/anthropic/v1/messages` and inject `ZAI_API_KEY` as `x-api-key`.
The sandbox receives a placeholder key; the provider secret remains in the proxy.
See Z.ai's [model documentation][zai-model] and [endpoint guide][zai-api].

`PAI_AGENT: scripts.price_check_agent:agent` selects the workflow's tool composition. It binds gh-aw's published
proxy-aware fetcher as `web_fetch`, adds Coder's filesystem and shell tools, and disables delegation. The shell retains proxy,
toolchain, and Git identity settings while excluding provider credential variables. The public engine supplies
the launcher, MCP composition, session recorder, and model routing. The pinned proxy retains its 500-request
limit; there is no workflow output-token cap.
This custom engine does not enforce gh-aw's `tools.bash` patterns. Coder supplies the shell; AWF controls network access,
and the trusted safe-output handler enforces the proposed file scope.

The fetcher permits only HTTPS origins from the provider manifest, rejects credentials and non-public DNS results,
and repeats these checks on every redirect. It delegates final DNS and routing to AWF's required proxy; there is no
direct-network fallback. TLS certificate verification remains enabled. Fetch results include pagination metadata;
use `start_index` to continue truncated content. Pydantic AI's default local fetcher pins an IP in CONNECT, which
AWF deliberately denies; trusting the proxy's rejection certificate would not fix the denied request.

The manifest origins are snapshotted before model execution as trusted operator configuration. The DNS preflight is defense in depth: Squid resolves the
hostname independently, so it does not pin the proxy's final destination IP or prevent resolver divergence/rebinding.
The tool's destination boundary is the exact official-origin allowlist plus verified HTTPS, rather than arbitrary-URL
fetching. Keep that allowlist on redirects; supporting untrusted origins requires destination-IP enforcement at the proxy.

`shared/price-check-engine.md` holds routing configuration and an explicit package pin. Import that file before
the public definition. gh-aw v0.91.1 validates root environment secrets before loading imported engine metadata,
and does not inherit the public version into this configuration. Keep the model preference in the source workflow.
Keep `excluded-env` in the routing import too: this engine ignores the root field in v0.91.1.

### Logfire telemetry

After the agent exits, a trusted step exports API-proxy request spans, an agent span and canonical gh-aw usage to the dedicated
[genai-prices Logfire project](https://logfire-eu.pydantic.info/logfire/genai-prices).
`LOGFIRE_OTLP_AUTHORIZATION` supplies the project's write credential. MCP access is a separate authorization:
grant the Logfire MCP connection access to `logfire/genai-prices` before querying these runs.
Pass the fully qualified `project: logfire/genai-prices` to MCP queries. The unqualified name can be rejected even when
the error lists that name as available. Run `codex mcp login logfire` if authorization still targets another project.
The credential exists only in the export step, outside the agent sandbox. The pinned compiler's native OTLP configuration
would expose exporter headers through its agent environment, so this workflow does not use that configuration.
Export failures appear in the run summary and export step without blocking independently validated price updates.

Filter telemetry by `gh-aw.repository = pydantic/genai-prices` and the exact `gh-aw.run.id`.
Check both span attributes and resource attributes because components can put run identifiers in either place.
Confirm a run's request spans arrive before treating export configuration as verified.
The separate `price_check.usage` span records cumulative `agent_usage.json` components under
`price_check.usage.uncached_input`, `cached_input`, `cache_creation` and `output`, labelled with
`price_check.usage.source = gh-aw.agent_usage`. Do not add that rollup to individual proxy counts.
Historical proxy versions reported zero input/cache counts; those zeros do not establish zero consumption.
If canonical usage is missing or invalid, the exporter keeps real request, agent and coverage spans and omits
`price_check.usage`. The agent span's `price_check.usage.status` and telemetry artifact's `usage_status` explain availability;
`usage_source` is null and `model_usage` is empty when unavailable. No zero token counts are inferred from missing data.
The `invoke_agent` span records canonical tool execution counts and `price_check.terminal_output_emitted`.
That field means the agent emitted a terminal item; check the separate `safe_outputs` job for acceptance or rejection.
Coder's CodeMode calls appear as `run_code`. The canonical session contains each call's code and returned output;
nested tool responses that the code does not return are not recorded separately.
The `agent` artifact includes `mcp-logs/price-check-telemetry.json` with the compact per-run accounting and tool counts, so future
investigations can start there without processing the full transcript. Dollar fields remain client estimates.

### Weekly coverage results

Each weekly run publishes `coverage.json` in the `price-check-coverage` Actions artifact and a compact provider table in
the run summary, including failed and incomplete checks. Preflight snapshots the manifest's exact required URLs and the
selected rollout backlog before research. Outside-manifest backlog providers use the existing trusted source selection.
Discovery requests remain explicit scopes; they do not expand the ordinary provider sweep.

`web_fetch` records actual attempt starts and completions automatically. The ledger includes failures, interrupted attempts,
requested offsets, returned ranges, total lengths, truncation and duration. Arbitrary follow-up URLs and exception text
are omitted. A required source is `retrieved` only when successful nonempty ranges cover the whole response without gaps
and agree on total length. Retries remain visible. Follow-up fetches never substitute for a missing exact required URL.
Pages can change between requests; range coverage does not establish a stable source snapshot.

Provider results are separately labelled as agent-reported. Each result assesses source readability, comparison status,
selected backlog pairs, and counts of price changes, new models, potential removals, unchecked fields and deferred changes.
A provider with planned URLs is complete only with full retrieval, readable source assessments, checked comparisons and
no unchecked or deferred findings. The `_discovery` scope has no fixed source list; its completion requires checked
selected backlog results and no unchecked or deferred findings. Missing provider, source or backlog results remain explicit;
HTTP success cannot establish verification.
These files provide observability, not a security attestation: the agent controls its execution and can alter its workspace.
The trusted post-agent summarizer reads bounded regular files and publishes only the defined metadata fields.
The separate `model-price-check-report` artifact and rollout callbacks retain their existing contract.

The existing trusted Logfire exporter adds `price_check.coverage` and one `price_check.provider_result` span per expected
provider to the same run trace. The coverage span contains totals and missing/invalid input states. Provider spans include
retrieval, agent-reported semantic status, compact source coverage, findings counts and selected backlog results.
No response page content or additional credential enters these spans. Coverage export failure preserves usage export.

[GenAI Prices Automation](https://github.com/apps/genai-prices-automation), App ID `1641661`, must be installed on
`pydantic/genai-prices` with **Contents: read/write** and **Pull requests: read/write**. You can generate a private key in
[the App's settings](https://github.com/organizations/pydantic/settings/apps/genai-prices-automation) under **Private keys**.
Store the complete downloaded PEM file as `PRICE_UPDATE_APP_PRIVATE_KEY`; never commit it or paste it into chat.

The permission-controlled `safe_outputs` job mints an installation token scoped only to `genai-prices`. Each run gets a
fresh short-lived token, which is revoked when the job finishes. App-created PRs trigger the repository's normal CI without
a personal access token. `PRICE_UPDATE_TOKEN` is no longer used. The agent's GitHub permissions remain read-only, and the
App private key is never passed to the agent. Slack credentials are passed only to `.github/workflows/price-update-slack.yml`.

### Slack notifications

Slack receives a message only after the workflow creates a ready-for-review PR. The message contains that PR's actual URL.
Skipped runs, clean checks, runs with only unverified findings, failed builds or tests, and authentication failures send no
Slack message. A created PR can include both verified updates and a list of skipped findings.
You can inspect failures and noop reasons in Actions. The App generates fresh short-lived tokens automatically, so there is
no personal-token expiry to monitor.

## Coverage

The weekly workflow is `.github/workflows/agentic-price-check.md`. [Genie Pricer](GENIE_PRICER.md) provides a separate targeted Slack entrypoint. It covers OpenAI, OpenAI Decisions, Anthropic, Google
(Gemini), Mistral, DeepSeek, xAI, Groq, Cerebras, MiniMax, MoonshotAI, Avian, Perplexity, Cohere, Voyage AI, Cloudflare
Workers AI, Cursor, Arcee, Baseten, GitHub Copilot, Databricks, TypeSafe, Z.AI, Meta, and Modal.

You define each provider's scope, official URLs, and pricing mappings in `.github/agentic-price-check-providers.yml`.
Each run reads that manifest once, completes research provider by provider, and starts one full validation pass after edits
and diff review are complete. Each official response is reused for the in-scope models it covers.
The workflow creates at most one PR per run. It skips while any PR authored by `app/genai-prices-automation` remains open,
including proposals from the previous three workflows. Renaming a PR does not bypass this guard. Merge or close those
proposals to resume checks. The workflow does not merge PRs, force-push branches, or close older proposals.

These checks complement `make check-for-price-discrepancies`, which uses aggregators such as LiteLLM and OpenRouter.

## Update safeguards

The workflow prompt and shared instructions in `.github/workflows/shared/price-update.md` require the agent to:

- Check existing canonical IDs and match rules before adding models. Do not add aliases as separate models.
- Compare all registry units and published tiers, resolving the last matching conditional record for each usage scope.
  Ignore shadowed historical rates and insert dated updates before later scope overrides and scheduled future rates.
  Do not guess missing prices or effective dates.
- Preserve historical prices. Insert dated conditional records for real rate changes; correct values in place only with
  evidence that the recorded price was already wrong. Defer changes with unverified timing or correction evidence.
  Test requests before and on each effective date in Python, JavaScript, and Go.
- Edit only the workflow's provider YAML. Regenerate artifacts with `make build`, never by hand.
- Run `make lint`, `make typecheck`, `make lint-go`, `make test`, `npm run ci`, and `make test-go` before proposing a PR.
  Update affected regression expectations in all three languages without weakening assertions.
- Leave frozen v1 data, the unit registry, and published v2 schemas unchanged.
- Include official source URLs, unit conversions, validation results, unchecked findings, and the AI disclaimer in the PR body.

The safe-output file allowlist permits only the covered providers, generated v2 and bundled data, the provider inventory, and
price regression assertions. It blocks code, dependencies, workflows, agent instructions, and registry changes. There is no
fallback issue when PR creation fails. Its existing 10 MiB patch limit accommodates the generated full-data snapshot.
Failures remain visible in Actions; Slack is reserved for created PRs.

The preflight snapshots the same allowlist and initial source SHA before agent execution. It reuses gh-aw's file-policy
validator and runs before commits, from AWF's read-only mounted directory. The agent also checks scope before validation.
The allowlist includes the existing `tests/test_price_check_additions.py` regression file. Candidates requiring other
regression files outside the allowlist are deferred. The trusted safe-output handler remains
the final scope gate; the preflight gives the agent feedback while it can still correct the proposal.

Unreadable sources, ambiguous mappings, missing fields, and potential removals are not safe edits. They appear in a PR's
skipped-findings section if another change can be verified, or in the noop summary otherwise. A partial check is not reported
as clean. A missing model on a pricing page is never enough evidence to remove it.

## Edit and compile

```bash
gh extension install github/gh-aw --pin v0.91.1
gh aw compile --no-check-update agentic-price-check agentic-model-price-check
```

The `.md` files are source. The `.lock.yml` files are compiled output. Never edit a lock file by hand. Compile this
pair with gh-aw v0.91.1; unrelated workflows can use a different compiler version.

The public engine requires gh-aw v0.91.1 or newer for canonical sessions and schema-valid merged usage.
This workflow pins v0.91.1 and firewall 0.28.31. Keep `max-ai-credits: -1` and `max-daily-ai-credits: -1`:
the compiler omits the configurable per-run credit budget and disables token steering. AWF still enforces
its fixed, non-configurable 10,000-credit ceiling. A custom upstream also disables
model fallback, preserving `glm-5.3-flash`.

`models.default-ai-credits-pricing` supplies fallback accounting in USD per million tokens, avoiding
`unknown_model_ai_credits` for an unrecognized model. Catalog pricing takes precedence over this fallback.
`models.providers.anthropic` supplies an accounting
overlay in USD per token, used for reporting and credit enforcement before catalog/fallback pricing for this provider.
Both use Z.ai's [published API rates][zai-pricing],
checked on 2026-10-15.
These are API-equivalent accounting figures, not Coding Plan charges or quota measurements. Threat detection
remains disabled under the existing safe-output policy.

### Verify a branch run

```bash
gh workflow run agentic-price-check.lock.yml --ref YOUR_BRANCH
```

Check that the `agent` job executed; a successful `pre_activation` followed by skipped jobs is not an engine test.
An open Automation App PR still triggers the production skip guard on manual runs.
Inspect the `agent` artifact's `agent-session.jsonl` for model, tool calls/results, and the terminal result.
Inspect `usage/aw_session.jsonl` and the API-proxy audit for reported usage and upstream request outcomes.
Confirm that safe outputs processed a real noop or created a PR. A noop must skip `notify_slack`;
a created PR must pass its actual URL to the unchanged Slack workflow. Preserve run URLs and source SHAs
when recording verification.

Download `price-check-coverage` and compare every expected provider and source against the run summary and correlated
Logfire coverage/provider spans. Missing reports and unreadable sources are incomplete research, even when the job succeeds.
Use `agent_usage.json` or `mcp-logs/price-check-telemetry.json` for all four canonical usage components. Preserve the run URL,
attempt, source SHA, model and engine version with each measurement. Do not infer a speed improvement from one run.

The [2026-10-17 verification attempt](https://github.com/pydantic/genai-prices/actions/runs/39051923357) reached the agent but
Z.ai rejected every model-message attempt with quota exhaustion. Its coverage artifact records all providers as incomplete;
token usage is unavailable. See the [attempt record and limitations](AGENTIC_PRICE_CHECK_PERFORMANCE.md#current-engine-startup-attempt).
This verifies incomplete-run reporting, not a successful research baseline. Restore provider quota before another model run.

The trusted host exporter described above uses service `gh-aw.agentic-price-check`, with the Actions run identity.
Native in-process model/tool export is deliberately disabled; exporter variables are excluded from the agent container.
The canonical session and usage artifacts remain available without an exporter. Missing Logfire rows or zero-valued
provider usage fields do not prove zero consumption. Compare only runs that reached the agent, and distinguish
reported tokens from Coding Plan quota consumption.

To add a provider to the ordinary weekly sweep, update `.github/agentic-price-check-providers.yml`, update the shared network policy if needed, and
add its YAML path to `create-pull-request.allowed-files` in both `agentic-price-check.md` and
`agentic-model-price-check.md`. Then recompile both workflows.

## Source limitations

`web-fetch` does not execute JavaScript. A pricing page rendered entirely in JavaScript can appear empty. Point the workflow
at an official static documentation page when one exists. Never replace an unreadable official source with cached snippets,
aggregator prices, or remembered values.

[gh-aw schedule syntax]: https://github.com/github/gh-aw/blob/main/docs/src/content/docs/reference/schedule-syntax.md
[GitHub Actions schedule syntax]: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule
[GitHub Actions concurrency]: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
[Pydantic AI engine]: https://github.com/pydantic/pydantic-ai/blob/main/src/pydantic_ai_harness/gh-aw/pydantic.md
[zai-model]: https://docs.z.ai/guides/vlm/glm-5.3-flash
[zai-api]: https://docs.z.ai/devpack/latest-model
[zai-pricing]: https://docs.z.ai/guides/overview/pricing
