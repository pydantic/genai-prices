#!/bin/bash

set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Current version:     `uv version --package genai-prices --short`"
  echo "PyPI latest version: `curl -s https://pypi.org/pypi/genai-prices/json | jq -r '.info.version'`"
  echo "NPM latest version:  `curl -s https://registry.npmjs.org/@pydantic/genai-prices/latest | jq -r '.version'`"
  echo "Usage: $0 <new-version>"
  exit 1
fi

# Strip leading "v" prefix if present
VERSION="${1#v}"

echo "setting Python package version to $VERSION"
uv version --package genai-prices --no-sync "$VERSION"
uv sync --locked --all-packages

echo "setting JS package version to $VERSION"
npm version --workspace=packages/js "$VERSION"

git checkout -b "release/$VERSION"
echo "Switched to branch 'release/$VERSION', next run:"
echo ""
echo "git commit -am 'Prep $VERSION release' && gh pr create -f"
