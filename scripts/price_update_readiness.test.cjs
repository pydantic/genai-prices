'use strict'

const assert = require('node:assert/strict')
const { test } = require('node:test')
const { collectSnapshot, evaluate } = require('./price_update_readiness.cjs')

const HEAD = 'a'.repeat(40)
const OTHER_HEAD = 'b'.repeat(40)

function reviewerCheck(app, name, overrides = {}) {
  return {
    id: app === 'macroscopeapp' ? 11 : 12,
    app: { slug: app },
    name,
    head_sha: HEAD,
    status: 'completed',
    conclusion: 'success',
    started_at: '2026-10-20T12:00:00Z',
    html_url: `https://github.com/checks/${app}`,
    ...overrides,
  }
}

function readySnapshot(overrides = {}) {
  return {
    headSha: HEAD,
    currentHeadSha: HEAD,
    headChanged: false,
    identityValid: true,
    checkRuns: [
      reviewerCheck('macroscopeapp', 'Macroscope - Correctness Check'),
      reviewerCheck('cubic-dev-ai', 'cubic · AI code reviewer'),
    ],
    statuses: [],
    workflowRuns: [
      { id: 50, path: '.github/workflows/ci.yml', head_sha: HEAD, status: 'completed', conclusion: 'success' },
    ],
    threads: [],
    reviewComments: [],
    issueComments: [],
    reviews: [],
    ...overrides,
  }
}

function githubClient({
  prs,
  checkRuns = [],
  annotations = {},
  statuses = [],
  workflowRuns = [],
  reviewComments = [],
  issueComments = [],
  reviews = [],
  threads = [],
} = {}) {
  const pages = []
  const annotationPages = []
  const endpoint =
    (values) =>
    async ({ page }) => {
      pages.push(page)
      return { data: page === 1 ? values : [] }
    }
  const defaultPR = {
    state: 'open',
    head: { sha: HEAD, ref: 'automation/hourly-price-update', repo: { full_name: 'pydantic/genai-prices' } },
    base: { ref: 'main', repo: { full_name: 'pydantic/genai-prices' } },
    user: { login: 'genai-prices-automation[bot]' },
  }
  let prCall = 0
  return {
    pages,
    annotationPages,
    rest: {
      pulls: {
        get: async () => ({ data: prs ? prs[Math.min(prCall++, prs.length - 1)] : defaultPR }),
        listReviewComments: endpoint(reviewComments),
        listReviews: endpoint(reviews),
      },
      checks: {
        listForRef: async () => ({ data: { check_runs: checkRuns } }),
        listAnnotations: async ({ check_run_id, page }) => {
          annotationPages.push([check_run_id, page])
          const items = annotations[check_run_id] ?? []
          return { data: page === 1 ? items : [] }
        },
      },
      repos: { listCommitStatusesForRef: endpoint(statuses) },
      actions: { listWorkflowRunsForRepo: async () => ({ data: { workflow_runs: workflowRuns } }) },
      issues: { listComments: endpoint(issueComments) },
    },
    graphql: async (query) => {
      assert.doesNotMatch(query, /isResolved url/)
      return {
        repository: {
          pullRequest: {
            reviewThreads: {
              nodes: threads,
              pageInfo: { hasNextPage: false, endCursor: null },
            },
          },
        },
      }
    },
  }
}

test('collects a validated same-repo automation PR snapshot and evaluates it as ready', async () => {
  const snapshot = await collectSnapshot(githubClient(), 'pydantic', 'genai-prices', 42)
  assert.equal(snapshot.headSha, HEAD)
  assert.equal(snapshot.identityValid, true)
  assert.equal(evaluate(readySnapshot()).state, 'ready')
})

test('a proposal retargeted away from main fails identity validation', async () => {
  const client = githubClient()
  client.rest.pulls.get = async () => ({
    data: {
      state: 'open',
      head: { sha: HEAD, ref: 'automation/hourly-price-update', repo: { full_name: 'pydantic/genai-prices' } },
      base: { ref: 'release', repo: { full_name: 'pydantic/genai-prices' } },
      user: { login: 'genai-prices-automation[bot]' },
    },
  })
  const snapshot = await collectSnapshot(client, 'pydantic', 'genai-prices', 42)
  assert.equal(snapshot.identityValid, false)
  assert.equal(snapshot.identity.baseRef, 'release')
  assert.equal(evaluate(snapshot).state, 'waiting')
})

