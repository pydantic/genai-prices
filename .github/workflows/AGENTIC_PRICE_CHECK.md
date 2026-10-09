# Agentic price-update workflow

```bash
gh secret set FIREWORKS_API_KEY
gh variable set PRICE_UPDATE_APP_CLIENT_ID --body Iv23libntR0K6oyQrZWX
gh secret set PRICE_UPDATE_APP_PRIVATE_KEY < /path/to/genai-prices-automation.private-key.pem
gh secret set SLACK_WEBHOOK_URL
gh variable set AGENTIC_WORKFLOWS_ENABLED --body true
gh workflow run agentic-price-check.lock.yml
```

This [gh-aw](https://github.com/github/gh-aw) workflow checks all twenty covered providers **daily** and on manual
dispatch. It combines verified new models and rate changes into one ready-for-review PR titled `Update provider prices`.
A separate job sends that PR's link to Slack. Runs with no verified changes send no notification. You can read skipped
findings in the PR body and noop reasons in the workflow run's summary.

## Configuration

| Variable or secret             | Purpose                                                                                             |
| ------------------------------ | --------------------------------------------------------------------------------------------------- |
| `AGENTIC_WORKFLOWS_ENABLED`    | Set this repository variable to `true` to enable the checks.                                        |
| `FIREWORKS_API_KEY`            | Repository secret for Claude Code through Fireworks using `minimax-m3`.                             |
| `PRICE_UPDATE_APP_CLIENT_ID`   | Repository variable containing the GenAI Prices Automation App's client ID: `Iv23libntR0K6oyQrZWX`. |
| `PRICE_UPDATE_APP_PRIVATE_KEY` | Repository secret containing the App's complete PEM private key.                                    |
| `SLACK_WEBHOOK_URL`            | Slack incoming-webhook URL for the channel that should receive price-update PR links.               |

You choose the Slack channel when you create the incoming webhook. Store its URL as a secret, never in a workflow or prompt.
The notification job uses the `price-updates` GitHub environment. You can restrict that environment to your default branch
and store the webhook secret there instead of at repository scope. The job fails if the secret is missing or Slack rejects
the request. It does not undo a successfully created PR.

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

The single workflow is `.github/workflows/agentic-price-check.md`. It covers OpenAI, Anthropic, Google (Gemini), Mistral,
DeepSeek, xAI, Groq, Cerebras, MiniMax, MoonshotAI, Avian, Perplexity, Cohere, Voyage AI, Cloudflare Workers AI, Cursor,
Arcee, Baseten, GitHub Copilot, and Databricks.

You define each provider's scope, official URLs, and pricing mappings in `.github/agentic-price-check-providers.yml`.
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
fallback issue when PR creation fails. Failures remain visible in Actions; Slack is reserved for created PRs.

Unreadable sources, ambiguous mappings, missing fields, and potential removals are not safe edits. They appear in a PR's
skipped-findings section if another change can be verified, or in the noop summary otherwise. A partial check is not reported
as clean. A missing model on a pricing page is never enough evidence to remove it.

## Edit and compile

```bash
gh extension install github/gh-aw --pin v0.82.2
gh aw compile --no-check-update agentic-price-check
```

The `.md` files are source. The `.lock.yml` files are compiled output. Never edit a lock file by hand. Compile this
workflow with the pinned version; other workflows can use a different compiler version.

**Keep gh-aw v0.82.2 and `max-ai-credits: -1` / `max-daily-ai-credits: -1`.** The Fireworks `minimax-m3` model is not in gh-aw's
pricing catalog. Its API proxy otherwise rejects requests with `HTTP 400 unknown_model_ai_credits`. The firewall pinned by
v0.82.2, version 0.27.22, drops the credit cap when it is `-1`. Newer firewalls no longer drop it. Both the compiler pin and
these credit settings are required until gh-aw adds the model to its catalog.

To use Anthropic directly, edit the workflow's `engine:` block. Set `ANTHROPIC_API_KEY` to your Anthropic secret and remove
`api-target`, `ANTHROPIC_BASE_URL`, and the `ANTHROPIC_MODEL` / `ANTHROPIC_DEFAULT_*_MODEL` overrides. Then recompile.
You can re-enable threat detection with a model that gh-aw prices; it is disabled for Minimax because its separate detection
credit guardrail cannot accept the unpriced model.

To add a provider, update `.github/agentic-price-check-providers.yml`, add its source domains to `network.allowed`, and
add its YAML path to `create-pull-request.allowed-files`. Then recompile.

## Source limitations

`web-fetch` does not execute JavaScript. A pricing page rendered entirely in JavaScript can appear empty. Point the workflow
at an official static documentation page when one exists. Never replace an unreadable official source with cached snippets,
aggregator prices, or remembered values.
