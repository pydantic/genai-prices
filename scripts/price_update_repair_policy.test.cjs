'use strict'

const assert = require('node:assert/strict')
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { test } = require('node:test')

const { applyPatch, validateAssessment } = require('./price_update_repair_policy.cjs')

const ACTION_VERDICTS = {
  fixed: 'net-positive → do',
  dismissed: 'net-neutral → skip',
  blocked: 'net-positive but out-of-scope → defer',
}

function git(directory, args, options = {}) {
  return execFileSync('git', args, {
    cwd: directory,
    encoding: options.encoding,
    env: { ...process.env, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null' },
  })
}

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'price-repair-policy-'))
  const directory = path.join(root, 'candidate')
  fs.mkdirSync(directory)
  git(directory, ['init', '--quiet'])
  git(directory, ['config', 'user.name', 'Policy Test'])
  git(directory, ['config', 'user.email', 'policy@example.test'])
  fs.mkdirSync(path.join(directory, 'prices', 'providers'), { recursive: true })
  fs.writeFileSync(
    path.join(directory, 'prices', 'providers', 'example.yml'),
    'prices_checked: 2026-10-20\nprices:\n  input_mtok: 1.0\n',
  )
  fs.mkdirSync(path.join(directory, 'tests'), { recursive: true })
  fs.writeFileSync(path.join(directory, 'tests', 'test_floor.py'), 'def test_kept():\n    assert 1 == 1\n')
  fs.writeFileSync(path.join(directory, 'tests', 'test_empty.py'), 'def test_empty():\n    pass\n')
  fs.writeFileSync(path.join(directory, 'tests', 'test_async.py'), 'async def test_async():\n    pass\n')
  fs.mkdirSync(path.join(directory, 'packages', 'js', 'src', '__tests__'), { recursive: true })
  fs.writeFileSync(
    path.join(directory, 'packages', 'js', 'src', '__tests__', 'floor.test.ts'),
    "test('kept', () => {\n  expect(1).toBe(1)\n})\ntest.each([1])('parameterized', (number) => {\n  expect(number).toBe(1)\n})\n",
  )
  fs.mkdirSync(path.join(directory, 'packages', 'go'), { recursive: true })
  fs.writeFileSync(
    path.join(directory, 'packages', 'go', 'floor_test.go'),
    'package example\n\nimport "testing"\n\nfunc TestKept(t *testing.T) {\n  if 1 != 1 { t.Error("not equal") }\n}\n',
  )
  fs.writeFileSync(path.join(directory, 'README.md'), 'base\n')
  git(directory, ['add', '--all'])
  git(directory, ['commit', '--quiet', '-m', 'base'])
  const headSha = git(directory, ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
  const patchPath = path.join(root, 'repair.patch')
  const reportPath = path.join(root, 'assessment.json')
  const expected = {
    prNumber: 12,
    headSha,
    requestId: 'request-1',
    findings: [{ id: 'finding-1', kind: 'review' }],
  }
  const report = {
    prNumber: expected.prNumber,
    headSha: expected.headSha,
    requestId: expected.requestId,
    assessments: [
      {
        id: 'finding-1',
        action: 'fixed',
        verdict: ACTION_VERDICTS.fixed,
        evidence: 'The source confirms this correction.',
      },
    ],
  }
  fs.writeFileSync(reportPath, JSON.stringify(report))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  return { root, directory, patchPath, reportPath, expected, report }
}

function writePatch(fixtureValue, mutate) {
  mutate(fixtureValue.directory)
  git(fixtureValue.directory, ['add', '--all'])
  const patchBytes = git(fixtureValue.directory, ['diff', '--cached', '--binary', 'HEAD'])
  fs.writeFileSync(fixtureValue.patchPath, patchBytes)
  git(fixtureValue.directory, ['reset', '--hard', 'HEAD'])
  return patchBytes
}

function setReport(fixtureValue, report = fixtureValue.report) {
  fs.writeFileSync(fixtureValue.reportPath, JSON.stringify(report))
}

