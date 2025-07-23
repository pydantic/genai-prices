#!/bin/bash
set -e

echo "Building packages..."
npm run build

if [ -f ".changeset/pre.json" ]; then
  echo "Publishing beta release..."
  npx @changesets/cli publish --pre-state .changeset/pre.json
else
  echo "Publishing stable release..."
  npx @changesets/cli publish
fi
