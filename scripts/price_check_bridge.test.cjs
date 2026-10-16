'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')

const { claimRequest, readBackfill, reportBackfill, reportTargetedResult } = require('./price_check_bridge.cjs')

const AUDIENCE = 'https://team.pydantic.work/api/webhooks/price-check'
const REQUEST_ID = 'b0f40d4a-62b2-4f98-a893-38da3b4677f0'
const OTHER_REQUEST_ID = 'c21a8884-30e0-4475-87f4-d128fa987c9f'
const CONTEXT = { payload: { client_payload: { request_id: REQUEST_ID, target_model: 'untrusted-model' } } }

function makeCore() {
  const outputs = {}
  const warnings = []
  const audiences = []
  return {
    outputs,
    warnings,
    audiences,
    async getIDToken(audience) {
      audiences.push(audience)
      return 'test-id-token'
    },
    setOutput(name, value) {
      outputs[name] = value
    },
    warning(message) {
      warnings.push(message)
    },
  }
}

function response(body, ok = true) {
  return {
    ok,
    async json() {
      return body
    },
  }
}

function makeArtifact(t, report) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'price-check-artifact-'))
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }))
  if (report !== undefined) writeReport(directory, report)
  return directory
}

function writeReport(directory, report) {
  const nested = path.join(directory, 'agent', 'results')
  fs.mkdirSync(nested, { recursive: true })
  fs.writeFileSync(path.join(nested, 'model-check-report.json'), JSON.stringify(report))
}

test('claimRequest authenticates and emits only the stored request', async () => {
  const core = makeCore()
  let request
  await claimRequest({
    core,
    context: CONTEXT,
    fetchImpl: async (url, options) => {
      request = { url, options }
      return response({
        claimed: true,
        request_id: REQUEST_ID,
        target_model: 'stored-model',
        source_url: 'https://source.example/pricing',
      })
    },
  })

  assert.deepEqual(core.audiences, [AUDIENCE])
  assert.equal(request.url, `${AUDIENCE}/claim`)
  assert.equal(request.options.headers.authorization, 'Bearer test-id-token')
  assert.deepEqual(JSON.parse(request.options.body), { request_id: REQUEST_ID })
  assert.deepEqual(core.outputs, {
    claimed: 'true',
    request: JSON.stringify({
      request_id: REQUEST_ID,
      target_model: 'stored-model',
      source_url: 'https://source.example/pricing',
    }),
  })
  assert.equal(core.outputs.request.includes('untrusted-model'), false)
})

test('duplicate claims set false outputs without exposing a request', async () => {
  const core = makeCore()
  await claimRequest({
    core,
    context: CONTEXT,
    fetchImpl: async () => response({ claimed: false, request_id: REQUEST_ID, target_model: 'stored-model' }),
  })

  assert.deepEqual(core.outputs, { claimed: 'false', request: '{}' })
})

test('claimRequest rejects malformed event IDs before fetching', async () => {
  const core = makeCore()
  let fetched = false
  await assert.rejects(
    claimRequest({
      core,
      context: { payload: { client_payload: { request_id: '../other' } } },
      fetchImpl: async () => {
        fetched = true
      },
    }),
    /Invalid price-check request ID/,
  )
  assert.equal(fetched, false)
})

test('claimRequest rejects unsafe stored source URLs', async () => {
  const core = makeCore()
  await assert.rejects(
    claimRequest({
      core,
      context: CONTEXT,
      fetchImpl: async () =>
        response({
          claimed: true,
          request_id: REQUEST_ID,
          target_model: 'stored-model',
          source_url: 'https://user:secret@source.example/pricing',
        }),
    }),
    /Invalid official source URL/,
  )
  assert.deepEqual(core.outputs, {})
})

test('bridge errors do not expose raw fetch errors or credentials', async () => {
  const core = makeCore()
  await assert.rejects(
    claimRequest({
      core,
      context: CONTEXT,
      fetchImpl: async () => {
        throw new Error('test-id-token private response body')
      },
    }),
    (error) => error.message === 'Price-check bridge request failed' && !error.message.includes('test-id-token'),
  )
})

