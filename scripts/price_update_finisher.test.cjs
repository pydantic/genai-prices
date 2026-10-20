const { test } = require('node:test')
const assert = require('node:assert/strict')
const { readState, watchOne, claim, recordResult } = require('./price_update_finisher.cjs')

const head = 'a'.repeat(40)
const repo = { owner: 'pydantic', repo: 'genai-prices' }
const core = { info() {}, setOutput() {} }

function fixture() {
  const calls = []
  const comments = []
  const pr = {
    state: 'open',
    base: { ref: 'main' },
    head: { sha: head, ref: 'automation/hourly-price-update', repo: { full_name: 'pydantic/genai-prices' } },
    user: { login: 'genai-prices-automation[bot]' },
  }
  const issues = {
    listComments: async () => ({ data: comments }),
    createComment: async (input) => {
      const comment = { id: comments.length + 1, body: input.body, user: { login: 'github-actions[bot]' } }
      comments.push(comment)
      calls.push(['comment', input])
      return { data: comment }
    },
    updateComment: async (input) => {
      comments.find((entry) => entry.id === input.comment_id).body = input.body
    },
  }
  const github = {
    rest: {
      issues,
      pulls: {
        get: async () => ({ data: pr }),
        createReplyForReviewComment: async (input) => calls.push(['reply', input]),
      },
      reactions: {
        createForPullRequestReviewComment: async (input) => calls.push(['reaction', input]),
        createForIssueComment: async (input) => calls.push(['reaction', input]),
      },
      repos: { createDispatchEvent: async (input) => calls.push(['dispatch', input]) },
      actions: { listWorkflowRuns: async () => ({ data: [] }) },
    },
    paginate: async (endpoint, params) => (await endpoint(params)).data,
    graphql: async (query, input) => calls.push(['resolve', input]),
  }
  const options = {
    github,
    repo,
    prNumber: 861,
    core,
    requestId: '123',
    collect: async () => ({ headSha: head, issueComments: comments }),
  }
  return { github, calls, comments, pr, options }
}

test('ready head does not invoke a repair model', async () => {
  const { options, calls, comments } = fixture()
  const result = await watchOne({ ...options, assess: () => ({ state: 'ready', reason: 'complete', findings: [] }) })
  assert.equal(result, 'ready')
  assert.equal(
    calls.some(([kind]) => kind === 'dispatch'),
    false,
  )
  assert.equal(readState(comments).status, 'ready')
})

test('missing hosted completion times out without dispatching or claiming readiness', async () => {
  const { options, calls } = fixture()
  let time = 0
  await assert.rejects(
    watchOne({
      ...options,
      assess: () => ({ state: 'waiting', reason: 'cubic is missing', findings: [] }),
      now: () => time,
      sleep: async () => {
        time += 30_000
      },
      timeoutMs: 60_000,
    }),
    /timed out/,
  )
  assert.equal(calls.length, 0)
})

test('a missing cubic check is requested once per head without spending a repair attempt', async () => {
  const { options, calls, comments } = fixture()
  let time = 0
  await assert.rejects(
    watchOne({
      ...options,
      assess: () => ({ state: 'waiting', reason: 'cubic is missing', findings: [] }),
      now: () => time,
      sleep: async () => {
        time += 30_000
      },
      timeoutMs: 240_000,
    }),
    /timed out/,
  )
  assert.equal(calls.filter(([kind, input]) => kind === 'comment' && input.body.startsWith('@cubic-dev-ai')).length, 1)
  assert.equal(
    calls.some(([kind]) => kind === 'dispatch'),
    false,
  )
  assert.equal(readState(comments).attempts, 0)
})

test('an in-flight repair cannot consume another repair attempt', async () => {
  const { options, github, comments, calls } = fixture()
  const assess = () => ({ state: 'repair', reason: 'failed', findings: [{ id: 'ci:1', kind: 'ci' }] })
  await watchOne({ ...options, assess, now: () => 0 })
  github.rest.actions.listWorkflowRuns = async () => ({ data: [{ id: 9 }] })
  let time = 200_000
  await assert.rejects(
    watchOne({
      ...options,
      assess,
      now: () => time,
      sleep: async () => {
        time += 30_000
      },
      timeoutMs: 60_000,
    }),
    /timed out/,
  )
  assert.equal(readState(comments).attempts, 1)
  assert.equal(calls.filter(([kind]) => kind === 'dispatch').length, 1)
})