test('a retarget between PR reads invalidates identity even when the head SHA is unchanged', async () => {
  const pr = (baseRef) => ({
    state: 'open',
    head: { sha: HEAD, ref: 'automation/hourly-price-update', repo: { full_name: 'pydantic/genai-prices' } },
    base: { ref: baseRef, repo: { full_name: 'pydantic/genai-prices' } },
    user: { login: 'genai-prices-automation[bot]' },
  })
  const snapshot = await collectSnapshot(
    githubClient({ prs: [pr('main'), pr('release')] }),
    'pydantic',
    'genai-prices',
    42,
  )
  assert.equal(snapshot.headChanged, false)
  assert.equal(snapshot.identityValid, false)
  assert.equal(evaluate(snapshot).state, 'waiting')
})

test('successful hosted checks with annotations produce assessable findings', async () => {
  const annotations = Array.from({ length: 100 }, (_, index) => ({
    path: 'prices/providers/example.yml',
    start_line: index + 1,
    annotation_level: 'warning',
    message: `Hosted annotation ${index + 1}`,
  }))
  const client = githubClient({
    checkRuns: [
      reviewerCheck('macroscopeapp', 'Macroscope - Correctness Check', { output: { annotations_count: 100 } }),
      reviewerCheck('cubic-dev-ai', 'cubic · AI code reviewer'),
    ],
    annotations: { 11: annotations },
    workflowRuns: [
      { id: 50, path: '.github/workflows/ci.yml', head_sha: HEAD, status: 'completed', conclusion: 'success' },
    ],
  })
  const snapshot = await collectSnapshot(client, 'pydantic', 'genai-prices', 42)
  const result = evaluate(snapshot)
  assert.equal(result.state, 'repair')
  assert.equal(result.findings[0].id, 'check:11')
  assert.match(result.findings[0].body, /Hosted annotation 100/)
  assert.deepEqual(client.annotationPages, [
    [11, 1],
    [11, 2],
  ])
  assert.equal(
    evaluate(snapshot, [
      { headSha: HEAD, id: 'check:11', action: 'dismissed', evidence: 'Annotation evidence reviewed.' },
    ]).state,
    'ready',
  )
})

test('neutral hosted checks with annotations produce assessable findings', async () => {
  const client = githubClient({
    checkRuns: [
      reviewerCheck('macroscopeapp', 'Macroscope - Correctness Check', {
        conclusion: 'neutral',
        output: { annotations_count: 1 },
      }),
      reviewerCheck('cubic-dev-ai', 'cubic · AI code reviewer'),
    ],
    annotations: {
      11: [
        {
          path: 'prices/providers/example.yml',
          start_line: 8,
          annotation_level: 'warning',
          message: 'Neutral check annotation needs review.',
        },
      ],
    },
    workflowRuns: [
      { id: 50, path: '.github/workflows/ci.yml', head_sha: HEAD, status: 'completed', conclusion: 'success' },
    ],
  })
  const snapshot = await collectSnapshot(client, 'pydantic', 'genai-prices', 42)
  const result = evaluate(snapshot)
  assert.equal(result.state, 'repair')
  assert.equal(result.findings[0].id, 'check:11')
  assert.match(result.findings[0].body, /Neutral check annotation needs review/)
  assert.equal(
    evaluate(snapshot, [{ headSha: HEAD, id: 'check:11', action: 'dismissed', evidence: 'Annotation reviewed.' }])
      .state,
    'ready',
  )
})

test('missing or delayed required reviewer checks keep the PR waiting', () => {
  const delayed = reviewerCheck('cubic-dev-ai', 'cubic · AI code reviewer', {
    status: 'in_progress',
    conclusion: null,
  })
  const missing = readySnapshot({ checkRuns: [reviewerCheck('macroscopeapp', 'Macroscope - Correctness Check')] })
  const running = readySnapshot({ checkRuns: [...missing.checkRuns, delayed] })
  assert.equal(evaluate(missing).state, 'waiting')
  assert.equal(evaluate(running).state, 'waiting')
})

