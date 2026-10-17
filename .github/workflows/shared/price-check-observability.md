---
post-steps:
  - name: Summarize weekly price-check coverage
    id: price-check-coverage
    if: ${{ always() && github.workflow == 'Price Check' }}
    continue-on-error: true
    uses: actions/github-script@3a2844b7e9c422d3c10d287c895573f7108da1b3 # v9.0.0
    with:
      script: |
        const path = require('node:path');
        const directory = path.join(process.env.RUNNER_TEMP, 'gh-aw/price-check-coverage');
        const { stageCoverage, summary } = require(path.join(directory, 'summarize.cjs'));
        const { report, output } = stageCoverage(directory, '/tmp/gh-aw/agent', {
          run_id: process.env.GITHUB_RUN_ID, run_attempt: process.env.GITHUB_RUN_ATTEMPT,
          sha: process.env.GITHUB_SHA,
        });
        core.setOutput('path', output);
        await core.summary.addRaw(summary(report)).write();
  - name: Upload weekly price-check coverage
    if: ${{ always() && steps.price-check-coverage.outputs.path != '' }}
    continue-on-error: true
    uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
    with:
      name: price-check-coverage
      path: ${{ steps.price-check-coverage.outputs.path }}
      if-no-files-found: error
  - name: Export price-check telemetry
    if: always()
    continue-on-error: true
    uses: actions/github-script@3a2844b7e9c422d3c10d287c895573f7108da1b3 # v9.0.0
    env:
      # Keep this credential scoped to the trusted step after the agent exits.
      OTEL_EXPORTER_OTLP_HEADERS: Authorization=${{ secrets.LOGFIRE_OTLP_AUTHORIZATION }}
      PRICE_CHECK_COVERAGE_PATH: ${{ steps.price-check-coverage.outputs.path }}
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
          let usageStatus = 'available';
          const modelUsage = Object.create(null);
          try {
            const usage = JSON.parse(fs.readFileSync('/tmp/gh-aw/agent_usage.json', 'utf8'));
            if (typeof usage.primary_model !== 'string' || !usage.primary_model ||
                ![usage.input_tokens, usage.cache_read_tokens, usage.cache_write_tokens, usage.output_tokens]
                  .every((value) => Number.isSafeInteger(value) && value >= 0)) {
              throw new Error('Invalid canonical usage');
            }
            modelUsage[usage.primary_model] = {
              inputTokens: usage.input_tokens, cacheReadInputTokens: usage.cache_read_tokens,
              cacheCreationInputTokens: usage.cache_write_tokens, outputTokens: usage.output_tokens,
            };
          } catch (error) {
            usageStatus = error.code === 'ENOENT' ? 'missing' : 'invalid';
            core.warning(`Canonical token usage unavailable (${usageStatus}); exporting recorded spans without token totals.`);
          }
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
            buildAttr('price_check.usage.status', usageStatus),
          ] });
          const coverageDirectory = path.join(process.env.RUNNER_TEMP, 'gh-aw/price-check-coverage');
          if (fs.existsSync(path.join(coverageDirectory, 'plan.json'))) {
            try {
            const { readBounded } = require(path.join(coverageDirectory, 'summarize.cjs'));
            const coverage = JSON.parse(readBounded(process.env.PRICE_CHECK_COVERAGE_PATH, 8 * 1024 * 1024));
            const coverageId = createHash('sha256').update(identity + ':coverage').digest('hex').slice(0, 16);
            addSpan({ spanId: coverageId, parentSpanId: rootId, spanName: 'price_check.coverage', attributes: [
              buildAttr('price_check.coverage.ledger_status', coverage.ledger_status),
              buildAttr('price_check.coverage.semantic_results_status', coverage.semantic_results_status),
              ...Object.entries(coverage.totals).map(([key, value]) => buildAttr('price_check.coverage.' + key, value)),
            ] });
            for (const provider of coverage.providers) addSpan({
              spanId: createHash('sha256').update(identity + ':provider:' + provider.provider_id).digest('hex').slice(0, 16),
              parentSpanId: coverageId, spanName: 'price_check.provider_result', attributes: [
                buildAttr('price_check.provider_id', provider.provider_id),
                buildAttr('price_check.retrieval_status', provider.retrieval_status),
                buildAttr('price_check.semantic_status', provider.semantic_status),
                buildAttr('price_check.complete', provider.complete),
                buildAttr('price_check.result_source', 'agent_report'),
                buildAttr('price_check.findings', JSON.stringify(provider.findings)),
                buildAttr('price_check.sources', JSON.stringify(provider.sources.map((source) => ({
                  url: source.url, retrieval_status: source.retrieval_status, semantic_status: source.semantic_status,
                  attempts: source.attempts.length,
                })))),
                buildAttr('price_check.backfill', JSON.stringify(provider.backfill)),
              ],
            });
            } catch (error) {
              const reason = error instanceof SyntaxError ? 'invalid_json'
                : error.code === 'ENOENT' ? 'missing_report' : 'invalid_report';
              core.warning(`Coverage telemetry unavailable (${reason}); inspect the coverage summary and artifact steps.`);
              addSpan({ spanId: createHash('sha256').update(identity + ':coverage-unavailable').digest('hex').slice(0, 16),
                parentSpanId: rootId, spanName: 'price_check.coverage', attributes: [
                  buildAttr('price_check.coverage.ledger_status', 'unavailable'),
                  buildAttr('price_check.coverage.error_kind', reason),
                ] });
            }
          }
          for (const [model, usage] of Object.entries(modelUsage)) {
            const counts = {
              uncached_input: usage.inputTokens, cached_input: usage.cacheReadInputTokens,
              cache_creation: usage.cacheCreationInputTokens, output: usage.outputTokens,
            };
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
            usage_status: usageStatus, usage_source: usageStatus === 'available' ? 'gh-aw.agent_usage' : null,
            model_usage: modelUsage, tool_counts: toolCounts,
            cost_is_client_estimate: true,
          }, null, 2));
          const usageSummary = usageStatus === 'available' ? 'canonical cumulative usage'
            : `canonical usage unavailable (${usageStatus})`;
          await core.summary.addRaw(`Logfire: exported ${requests.length} request spans; ${usageSummary}.\n`).write();
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
