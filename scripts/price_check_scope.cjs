'use strict'

const fs = require('node:fs')
const { execFileSync } = require('node:child_process')

try {
  const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
  if (
    !/^[a-f0-9]{40}$/.test(config.base_sha) ||
    !Array.isArray(config.allowed_files) ||
    !config.allowed_files.length ||
    !config.allowed_files.every((pattern) => typeof pattern === 'string' && pattern.length > 0)
  )
    throw new Error('Missing Price Check scope configuration')
  const { checkFileProtectionPostApply } = require(config.helper_path)
  const staged = process.argv.includes('--staged')
  const root = execFileSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim()
  const diff = execFileSync(
    'git',
    [
      'diff',
      '--no-ext-diff',
      '--no-relative',
      '--name-only',
      '--no-renames',
      '-z',
      ...(staged ? ['--cached'] : []),
      config.base_sha,
      '--',
    ],
    { cwd: root },
  )
  const untracked = staged
    ? Buffer.alloc(0)
    : execFileSync('git', ['ls-files', '--others', '--exclude-standard', '-z'], { cwd: root })
  const files = [...new Set(Buffer.concat([diff, untracked]).toString('utf8').split('\0').filter(Boolean))]
  const result = checkFileProtectionPostApply(files, config)
  if (result.action !== 'allow')
    throw new Error(
      `Outside create-pull-request.allowed-files: ${result.files.join(', ')}. Restore and defer affected candidates.`,
    )
  console.log('Price Check file scope passed')
} catch (error) {
  console.error(error.message)
  process.exitCode = 1
}
