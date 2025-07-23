#!/usr/bin/env node

const fs = require('fs')
const { execSync } = require('child_process')

console.log('Building packages...')
execSync('npm run build', { stdio: 'inherit' })

if (fs.existsSync('.changeset/pre.json')) {
  console.log('Publishing beta release...')
  try {
    execSync('npx @changesets/cli publish --pre-state .changeset/pre.json', { stdio: 'inherit' })
  } catch (error) {
    console.log('Beta publish failed, exiting beta mode...')
    execSync('npx @changesets/cli pre exit', { stdio: 'inherit' })
    execSync('git add .', { stdio: 'inherit' })
    execSync('git commit -m "Exit beta mode after failed publish"', { stdio: 'inherit' })
    console.log('Beta mode exited and changes committed. CI will retry in stable mode.')
    process.exit(1)
  }
} else {
  console.log('Publishing stable release...')
  execSync('npx @changesets/cli publish --force', { stdio: 'inherit' })
}
