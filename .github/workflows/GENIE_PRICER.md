# Genie Pricer

Mention `@genie-pricer add prices for the new <model>` in `#project-genai-prices`.
An optional HTTPS announcement link can follow the model name. Request one model per message.
The bot replies in that message's thread and updates the reply with the Actions run and final result.

The dedicated Slack app is separate from existing price-update notifications. Its manifest is
[`../slack/genie-pricer.manifest.json`](../slack/genie-pricer.manifest.json).
The receiver runs in the existing Pydantic Work Team Worker; its setup lives in `team-app/GENIE_PRICER.md` there.

## Targeted runs

The receiver verifies Slack's raw-body signature, timestamp, app, workspace, channel, and configured users.
It persists the request before acknowledging Slack. Repeated delivery and active requests for the same normalized model
reuse the existing request. The receiver makes no model call.

A scoped Pydanty App token sends `genie-pricer-model-request` through GitHub `repository_dispatch`.
Only an opaque request ID, model name, and optional source link enter the GitHub event.
`agentic-model-price-check.md` allowlists Pydanty and atomically claims the request before its agent job.
The OIDC-authenticated claim returns the stored request. Duplicate dispatches cannot enter a second agent job for that claim.

The agent uses the same CLAI 2 engine and GLM route as the weekly check. It follows `/add-price-model`, checks confirmed
hosting providers, and limits edits to that model, aliases, necessary generated data, and pricing regressions.
The source snapshot includes every existing provider file, including AWS, Azure, and OpenRouter.
The fetcher retains HTTPS, proxy, DNS, redirect, and exact-host checks. Its firewall policy lives in
`shared/price-check-network.md`; source changes need corresponding policy updates.

The agent runs the full shared validation sequence and submits one PR through safe outputs. It cannot merge.
A trusted job reports the handler's actual PR URL or the no-change/failure outcome. Slack secrets and OIDC tokens stay
outside the agent. The skill's local push commands do not apply inside gh-aw. A probe without a supplied credential leaves
undocumented aliases unchanged and reports missing verification; verified provider prices can still be added.

## Delayed provider rollouts

The agent writes `/tmp/gh-aw/agent/model-check-report.json`, uploaded as the dedicated
`model-price-check-report` artifact, listing plausible hosts whose requested model
or price is not yet verifiable. The trusted callback validates and stores those pending pairs. A missing or malformed
report retains a model-discovery backlog entry and is reported as incomplete.

The existing Monday 06:00 UTC workflow reads the backlog through an OIDC-authenticated job and checks those model/provider
pairs in the same invocation as its ordinary sweep. Each run selects at most ten whole requests within a 64 KiB
backlog output, rotating by workflow run number; omitted requests stay pending. It adds no schedule and does not sweep unrelated models at backlog
providers. The copied preflight policy permits the weekly manifest and selected backlog providers; an incomplete
provider-discovery request permits existing providers for that requested model. An absent listing or missing price keeps a pair pending.
The trusted publisher independently checks the downloaded Git transports against that same provider policy before
creating a PR, including actual changed paths from bundles and patches.

A weekly report associates newly verified pairs with the created PR; those pairs clear after that PR merges.
An explicitly verified listing already present on main can clear its own pair. Closing a proposal without merging
returns its pairs to the backlog. Missing reports never erase the backlog.

## Deployment and checks

Deploy the Team Worker and apply its D1 migration before merging these workflow changes. Configure the new Slack app and
its Worker secrets, then enable `app_mention` after the targeted lockfile exists on main. The previous notifier stays intact.

Compile both sources with gh-aw `v0.91.1`. The new entrypoint uses the existing Z.ai, safe-output App, and trusted Logfire
secrets with the same boundaries. Callback jobs separately request job-scoped OIDC tokens.
Run workflow contract tests, source/bridge/transport/scope tests, the pinned agent-composition check, and repository checks.

Compilation and mocked tests do not establish live Slack delivery or Actions activation. After merge and deployment,
verify a controlled request's real claim, run correlation, and thread result. Per-run tokens do not establish shared-account
plan usage or quota savings.