test('a head change during collection keeps the snapshot waiting', async () => {
  let call = 0
  const client = githubClient({
    prs: [
      {
        state: 'open',
        head: { sha: HEAD, ref: 'automation/hourly-price-update', repo: { full_name: 'pydantic/genai-prices' } },
        base: { ref: 'main', repo: { full_name: 'pydantic/genai-prices' } },
        user: { login: 'genai-prices-automation[bot]' },
      },
      {
        state: 'open',
        head: { sha: OTHER_HEAD, ref: 'automation/hourly-price-update', repo: { full_name: 'pydantic/genai-prices' } },
        base: { ref: 'main', repo: { full_name: 'pydantic/genai-prices' } },
        user: { login: 'genai-prices-automation[bot]' },
      },
    ],
  })
  client.rest.pulls.get = async () => ({
    data: [
      {
        state: 'open',
        head: { sha: HEAD, ref: 'automation/hourly-price-update', repo: { full_name: 'pydantic/genai-prices' } },
        base: { ref: 'main', repo: { full_name: 'pydantic/genai-prices' } },
        user: { login: 'genai-prices-automation[bot]' },
      },
      {
        state: 'open',
        head: { sha: OTHER_HEAD, ref: 'automation/hourly-price-update', repo: { full_name: 'pydantic/genai-prices' } },
        base: { ref: 'main', repo: { full_name: 'pydantic/genai-prices' } },
        user: { login: 'genai-prices-automation[bot]' },
      },
    ][call++],
  })
  const snapshot = await collectSnapshot(client, 'pydantic', 'genai-prices', 42)
  assert.equal(snapshot.headChanged, true)
  assert.equal(evaluate(snapshot).state, 'waiting')
})

test('excludes the finisher and repair workflows from self-wait', () => {
  const snapshot = readySnapshot({
    workflowRuns: [
      { id: 1, path: '.github/workflows/ci.yml', head_sha: HEAD, status: 'completed', conclusion: 'success' },
      { id: 2, path: '.github/workflows/finish-price-update.yml', status: 'in_progress' },
      { id: 3, path: '.github/workflows/repair-price-update.lock.yml', status: 'completed', conclusion: 'failure' },
    ],
  })
  assert.equal(evaluate(snapshot).state, 'ready')
})

test('excludes only github-actions checks tied to self-wait workflows', () => {
  const ownChecks = readySnapshot({
    checkRuns: [
      ...readySnapshot().checkRuns,
      {
        id: 91,
        app: { slug: 'github-actions' },
        name: 'watch',
        check_suite: { id: 900 },
        status: 'in_progress',
        details_url: 'https://github.com/pydantic/genai-prices/actions/runs/99',
      },
      {
        id: 92,
        app: { slug: 'github-actions' },
        name: 'repair-agent',
        status: 'completed',
        conclusion: 'failure',
        details_url: 'https://github.com/pydantic/genai-prices/actions/runs/101',
      },
    ],
    workflowRuns: [
      ...readySnapshot().workflowRuns,
      { id: 99, check_suite_id: 900, path: '.github/workflows/finish-price-update.yml', status: 'in_progress' },
      { id: 101, path: '.github/workflows/repair-price-update.lock.yml', status: 'completed', conclusion: 'failure' },
    ],
  })
  assert.equal(evaluate(ownChecks).state, 'ready')

  const foreignCheck = readySnapshot({
    checkRuns: [
      ...readySnapshot().checkRuns,
      {
        id: 93,
        app: { slug: 'foreign-reviewer' },
        name: 'watch',
        status: 'in_progress',
        details_url: 'https://github.com/pydantic/genai-prices/actions/runs/99',
      },
    ],
    workflowRuns: [
      ...readySnapshot().workflowRuns,
      { id: 99, path: '.github/workflows/finish-price-update.yml', status: 'in_progress' },
    ],
  })
  const result = evaluate(foreignCheck)
  assert.equal(result.state, 'waiting')
  assert.match(result.reason, /Check watch is in_progress/)
})

