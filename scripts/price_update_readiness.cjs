'use strict'

const SELF_WAIT_WORKFLOWS = new Set([
  '.github/workflows/finish-price-update.yml',
  '.github/workflows/repair-price-update.lock.yml',
])
const REVIEWERS = [
  { app: 'macroscopeapp', name: 'Macroscope - Correctness Check' },
  { app: 'cubic-dev-ai', name: 'cubic · AI code reviewer' },
]
const HOSTED_REVIEWERS = new Set(['macroscopeapp[bot]', 'macroscope[bot]', 'cubic-dev-ai[bot]'])
const CI_WORKFLOW = '.github/workflows/ci.yml'
const MAX_PAGES = 1000

function fail(message) {
  throw new Error(message)
}

function reviewUnavailable(check) {
  return (
    check.app?.slug === 'cubic-dev-ai' &&
    check.conclusion === 'neutral' &&
    /review line limit reached|monthly review limit/i.test(
      `${check.output?.title ?? ''}\n${check.output?.summary ?? ''}\n${check.output?.text ?? ''}`,
    )
  )
}

function fullName(owner, name) {
  return `${owner}/${name}`
}

function repoFullName(value) {
  return value?.full_name ?? (value?.owner?.login && value?.name ? fullName(value.owner.login, value.name) : '')
}

function isAutomationPR(pr, repo) {
  return (
    pr?.state === 'open' &&
    repoFullName(pr.base?.repo) === repo &&
    pr.base?.ref === 'main' &&
    repoFullName(pr.head?.repo) === repo &&
    pr.user?.login === 'genai-prices-automation[bot]'
  )
}

function arrayFrom(response, keys = []) {
  const data = response?.data
  if (Array.isArray(data)) return data
  for (const key of keys) if (Array.isArray(data?.[key])) return data[key]
  fail('GitHub returned an invalid paginated response')
}

async function allPages(endpoint, params, keys = []) {
  const result = []
  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const response = await endpoint({ ...params, per_page: 100, page })
    const values = arrayFrom(response, keys)
    result.push(...values)
    if (values.length < 100) return result
  }
  fail('GitHub pagination exceeded the safety limit')
}

async function reviewThreads(github, owner, name, prNumber) {
  if (typeof github.graphql !== 'function') fail('GitHub GraphQL is unavailable')
  const threads = []
  let cursor = null
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const response = await github.graphql(
      `query PriceUpdateReviewThreads($owner: String!, $name: String!, $number: Int!, $cursor: String) {
        repository(owner: $owner, name: $name) {
          pullRequest(number: $number) {
            reviewThreads(first: 100, after: $cursor) {
              nodes {
                id isResolved
                comments(first: 100) { nodes { databaseId body url author { login } } pageInfo { hasNextPage endCursor } }
              }
              pageInfo { hasNextPage endCursor }
            }
          }
        }
      }`,
      { owner, name, number: prNumber, cursor },
    )
    if (response?.errors?.length) fail('GitHub review-thread query failed')
    const connection = response?.repository?.pullRequest?.reviewThreads
    if (!connection || !Array.isArray(connection.nodes) || !connection.pageInfo)
      fail('GitHub returned invalid review threads')
    for (const thread of connection.nodes) {
      const comments = thread.comments
      if (!comments || !Array.isArray(comments.nodes) || !comments.pageInfo)
        fail('GitHub returned invalid thread comments')
      let commentNodes = [...comments.nodes]
      let commentCursor = comments.pageInfo.endCursor
      for (let commentPage = 0; comments.pageInfo.hasNextPage; commentPage += 1) {
        if (commentPage >= MAX_PAGES || !commentCursor) fail('GitHub thread-comment pagination was truncated')
        const more = await github.graphql(
          `query PriceUpdateThreadComments($thread: ID!, $cursor: String) {
            node(id: $thread) {
              ... on PullRequestReviewThread {
                comments(first: 100, after: $cursor) { nodes { databaseId body url author { login } } pageInfo { hasNextPage endCursor } }
              }
            }
          }`,
          { thread: thread.id, cursor: commentCursor },
        )
        if (more?.errors?.length) fail('GitHub thread-comment query failed')
        const moreComments = more?.node?.comments
        if (!moreComments || !Array.isArray(moreComments.nodes) || !moreComments.pageInfo)
          fail('GitHub returned invalid thread comments')
        commentNodes.push(...moreComments.nodes)
        comments.pageInfo = moreComments.pageInfo
        commentCursor = comments.pageInfo.endCursor
      }
      threads.push({ ...thread, comments: commentNodes })
    }
    if (!connection.pageInfo.hasNextPage) return threads
    cursor = connection.pageInfo.endCursor
    if (!cursor) fail('GitHub review-thread pagination was truncated')
  }
  fail('GitHub review-thread pagination exceeded the safety limit')
}