test('applies an allowed text patch and returns hashes and changed paths', (t) => {
  const value = fixture(t)
  writePatch(value, (directory) => {
    const providerPath = path.join(directory, 'prices', 'providers', 'example.yml')
    const providerYaml = fs.readFileSync(providerPath, 'utf8')
    fs.writeFileSync(
      providerPath,
      providerYaml
        .replace('prices_checked: 2026-10-20', 'prices_checked: 2026-10-21')
        .replace('input_mtok: 1.0', 'input_mtok: 2.0'),
    )
  })

  const result = applyPatch({ ...value, directory: value.directory })

  assert.equal(result.report.assessments[0].evidence, value.report.assessments[0].evidence)
  assert.match(result.patchSha256, /^[0-9a-f]{64}$/)
  assert.match(result.reportSha256, /^[0-9a-f]{64}$/)
  assert.deepEqual(result.changedPaths, ['prices/providers/example.yml'])
  assert.equal(
    git(value.directory, ['diff', '--cached', '--name-only'], { encoding: 'utf8' }).trim(),
    'prices/providers/example.yml',
  )
})

test('rejects a forbidden path and resets the candidate', (t) => {
  const value = fixture(t)
  writePatch(value, (directory) => fs.writeFileSync(path.join(directory, 'prices', 'units.yml'), 'units: []\n'))

  assert.throws(() => applyPatch(value), /outside the repair allowlist/)
  assert.equal(git(value.directory, ['status', '--porcelain'], { encoding: 'utf8' }), '')
})

test('rejects symlinks in staged changes', (t) => {
  const value = fixture(t)
  writePatch(value, (directory) => {
    const target = path.join(directory, 'prices', 'providers', 'example.yml')
    fs.unlinkSync(target)
    fs.symlinkSync('README.md', target)
  })

  assert.throws(() => applyPatch(value), /staged [A-Z]+ changes|file mode is forbidden/)
})

test('rejects deletion patches', (t) => {
  const value = fixture(t)
  writePatch(value, (directory) => fs.unlinkSync(path.join(directory, 'prices', 'providers', 'example.yml')))

  assert.throws(() => applyPatch(value), /staged D changes are forbidden/)
})

test('rejects Python assertion removal', (t) => {
  const value = fixture(t)
  writePatch(value, (directory) => {
    const testPath = path.join(directory, 'tests', 'test_floor.py')
    fs.writeFileSync(testPath, fs.readFileSync(testPath, 'utf8').replace('    assert 1 == 1\n', '    pass\n'))
  })

  assert.throws(() => applyPatch(value), /test-count floor failed for tests\/test_floor\.py/)
})

test('rejects a Python test declaration removal even when it had no assertions', (t) => {
  const value = fixture(t)
  writePatch(value, (directory) => fs.writeFileSync(path.join(directory, 'tests', 'test_empty.py'), ''))

  assert.throws(() => applyPatch(value), /declarations 1 -> 0, assertions 0 -> 0/)
})

test('counts async Python test declarations', (t) => {
  const value = fixture(t)
  writePatch(value, (directory) => fs.writeFileSync(path.join(directory, 'tests', 'test_async.py'), ''))

  assert.throws(() => applyPatch(value), /declarations 1 -> 0, assertions 0 -> 0/)
})

test('counts JavaScript test.each declarations', (t) => {
  const value = fixture(t)
  writePatch(value, (directory) => {
    const testPath = path.join(directory, 'packages', 'js', 'src', '__tests__', 'floor.test.ts')
    const contents = fs.readFileSync(testPath, 'utf8')
    const parameterizedTest = "test.each([1])('parameterized', (number) => {\n  expect(number).toBe(1)\n})\n"
    fs.writeFileSync(testPath, contents.replace(parameterizedTest, ''))
  })

  assert.throws(() => applyPatch(value), /test-count floor failed for packages\/js\/src\/__tests__\/floor\.test\.ts/)
})

test('rejects JavaScript assertion removal', (t) => {
  const value = fixture(t)
  writePatch(value, (directory) => {
    const testPath = path.join(directory, 'packages', 'js', 'src', '__tests__', 'floor.test.ts')
    fs.writeFileSync(testPath, fs.readFileSync(testPath, 'utf8').replace('  expect(1).toBe(1)\n', '  void 0\n'))
  })

  assert.throws(() => applyPatch(value), /test-count floor failed for packages\/js\/src\/__tests__\/floor\.test\.ts/)
})