test('readBackfill emits only validated stored request fields', async () => {
  const core = makeCore()
  let request
  await readBackfill({
    core,
    context: {},
    fetchImpl: async (url, options) => {
      request = { url, options }
      return response({
        pending: [
          {
            request_id: REQUEST_ID,
            target_model: 'stored-model',
            provider_id: 'openai',
            source_url: 'https://source.example/pricing',
            slack_user: 'hidden',
          },
        ],
      })
    },
  })

  assert.equal(request.url, `${AUDIENCE}/backfill`)
  assert.equal(request.options.headers.authorization, 'Bearer test-id-token')
  assert.deepEqual(JSON.parse(core.outputs.pending), [
    {
      request_id: REQUEST_ID,
      target_model: 'stored-model',
      provider_id: 'openai',
      source_url: 'https://source.example/pricing',
    },
  ])
  assert.equal(core.outputs.pending.includes('slack_user'), false)
})

test('readBackfill accepts the reserved discovery sentinel', async () => {
  const core = makeCore()
  await readBackfill({
    core,
    context: {},
    fetchImpl: async () =>
      response({
        pending: [{ request_id: REQUEST_ID, target_model: 'stored-model', provider_id: '_discovery' }],
      }),
  })

  assert.deepEqual(JSON.parse(core.outputs.pending), [
    { request_id: REQUEST_ID, target_model: 'stored-model', provider_id: '_discovery' },
  ])
})

test('readBackfill rejects unsafe and unknown provider IDs', async () => {
  const core = makeCore()
  await assert.rejects(
    readBackfill({
      core,
      context: {},
      fetchImpl: async () =>
        response({ pending: [{ request_id: REQUEST_ID, target_model: 'model', provider_id: '../aws' }] }),
    }),
    /Invalid provider ID/,
  )
  assert.deepEqual(core.outputs, {})
})

test('targeted report preserves a real PR and marks a missing report incomplete', async (t) => {
  const core = makeCore()
  let body
  await reportTargetedResult({
    core,
    context: CONTEXT,
    env: {
      RUNNER_TEMP: os.tmpdir(),
      AGENT_RESULT: 'failure',
      SAFE_OUTPUT_RESULT: 'success',
      CREATED_PR_URL: 'https://github.com/pydantic/genai-prices/pull/123',
    },
    artifactDirectory: makeArtifact(t),
    fetchImpl: async (url, options) => {
      assert.equal(url, `${AUDIENCE}/result`)
      body = JSON.parse(options.body)
      return response({}, true)
    },
  })

  assert.equal(body.request_id, REQUEST_ID)
  assert.equal(body.state, 'proposed')
  assert.equal(body.pr_url, 'https://github.com/pydantic/genai-prices/pull/123')
  assert.match(body.summary, /Incomplete/)
  assert.deepEqual(body.pending_providers, ['_discovery'])
})

test('targeted noop is complete only with successful jobs and a valid report', async (t) => {
  const core = makeCore()
  const artifactDirectory = makeArtifact(t, { summary: 'No changes were needed.', pending_providers: [] })
  let body
  await reportTargetedResult({
    core,
    context: CONTEXT,
    env: { AGENT_RESULT: 'success', SAFE_OUTPUT_RESULT: 'success', CREATED_PR_URL: '' },
    artifactDirectory,
    fetchImpl: async (_url, options) => {
      body = JSON.parse(options.body)
      return response({}, true)
    },
  })

  assert.equal(body.state, 'complete')
  assert.equal(body.pr_url, null)
  assert.deepEqual(body.pending_providers, [])
  assert.equal(body.summary, 'No changes were needed.')
})

test('targeted report does not call a failed run complete or accept an invalid PR URL', async (t) => {
  const core = makeCore()
  const artifactDirectory = makeArtifact(t, { summary: 'Partial work.', pending_providers: ['aws'] })
  let body
  await reportTargetedResult({
    core,
    context: CONTEXT,
    env: {
      AGENT_RESULT: 'failure',
      SAFE_OUTPUT_RESULT: 'success',
      CREATED_PR_URL: 'https://github.com.evil.test/pydantic/genai-prices/pull/7',
    },
    artifactDirectory,
    fetchImpl: async (_url, options) => {
      body = JSON.parse(options.body)
      return response({}, true)
    },
  })

  assert.equal(body.state, 'failed')
  assert.equal(body.pr_url, null)
  assert.match(body.summary, /^Incomplete:/)
  assert.deepEqual(body.pending_providers, ['aws'])
})

