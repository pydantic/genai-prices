#!/usr/bin/env node

const fs = require('fs')
const { execSync } = require('child_process')

console.log('Building packages...')
execSync('npm run build', { stdio: 'inherit' })

if (fs.existsSync('.changeset/pre.json')) {
  console.log('Publishing beta release...')
  execSync('npx @changesets/cli publish --pre-state .changeset/pre.json', { stdio: 'inherit' })
} else {
  console.log('Publishing stable release...')
  execSync('npx @changesets/cli publish', { stdio: 'inherit' })
}
