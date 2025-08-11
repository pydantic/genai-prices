#!/bin/bash

set -e

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <new-version>"
  exit 1
fi

echo "setting Python package version to $1"
uvx --from=toml-cli toml set --toml-path=packages/python/pyproject.toml project.version $1
make sync

echo "setting JS package version to $1"
npm version --workspace=packages/js $1

git checkout -b "release/$1"