test('targeted report rejects provider IDs outside trusted checkout files', async (t) => {
  const core = makeCore()
  const artifactDirectory = makeArtifact(t, { summary: 'Not clean.', pending_providers: ['aws/../../openai'] })
  let body
  await reportTargetedResult({
    core,
    context: CONTEXT,
    env: { AGENT_RESULT: 'success', SAFE_OUTPUT_RESULT: 'success' },
    artifactDirectory,
    fetchImpl: async (_url, options) => {
      body = JSON.parse(options.body)
      return response({}, true)
    },
  })

  assert.equal(body.state, 'failed')
  assert.deepEqual(body.pending_providers, ['_discovery'])
})

test('targeted report rejects artifact symlinks and oversized files', async (t) => {
  const core = makeCore()
  const symlinkDirectory = makeArtifact(t)
  const target = path.join(symlinkDirectory, 'target.json')
  fs.writeFileSync(target, JSON.stringify({ summary: 'bad', pending_providers: [] }))
  fs.symlinkSync(target, path.join(symlinkDirectory, 'model-check-report.json'))
  const oversizedDirectory = makeArtifact(t)
  fs.writeFileSync(path.join(oversizedDirectory, 'model-check-report.json'), 'x'.repeat(32 * 1024 + 1))
  const bodies = []
  const common = {
    core,
    context: CONTEXT,
    env: { AGENT_RESULT: 'success', SAFE_OUTPUT_RESULT: 'success' },
    fetchImpl: async (_url, options) => {
      bodies.push(JSON.parse(options.body))
      return response({}, true)
    },
  }
  await reportTargetedResult({ ...common, artifactDirectory: symlinkDirectory })
  await reportTargetedResult({ ...common, artifactDirectory: oversizedDirectory })

  assert.equal(bodies.length, 2)
  assert.ok(bodies.every((body) => body.state === 'failed' && body.pending_providers[0] === '_discovery'))
})

test('backfill deduplicates repeated request rows and retains proposed providers in discovery', async (t) => {
  const core = makeCore()
  const artifactDirectory = makeArtifact(t, {
    backfill_results: [
      {
        request_id: REQUEST_ID,
        pending_providers: ['_discovery', 'aws'],
        verified_providers: ['openai'],
        already_present_providers: ['azure'],
      },
    ],
  })
  let body
  await reportBackfill({
    core,
    context: {},
    env: {
      PENDING_BACKFILL: JSON.stringify([
        { request_id: REQUEST_ID, provider_id: 'aws' },
        { request_id: REQUEST_ID, provider_id: 'azure' },
      ]),
      AGENT_RESULT: 'success',
      SAFE_OUTPUT_RESULT: 'success',
      CREATED_PR_URL: 'https://github.com/pydantic/genai-prices/pull/124',
    },
    artifactDirectory,
    fetchImpl: async (url, options) => {
      assert.equal(url, `${AUDIENCE}/backfill`)
      body = JSON.parse(options.body)
      return response({}, true)
    },
  })

  assert.deepEqual(body, {
    pr_url: 'https://github.com/pydantic/genai-prices/pull/124',
    verified_pairs: [{ request_id: REQUEST_ID, provider_id: 'openai' }],
    discoveries: [{ request_id: REQUEST_ID, pending_providers: ['_discovery', 'aws', 'openai'] }],
    resolved_pairs: [{ request_id: REQUEST_ID, provider_id: 'azure' }],
  })
})