function checkKey(check) {
  return `${check.app?.slug ?? ''}\0${check.name ?? ''}`
}

function latestBy(items, key, timestamp) {
  const selected = new Map()
  for (const item of items) {
    const id = key(item)
    const previous = selected.get(id)
    const currentTime = Date.parse(timestamp(item) ?? '') || 0
    const previousTime = previous ? Date.parse(timestamp(previous) ?? '') || 0 : 0
    if (
      !previous ||
      currentTime > previousTime ||
      (currentTime === previousTime && Number(item.id) > Number(previous.id))
    )
      selected.set(id, item)
  }
  return [...selected.values()]
}

function latestCheckAttempts(items) {
  const selected = new Map()
  for (const item of items) {
    const key = checkKey(item)
    const previous = selected.get(key)
    const currentId = Number(item.id)
    const previousId = Number(previous?.id)
    const currentIdIsNumeric = Number.isSafeInteger(currentId) && currentId > 0
    const previousIdIsNumeric = Number.isSafeInteger(previousId) && previousId > 0
    if (currentIdIsNumeric && previousIdIsNumeric && currentId !== previousId) {
      if (currentId > previousId) selected.set(key, item)
      continue
    }
    const currentTime = Date.parse(item.started_at ?? item.completed_at ?? '') || 0
    const previousTime = previous ? Date.parse(previous.started_at ?? previous.completed_at ?? '') || 0 : 0
    if (!previous || currentTime > previousTime || (currentTime === previousTime && currentId > previousId))
      selected.set(key, item)
  }
  return [...selected.values()]
}

function checkIsFailure(check) {
  return check.status === 'completed' && !['success', 'neutral', 'skipped', 'cancelled'].includes(check.conclusion)
}

