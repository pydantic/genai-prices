# Price check performance and follow-up plan

The 25-provider check still spends most of its work inside the model loop. The next changes should collect and compare
evidence in code, give provider agents only changed or unresolved work, and measure completeness alongside runtime.
The implementation stages below are proposals. The current workflow still runs one agent and checks every provider.

## Measured baseline

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

### Accounting method

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

### 1. Make each run observable and reproducible

Export agent and request spans to the dedicated `logfire/genai-prices` project. Grant MCP access to the same project.
Correlate repository, run ID, attempt and commit; add provider and phase when the provider execution boundary exists.
Export cumulative CLI accounting separately from proxy counters until input/cache reporting is reconciled.
Record tool names, duration, coverage, retries and validation outcomes alongside token usage.

The first follow-up exports recorded proxy spans, cumulative per-model CLI usage and tool-use counts in a trusted post-agent
step. The Logfire credential is scoped only to that step. A CLI smoke event and readback verified the dedicated instance's
`.info` ingestion endpoint. MCP readback works with `project: logfire/genai-prices` after `codex mcp login logfire`.
The unqualified `genai-prices` name is rejected despite appearing in the error's available-project list.
The actual exporter was replayed against the archived follow-up without new LLM calls. MCP recovered 188 request spans,
one agent span and one cumulative usage span. This validates export and readback; a future workflow run must still verify
the compiled step inside Actions. Provider phase spans and individual tool durations remain follow-up work.

For future runs, start with `agent/telemetry.json` inside the `agent` artifact or the `price_check.usage` span.
For the archived follow-up, pass `start_timestamp: 2026-10-15T16:15:00Z` and
`end_timestamp: 2026-10-15T17:20:00Z` to MCP. Its default recent window will not find this historical run.

```sql
SELECT attributes->>'gen_ai.request.model' AS model,
       attributes->>'price_check.usage.uncached_input' AS uncached_input,
       attributes->>'price_check.usage.cached_input' AS cached_input,
       attributes->>'price_check.usage.output' AS output
FROM records
WHERE span_name = 'price_check.usage'
  AND otel_resource_attributes->>'gh-aw.run.id' = '38768031115'
LIMIT 10
```

Acceptance: query an exact run through MCP, recover its request count and complete token components, and locate failed
tools or phases without downloading the whole transcript. Missing export must be visible in the run summary.

### 2. Fetch and compare evidence in code

Add a manifest-driven fetch ledger with per-source retrieval and readability status. Fetch shared URLs once per run.
Use a shared bounded HTTP pool and retry policy. A failed or partial source remains explicitly unresolved.

Feed existing pure parsers for Arcee, Cloudflare, Cursor and Baseten into typed evidence records. Include canonical IDs,
aliases, each price key and tier, units, scope, effective-date evidence and source URL. Reuse Decimal conversions and
the existing matching/pricing logic. Report collisions and unsupported shapes explicitly.

Do not invoke importer writers blindly. Their update policy can date a change at the run date; a verified price effective
date is a separate requirement. Add shape and completeness checks where a parser can skip malformed rows.

Acceptance: omissions, malformed source rows, wrong units and alias collisions produce explicit findings. Readable
unchanged fixtures yield no candidates. Existing historical prices and scoped overrides remain intact.

### 3. Bound provider agents and use one finisher

Dispatch one due provider per task with its compact evidence and ownership of only its provider YAML. Share downloaded
evidence. Return structured findings and a provider patch; prohibit nested delegation and shared-file edits.
Start an experiment with three concurrent provider tasks, enforced by the controller rather than prompt wording.
Measure concurrency one versus three against the same source snapshot and provider set.

The pinned Claude CLI is 2.1.198. The native configurable subagent concurrency/depth limits require 2.1.217 or later.
Verify a compatible CLI upgrade or enforce the provider-session pool outside the CLI before removing the current deny.
Do not rely on an environment variable unsupported by the installed CLI.

After provider tasks finish, one finisher combines their patches, checks coverage and evidence, builds generated files,
updates affected regression assertions, and runs the full validation sequence. Provider agents do not run full builds,
edit generated files, commit, or publish. A separate review examines the combined provider diff and evidence before
publication. The finisher retains explicit unresolved findings even when it can propose independent verified changes.

Add cheap environment/import and model-order preflight checks. The workflow already syncs dependencies, so diagnose
the environment lifecycle before adding another installation step. Supervise validation in code and return compact errors.

Acceptance: concurrency stays within the configured pool, only the finisher touches shared artifacts, every due provider
has a result, and comparison against the sequential baseline measures coverage, tokens, retries and latency together.

### 4. Reuse evidence and select providers by cadence

Persist verified evidence with HTTP validators/content hashes and manifest, YAML, unit-registry and parser versions.
Revalidate sources before reuse. Preserve unresolved/deferred findings and invalidate when a scheduled price takes effect.
An error page, empty parse or incomplete prior check cannot produce a clean unchanged result.
Skip model execution when due providers have complete, unchanged evidence and no unresolved work requiring judgment.

Proposed initial cadence, within the existing weekday America/Los_Angeles window:

| Provider group                          | Cadence         |
| --------------------------------------- | --------------- |
| OpenAI, Anthropic, Google, xAI and Meta | Hourly          |
| Other covered providers                 | Every two hours |

Treat OpenAI and OpenAI Decisions as one scheduling group while retaining separate coverage records.
Use explicit manifest cadence/priority fields and a deterministic due-provider selector. Record the last successful
verification, so failures do not postpone the next check or make a provider appear fresh. Provide a manual all-provider
override. Select due providers before any model work and retain one coordinated publication path.

Adjust tiers using observed usage and change frequency. Do not infer usage from provider nationality or company size.
Keep freshness requirements separate from evidence caching: an unchanged source still needs its due revalidation.

Acceptance: an unchanged verified fixture invokes no model, a changed or unresolved source reaches the relevant provider
task, cache invalidation covers data/parser/time changes, and hourly/two-hour selection is tested at scheduling boundaries.

Benchmark an unchanged run and a changed run after each stage. Compare complete provider coverage and correct findings
before interpreting lower duration or fewer tokens as an improvement. Grok/X discovery remains a separate experiment.

[first-run]: https://github.com/pydantic/genai-prices/actions/runs/38748564180
[second-run]: https://github.com/pydantic/genai-prices/actions/runs/38768031115
[usage-docs]: https://code.claude.com/docs/en/agent-sdk/cost-tracking
