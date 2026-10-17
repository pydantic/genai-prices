'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { test } = require('node:test')
const {
  readBounded,
  parseEvents,
  parseResults,
  buildCoverage,
  stageCoverage,
  summary,
} = require('./price_check_coverage.cjs')

const url = 'https://pricing.example/prices#standard'
const plan = {
  providers: [
    { provider_id: 'weekly', file: 'weekly.yml', weekly: true, sources: [url], backfill: [] },
    {
      provider_id: 'backlog',
      file: 'backlog.yml',
      weekly: false,
      sources: ['https://other.example/'],
      backfill: [{ request_id: 'request', target_model: 'model', provider_id: 'backlog' }],
    },
    {
      provider_id: '_discovery',
      file: null,
      weekly: false,
      sources: [],
      backfill: [{ request_id: 'discovery', target_model: 'model', provider_id: '_discovery' }],
    },
  ],
}
const input = (value, status = 'present') => ({ value, status })
const result = (overrides = {}) => ({
  provider_id: 'weekly',
  status: 'checked',
  sources: [{ url, status: 'readable' }],
  backfill: [],
  price_changes: 0,
  new_models: 0,
  potential_removals: 0,
  unchecked_fields: 0,
  deferred_changes: 0,
  ...overrides,
})
function page(id, start = 0, end = 10, total = 10, source = url) {
  const attempt_id = id.toString(16).padStart(32, '0')
  return [
    { type: 'start', attempt_id, source, start_index: start, max_length: 20000, time_ms: 100 },
    {
      type: 'finish',
      attempt_id,
      outcome: 'response',
      status: 200,
      start_index: start,
      end_index: end,
      total_length: total,
      truncated: end < total,
      time_ms: 120,
    },
  ]
}
const parsedEvents = (events) => parseEvents(events.map((event) => JSON.stringify(event)).join('\n'))

test('missing output retains every expected provider and exact URL including backlog and discovery', () => {
  const report = buildCoverage(plan, input([], 'missing'), input([], 'missing'))
  assert.equal(report.providers.length, 3)
  assert.equal(report.providers[0].sources[0].url, url)
  assert.equal(report.providers[0].retrieval_status, 'not_attempted')
  assert.equal(report.providers[1].backfill[0].semantic_status, 'missing')
  assert.equal(report.providers[2].semantic_status, 'missing')
  assert.equal(report.totals.providers_complete, 0)
  assert.match(summary(report), /0\/2 exact sources retrieved/)
})

test('retrieval is independent of semantic claims and deferred evidence', () => {
  for (const assessment of [
    result({ sources: [] }),
    result({ unchecked_fields: 1 }),
    result({ deferred_changes: 1 }),
    result({ status: 'partial' }),
  ]) {
    const report = buildCoverage(plan, input(parsedEvents(page(1))), input([assessment]))
    assert.equal(report.providers[0].retrieval_status, 'retrieved')
    assert.equal(report.providers[0].complete, false)
  }
  assert.equal(buildCoverage(plan, input(parsedEvents(page(1))), input([result()])).providers[0].complete, true)
  assert.equal(buildCoverage(plan, input([]), input([result()])).providers[0].complete, false)
})

test('pagination requires complete nonempty contiguous ranges of consistent total length', () => {
  for (const events of [
    page(1, 0, 5),
    [...page(1, 0, 4), ...page(2, 5, 10)],
    [...page(1, 0, 5), ...page(2, 5, 11, 11)],
    page(1, 0, 0, 0),
  ]) {
    assert.equal(
      buildCoverage(plan, input(parsedEvents(events)), input([result()])).providers[0].sources[0].retrieval_status,
      'partial',
    )
  }
  const report = buildCoverage(plan, input(parsedEvents([...page(1, 0, 5), ...page(2, 5, 10)])), input([result()]))
  assert.equal(report.providers[0].complete, true)
  assert.equal(report.providers[0].sources[0].attempts.length, 2)
})