test('uses latest reruns and latest status per context', () => {
  const snapshot = readySnapshot({
    checkRuns: [
      reviewerCheck('macroscopeapp', 'Macroscope - Correctness Check', {
        id: 10,
        conclusion: 'failure',
        started_at: '2026-10-20T10:00:00Z',
      }),
      reviewerCheck('macroscopeapp', 'Macroscope - Correctness Check', { id: 11, started_at: '2026-10-20T11:00:00Z' }),
      reviewerCheck('cubic-dev-ai', 'cubic · AI code reviewer'),
    ],
    statuses: [
      { id: 21, context: 'build', state: 'failure', created_at: '2026-10-20T10:00:00Z' },
      { id: 22, context: 'build', state: 'success', created_at: '2026-10-20T11:00:00Z' },
    ],
  })
  assert.equal(evaluate(snapshot).state, 'ready')
})

test('a newer queued reviewer check run supersedes an older success without timestamps', () => {
  const snapshot = readySnapshot({
    checkRuns: [
      reviewerCheck('macroscopeapp', 'Macroscope - Correctness Check', {
        id: 10,
        started_at: '2026-10-20T10:00:00Z',
      }),
      reviewerCheck('macroscopeapp', 'Macroscope - Correctness Check', {
        id: 11,
        status: 'queued',
        conclusion: null,
        started_at: null,
        completed_at: null,
      }),
      reviewerCheck('cubic-dev-ai', 'cubic · AI code reviewer', { id: 12 }),
    ],
  })
  const result = evaluate(snapshot)
  assert.equal(result.state, 'waiting')
  assert.match(result.reason, /Waiting for reviewer check Macroscope/)
})

test('a completed failed CI run is a repair finding, and a newer workflow rerun supersedes an older failure', () => {
  const failedCI = readySnapshot({
    workflowRuns: [
      {
        id: 50,
        path: '.github/workflows/ci.yml',
        status: 'completed',
        conclusion: 'failure',
        run_started_at: '2026-10-20T10:00:00Z',
      },
    ],
  })
  const failed = evaluate(failedCI)
  assert.equal(failed.state, 'repair')
  assert.equal(failed.findings[0].kind, 'ci')
  assert.doesNotMatch(failed.reason, /has not completed successfully/)

  const rerun = readySnapshot({
    workflowRuns: [
      {
        id: 49,
        path: '.github/workflows/ci.yml',
        status: 'completed',
        conclusion: 'failure',
        run_started_at: '2026-10-20T10:00:00Z',
      },
      {
        id: 50,
        path: '.github/workflows/ci.yml',
        status: 'completed',
        conclusion: 'success',
        run_started_at: '2026-10-20T11:00:00Z',
      },
    ],
  })
  assert.equal(evaluate(rerun).state, 'ready')

  const skippedCI = readySnapshot({
    workflowRuns: [{ id: 51, path: '.github/workflows/ci.yml', status: 'completed', conclusion: 'skipped' }],
  })
  assert.equal(evaluate(skippedCI).state, 'repair')
})

test('release and dependent check skips do not create repair findings', () => {
  const snapshot = readySnapshot({
    checkRuns: [
      ...readySnapshot().checkRuns,
      { id: 81, app: { slug: 'github-actions' }, name: 'publishPyPI', status: 'completed', conclusion: 'skipped' },
      { id: 82, app: { slug: 'github-actions' }, name: 'checkrelease', status: 'completed', conclusion: 'skipped' },
      { id: 83, app: { slug: 'github-actions' }, name: 'coverage', status: 'completed', conclusion: 'neutral' },
    ],
    workflowRuns: [
      ...readySnapshot().workflowRuns,
      { id: 84, path: '.github/workflows/release.yml', status: 'completed', conclusion: 'skipped' },
      { id: 85, path: '.github/workflows/dependent.yml', status: 'completed', conclusion: 'neutral' },
    ],
  })
  assert.equal(evaluate(snapshot).state, 'ready')
})

