# Price check performance and follow-up plan

The weekly check runs Monday at 06:00 UTC (Sunday evening in Los Angeles), with manual dispatch available.
It uses Pydantic AI harness `0.56.0`, `anthropic/glm-5.3-flash`, and `Coder(sub_agents=False)`.
One sequential invocation checks the 25-provider manifest plus the selected requested-model rollout backlog.
Exact-source retrieval coverage and agent-reported comparison results now accompany runtime and token accounting.
No persistent evidence cache, provider concurrency, provider cadence tiers or engine change is part of this implementation.

## Current-engine verification

Two 2026-10-17 attempts stopped before research on distinct provider account errors. The
[machine-readable record](../price-check/benchmark-2026-10-17.json) preserves their implementation and verification SHAs,
test controls, counters and limitations.

| Attempt                                                                          | Provider rejection                                  | Agent job | Workflow | Live Logfire export                |
| -------------------------------------------------------------------------------- | --------------------------------------------------- | --------: | -------: | ---------------------------------- |
| [39051923357](https://github.com/pydantic/genai-prices/actions/runs/39051923357) | Quota exhausted, code 1310                          |     212 s |    306 s | Stopped on missing canonical usage |
| [39053454043](https://github.com/pydantic/genai-prices/actions/runs/39053454043) | Insufficient balance or resource package, code 1113 |     168 s |    262 s | Verified with usage unavailable    |

Each attempt made one successful catalog request and three HTTP 429 model-message attempts. No model-message request
succeeded. Canonical token usage was absent and remains unavailable, rather than zero. These are startup-failure timings;
neither attempt provides a successful research baseline or a speed comparison.

Both coverage artifacts retained every expected provider and source: 25 providers, 37 exact URLs, no fetch attempts and
no complete providers. Ledger and semantic-result inputs were correctly marked missing. Backlog retrieval fell back to an
empty selection because the receiver was unavailable. These attempts do not verify rollout backlog selection or callbacks.
Their test refs removed the open-PR skip guard, staged safe outputs and disabled the callback.

The first attempt's exporter stopped on missing canonical usage. The corrected exporter was then verified in the second
Actions run and through exact-run Logfire MCP readback: four real request spans, one agent span, one coverage span and
25 provider-result spans. `usage_status` is `missing`; no usage span or token totals were invented. Logfire coverage counters
match the artifact. These checks establish failure reporting.

A third attempt, [39054066763](https://github.com/pydantic/genai-prices/actions/runs/39054066763), reached research after
credential replacement. It was cancelled after 455 s of agent execution (532 s workflow) when report collection exposed
a filesystem boundary: CodeMode's scratch `/tmp` and environment cannot access the host reporting paths directly.
The host fetch ledger recorded four attempts and two retrieved sources; semantic results remained missing.
All 22 model-message requests succeeded. Canonical usage was 82,045 uncached input, 956,928 cache-read input,
zero cache-write input and 4,914 output tokens; all four components were verified in correlated Logfire spans.
This interrupted integration sample is not a completed baseline.
Its test ref also removed the skip guard, staged safe outputs and disabled the rollout callback.
The selected backlog and callback were not live-verified.

Weekly reporting now reads the trusted plan and persists assessments through host-backed tools called from CodeMode.
A no-LLM test exercises the actual CLAI 0.56.0 composition, host persistence and rejection of an out-of-plan provider.

### Completed operational sample

[Run 39055754395](https://github.com/pydantic/genai-prices/actions/runs/39055754395) completed with a terminal noop.
It measured implementation `6d77abb3713e4e1afc00020b042b21c1d5e57799` through staged verification ref
`49dea8a5e92d0b9d0a53baf0dbe6f38ae1ba3c3f`. The agent job took 77m45s, its engine execution step 74m44s and the workflow 79m29s.

| Canonical token component |     Tokens |
| ------------------------- | ---------: |
| Uncached input            |  2,218,036 |
| Cache-read input          | 26,369,920 |
| Cache-write input         |          0 |
| Output                    |    143,240 |

All four components match the artifact, the 232 unique successful model-message usage records and Logfire readback.
The session's 28,587,956 input tokens include cached reads; subtracting 26,369,920 yields the uncached input above.
There were 234 unique API requests: one successful model-catalog request, 232 successful messages and one HTTP 502 message.
No HTTP 429 was observed.

Partitioning message requests by their start relative to the first full validation command at 18:53:38.192908 UTC gives:

| Phase                        | Message requests (successful) | Uncached input | Cache reads |  Output |
| ---------------------------- | ----------------------------: | -------------: | ----------: | ------: |
| Before first full validation |                     201 (200) |      1,023,890 |  22,407,744 | 128,880 |
| From first full validation   |                       32 (32) |      1,194,146 |   3,962,176 |  14,360 |

Cache writes were zero in both phases. The validation/reporting phase contains over half the reported uncached input;
this partition does not isolate retest cost, prove cache expiry or estimate runtime without validation.
Sixteen `run_code` starts contained both `time.sleep` and `tail`, the defined count for validation polling.

The durable report contains every expected provider: 10 of 25 complete, with semantic statuses 19 checked, two partial
and four missing (`cerebras`, `deepseek`, `minimax`, `typesafe`). The agent's final claim of 23 checked plus two partial
does not match the saved host records and is not the coverage result. An agent-reported checked status also remains
incomplete when sources, unchecked fields or deferred findings prevent completion.

Retrieval covered 36 of 37 required sources across 81 attempts, four failures and 13 follow-up attempts.
Thirteen attempts were unassigned; their URLs are not retained, so total distinct fetched URLs are unknown.
The sole partial source was Google's pricing page: reported lengths included 60,314, 64,634 and 77,897 characters.
The ledger's consistency guard kept retrieval partial even though the agent assessed the source as readable.
Fetch durations sum to 64.540s (overlap is possible), with a 1.948s maximum attempt.
This sum is not a wall-time breakdown. Archived session events show a longest inter-event gap of 311.595s;
the longest failed model request was the HTTP 502 at 287.886s. The live browser view omitted intervening events,
so its apparent quiet intervals were not reliable timing evidence.

Logfire trace `baa7e223c46af00c9e18f996fbfe3b7a` contains all 234 request spans, the usage/agent/coverage spans and
25 provider-result spans. All provider statuses, coverage totals and canonical usage components match the artifacts.
The selected rollout backlog fell back to empty; callbacks and Slack were skipped, and no pricing PR was created.

The host-bridge verification ref deliberately removes the skip guard, which conflicts with
`test_price_updates_create_pr_before_notifying_slack` in `tests/test_price_update_workflows.py`.
The live agent reproduced that failure on the pristine test ref and reran pytest with that test deselected.
Production head `6d77abb3` retains the guard and passed full validation and hosted CI.
The verification-only diagnosis and retest add elapsed time; this run cannot establish clean production validation
or a controlled performance comparison. The production guard and its test remain unchanged.
Real provider findings and variable latency also prevent a steady-state duration claim from this single sample.
The final prompt adds discovery-catalog and terminal-reconciliation instructions after the measured implementation;
that final prompt was not live-validated, and no additional model run was made.

The changing Google pagination lengths support investigating consistent per-run source snapshots as a follow-up.
Other observed work included rediscovering unit ancestry/model matching and polling background validation;
structured comparisons and validation supervision are separate follow-up opportunities.
Importer HTTP in the Simon Willison tests is mocked; repeated full-YAML parsing is a possible validation cost,
not evidence for the agent's network attribution. These observations do not add tools, caching or timeout changes here.

Local no-LLM diagnostics used harness/CLAI `0.56.0`, Pydantic AI `2.56.0`, Anthropic SDK `1.15.0` and HTTPX2 `2.13.1`.
These are locally resolved versions; the SDK version was not separately verified in the live job.
The provider's defaults were 5 s connect and 600 s read/write/pool timeouts, with two SDK retries.
A mocked pre-response timeout made three attempts. A loopback streaming check confirmed that read inactivity,
rather than total response duration, triggers the read timeout. These settings do not attribute any live quiet interval;
that requires the run's proxy timestamps. This PR does not change timeout settings.

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