test('failures, retries, interrupted attempts and follow-up URLs remain distinct', () => {
  const failed = page(1)
  failed[1] = {
    type: 'finish',
    attempt_id: failed[0].attempt_id,
    outcome: 'error',
    error_kind: 'transport',
    time_ms: 110,
  }
  const interrupted = page(2).slice(0, 1)
  const events = parsedEvents([...failed, ...interrupted, ...page(3), ...page(4, 0, 10, 10, null)])
  const report = buildCoverage(plan, input(events), input([result()]))
  assert.equal(report.providers[0].complete, true)
  assert.equal(report.totals.failures, 1)
  assert.equal(report.totals.incomplete_attempts, 1)
  assert.equal(report.totals.follow_up_attempts, 1)
  assert.equal(
    buildCoverage(plan, input(parsedEvents(failed)), input([result()])).providers[0].sources[0].retrieval_status,
    'failed',
  )
  assert.equal(buildCoverage(plan, input(parsedEvents(interrupted)), input([result()])).providers[0].complete, false)
  const nonSuccess = page(5)
  nonSuccess[1].status = 302
  const rejected = buildCoverage(plan, input(parsedEvents(nonSuccess)), input([result()]))
  assert.equal(rejected.totals.failures, 1)
  assert.equal(rejected.providers[0].complete, false)
})

test('one provider result cannot silently complete selected backlog comparisons', () => {
  const scope = { providers: [{ ...plan.providers[0], backfill: plan.providers[1].backfill }] }
  assert.equal(buildCoverage(scope, input(parsedEvents(page(1))), input([result()])).providers[0].complete, false)
  assert.equal(
    buildCoverage(
      scope,
      input(parsedEvents(page(1))),
      input([result({ backfill: [{ request_id: 'request', status: 'checked' }] })]),
    ).providers[0].complete,
    true,
  )
})

test('discovery is assessed from every selected backlog pair without a fixed source list', () => {
  const checked = result({
    provider_id: '_discovery',
    sources: [],
    backfill: [{ request_id: 'discovery', status: 'checked' }],
  })
  const report = buildCoverage(plan, input([]), input([checked]))
  const discovery = report.providers.find((provider) => provider.provider_id === '_discovery')
  assert.equal(discovery.retrieval_status, 'not_applicable')
  assert.equal(discovery.complete, true)
})

test('malformed, duplicated and unpaired events or results fail closed', () => {
  assert.throws(() => parseEvents('bad json'))
  assert.throws(() => parsedEvents([{ ...page(1)[1], end_index: 99 }]))
  assert.throws(() => parseResults(JSON.stringify({ providers: [result(), result()] })))
  assert.throws(() => parseResults(JSON.stringify({ providers: [result({ unchecked_fields: -1 })] })))
  assert.throws(() =>
    parseResults(JSON.stringify({ providers: [result({ backfill: [{ request_id: 'r', status: 'invented' }] })] })),
  )
  for (const events of [[...page(1), ...page(1)], [page(1)[1]]]) {
    const report = buildCoverage(plan, input(parsedEvents(events)), input([result()]))
    assert.equal(report.ledger_status, 'invalid')
    assert.equal(report.providers[0].complete, false)
  }
})

test('bounded staging rejects links, oversized files and malformed JSON while publishing explicit missing results', (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'price-check-coverage-test-'))
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }))
  const agent = path.join(directory, 'agent')
  fs.mkdirSync(agent)
  fs.writeFileSync(path.join(directory, 'plan.json'), JSON.stringify(plan))
  const original = path.join(directory, 'original')
  fs.writeFileSync(original, 'safe')
  const link = path.join(directory, 'link')
  fs.symlinkSync(original, link)
  assert.throws(() => readBounded(link, 10))
  assert.throws(() => readBounded(original, 2))
  assert.throws(() => readBounded(directory, 100))
  let staged = stageCoverage(directory, agent, { run_id: '123', sha: 'abc' })
  assert.equal(staged.report.ledger_status, 'missing')
  assert.equal(JSON.parse(fs.readFileSync(staged.output)).run_id, '123')
  fs.writeFileSync(path.join(agent, 'price-check-fetch-attempts.jsonl'), 'invalid')
  fs.writeFileSync(path.join(agent, 'provider-results.json'), 'invalid')
  staged = stageCoverage(directory, agent, {})
  assert.equal(staged.report.ledger_status, 'invalid')
  assert.equal(staged.report.semantic_results_status, 'invalid')
})

test('untrusted extra fields and URLs never survive into the report', () => {
  const events = parsedEvents(page(1).map((event) => ({ ...event, content: 'private page' })))
  const results = parseResults(
    JSON.stringify({
      providers: [
        result({
          content: 'secret',
          sources: [
            { url, status: 'readable', content: 'secret' },
            { url: 'https://user:secret@evil.test/', status: 'readable' },
          ],
        }),
      ],
    }),
  )
  const serialized = JSON.stringify(buildCoverage(plan, input(events), input(results)))
  assert.doesNotMatch(serialized, /private page|secret|evil/)
})
