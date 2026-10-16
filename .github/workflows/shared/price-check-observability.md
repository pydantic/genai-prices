---
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
          const event = process.env.GITHUB_EVENT_PATH
            ? JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8')) : {};
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
---
