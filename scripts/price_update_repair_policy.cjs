'use strict'

const { execFileSync } = require('node:child_process')
const { createHash } = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')

const MAX_PATCH_BYTES = 20 * 1024 * 1024
const MAX_REPORT_BYTES = 128 * 1024
const MAX_ID_LENGTH = 200
const VERDICTS = [
  'net-positive → do',
  'net-positive but out-of-scope → defer',
  'net-neutral → skip',
  'net-negative → skip',
]

const gitEnv = {
  ...process.env,
  GIT_CONFIG_NOSYSTEM: '1',
  GIT_CONFIG_GLOBAL: process.platform === 'win32' ? 'NUL' : '/dev/null',
  GIT_TERMINAL_PROMPT: '0',
  GIT_PAGER: 'cat',
  PAGER: 'cat',
}

function fail(message) {
  throw new Error(message)
}

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function boundedString(value, label) {
  if (typeof value !== 'string' || value.length === 0 || value.length > MAX_ID_LENGTH || value.trim() !== value) {
    fail(`${label} must be a nonempty string of at most ${MAX_ID_LENGTH} characters`)
  }
  return value
}

function validateExpected(expected) {
  if (!isRecord(expected)) fail('expected must be an object')
  if (!Number.isSafeInteger(expected.prNumber) || expected.prNumber <= 0)
    fail('expected.prNumber must be a positive integer')
  boundedString(expected.headSha, 'expected.headSha')
  boundedString(expected.requestId, 'expected.requestId')
  if (!Array.isArray(expected.findings)) fail('expected.findings must be an array')

  const findings = new Map()
  for (const finding of expected.findings) {
    if (!isRecord(finding)) fail('each expected finding must be an object')
    const id = boundedString(finding.id, 'expected finding id')
    if (findings.has(id)) fail(`duplicate expected finding id: ${id}`)
    if (!['thread', 'check', 'comment', 'review', 'ci'].includes(finding.kind))
      fail(`expected finding ${id} has an invalid kind`)
    findings.set(id, finding)
  }
  return findings
}

function validateAssessment(report, expected) {
  const expectedFindings = validateExpected(expected)
  if (!isRecord(report)) fail('assessment report must be an object')
  if (report.prNumber !== expected.prNumber) fail('assessment report PR number does not match')
  if (report.headSha !== expected.headSha) fail('assessment report head SHA does not match')
  if (report.requestId !== expected.requestId) fail('assessment report request ID does not match')
  if (!Array.isArray(report.assessments)) fail('assessment report assessments must be an array')
  if (report.assessments.length !== expectedFindings.size)
    fail('assessment report must contain exactly one assessment per expected finding')

  const seen = new Set()
  const assessments = report.assessments.map((assessment) => {
    if (!isRecord(assessment)) fail('each assessment must be an object')
    const id = boundedString(assessment.id, 'assessment id')
    if (seen.has(id)) fail(`duplicate assessment id: ${id}`)
    const finding = expectedFindings.get(id)
    if (!finding) fail(`unknown assessment id: ${id}`)
    if (!['fixed', 'dismissed', 'blocked'].includes(assessment.action)) fail(`assessment ${id} has an invalid action`)
    if (!VERDICTS.includes(assessment.verdict)) fail(`assessment ${id} has an invalid verdict`)
    if (assessment.action === 'fixed' && assessment.verdict !== 'net-positive → do') {
      fail(`fixed assessment ${id} must have the net-positive do verdict`)
    }
    if (
      assessment.action === 'dismissed' &&
      !['net-neutral → skip', 'net-negative → skip'].includes(assessment.verdict)
    ) {
      fail(`dismissed assessment ${id} must have a skip verdict`)
    }
    if (assessment.action === 'blocked' && assessment.verdict !== 'net-positive but out-of-scope → defer') {
      fail(`blocked assessment ${id} must have the net-positive defer verdict`)
    }
    if (typeof assessment.evidence !== 'string' || assessment.evidence.trim().length === 0) {
      fail(`assessment ${id} must include nonempty evidence`)
    }
    if (finding.kind === 'ci' && assessment.action === 'dismissed') fail(`CI finding ${id} cannot be dismissed`)
    seen.add(id)
    return { id, action: assessment.action, verdict: assessment.verdict, evidence: assessment.evidence }
  })

  return {
    prNumber: report.prNumber,
    headSha: report.headSha,
    requestId: report.requestId,
    assessments,
  }
}

