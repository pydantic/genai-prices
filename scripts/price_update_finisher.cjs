const fs = require('node:fs')
const path = require('node:path')
const { execFileSync } = require('node:child_process')
const { collectSnapshot, evaluate } = require('./price_update_readiness.cjs')

const MARKER = '<!-- price-update-finisher-state\n'
const REPAIR_WORKFLOW = 'repair-price-update.lock.yml'
const MAX_ATTEMPTS = 3
const BRANCHES = ['automation/hourly-price-update', 'automation/weekly-price-update']

function readState(comments) {
  const states = comments.filter(
    (comment) => comment.user?.login === 'github-actions[bot]' && comment.body?.startsWith(MARKER),
  )
  if (!states.length) return { attempts: 0, assessments: [] }
  const comment = states.at(-1)
  const raw = comment.body.split(MARKER)[1].split('\n-->')[0]
  const state = JSON.parse(raw)
  if (
    !Number.isSafeInteger(state.attempts) ||
    state.attempts < 0 ||
    state.attempts > MAX_ATTEMPTS ||
    !Array.isArray(state.assessments)
  )
    throw new Error('Invalid finisher state')
  if (
    state.reviewRequests &&
    (!Array.isArray(state.reviewRequests) ||
      !state.reviewRequests.every((sha) => typeof sha === 'string' && /^[a-f0-9]{40}$/.test(sha)))
  )
    throw new Error('Invalid reviewer request state')
  return { ...state, commentId: comment.id }
}

async function writeState(github, repo, prNumber, state, message) {
  const body = `${MARKER}${JSON.stringify(state)}\n-->\n\n${message}`
  if (state.commentId) {
    await github.rest.issues.updateComment({ ...repo, comment_id: state.commentId, body })
    return state.commentId
  }
  const response = await github.rest.issues.createComment({ ...repo, issue_number: prNumber, body })
  return response.data.id
}

async function assertHead(github, repo, prNumber, expectedHead) {
  const { data: pr } = await github.rest.pulls.get({ ...repo, pull_number: prNumber })
  if (
    pr.state !== 'open' ||
    pr.base?.ref !== 'main' ||
    pr.head.sha !== expectedHead ||
    !BRANCHES.includes(pr.head.ref) ||
    pr.head.repo?.full_name !== `${repo.owner}/${repo.repo}` ||
    pr.user.login !== 'genai-prices-automation[bot]'
  ) {
    throw new Error('Price proposal identity or head changed')
  }
  return pr
}

