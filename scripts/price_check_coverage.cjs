'use strict'

const fs = require('node:fs')
const path = require('node:path')

const counts = ['price_changes', 'new_models', 'potential_removals', 'unchecked_fields', 'deferred_changes']
const integer = (value) => Number.isSafeInteger(value) && value >= 0
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value)

function readBounded(file, limit) {
  let descriptor
  try {
    descriptor = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK)
    const stats = fs.fstatSync(descriptor)
    if (!stats.isFile() || stats.size > limit) throw new Error('Invalid input file')
    const buffer = Buffer.alloc(limit + 1)
    const size = fs.readSync(descriptor, buffer, 0, buffer.length, 0)
    if (size !== stats.size || size > limit) throw new Error('Invalid input file')
    return buffer.subarray(0, size).toString('utf8')
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor)
  }
}

function readInput(file, limit, parse) {
  try {
    return { status: 'present', value: parse(readBounded(file, limit)) }
  } catch (error) {
    return { status: error.code === 'ENOENT' ? 'missing' : 'invalid', value: [] }
  }
}

function parseEvents(text) {
  return text
    .split('\n')
    .filter(Boolean)
    .map((line) => {
      const event = JSON.parse(line)
      if (!object(event) || !/^[a-f0-9]{32}$/.test(event.attempt_id) || !integer(event.time_ms))
        throw new Error('Invalid fetch event')
      if (event.type === 'start') {
        if (
          !(event.source === null || typeof event.source === 'string') ||
          !integer(event.start_index) ||
          !integer(event.max_length)
        )
          throw new Error('Invalid fetch start')
      } else if (event.type === 'finish') {
        if (!['response', 'error'].includes(event.outcome)) throw new Error('Invalid fetch finish')
        if (
          event.outcome === 'response' &&
          !(
            integer(event.status) &&
            integer(event.start_index) &&
            integer(event.end_index) &&
            integer(event.total_length) &&
            event.start_index <= event.end_index &&
            event.end_index <= event.total_length &&
            typeof event.truncated === 'boolean' &&
            event.truncated === event.end_index < event.total_length
          )
        )
          throw new Error('Invalid response range')
      } else throw new Error('Invalid fetch event type')
      return event
    })
}

function attemptsFrom(events, sources) {
  const attempts = new Map()
  for (const event of events.filter((event) => event.type === 'start')) {
    if (attempts.has(event.attempt_id)) throw new Error('Duplicate fetch attempt')
    attempts.set(event.attempt_id, {
      attempt_id: event.attempt_id,
      source: sources.has(event.source) ? event.source : null,
      requested_start: event.start_index,
      max_length: event.max_length,
      start_ms: event.time_ms,
      outcome: 'incomplete',
    })
  }
  const completed = new Set()
  for (const event of events.filter((event) => event.type === 'finish')) {
    const attempt = attempts.get(event.attempt_id)
    if (!attempt || completed.has(event.attempt_id)) throw new Error('Unpaired fetch completion')
    completed.add(event.attempt_id)
    attempt.outcome = event.outcome
    attempt.end_ms = event.time_ms
    attempt.duration_ms = Math.max(0, event.time_ms - attempt.start_ms)
    if (event.outcome === 'response') {
      for (const key of ['status', 'start_index', 'end_index', 'total_length', 'truncated']) attempt[key] = event[key]
      if (event.start_index !== attempt.requested_start) attempt.outcome = 'invalid_response'
    } else {
      attempt.error_kind = ['transport', 'cancelled', 'invalid_response_or_execution'].includes(event.error_kind)
        ? event.error_kind
        : 'unknown'
      if (integer(event.http_status) && event.http_status >= 100 && event.http_status <= 599)
        attempt.http_status = event.http_status
    }
  }
  return [...attempts.values()]
}

function retrievalStatus(attempts) {
  if (!attempts.length) return 'not_attempted'
  const pages = attempts.filter(
    (attempt) => attempt.outcome === 'response' && attempt.status >= 200 && attempt.status < 300,
  )
  if (!pages.length) return 'failed'
  const lengths = new Set(pages.map((page) => page.total_length))
  if (lengths.size !== 1 || pages[0].total_length === 0) return 'partial'
  let end = 0
  for (const page of [...pages].sort((a, b) => a.start_index - b.start_index)) {
    if (page.start_index > end) return 'partial'
    end = Math.max(end, page.end_index)
  }
  return end === pages[0].total_length ? 'retrieved' : 'partial'
}

function parseResults(text) {
  const results = JSON.parse(text)
  if (!Array.isArray(results.providers)) throw new Error('Invalid provider results')
  const ids = new Set()
  for (const result of results.providers) {
    if (
      !object(result) ||
      typeof result.provider_id !== 'string' ||
      ids.has(result.provider_id) ||
      !['checked', 'partial', 'unresolved'].includes(result.status) ||
      !counts.every((key) => integer(result[key])) ||
      !Array.isArray(result.sources) ||
      !Array.isArray(result.backfill)
    )
      throw new Error('Invalid provider result')
    ids.add(result.provider_id)
    const requests = new Set()
    for (const row of result.backfill) {
      if (
        !object(row) ||
        typeof row.request_id !== 'string' ||
        requests.has(row.request_id) ||
        !['checked', 'partial', 'unresolved'].includes(row.status)
      )
        throw new Error('Invalid backfill assessment')
      requests.add(row.request_id)
    }
    const urls = new Set()
    for (const source of result.sources) {
      if (
        !object(source) ||
        typeof source.url !== 'string' ||
        urls.has(source.url) ||
        !['readable', 'unreadable', 'unresolved'].includes(source.status)
      )
        throw new Error('Invalid source assessment')
      urls.add(source.url)
    }
  }
  return results.providers
}