test('check failures require dismissal evidence, while hosted comments and reviews accept fixed assessments', () => {
  const failedCheck = reviewerCheck('macroscopeapp', 'Macroscope - Correctness Check', {
    id: 13,
    conclusion: 'failure',
  })
  const snapshot = readySnapshot({
    checkRuns: [failedCheck, reviewerCheck('cubic-dev-ai', 'cubic · AI code reviewer')],
    issueComments: [
      {
        id: 31,
        body: 'Please repair this.',
        user: { login: 'macroscope[bot]' },
        html_url: 'https://github.com/comment/31',
      },
    ],
    reviews: [
      {
        id: 41,
        state: 'CHANGES_REQUESTED',
        commit_id: HEAD,
        body: 'Needs work',
        html_url: 'https://github.com/review/41',
      },
    ],
  })
  const fixed = [
    { headSha: HEAD, id: 'check:13', action: 'fixed', evidence: 'A newer run passed.' },
    { headSha: HEAD, id: 'comment:31', action: 'fixed', evidence: 'Repair landed.' },
    { headSha: HEAD, id: 'review:41', action: 'fixed', evidence: 'Repair landed.' },
  ]
  let result = evaluate(snapshot, fixed)
  assert.equal(result.state, 'repair')
  assert.deepEqual(
    result.findings.map((item) => item.id),
    ['check:13'],
  )
  result = evaluate(snapshot, [
    ...fixed,
    { headSha: HEAD, id: 'check:13', action: 'dismissed', evidence: 'Reviewer check accepted.' },
  ])
  assert.equal(result.state, 'ready')
})

test('the latest substantive review per author supersedes CHANGES_REQUESTED, while COMMENTED does not', () => {
  const review = (id, state, submitted_at, login = 'reviewer') => ({
    id,
    state,
    submitted_at,
    commit_id: HEAD,
    user: { login },
    body: `${state} review ${id}`,
    html_url: `https://github.com/review/${id}`,
  })
  const reviews = [
    review(40, 'CHANGES_REQUESTED', '2026-10-20T10:00:00Z'),
    review(41, 'COMMENTED', '2026-10-20T11:00:00Z'),
  ]
  let result = evaluate(readySnapshot({ reviews }))
  assert.equal(result.state, 'repair')
  assert.deepEqual(
    result.findings.map((item) => item.id),
    ['review:40'],
  )

  for (const state of ['APPROVED', 'DISMISSED']) {
    result = evaluate(readySnapshot({ reviews: [...reviews, review(42, state, '2026-10-20T12:00:00Z')] }))
    assert.equal(result.state, 'ready')
  }
})

test('non-reviewer failures cannot be dismissed', () => {
  const snapshot = readySnapshot({
    checkRuns: [
      ...readySnapshot().checkRuns,
      {
        id: 70,
        app: { slug: 'github-actions' },
        name: 'unit-tests',
        status: 'completed',
        conclusion: 'failure',
        started_at: '2026-10-20T13:00:00Z',
      },
    ],
  })
  const result = evaluate(snapshot, [{ headSha: HEAD, id: 'check:70', action: 'dismissed', evidence: 'Reviewed.' }])
  assert.equal(result.state, 'repair')
  assert.equal(result.findings[0].id, 'check:70')
  assert.equal(result.findings[0].kind, 'ci')
})

test('status and workflow failures use the non-dismissible CI finding kind', () => {
  const snapshot = readySnapshot({
    statuses: [{ id: 71, context: 'integration', state: 'failure', description: 'Integration failed.' }],
    workflowRuns: [
      ...readySnapshot().workflowRuns,
      {
        id: 72,
        path: '.github/workflows/other.yml',
        status: 'completed',
        conclusion: 'failure',
        display_title: 'Other workflow failed.',
      },
    ],
  })
  const result = evaluate(snapshot, [
    { headSha: HEAD, id: 'status:71', action: 'dismissed', evidence: 'Reviewed.' },
    { headSha: HEAD, id: 'workflow:72', action: 'dismissed', evidence: 'Reviewed.' },
  ])
  assert.equal(result.state, 'repair')
  assert.deepEqual(
    result.findings.map((item) => item.kind),
    ['ci', 'ci'],
  )
})