test('rejects Go assertion removal', (t) => {
  const value = fixture(t)
  writePatch(value, (directory) => {
    const testPath = path.join(directory, 'packages', 'go', 'floor_test.go')
    fs.writeFileSync(testPath, fs.readFileSync(testPath, 'utf8').replace('t.Error("not equal")', 'return'))
  })

  assert.throws(() => applyPatch(value), /test-count floor failed for packages\/go\/floor_test\.go/)
})

test('rejects a candidate whose HEAD differs from the requested head', (t) => {
  const value = fixture(t)
  value.expected.headSha = 'f'.repeat(40)
  value.report.headSha = value.expected.headSha
  setReport(value)
  fs.writeFileSync(value.patchPath, '')

  assert.throws(() => applyPatch(value), /candidate HEAD does not match/)
})

test('rejects reports with mismatched PR, head, or request identifiers', (t) => {
  const value = fixture(t)
  fs.writeFileSync(value.patchPath, '')
  for (const [field, mismatch] of [
    ['prNumber', /PR number does not match/],
    ['headSha', /head SHA does not match/],
    ['requestId', /request ID does not match/],
  ]) {
    const report = { ...value.report, [field]: field === 'prNumber' ? 99 : 'different' }
    setReport(value, report)
    assert.throws(() => applyPatch(value), mismatch)
  }
})

test('accepts a no-change dismissal report with an empty patch', (t) => {
  const value = fixture(t)
  value.report.assessments[0].action = 'dismissed'
  value.report.assessments[0].verdict = ACTION_VERDICTS.dismissed
  setReport(value)
  fs.writeFileSync(value.patchPath, '')

  const result = applyPatch(value)

  assert.deepEqual(result.changedPaths, [])
})

test('rejects duplicate and unknown assessment ids', (t) => {
  const value = fixture(t)
  const duplicate = { ...value.report, assessments: [value.report.assessments[0], value.report.assessments[0]] }
  assert.throws(
    () =>
      validateAssessment(duplicate, {
        ...value.expected,
        findings: [...value.expected.findings, { id: 'finding-2', kind: 'review' }],
      }),
    /duplicate assessment id/,
  )
  const unknown = { ...value.report, assessments: [{ ...value.report.assessments[0], id: 'other' }] }
  assert.throws(() => validateAssessment(unknown, value.expected), /unknown assessment id/)
})

test('allows a blocked CI finding with defer verdict and rejects dismissing CI', () => {
  const expected = { prNumber: 12, headSha: 'a'.repeat(40), requestId: 'r', findings: [{ id: 'ci-1', kind: 'ci' }] }
  const report = {
    prNumber: 12,
    headSha: expected.headSha,
    requestId: 'r',
    assessments: [
      {
        id: 'ci-1',
        action: 'blocked',
        verdict: ACTION_VERDICTS.blocked,
        evidence: 'Tracking PR comment 44 retains this finding.',
      },
    ],
  }
  assert.equal(validateAssessment(report, expected).assessments[0].action, 'blocked')
  assert.throws(
    () =>
      validateAssessment(
        {
          ...report,
          assessments: [{ ...report.assessments[0], action: 'dismissed', verdict: ACTION_VERDICTS.dismissed }],
        },
        expected,
      ),
    /cannot be dismissed/,
  )
})

test('rejects symlinked patch and report artifacts', (t) => {
  const value = fixture(t)
  writePatch(value, () => {})
  const patchTarget = path.join(value.root, 'real.patch')
  fs.copyFileSync(value.patchPath, patchTarget)
  fs.unlinkSync(value.patchPath)
  fs.symlinkSync(patchTarget, value.patchPath)
  assert.throws(() => applyPatch(value), /patch must be a regular non-symlink file/)

  fs.unlinkSync(value.patchPath)
  fs.writeFileSync(value.patchPath, '')
  const reportTarget = path.join(value.root, 'real-report.json')
  fs.copyFileSync(value.reportPath, reportTarget)
  fs.unlinkSync(value.reportPath)
  fs.symlinkSync(reportTarget, value.reportPath)
  assert.throws(() => applyPatch(value), /assessment report must be a regular non-symlink file/)
})
