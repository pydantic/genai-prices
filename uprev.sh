#!/bin/bash

set -e

if [ "$#" -ne 1 ]; then
  echo "Current version:     `uvx --from=toml-cli toml get --toml-path=packages/python/pyproject.toml project.version`"
  echo "PyPI latest version: `curl -s https://pypi.org/pypi/genai-prices/json | jq -r '.info.version'`"
  echo "NPM latest version:  `curl -s https://registry.npmjs.org/@pydantic/genai-prices/latest | jq -r '.version'`"
  echo "Usage: $0 <new-version>"
  exit 1
fi

echo "setting Python package version to $1"
uvx --from=toml-cli toml set --toml-path=packages/python/pyproject.toml project.version $1
make sync

echo "setting JS package version to $1"
npm version --workspace=packages/js $1

git checkout -b "release/$1"
echo "Switched to branch 'release/$1', next run:"
echo ""
echo "git commit -am 'Prep $1 release' && gh pr create -f"