function workflowPath(run) {
  return String(run.path ?? '').replace(/^\.\//, '')
}

function isSelfWaitCheck(check, workflowRuns) {
  if (check.app?.slug !== 'github-actions') return false
  return workflowRuns.some((run) => {
    if (!SELF_WAIT_WORKFLOWS.has(workflowPath(run))) return false
    const suiteId = check.check_suite?.id
    if (suiteId != null && run.check_suite_id != null) return String(suiteId) === String(run.check_suite_id)
    try {
      const path = new URL(check.details_url).pathname.split('/')
      return path.some(
        (part, index) => part === 'actions' && path[index + 1] === 'runs' && path[index + 2] === String(run.id),
      )
    } catch {
      return false
    }
  })
}

function finding({
  kind,
  id,
  body,
  url,
  replyTarget,
  reactionTarget,
  dismissible = true,
  source,
  threadId,
  commentId,
}) {
  return {
    kind,
    id,
    body: body ?? '',
    url: url ?? '',
    replyTarget: replyTarget ?? null,
    reactionTarget: reactionTarget ?? null,
    dismissible,
    source,
    ...(threadId ? { threadId } : {}),
    ...(commentId !== undefined ? { commentId } : {}),
  }
}

async function collectSnapshot(github, owner, name, prNumber) {
  const repo = fullName(owner, name)
  const getPR = () => github.rest.pulls.get({ owner, repo: name, pull_number: prNumber })
  const firstPR = (await getPR())?.data
  if (!firstPR || !firstPR.head?.sha) fail('GitHub returned an invalid pull request')
  const headSha = firstPR.head.sha
  const [checkRuns, statuses, workflowRuns, threads, issueComments, reviews] = await Promise.all([
    allPages(github.rest.checks.listForRef, { owner, repo: name, ref: headSha }, ['check_runs']),
    allPages(github.rest.repos.listCommitStatusesForRef, { owner, repo: name, ref: headSha }),
    allPages(github.rest.actions.listWorkflowRunsForRepo, { owner, repo: name, head_sha: headSha }, ['workflow_runs']),
    reviewThreads(github, owner, name, prNumber),
    allPages(github.rest.issues.listComments, { owner, repo: name, issue_number: prNumber }),
    allPages(github.rest.pulls.listReviews, { owner, repo: name, pull_number: prNumber }),
  ])
  const headChecks = checkRuns.filter((check) => check.head_sha === headSha)
  const annotatedChecks = await Promise.all(
    latestCheckAttempts(headChecks)
      .filter(
        (check) =>
          REVIEWERS.some((reviewer) => reviewer.app === check.app?.slug && reviewer.name === check.name) &&
          check.status === 'completed' &&
          ['success', 'neutral'].includes(check.conclusion) &&
          Number(check.output?.annotations_count) > 0,
      )
      .map(async (check) => [
        check.id,
        await allPages(github.rest.checks.listAnnotations, {
          owner,
          repo: name,
          check_run_id: check.id,
        }),
      ]),
  )
  const annotationsByCheck = new Map(annotatedChecks)
  const lastPR = (await getPR())?.data
  if (!lastPR || !lastPR.head?.sha) fail('GitHub returned an invalid pull request on recheck')
  const identityValid = isAutomationPR(firstPR, repo) && isAutomationPR(lastPR, repo)
  return {
    owner,
    repo: name,
    prNumber,
    headSha,
    currentHeadSha: lastPR.head.sha,
    headChanged: lastPR.head.sha !== headSha,
    identity: {
      number: firstPR.number ?? prNumber,
      url: firstPR.html_url ?? '',
      state: firstPR.state,
      baseRepo: repoFullName(firstPR.base?.repo),
      baseRef: firstPR.base?.ref,
      headRepo: repoFullName(firstPR.head?.repo),
      headRef: firstPR.head.ref,
      author: firstPR.user?.login,
    },
    identityValid,
    checkRuns: headChecks.map((check) => ({ ...check, annotations: annotationsByCheck.get(check.id) ?? [] })),
    statuses,
    workflowRuns: workflowRuns.filter((run) => run.head_sha === headSha),
    threads,
    issueComments,
    reviews,
  }
}

function evaluate(snapshot, assessments = []) {
  if (!snapshot || typeof snapshot !== 'object') fail('Invalid GitHub snapshot')
  const findings = []
  const waiting = []
  if (snapshot.headChanged || snapshot.currentHeadSha !== snapshot.headSha)
    waiting.push('PR head changed during collection')
  if (!snapshot.identityValid) waiting.push('PR is not an open automation proposal in this repository')

  const dismissals = new Set(
    assessments
      .filter(
        (assessment) =>
          assessment &&
          assessment.headSha === snapshot.headSha &&
          ['fixed', 'dismissed'].includes(assessment.action) &&
          typeof assessment.id === 'string' &&
          typeof assessment.evidence === 'string' &&
          assessment.evidence.trim().length > 0,
      )
      .map((assessment) => assessment.id),
  )
  const add = (item) => {
    const accepted =
      assessments.find(
        (assessment) =>
          assessment?.id === item.id &&
          assessment.headSha === snapshot.headSha &&
          assessment.action === 'dismissed' &&
          typeof assessment.evidence === 'string' &&
          assessment.evidence.trim().length > 0,
      ) ??
      assessments.find(
        (assessment) =>
          assessment?.id === item.id &&
          assessment.headSha === snapshot.headSha &&
          assessment.action === 'fixed' &&
          typeof assessment.evidence === 'string' &&
          assessment.evidence.trim().length > 0,
      )
    const acceptedAction = accepted?.action
    const assessed =
      item.dismissible &&
      dismissals.has(item.id) &&
      (acceptedAction === 'dismissed' || (acceptedAction === 'fixed' && ['comment', 'review'].includes(item.kind)))
    if (!assessed) findings.push(item)
  }

  const workflowRuns = snapshot.workflowRuns ?? []
  const checks = latestCheckAttempts(
    (snapshot.checkRuns ?? []).filter((check) => !isSelfWaitCheck(check, workflowRuns)),
  )
  for (const { app, name } of REVIEWERS) {
    const check = checks.find((item) => item.app?.slug === app && item.name === name)
    if (!check || check.status !== 'completed' || ['cancelled', 'skipped'].includes(check.conclusion)) {
      waiting.push(`Waiting for reviewer check ${name}`)
      continue
    }
    if (reviewUnavailable(check)) waiting.push(`Waiting for reviewer check ${name}: review quota exhausted`)
  }

  let ciSeen = false
  for (const check of checks) {
    if (check.status !== 'completed') {
      waiting.push(`Check ${check.name ?? check.id} is ${check.status ?? 'in progress'}`)
      continue
    }
    const requiredReviewer = REVIEWERS.some(
      (reviewer) => reviewer.app === check.app?.slug && reviewer.name === check.name,
    )
    if (requiredReviewer) {
      if (reviewUnavailable(check)) continue
      const body = check.output?.summary || check.output?.text
      const annotationEvidence = (check.annotations ?? [])
        .map((annotation) => {
          const location = `${annotation.path ?? 'unknown'}${annotation.start_line ? `:${annotation.start_line}` : ''}`
          const message =
            annotation.message || annotation.title || annotation.raw_details || 'Annotation details unavailable'
          return `${location}: ${annotation.annotation_level ?? 'notice'}: ${message}`
        })
        .join('\n')
      const evidence = []
      if (['success', 'neutral'].includes(check.conclusion) && Number(check.output?.annotations_count) > 0)
        evidence.push(
          annotationEvidence || `${check.name} check reports ${check.output.annotations_count} annotation(s).`,
        )
      if (
        check.conclusion !== 'success' &&
        check.conclusion !== 'cancelled' &&
        check.conclusion !== 'skipped' &&
        !(check.conclusion === 'neutral' && !body)
      )
        evidence.push(body || `${check.name} concluded ${check.conclusion}`)
      if (evidence.length)
        add(
          finding({
            kind: 'check',
            id: `check:${check.id}`,
            body: evidence.join('\n\n'),
            url: check.html_url,
            replyTarget: null,
            reactionTarget: check.id,
            source: 'check',
            dismissible: true,
          }),
        )
      continue
    }
    if (checkIsFailure(check))
      add(
        finding({
          kind: 'ci',
          id: `check:${check.id}`,
          body: check.output?.summary || check.output?.text || `${check.name} concluded ${check.conclusion}`,
          url: check.html_url,
          reactionTarget: check.id,
          source: 'check',
          dismissible: false,
        }),
      )
  }
  for (const status of latestBy(
    snapshot.statuses ?? [],
    (item) => item.context ?? '',
    (item) => item.updated_at ?? item.created_at,
  )) {
    if (status.state === 'pending') waiting.push(`Status ${status.context} is pending`)
    else if (status.state !== 'success')
      add(
        finding({
          kind: 'ci',
          id: `status:${status.id}`,
          body: status.description || `${status.context} is ${status.state}`,
          url: status.target_url,
          reactionTarget: status.id,
          source: 'status',
          dismissible: false,
        }),
      )
  }

  const workflowAttempts = latestBy(
    workflowRuns,
    (run) => workflowPath(run),
    (run) => run.run_started_at ?? run.created_at ?? run.updated_at,
  )
  for (const run of workflowAttempts) {
    const path = workflowPath(run)
    if (SELF_WAIT_WORKFLOWS.has(path)) continue
    if (path === CI_WORKFLOW) ciSeen = true
    if (run.status !== 'completed') {
      waiting.push(`Workflow ${run.name ?? run.id} is ${run.status ?? 'in progress'}`)
      continue
    }
    if (
      run.conclusion !== 'success' &&
      (path === CI_WORKFLOW || !['neutral', 'skipped', 'cancelled'].includes(run.conclusion))
    )
      add(
        finding({
          kind: 'ci',
          id: `workflow:${run.id}`,
          body: run.display_title || `${run.name} concluded ${run.conclusion}`,
          url: run.html_url,
          reactionTarget: run.id,
          source: 'workflow',
          dismissible: false,
        }),
      )
  }
  const ciRun = workflowAttempts.find((run) => workflowPath(run) === CI_WORKFLOW)
  if (!ciSeen || !ciRun || ciRun.status !== 'completed')
    waiting.push('CI workflow ci.yml has not completed successfully on this head')

  for (const thread of snapshot.threads ?? []) {
    if (thread.isResolved) continue
    const firstComment = thread.comments?.[0]
    if (!firstComment || firstComment.databaseId == null || !Number.isSafeInteger(Number(firstComment.databaseId)))
      fail('Unresolved review thread has no numeric comment ID')
    const commentId = Number(firstComment.databaseId)
    findings.push(
      finding({
        kind: 'thread',
        id: `thread:${thread.id}`,
        body: firstComment.body,
        url: firstComment.url,
        replyTarget: commentId,
        reactionTarget: commentId,
        threadId: thread.id,
        commentId,
        source: 'review-thread',
        dismissible: false,
      }),
    )
  }
  for (const comment of snapshot.issueComments ?? []) {
    if (!HOSTED_REVIEWERS.has(comment.user?.login) || !comment.body?.trim()) continue
    add(
      finding({
        kind: 'comment',
        id: `comment:${comment.id}`,
        body: comment.body,
        url: comment.html_url,
        replyTarget: comment.id,
        reactionTarget: comment.id,
        commentId: comment.id,
        source: 'issue-comment',
      }),
    )
  }
  const latestReviews = latestBy(
    (snapshot.reviews ?? []).filter(
      (review) =>
        review.commit_id === snapshot.headSha && ['CHANGES_REQUESTED', 'APPROVED', 'DISMISSED'].includes(review.state),
    ),
    (review) => review.user?.login ?? `review:${review.id}`,
    (review) => review.submitted_at,
  )
  for (const review of latestReviews) {
    if (review.state !== 'CHANGES_REQUESTED') continue
    add(
      finding({
        kind: 'review',
        id: `review:${review.id}`,
        body: review.body,
        url: review.html_url,
        replyTarget: review.id,
        reactionTarget: review.id,
        source: 'review',
      }),
    )
  }

  const reason = waiting.length
    ? waiting.join('; ')
    : findings.length
      ? 'Review findings need repair or explicit assessment'
      : 'All checks and reviews are clear for this head'
  return { state: waiting.length ? 'waiting' : findings.length ? 'repair' : 'ready', findings, reason }
}

module.exports = { collectSnapshot, evaluate, isAutomationPR }