test('repair dispatches are persisted and bounded across workflow invocations', async () => {
  const { options, calls, comments } = fixture()
  const assess = () => ({ state: 'repair', reason: 'failed', findings: [{ id: 'ci:1', kind: 'ci' }] })
  let time = 0
  for (let attempt = 1; attempt <= 3; attempt++) {
    time += 120_001
    assert.equal(await watchOne({ ...options, assess, now: () => time }), 'repair-requested')
    const state = readState(comments)
    assert.equal(state.attempts, attempt)
    assert.equal(state.requestId, `123-861-${attempt}`)
    assert.equal(calls.filter(([kind]) => kind === 'dispatch').length, attempt)
  }
  time += 120_001
  await assert.rejects(watchOne({ ...options, assess, now: () => time }), /repair limit/)
})

test('a changed head cannot trigger assessment writes or a repair', async () => {
  const { options, pr, calls } = fixture()
  pr.head.sha = 'b'.repeat(40)
  await assert.rejects(
    watchOne({ ...options, assess: () => ({ state: 'repair', reason: 'finding', findings: [] }) }),
    /head changed/,
  )
  assert.equal(calls.length, 0)
})

test('a retargeted base cannot authorize readiness or a repair', async () => {
  const { options, pr, calls } = fixture()
  pr.base.ref = 'release'
  await assert.rejects(
    watchOne({ ...options, assess: () => ({ state: 'ready', reason: 'complete', findings: [] }) }),
    /identity or head changed/,
  )
  assert.equal(calls.length, 0)
})

test('untrusted or malformed state cannot authorize uncounted repairs', () => {
  assert.deepEqual(
    readState([{ id: 1, user: { login: 'someone' }, body: '<!-- price-update-finisher-state\n{}\n-->' }]),
    { attempts: 0, assessments: [] },
  )
  assert.throws(
    () =>
      readState([
        {
          id: 1,
          user: { login: 'github-actions[bot]' },
          body: '<!-- price-update-finisher-state\n{"attempts":99,"assessments":[]}\n-->',
        },
      ]),
    /Invalid/,
  )
})

test('arbitrary dispatch input cannot claim an existing-PR write path', async () => {
  const { github } = fixture()
  await assert.rejects(
    claim({
      github,
      context: {
        repo,
        payload: {
          client_payload: {
            pr_number: 861,
            head_sha: head,
            request_id: '123-861-1',
            state_comment_id: 9,
          },
        },
      },
      core,
    }),
    /Unclaimed/,
  )
})

test('validated findings receive an inline verdict, reaction, reply and resolution', async () => {
  const { options, github, calls, comments } = fixture()
  await watchOne({ ...options, assess: () => ({ state: 'repair', reason: 'finding', findings: [] }) })
  const expected = {
    prNumber: 861,
    headSha: head,
    requestId: '123-861-1',
    findings: [{ id: 'thread:one', kind: 'thread', threadId: 'one', commentId: 7 }],
  }
  const report = {
    ...expected,
    assessments: [
      {
        id: 'thread:one',
        action: 'dismissed',
        verdict: 'net-negative → skip',
        evidence: 'The recorded response and a focused reproduction prove the value.',
      },
    ],
  }
  await recordResult({ github, context: { repo }, core, expected, report, publishedHead: head })
  assert.match(calls.find(([kind]) => kind === 'reply')[1].body, /net-negative → skip/)
  assert.equal(calls.find(([kind]) => kind === 'reaction')[1].content, '-1')
  assert.equal(calls.find(([kind]) => kind === 'resolve')[1].id, 'one')
  assert.equal(readState(comments).status, 'assessed')
})

test('blocked findings remain tracked and unresolved', async () => {
  const { options, github, calls, comments } = fixture()
  await watchOne({ ...options, assess: () => ({ state: 'repair', reason: 'finding', findings: [] }) })
  const expected = {
    prNumber: 861,
    headSha: head,
    requestId: '123-861-1',
    findings: [{ id: 'thread:one', kind: 'thread', threadId: 'one', commentId: 7 }],
  }
  const report = {
    ...expected,
    assessments: [
      {
        id: 'thread:one',
        action: 'blocked',
        verdict: 'net-positive but out-of-scope → defer',
        evidence: 'Requires a new billable unit and contract version.',
      },
    ],
  }
  await recordResult({ github, context: { repo }, core, expected, report, publishedHead: head })
  assert.equal(
    calls.some(([kind]) => kind === 'resolve'),
    false,
  )
  assert.equal(readState(comments).status, 'blocked')
  await assert.rejects(
    watchOne({ ...options, assess: () => ({ state: 'repair', reason: 'finding', findings: [] }) }),
    /maintainer action/,
  )
})