function buildCoverage(plan, ledger, results) {
  const sources = new Set(plan.providers.flatMap((provider) => provider.sources))
  let attempts = []
  try {
    attempts = attemptsFrom(ledger.value, sources)
  } catch {
    ledger = { status: 'invalid', value: [] }
  }
  const providers = plan.providers.map((provider) => {
    const result = results.value.find((row) => row.provider_id === provider.provider_id)
    const sourceResults = provider.sources.map((url) => {
      const sourceAttempts = attempts.filter((attempt) => attempt.source === url)
      return {
        url,
        retrieval_status: retrievalStatus(sourceAttempts),
        attempts: sourceAttempts,
        semantic_status: result?.sources.find((source) => source.url === url)?.status ?? 'missing',
      }
    })
    const retrieved = sourceResults.filter((source) => source.retrieval_status === 'retrieved').length
    const backfill = provider.backfill.map((row) => ({
      ...row,
      semantic_status:
        result?.backfill.find((assessment) => assessment.request_id === row.request_id)?.status ?? 'missing',
    }))
    const retrieval = !sourceResults.length
      ? 'not_applicable'
      : retrieved === sourceResults.length
        ? 'retrieved'
        : sourceResults.some((source) => source.attempts.length)
          ? 'partial'
          : 'not_attempted'
    return {
      ...provider,
      backfill,
      sources: sourceResults,
      retrieval_status: retrieval,
      semantic_status: result?.status ?? 'missing',
      findings: result ? Object.fromEntries(counts.map((key) => [key, result[key]])) : null,
      complete:
        ledger.status === 'present' &&
        result?.status === 'checked' &&
        (retrieval === 'retrieved' || provider.provider_id === '_discovery') &&
        sourceResults.every((source) => source.semantic_status === 'readable') &&
        backfill.every((row) => row.semantic_status === 'checked') &&
        result.unchecked_fields === 0 &&
        result.deferred_changes === 0,
    }
  })
  return {
    schema_version: 1,
    ledger_status: ledger.status,
    semantic_results_status: results.status,
    totals: {
      providers_expected: providers.length,
      providers_complete: providers.filter((provider) => provider.complete).length,
      sources_expected: sources.size,
      sources_retrieved: [...sources].filter(
        (url) => retrievalStatus(attempts.filter((attempt) => attempt.source === url)) === 'retrieved',
      ).length,
      attempts: attempts.length,
      failures: attempts.filter(
        (attempt) =>
          ['error', 'invalid_response'].includes(attempt.outcome) ||
          (attempt.outcome === 'response' && (attempt.status < 200 || attempt.status >= 300)),
      ).length,
      incomplete_attempts: attempts.filter((attempt) => attempt.outcome === 'incomplete').length,
      follow_up_attempts: attempts.filter((attempt) => attempt.source === null).length,
    },
    providers,
    other_attempts: attempts.filter((attempt) => attempt.source === null),
  }
}

function stageCoverage(directory, agentDirectory, identity) {
  const plan = JSON.parse(readBounded(path.join(directory, 'plan.json'), 256 * 1024))
  const ledger = readInput(path.join(agentDirectory, 'price-check-fetch-attempts.jsonl'), 4 * 1024 * 1024, parseEvents)
  const results = readInput(path.join(agentDirectory, 'provider-results.json'), 128 * 1024, parseResults)
  const report = { ...buildCoverage(plan, ledger, results), ...identity }
  const staged = fs.mkdtempSync(path.join(directory, 'report-'))
  const output = path.join(staged, 'coverage.json')
  fs.writeFileSync(output, JSON.stringify(report, null, 2), { flag: 'wx', mode: 0o600 })
  return { report, output }
}

function summary(report) {
  const totals = report.totals
  return (
    `\n### Price-check coverage\n\n` +
    `${totals.sources_retrieved}/${totals.sources_expected} exact sources retrieved; ` +
    `${totals.providers_complete}/${totals.providers_expected} providers complete. ` +
    `Fetch ledger: ${report.ledger_status}; agent-reported results: ${report.semantic_results_status}.\n\n` +
    '| Provider | Retrieval | Agent-reported check | Complete |\n| --- | --- | --- | --- |\n' +
    report.providers
      .map(
        (provider) =>
          `| ${provider.provider_id} | ${provider.retrieval_status} | ${provider.semantic_status} | ${provider.complete} |`,
      )
      .join('\n') +
    '\n\nSee the `price-check-coverage` artifact for exact-source attempts, pagination and findings counts. ' +
    'Retrieval does not establish semantic verification. This instrumentation is not a security attestation.\n'
  )
}

module.exports = { readBounded, parseEvents, parseResults, buildCoverage, stageCoverage, summary }