function readBoundedRegularFile(filePath, maxBytes, label) {
  const absolutePath = path.resolve(filePath)
  let stat
  try {
    stat = fs.lstatSync(absolutePath)
  } catch (error) {
    fail(`${label} cannot be read: ${error.message}`)
  }
  if (stat.isSymbolicLink() || !stat.isFile()) fail(`${label} must be a regular non-symlink file`)
  if (stat.size > maxBytes) fail(`${label} exceeds the ${maxBytes}-byte limit`)
  return { absolutePath, contents: fs.readFileSync(absolutePath) }
}

function runGit(directory, args, options = {}) {
  try {
    return execFileSync('git', args, {
      cwd: directory,
      env: gitEnv,
      encoding: options.encoding,
      maxBuffer: MAX_PATCH_BYTES + MAX_REPORT_BYTES,
      stdio: options.stdio || ['ignore', 'pipe', 'pipe'],
    })
  } catch (error) {
    const detail = error.stderr ? String(error.stderr).trim() : error.message
    fail(`git ${args[0]} failed${detail ? `: ${detail}` : ''}`)
  }
}

function allowedPath(filePath) {
  if (filePath.includes('\\') || filePath.startsWith('/') || filePath.split('/').includes('..')) return false
  return (
    (/^prices\/providers\/[^/]+\.yml$/.test(filePath) && !filePath.endsWith('.schema.yml')) ||
    /^prices\/src\/prices\/(?:source_[^/]+|update|variants|proposed_start_dates)\.py$/.test(filePath) ||
    /^tests\/test_[^/]+\.py$/.test(filePath) ||
    /^packages\/js\/src\/__tests__\/[^/]+(?:\/[^/]+)*\.ts$/.test(filePath) ||
    /^packages\/go\/[^/]+_test\.go$/.test(filePath) ||
    [
      'prices/new_data/v2/data.json',
      'prices/new_data/v2/data_slim.json',
      'packages/python/genai_prices/data.py',
      'packages/js/src/data.ts',
      'packages/go/internal/data/prices.json',
      'tests/dataset/usages.json',
    ].includes(filePath)
  )
}

