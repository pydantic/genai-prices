---
pre-agent-steps:
  - name: Record the trusted price-check start time
    if: always()
    run: echo "PRICE_CHECK_JOB_STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$GITHUB_ENV"
post-steps:
  - name: Export price-check telemetry
    if: always()
    continue-on-error: true
    uses: actions/github-script@3a2844b7e9c422d3c10d287c895573f7108da1b3 # v9.0.0
    env:
      # Keep this credential scoped to the trusted step after the agent exits.
      OTEL_EXPORTER_OTLP_HEADERS: Authorization=${{ secrets.LOGFIRE_OTLP_AUTHORIZATION }}
      PRICE_CHECK_JOB_STATUS: ${{ job.status }}
    with:
      script: |
        const fs = require('node:fs');
        const path = require('node:path');
        const { createHash } = require('node:crypto');
        const { buildAttr, buildOTLPPayload, sendOTLPSpan } = require(
          path.join(process.env.RUNNER_TEMP, 'gh-aw/actions/send_otlp_span.cjs')
        );
        try {
          const diagnostics = [];
          const readRecords = (file) => {
            try { return fs.readFileSync(file, 'utf8').split('\n').flatMap((line) => {
              try {
                const record = JSON.parse(line);
                return record && typeof record === 'object' && !Array.isArray(record) ? [record] : [];
              } catch { return []; }
            }); } catch { return []; }
          };
          const readJson = (file) => {
            try { return JSON.parse(fs.readFileSync(file, 'utf8')); }
            catch { return undefined; }
          };
          const log = readRecords('/tmp/gh-aw/agent-session.jsonl');
          const usage = readJson('/tmp/gh-aw/agent_usage.json');
          const output = readJson('/tmp/gh-aw/agent_output.json') ?? {};
          const terminalEmitted = Array.isArray(output.items)
            && output.items.some((item) => ['noop', 'create_pull_request', 'report_incomplete', 'repair_staged'].includes(item.type));
          const sessionResult = log.find((record) => record.type === 'session.result');
          const sessionStatus = sessionResult?.data?.status;
          const cancelled = process.env.PRICE_CHECK_JOB_STATUS === 'cancelled';
          const agentOutcome = cancelled ? 'cancelled' : sessionStatus === 'success' ? 'success'
            : sessionStatus === 'error' || process.env.PRICE_CHECK_JOB_STATUS === 'failure' ? 'error' : 'unknown';
          if (agentOutcome === 'unknown') diagnostics.push('Agent outcome is missing.');
          const requests = [...new Map(readRecords(
            '/tmp/gh-aw/sandbox/firewall/logs/api-proxy-logs/otel.jsonl'
          ).map((record) => [record.spanId, record])).values()];
          if (!requests.length) diagnostics.push('No API request spans.');
          const counts = usage && {
            uncached_input: usage.input_tokens, cached_input: usage.cache_read_tokens,
            cache_creation: usage.cache_write_tokens, output: usage.output_tokens,
          };
          const usageValid = counts && Object.values(counts).every((value) => Number.isSafeInteger(value) && value >= 0);
          if (!usageValid) diagnostics.push('Canonical cumulative usage is missing or invalid.');
          const model = usageValid && typeof usage.primary_model === 'string' && usage.primary_model
            ? usage.primary_model : undefined;
          if (usageValid && !model) diagnostics.push('Canonical usage has no primary model.');
          const sessionTimes = log.flatMap((record) => {
            const data = record.data ?? {};
            return [record.startTimeMs, record.endTimeMs, data.startTimeMs, data.endTimeMs, record.timestamp, data.timestamp]
              .map((value) => typeof value === 'number' ? value : typeof value === 'string' ? Date.parse(value) : NaN)
              .filter((value) => Number.isFinite(value) && value > 0);
          });
          const requestTimes = requests.flatMap((record) => [record.startTimeMs, record.endTimeMs]);
          const validRequestTimes = requestTimes.filter((value) => Number.isFinite(value) && value > 0);
          const jobStart = Date.parse(process.env.PRICE_CHECK_JOB_STARTED_AT ?? '');
          const now = Date.now();
          const allTimes = validRequestTimes.length ? validRequestTimes : sessionTimes;
          const startMs = allTimes.length ? Math.min(...allTimes) : Number.isFinite(jobStart) ? jobStart : now;
          const endMs = allTimes.length ? Math.max(...allTimes) : now;
          const identity = [process.env.GITHUB_REPOSITORY, process.env.GITHUB_RUN_ID, process.env.GITHUB_RUN_ATTEMPT].join(':');
          const digest = createHash('sha256').update(identity).digest('hex');
          const traceId = digest.slice(0, 32);
          const rootId = digest.slice(32, 48);
          const event = process.env.GITHUB_EVENT_PATH ? readJson(process.env.GITHUB_EVENT_PATH) ?? {} : {};
          const requestId = event.client_payload?.request_id;
          const resourceAttributes = Object.entries({
            'gh-aw.repository': process.env.GITHUB_REPOSITORY,
            'gh-aw.run.id': process.env.GITHUB_RUN_ID,
            'github.run_attempt': process.env.GITHUB_RUN_ATTEMPT,
            'github.sha': process.env.GITHUB_SHA,
            'price_check.request_id': typeof requestId === 'string' ? requestId : '',
            'price_check.target_model': typeof event.client_payload?.target_model === 'string' ? event.client_payload.target_model : '',
            'price_check.workflow': process.env.GITHUB_WORKFLOW ?? '',
          }).map(([key, value]) => buildAttr(key, value));
          const payloads = [];
          const addSpan = (options) => payloads.push(buildOTLPPayload({
            traceId, serviceName: process.env.PRICE_CHECK_SERVICE_NAME || 'gh-aw.agentic-price-check',
            resourceAttributes, startMs, endMs, ...options,
          }));
          const toolCounts = {};
          for (const record of log) {
            const name = record.data?.toolName;
            if (record.type === 'tool.execution_start' && typeof name === 'string')
              toolCounts[name] = (toolCounts[name] ?? 0) + 1;
          }
          addSpan({ spanId: rootId, spanName: 'invoke_agent', statusCode: agentOutcome === 'success' ? 1 : 2, attributes: [
            buildAttr('gen_ai.operation.name', 'invoke_agent'), buildAttr('gen_ai.agent.name', 'Price Check'),
            buildAttr('price_check.agent_outcome', agentOutcome), buildAttr('price_check.outcome_scope', 'agent_only'),
            buildAttr('price_check.telemetry_coverage', diagnostics.length ? 'incomplete' : 'complete'),
            buildAttr('price_check.telemetry_diagnostic', diagnostics.join(' ')),
            buildAttr('price_check.terminal_output_emitted', terminalEmitted),
            buildAttr('price_check.tool_counts', JSON.stringify(toolCounts)),
          ] });
          if (usageValid) {
            addSpan({ spanId: createHash('sha256').update(identity + model).digest('hex').slice(0, 16),
              parentSpanId: rootId, spanName: 'price_check.usage', attributes: [
                ...(model ? [buildAttr('gen_ai.request.model', model)] : []),
                buildAttr('price_check.usage.source', 'gh-aw.agent_usage'),
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
            agent_outcome: agentOutcome, outcome_scope: 'agent_only', telemetry_coverage: diagnostics.length ? 'incomplete' : 'complete',
            telemetry_diagnostics: diagnostics, usage_source: usageValid ? 'gh-aw.agent_usage' : null,
            model: model ?? null, usage_counts: usageValid ? counts : null, tool_counts: toolCounts,
            cost_is_client_estimate: true,
          }, null, 2));
          await core.summary.addRaw(`Logfire: exported agent-only telemetry with ${requests.length} request spans.\n`).write();
        } catch (error) {
          await core.summary.addRaw(`Logfire telemetry incomplete: ${error.message}\n`).write();
          throw error;
        }
  - name: Stage the model price-check report
    id: stage-model-price-report
    if: always()
    continue-on-error: true
    uses: actions/github-script@3a2844b7e9c422d3c10d287c895573f7108da1b3 # v9.0.0
    with:
      script: |
        const fs = require('node:fs');
        const path = require('node:path');
        let descriptor;
        try {
          descriptor = fs.openSync('/tmp/gh-aw/agent/model-check-report.json', fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
          const stats = fs.fstatSync(descriptor);
          if (!stats.isFile() || stats.size > 32 * 1024) throw new Error('Invalid report file');
          const buffer = Buffer.alloc(32 * 1024 + 1);
          const size = fs.readSync(descriptor, buffer, 0, buffer.length, 0);
          if (size !== stats.size || size > 32 * 1024) throw new Error('Invalid report file');
          const directory = fs.mkdtempSync(path.join(process.env.RUNNER_TEMP, 'price-check-report-'));
          const output = path.join(directory, 'model-check-report.json');
          fs.writeFileSync(output, buffer.subarray(0, size), { flag: 'wx', mode: 0o600 });
          core.setOutput('path', output);
        } catch {
          core.setOutput('path', '');
          core.warning('Model price-check report is missing or invalid; callback will retain unresolved discovery.');
        } finally {
          if (descriptor !== undefined) fs.closeSync(descriptor);
        }
  - name: Upload the model price-check report
    if: ${{ always() && steps.stage-model-price-report.outputs.path != '' }}
    continue-on-error: true
    uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
    with:
      name: model-price-check-report
      path: ${{ steps.stage-model-price-report.outputs.path }}
      if-no-files-found: ignore
---
