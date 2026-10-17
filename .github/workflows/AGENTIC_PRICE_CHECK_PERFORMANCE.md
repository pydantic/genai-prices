# Price check performance and follow-up plan

The weekly check runs Monday at 06:00 UTC (Sunday evening in Los Angeles), with manual dispatch available.
It uses Pydantic AI harness `0.56.0`, `anthropic/glm-5.3-flash`, and `Coder(sub_agents=False)`.
One sequential invocation checks the 25-provider manifest plus the selected requested-model rollout backlog.
Exact-source retrieval coverage and agent-reported comparison results now accompany runtime and token accounting.
No persistent evidence cache, provider concurrency, provider cadence tiers or engine change is part of this implementation.

## Current-engine startup attempt

The [2026-10-17 attempt](https://github.com/pydantic/genai-prices/actions/runs/39051923357) stopped before research because
Z.ai returned `Weekly/Monthly Limit Exhausted` (code 1310). The [machine-readable record](../price-check/benchmark-2026-10-17.json)
preserves its implementation and verification SHAs, test controls, counters and limitations.
One catalog request succeeded; all three model-message attempts returned HTTP 429. No model-message request succeeded.
Canonical token usage was absent and remains unavailable, rather than zero.

The agent job took 212 seconds and the whole workflow took 306 seconds. These are startup-failure timings, not a successful
research baseline or a speed comparison. The coverage artifact retained every expected provider and source: 25 providers,
37 exact URLs, no fetch attempts, and no complete providers. Ledger and semantic-result inputs were correctly marked missing.
Backlog retrieval fell back to an empty selection because the receiver was unavailable; this attempt does not verify rollout
backlog selection or callbacks. Its test ref removed the open-PR skip guard, staged safe outputs and disabled the callback.

The live telemetry exporter stopped on the missing canonical usage file. The exporter now retains actual failure/request
and coverage spans when usage is unavailable, without a usage span or invented token totals. An offline replay of the
captured data preserved the coverage counters and produced failure, coverage and provider spans without sending telemetry.
A new live run must verify the corrected exporter and establish a successful current-engine research baseline after quota
is restored.

## Historical Claude measurements

The [machine-readable measurements](../price-check/benchmark-2026-10-15.json) preserve the compact baseline independently
of Actions artifact retention. Raw transcripts remain in Actions artifacts; credentials and raw transcripts do not belong
in this repository.

| Measurement                     | [First 25-provider attempt][first-run] | [Successful follow-up][second-run] |
| ------------------------------- | -------------------------------------: | ---------------------------------: |
| Agent job                       |                                 89m30s |                             51m55s |
| Uncached input tokens           |                              2,617,858 |                            513,319 |
| Cached input reads              |                             37,988,032 |                         31,472,320 |
| Output tokens                   |                                580,912 |                            126,439 |
| Successful model requests       |                                    374 |                                180 |
| HTTP 429 responses              |                                    620 |                                  0 |
| Explicit research-task launches |                                     34 |                                  0 |
| WebFetch calls                  |                                    106 |                                 39 |

The follow-up ran source commit `614ae71063305ef9b79ecefc4d45531c16d3f060`. It differs from production commit
`94d27b8eafdeaddfeaef36fe290c468532fcdd4e` only in its literal test PR base and the compiled workflow.
It produced PR #793. These measurements describe execution, not the correctness of every proposed data change.

The first run reached 17 simultaneous research tasks. The follow-up disabled Claude's `Agent` and legacy `Task` tools.
This comparison shows reduced runtime and rate-limit pressure; it does not isolate causation or establish that one agent
is optimal. Neither run measures an unchanged steady state.

### Historical accounting method

Download the `agent` artifact for the exact run, before its retention period expires:

```bash
gh run download 38768031115 --repo pydantic/genai-prices --name agent --dir price-check-artifact
```

`agent-stdio.log` mixes debug text and JSON records. Read complete JSON lines with `type: result` and use the last
cumulative `modelUsage` object for each CLI session. Do not add repeated cumulative objects. In the first run, four result
events repeat the same cumulative object. If an invocation resumes or resets a session, establish its accounting scope
before combining results.

`modelUsage` covers more calls than the result's top-level `usage`. In the follow-up, top-level output was 72,073 while
`modelUsage` output was 126,439. The archive does not establish the internal reason for that difference.
The API proxy's 180 unique successful `/v1/messages` request IDs independently sum to 126,439 output tokens.
Deduplicate proxy records by request ID. `usage/agent/token_usage.jsonl` is a duplicate of the agent's proxy usage file;
never sum both copies.

The proxy reports zero input and cache counts for this endpoint. Use the CLI's per-model input and cache fields; do not
interpret proxy zeros as zero consumption. Keep cached reads separate from uncached input. Client `costUSD` estimates
are not authoritative provider billing. See [Claude usage accounting][usage-docs].

Logfire MCP was authenticated during the investigation, but scoped to `logfire/pydantic-ai`. No matching run was found
in that accessible project. The measurements above came from Actions archives, not Logfire queries.

## Trace findings

- The manifest requires 37 source URLs. The follow-up fetched 37 unique URLs, but missed the required Moonshot
  `chat-k27-code.md` and `chat-k26.md` URLs. A count alone cannot establish coverage.
- The 39 fetch calls contain only two repeated URLs: a truncated/unreadable Vertex retry and a targeted Voyage follow-up.
  Cross-run reuse offers more remaining savings than removing duplicate fetches in this run.
- Model-matching investigation repeated source searches around Gemini TTS. A tool exposing existing matching behavior
  can resolve aliases and collisions without asking an agent to rediscover engine semantics.
- Validation started three times. The first two attempts stopped during build: an environment/import failure and unsorted
  Baseten model IDs. Only the final attempt ran the complete validation chain successfully.
- Eight sleep/tail polling commands created extra model roundtrips while waiting for real validation. Process supervision
  can remove those roundtrips, but cannot remove the underlying test runtime.

## Implementation stages

### 1. Measure the current engine

Export agent and request spans to the dedicated `logfire/genai-prices` project. Grant MCP access to the same project.
Correlate repository, run ID, attempt and commit; add provider and phase when the provider execution boundary exists.
Export canonical gh-aw accounting separately from proxy counters.
Record tool names, duration, coverage, retries and validation outcomes alongside token usage.

The trusted post-agent step exports proxy spans, canonical `agent_usage.json` totals and tool-use counts.
The Logfire credential remains scoped only to that step. Query MCP with `project: logfire/genai-prices`.
The `price_check.usage` span labels the accounting source `gh-aw.agent_usage` and retains uncached input, cache reads,
cache writes and output separately. Do not add these totals to proxy usage or substitute historical Claude `modelUsage`.

For current runs, start with `mcp-logs/price-check-telemetry.json` inside the `agent` artifact,
the separate `price-check-coverage` artifact, and the correlated `price_check.usage` and `price_check.coverage` spans.
For the archived follow-up, pass `start_timestamp: 2026-10-15T16:15:00Z` and
`end_timestamp: 2026-10-15T17:20:00Z` to MCP. Its default recent window will not find this historical run.

```sql
SELECT attributes->>'gen_ai.request.model' AS model,
       attributes->>'price_check.usage.uncached_input' AS uncached_input,
       attributes->>'price_check.usage.cached_input' AS cached_input,
       attributes->>'price_check.usage.cache_creation' AS cache_creation,
       attributes->>'price_check.usage.output' AS output
FROM records
WHERE span_name = 'price_check.usage'
  AND otel_resource_attributes->>'gh-aw.run.id' = '38768031115'
LIMIT 10
```

Acceptance: query an exact run through MCP, recover its request count and complete token components, and locate failed
tools or phases without downloading the whole transcript. Missing export must be visible in the run summary.

### 2. Record exact-source coverage and provider results

The preflight snapshots the canonical weekly manifest's exact URLs and the selected backlog provider scopes.
The fetch wrapper records starts, failures, returned ranges, truncation and duration without page contents.
A trusted bounded reader reconciles every expected provider and exact URL, even when the agent stops before reporting.
Transport retrieval and agent-reported readability/comparison status remain separate. Missing results, gaps in pagination,
inconsistent response lengths and unresolved backlog comparisons cannot produce a complete provider result.
See the [coverage contract](AGENTIC_PRICE_CHECK.md#weekly-coverage-results) for artifact fields and interpretation.

Acceptance: a current-engine workflow run produces the coverage artifact and summary. Logfire readback for that exact
run recovers coverage totals, every provider result, request spans and all four canonical usage components. Record source
SHA and any test-ref-only activation or publication differences. This establishes a baseline, not a claimed speedup.

### 3. Future deterministic comparisons

Feed existing pure parsers for Arcee, Cloudflare, Cursor and Baseten into typed evidence records. Include canonical IDs,
aliases, each price key and tier, units, scope, effective-date evidence and source URL. Reuse Decimal conversions and
the existing matching/pricing logic. Report collisions and unsupported shapes explicitly.

Do not invoke importer writers blindly. Their update policy can date a change at the run date; a verified price effective
date is a separate requirement. Add shape and completeness checks where a parser can skip malformed rows.

Acceptance: omissions, malformed source rows, wrong units and alias collisions produce explicit findings. Readable
unchanged fixtures yield no candidates. Existing historical prices and scoped overrides remain intact.

Persistent evidence reuse and bounded provider execution require separate design and measured comparisons against the
current sequential engine. They must preserve historical-price evidence, explicit unresolved findings, one validation and
publication path, and the weekly schedule. No hourly or two-hour provider selector is configured.
Compare complete coverage and verified findings before interpreting duration or token differences as improvements.

[first-run]: https://github.com/pydantic/genai-prices/actions/runs/38748564180
[second-run]: https://github.com/pydantic/genai-prices/actions/runs/38768031115
[usage-docs]: https://code.claude.com/docs/en/agent-sdk/cost-tracking