test('backfill permits discoveries and already-present resolutions without a PR', async (t) => {
  const core = makeCore()
  const artifactDirectory = makeArtifact(t, {
    backfill_results: [
      { request_id: REQUEST_ID, pending_providers: [], verified_providers: [], already_present_providers: ['azure'] },
    ],
  })
  let body
  await reportBackfill({
    core,
    context: {},
    env: {
      PENDING_BACKFILL: JSON.stringify([{ request_id: REQUEST_ID }]),
      AGENT_RESULT: 'success',
      SAFE_OUTPUT_RESULT: 'success',
    },
    artifactDirectory,
    fetchImpl: async (_url, options) => {
      body = JSON.parse(options.body)
      return response({}, true)
    },
  })

  assert.equal(body.pr_url, null)
  assert.deepEqual(body.verified_pairs, [])
  assert.deepEqual(body.resolved_pairs, [{ request_id: REQUEST_ID, provider_id: 'azure' }])
  assert.deepEqual(body.discoveries, [{ request_id: REQUEST_ID, pending_providers: [] }])
})

test('backfill skips without pending input and leaves backlog unchanged for a missing report', async (t) => {
  const core = makeCore()
  let calls = 0
  const fetchImpl = async () => {
    calls += 1
    return response({}, true)
  }
  await reportBackfill({ core, context: {}, env: {}, artifactDirectory: makeArtifact(t), fetchImpl })
  await reportBackfill({
    core,
    context: {},
    env: { PENDING_BACKFILL: JSON.stringify([{ request_id: REQUEST_ID }]) },
    artifactDirectory: makeArtifact(t),
    fetchImpl,
  })

  assert.equal(calls, 0)
  assert.equal(core.warnings.length, 1)
  assert.match(core.warnings[0], /left unchanged/)
})

test('backfill ignores a report with missing, mismatched, or unsafe results', async (t) => {
  const core = makeCore()
  const directories = [
    makeArtifact(t, {
      backfill_results: [{ request_id: OTHER_REQUEST_ID, pending_providers: [], verified_providers: [] }],
    }),
    makeArtifact(t, {
      backfill_results: [{ request_id: REQUEST_ID, pending_providers: ['../../aws'], verified_providers: [] }],
    }),
    makeArtifact(t, { summary: 'No backfill results.' }),
  ]
  let calls = 0
  for (const artifactDirectory of directories) {
    await reportBackfill({
      core,
      context: {},
      env: { PENDING_BACKFILL: JSON.stringify([{ request_id: REQUEST_ID }]) },
      artifactDirectory,
      fetchImpl: async () => {
        calls += 1
        return response({}, true)
      },
    })
  }

  assert.equal(calls, 0)
  assert.equal(core.warnings.length, 3)
})

test('backfill leaves pending discoveries unchanged after failed jobs', async (t) => {
  const core = makeCore()
  const artifactDirectory = makeArtifact(t, {
    backfill_results: [
      {
        request_id: REQUEST_ID,
        pending_providers: ['_discovery'],
        verified_providers: ['openai'],
        already_present_providers: ['azure'],
      },
    ],
  })
  let calls = 0
  await reportBackfill({
    core,
    context: {},
    env: {
      PENDING_BACKFILL: JSON.stringify([{ request_id: REQUEST_ID }]),
      AGENT_RESULT: 'failure',
      SAFE_OUTPUT_RESULT: 'success',
    },
    artifactDirectory,
    fetchImpl: async () => {
      calls += 1
      return response({}, true)
    },
  })

  assert.equal(calls, 0)
  assert.match(core.warnings[0], /left unchanged/)
})

test('backfill requires every expected ID and skips an empty pending list', async (t) => {
  const core = makeCore()
  const artifactDirectory = makeArtifact(t, { backfill_results: [] })
  let calls = 0
  const fetchImpl = async () => {
    calls += 1
    return response({}, true)
  }
  await reportBackfill({
    core,
    context: {},
    env: { PENDING_BACKFILL: JSON.stringify([{ request_id: REQUEST_ID }]) },
    artifactDirectory,
    fetchImpl,
  })
  await reportBackfill({ core, context: {}, env: { PENDING_BACKFILL: '[]' }, artifactDirectory, fetchImpl })

  assert.equal(calls, 0)
  assert.equal(core.warnings.length, 1)
})