async function watchOne({
  github,
  repo,
  prNumber,
  core,
  requestId,
  now = Date.now,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  timeoutMs = 30 * 60 * 1000,
  collect = collectSnapshot,
  assess = evaluate,
}) {
  const deadline = now() + timeoutMs
  const missingReviewerSince = new Map()
  while (now() < deadline) {
    const snapshot = await collect(github, repo.owner, repo.repo, prNumber)
    const state = readState(snapshot.issueComments)
    const result = assess(snapshot, state.assessments)
    core.info(`#${prNumber}: ${result.state}: ${result.reason}`)
    if (result.state === 'waiting') {
      const cubic = snapshot.checkRuns?.find(
        (check) => check.app?.slug === 'cubic-dev-ai' && check.name === 'cubic · AI code reviewer',
      )
      if (!cubic && !state.reviewRequests?.includes(snapshot.headSha)) {
        if (!missingReviewerSince.has(snapshot.headSha)) missingReviewerSince.set(snapshot.headSha, now())
        if (now() - missingReviewerSince.get(snapshot.headSha) >= 120_000) {
          await assertHead(github, repo, prNumber, snapshot.headSha)
          await github.rest.issues.createComment({
            ...repo,
            issue_number: prNumber,
            body: `@cubic-dev-ai review this PR\n\nRequired review requested for ${snapshot.headSha}.`,
          })
          await writeState(
            github,
            repo,
            prNumber,
            { ...state, reviewRequests: [...(state.reviewRequests || []), snapshot.headSha] },
            `Waiting for the required cubic review for ${snapshot.headSha}.`,
          )
        }
      }
      await sleep(30_000)
      continue
    }
    await assertHead(github, repo, prNumber, snapshot.headSha)
    if (result.state === 'ready') {
      await writeState(
        github,
        repo,
        prNumber,
        { ...state, headSha: snapshot.headSha, status: 'ready' },
        `Ready for maintainer review at ${snapshot.headSha}: CI, Macroscope, and cubic completed; no unresolved findings. No merge was performed.`,
      )
      return 'ready'
    }
    if (state.status === 'blocked')
      throw new Error(`#${prNumber}: repair requires maintainer action; see the tracked findings`)
    if (state.status === 'repair-requested') {
      const active = await Promise.all(
        ['queued', 'in_progress'].map((status) =>
          github.paginate(github.rest.actions.listWorkflowRuns, {
            ...repo,
            workflow_id: REPAIR_WORKFLOW,
            status,
            per_page: 100,
          }),
        ),
      )
      if (active.flat().length || now() - state.requestedAt < 120_000) {
        await sleep(30_000)
        continue
      }
    }
    if (state.attempts >= MAX_ATTEMPTS)
      throw new Error(`#${prNumber}: repair limit reached; unresolved findings remain`)
    const attempt = state.attempts + 1
    const id = `${requestId}-${prNumber}-${attempt}`
    const next = {
      ...state,
      attempts: attempt,
      headSha: snapshot.headSha,
      requestId: id,
      status: 'repair-requested',
      requestedAt: now(),
    }
    const commentId = await writeState(
      github,
      repo,
      prNumber,
      next,
      `Assessing CI and hosted review findings at ${snapshot.headSha} (repair attempt ${attempt}/${MAX_ATTEMPTS}).`,
    )
    // Persist the bounded attempt before dispatch. A failed dispatch never creates an uncounted retry.
    await github.rest.repos.createDispatchEvent({
      ...repo,
      event_type: 'price-update-repair',
      client_payload: {
        pr_number: prNumber,
        head_sha: snapshot.headSha,
        request_id: id,
        state_comment_id: commentId,
      },
    })
    return 'repair-requested'
  }
  throw new Error(`#${prNumber}: timed out waiting for head-specific CI, Macroscope, and cubic`)
}

async function watch({ github, context, core }) {
  const repo = context.repo
  let prs
  const selected = context.payload.inputs?.pr_number
  if (selected) {
    const number = Number(selected)
    if (!Number.isSafeInteger(number) || number <= 0) throw new Error('Invalid PR number')
    prs = [number]
  } else {
    const proposals = await Promise.all(
      BRANCHES.map((branch) =>
        github.paginate(github.rest.pulls.list, {
          ...repo,
          state: 'open',
          head: `${repo.owner}:${branch}`,
          per_page: 100,
        }),
      ),
    )
    prs = proposals.flat().map((pr) => pr.number)
  }
  for (const prNumber of prs) await watchOne({ github, repo, prNumber, core, requestId: String(context.runId) })
  await core.summary
    .addRaw(
      prs.length
        ? 'Inspected price proposals. A dispatched repair continues in Price update repair.\n'
        : 'No open price proposals.\n',
    )
    .write()
}

async function claim({ github, context, core }) {
  const input = context.payload.client_payload
  if (
    !input ||
    !Number.isSafeInteger(input.pr_number) ||
    input.pr_number <= 0 ||
    !/^[a-f0-9]{40}$/.test(input.head_sha) ||
    !/^[0-9]+-[0-9]+-[1-3]$/.test(input.request_id) ||
    !Number.isSafeInteger(input.state_comment_id)
  )
    throw new Error('Invalid repair request')
  const repo = context.repo
  await assertHead(github, repo, input.pr_number, input.head_sha)
  const comments = await github.paginate(github.rest.issues.listComments, {
    ...repo,
    issue_number: input.pr_number,
    per_page: 100,
  })
  const state = readState(comments)
  if (
    state.commentId !== input.state_comment_id ||
    state.headSha !== input.head_sha ||
    state.requestId !== input.request_id ||
    state.status !== 'repair-requested'
  )
    throw new Error('Unclaimed repair request')
  const snapshot = await collectSnapshot(github, repo.owner, repo.repo, input.pr_number)
  const result = evaluate(snapshot, state.assessments)
  if (snapshot.headSha !== input.head_sha || result.state !== 'repair')
    throw new Error('Repair snapshot is no longer actionable')
  const logs = []
  for (const run of snapshot.workflowRuns) {
    if (run.conclusion !== 'failure') continue
    const text = execFileSync(
      'gh',
      ['run', 'view', String(run.id), '--repo', `${repo.owner}/${repo.repo}`, '--log-failed'],
      { encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 },
    )
    logs.push({ runId: run.id, log: text })
  }
  const expected = {
    prNumber: input.pr_number,
    headSha: input.head_sha,
    requestId: input.request_id,
    findings: result.findings,
  }
  const directory = path.join(process.env.RUNNER_TEMP, 'price-repair-context')
  fs.mkdirSync(directory, { recursive: true })
  fs.writeFileSync(path.join(directory, 'context.json'), JSON.stringify({ expected, snapshot, logs }))
  core.setOutput('context', directory)
  core.setOutput('head', input.head_sha)
  core.setOutput('pr', String(input.pr_number))
  core.setOutput('request', input.request_id)
}

