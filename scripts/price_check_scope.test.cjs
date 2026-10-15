'use strict'

const assert = require('node:assert/strict')
const { execFileSync, spawnSync } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { test } = require('node:test')

test('the compiler scope check rejects the live blocked file before commit', (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'price-check-scope-'))
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }))
  const git = (...args) => execFileSync('git', args, { cwd: directory, encoding: 'utf8' }).trim()
  git('init', '-q')
  git('config', 'user.name', 'Scope test')
  git('config', 'user.email', 'scope@example.test')
  fs.mkdirSync(path.join(directory, 'tests'))
  fs.writeFileSync(path.join(directory, 'tests/test_price_calc.py'), 'original\n')
  git('add', '.')
  git('commit', '-qm', 'baseline')
  const base = git('rev-parse', 'HEAD')
  const configFile = path.join(directory, '.git/policy.json')
  fs.writeFileSync(
    configFile,
    JSON.stringify({
      base_sha: base,
      allowed_files: ['tests/test_price_calc.py'],
      helper_path: path.join(
        process.env.PRICE_CHECK_GH_AW_ACTIONS || path.join(process.env.RUNNER_TEMP, 'gh-aw/actions'),
        'manifest_file_helpers.cjs',
      ),
    }),
  )
  const check = (...args) =>
    spawnSync(process.execPath, [path.join(__dirname, 'price_check_scope.cjs'), configFile, ...args], {
      cwd: directory,
      encoding: 'utf8',
    })
  fs.writeFileSync(path.join(directory, 'tests/test_price_calc.py'), 'updated\n')
  assert.equal(check().status, 0)
  fs.writeFileSync(path.join(directory, 'tests/test_price_check_additions.py'), 'blocked\n')
  assert.match(check().stderr, /tests\/test_price_check_additions.py/)
  git('add', '.')
  assert.equal(check('--staged').status, 1)
  git('reset', '-q', '--', 'tests/test_price_check_additions.py')
  fs.unlinkSync(path.join(directory, 'tests/test_price_check_additions.py'))
  assert.equal(check('--staged').status, 0)
  git('mv', 'tests/test_price_calc.py', 'tests/renamed.py')
  assert.match(check('--staged').stderr, /tests\/renamed.py/)
})