function testCounts(filePath, contents) {
  const text = contents.toString('utf8')
  if (/^tests\/test_[^/]+\.py$/.test(filePath)) {
    return {
      declarations: [...text.matchAll(/^\s*(?:async\s+)?def\s+test_[A-Za-z0-9_]+\s*\(/gm)].length,
      assertions: [...text.matchAll(/^\s*assert\b|\bpytest\.(?:raises|warns)\s*\(/gm)].length,
    }
  }
  if (/^packages\/js\/src\/__tests__\/[^/]+(?:\/[^/]+)*\.ts$/.test(filePath)) {
    return {
      declarations: [...text.matchAll(/\b(?:it|test)(?:\.(?:each|only|skip|todo|concurrent))*\s*\(/g)].length,
      assertions: [...text.matchAll(/\bexpect\s*\(|\bassert(?:\s*\(|\.[A-Za-z_$][\w$]*\s*\()/g)].length,
    }
  }
  if (/^packages\/go\/[^/]+_test\.go$/.test(filePath)) {
    return {
      declarations: [...text.matchAll(/^\s*func\s+Test[A-Z][A-Za-z0-9_]*\s*\(|\bt\.Run\s*\(/gm)].length,
      assertions: [...text.matchAll(/\bt\.(?:Error|Errorf|Fatal|Fatalf|Fail|FailNow)\s*\(/g)].length,
    }
  }
  return null
}

function validateTestCounts(directory, entry, stagedContents) {
  if (entry.status !== 'M') return
  const stagedCounts = testCounts(entry.filePath, stagedContents)
  if (!stagedCounts) return
  const baselineContents = runGit(directory, ['cat-file', 'blob', `HEAD:${entry.filePath}`])
  const baselineCounts = testCounts(entry.filePath, baselineContents)
  if (!baselineCounts) return
  if (stagedCounts.declarations < baselineCounts.declarations || stagedCounts.assertions < baselineCounts.assertions) {
    fail(
      `test-count floor failed for ${entry.filePath}: ` +
        `declarations ${baselineCounts.declarations} -> ${stagedCounts.declarations}, ` +
        `assertions ${baselineCounts.assertions} -> ${stagedCounts.assertions}`,
    )
  }
}

function parseRawDiff(output) {
  const fields = output.toString('utf8').split('\0')
  if (fields.pop() !== '') fail('could not parse staged path metadata')
  const entries = []
  for (let index = 0; index < fields.length; ) {
    const metadata = fields[index++]
    const match = /^:([0-7]{6}) ([0-7]{6}) [0-9a-f]+ [0-9a-f]+ ([A-Z])$/.exec(metadata)
    if (!match || index >= fields.length) fail('could not parse staged path metadata')
    entries.push({ oldMode: match[1], newMode: match[2], status: match[3], filePath: fields[index++] })
  }
  return entries
}

function inspectStagedChanges(directory) {
  const raw = runGit(directory, [
    'diff',
    '--cached',
    '--raw',
    '--no-abbrev',
    '--no-renames',
    '--no-ext-diff',
    '--no-textconv',
    '-z',
  ])
  const entries = parseRawDiff(raw)
  const numstat = runGit(directory, [
    'diff',
    '--cached',
    '--numstat',
    '--no-renames',
    '--no-ext-diff',
    '--no-textconv',
    '-z',
  ]).toString('utf8')
  const numstatEntries = numstat
    .split('\0')
    .filter(Boolean)
    .map((entry) => entry.split('\t'))
  const binaryPaths = numstatEntries.filter((entry) => entry[0] === '-' || entry[1] === '-').map((entry) => entry[2])
  if (binaryPaths.length) fail(`binary patch content is forbidden: ${binaryPaths.join(', ')}`)

  for (const entry of entries) {
    if (entry.status !== 'A' && entry.status !== 'M')
      fail(`staged ${entry.status} changes are forbidden: ${entry.filePath}`)
    if (entry.newMode !== '100644' || (entry.status === 'M' && entry.oldMode !== '100644')) {
      fail(`staged file mode is forbidden: ${entry.filePath}`)
    }
    if (!allowedPath(entry.filePath)) fail(`staged path is outside the repair allowlist: ${entry.filePath}`)
    const contents = runGit(directory, ['cat-file', 'blob', `:${entry.filePath}`])
    if (contents.includes(0) || !Buffer.from(contents.toString('utf8'), 'utf8').equals(contents)) {
      fail(`staged file must contain UTF-8 text: ${entry.filePath}`)
    }
    validateTestCounts(directory, entry, contents)
  }
  return entries.map((entry) => entry.filePath).sort()
}

function applyPatch({ directory, patchPath, reportPath, expected }) {
  const patch = readBoundedRegularFile(patchPath, MAX_PATCH_BYTES, 'patch')
  const reportFile = readBoundedRegularFile(reportPath, MAX_REPORT_BYTES, 'assessment report')
  let parsedReport
  try {
    parsedReport = JSON.parse(reportFile.contents.toString('utf8'))
  } catch (error) {
    fail(`assessment report is not valid JSON: ${error.message}`)
  }
  const report = validateAssessment(parsedReport, expected)
  const patchSha256 = createHash('sha256').update(patch.contents).digest('hex')
  const reportSha256 = createHash('sha256').update(reportFile.contents).digest('hex')

  const candidateDirectory = path.resolve(directory)
  const actualHead = runGit(candidateDirectory, ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
  if (actualHead !== expected.headSha) fail('candidate HEAD does not match expected head SHA')
  const status = runGit(candidateDirectory, ['status', '--porcelain=v1', '--untracked-files=all'], {
    encoding: 'utf8',
  })
  if (status !== '') fail('candidate index and worktree must be clean')

  try {
    if (patch.contents.length > 0) {
      runGit(candidateDirectory, ['apply', '--index', '--binary', '--', patch.absolutePath], {
        stdio: ['ignore', 'ignore', 'pipe'],
      })
    } else if (report.assessments.some((assessment) => assessment.action === 'fixed')) {
      fail('a fixed assessment requires a nonempty patch')
    }
    runGit(candidateDirectory, ['diff', '--quiet'], { stdio: ['ignore', 'ignore', 'pipe'] })
    const changedPaths = inspectStagedChanges(candidateDirectory)
    return { report, patchSha256, reportSha256, changedPaths }
  } catch (error) {
    // The clean-candidate precondition means reset only removes changes from this patch application.
    runGit(candidateDirectory, ['reset', '--hard', expected.headSha], { stdio: ['ignore', 'ignore', 'pipe'] })
    throw error
  }
}

module.exports = { validateAssessment, applyPatch }