function loadExpected(directory) {
  return JSON.parse(fs.readFileSync(path.join(directory, 'context.json'), 'utf8')).expected
}

async function recordResult({ github, context, core, expected, report, publishedHead }) {
  const repo = context.repo
  const { validateAssessment } = require('./price_update_repair_policy.cjs')
  validateAssessment(report, expected)
  await assertHead(github, repo, expected.prNumber, publishedHead)
  const state = readState(
    await github.paginate(github.rest.issues.listComments, {
      ...repo,
      issue_number: expected.prNumber,
      per_page: 100,
    }),
  )
  if (state.requestId !== expected.requestId || state.headSha !== expected.headSha)
    throw new Error('Repair claim changed')
  for (const assessment of report.assessments) {
    const finding = expected.findings.find((entry) => entry.id === assessment.id)
    const body = `**${assessment.verdict}** — ${assessment.evidence}\n\nAssessed against ${expected.headSha}; result at ${publishedHead}.`
    await assertHead(github, repo, expected.prNumber, publishedHead)
    if (finding.kind === 'thread') {
      await github.rest.reactions.createForPullRequestReviewComment({
        ...repo,
        comment_id: finding.commentId,
        content: assessment.action === 'dismissed' ? '-1' : '+1',
      })
      await assertHead(github, repo, expected.prNumber, publishedHead)
      await github.rest.pulls.createReplyForReviewComment({
        ...repo,
        pull_number: expected.prNumber,
        comment_id: finding.commentId,
        body,
      })
      if (assessment.action !== 'blocked') {
        await assertHead(github, repo, expected.prNumber, publishedHead)
        await github.graphql('mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}', {
          id: finding.threadId,
        })
      }
    } else {
      if (finding.kind === 'comment') {
        await github.rest.reactions.createForIssueComment({
          ...repo,
          comment_id: finding.commentId,
          content: assessment.action === 'dismissed' ? '-1' : '+1',
        })
      }
      await assertHead(github, repo, expected.prNumber, publishedHead)
      await github.rest.issues.createComment({
        ...repo,
        issue_number: expected.prNumber,
        body: `${body}\n\nFinding: ${finding.url || finding.id}`,
      })
    }
  }
  await assertHead(github, repo, expected.prNumber, publishedHead)
  const blocked = report.assessments.some((entry) => entry.action === 'blocked')
  await writeState(
    github,
    repo,
    expected.prNumber,
    {
      ...state,
      headSha: publishedHead,
      status: blocked ? 'blocked' : 'assessed',
      assessments: [
        ...state.assessments.filter(
          (entry) =>
            entry.headSha === expected.headSha && !report.assessments.some((current) => current.id === entry.id),
        ),
        ...report.assessments,
      ].map((entry) => ({ ...entry, headSha: publishedHead })),
    },
    blocked
      ? 'Some findings require maintainer action; the findings above remain tracked and unresolved.'
      : `Assessment completed at ${publishedHead}. Waiting for CI, Macroscope, and cubic before readiness.`,
  )
  core.setOutput('blocked', String(blocked))
}

module.exports = {
  readState,
  writeState,
  assertHead,
  watchOne,
  watch,
  claim,
  loadExpected,
  recordResult,
  REPAIR_WORKFLOW,
}