test('unresolved review threads carry thread and numeric comment IDs; resolved threads add no finding', () => {
  const snapshot = readySnapshot({
    threads: [
      {
        id: 'PRRT_kwDO123',
        isResolved: false,
        url: 'https://github.com/thread',
        comments: [{ databaseId: 51, body: 'Please fix this.', url: 'https://github.com/thread#comment-51' }],
      },
    ],
  })
  const result = evaluate(snapshot, [
    { headSha: HEAD, id: 'thread:PRRT_kwDO123', action: 'dismissed', evidence: 'Handled.' },
  ])
  assert.equal(result.state, 'repair')
  assert.equal(result.findings[0].replyTarget, 51)
  assert.equal(result.findings[0].reactionTarget, 51)
  assert.equal(result.findings[0].threadId, 'PRRT_kwDO123')
  assert.equal(result.findings[0].commentId, 51)

  const resolved = readySnapshot({
    threads: [
      { id: 'PRRT_kwDO123', isResolved: true, comments: [{ databaseId: 51, body: 'Resolved inline comment.' }] },
    ],
    reviewComments: [{ id: 51, body: 'Legacy duplicate must be ignored.', user: { login: 'macroscopeapp[bot]' } }],
  })
  assert.equal(evaluate(resolved).state, 'ready')
})

test('neutral required reviewer checks without finding content do not need dismissal', () => {
  const snapshot = readySnapshot({
    checkRuns: [
      reviewerCheck('macroscopeapp', 'Macroscope - Correctness Check', { conclusion: 'neutral' }),
      reviewerCheck('cubic-dev-ai', 'cubic · AI code reviewer'),
    ],
  })
  assert.equal(evaluate(snapshot).state, 'ready')
})

test('a skipped required reviewer check remains waiting without creating a repair finding', () => {
  const snapshot = readySnapshot({
    checkRuns: [
      reviewerCheck('macroscopeapp', 'Macroscope - Correctness Check', { conclusion: 'skipped' }),
      reviewerCheck('cubic-dev-ai', 'cubic · AI code reviewer'),
    ],
  })
  const result = evaluate(snapshot)
  assert.equal(result.state, 'waiting')
  assert.match(result.reason, /Waiting for reviewer check Macroscope/)
  assert.deepEqual(result.findings, [])
})

test('no checks or CI leaves the snapshot waiting', () => {
  const snapshot = readySnapshot({ checkRuns: [], workflowRuns: [] })
  assert.equal(evaluate(snapshot).state, 'waiting')
})

test('fails closed when REST pagination exceeds a page or GraphQL pagination is truncated', async () => {
  const client = githubClient()
  const commentPages = []
  client.rest.issues.listComments = async ({ page }) => {
    commentPages.push(page)
    return { data: page === 1 ? Array.from({ length: 100 }, (_, id) => ({ id })) : [] }
  }
  await collectSnapshot(client, 'pydantic', 'genai-prices', 42)
  assert.deepEqual(commentPages, [1, 2])

  const broken = githubClient()
  broken.graphql = async () => ({
    repository: { pullRequest: { reviewThreads: { nodes: [], pageInfo: { hasNextPage: true, endCursor: null } } } },
  })
  await assert.rejects(collectSnapshot(broken, 'pydantic', 'genai-prices', 42), /pagination was truncated/)
})

test('invalid automation identity cannot become ready or repair', async () => {
  const client = githubClient()
  client.rest.pulls.get = async () => ({
    data: {
      state: 'open',
      head: { sha: HEAD, ref: 'feature/branch', repo: { full_name: 'pydantic/genai-prices' } },
      base: { ref: 'main', repo: { full_name: 'pydantic/genai-prices' } },
      user: { login: 'someone-else' },
    },
  })
  const snapshot = await collectSnapshot(client, 'pydantic', 'genai-prices', 42)
  assert.equal(snapshot.identityValid, false)
  assert.equal(evaluate(snapshot).state, 'waiting')
})
